#!/usr/bin/env python3
"""回填自主跟踪方案的前向验证记录（walk-forward，无前视偏差）。

背景：自主跟踪方案的前向固化(fwd_*)从部署日才开始积累，样本 0 期，无法立即验证。
本脚本对 status='forwarding' 的方案，从数据最早(2025-01-01)起逐期回放：
第 i 期用前 i 期数据算「高位触发」信号（各维度 gap >= 近60期历史最高 - offset），
选号(号码并集)作为「第 i+1 期买入」，用第 i+1 期实际开奖号结算 hit，回填 dim_forward_track(dim_key='scheme:<key>')。

口径与 _backtest_scheme / _generate_scheme_forward 完全一致（高位触发 → 号码并集 → 单期买）。
回填后调 _update_scheme_forward_stats 回填方案表 fwd_* 指标。
"""
import sys, os, json
from datetime import datetime

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # backend/
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)
import main

WINDOW = 60

db = main.get_db()
fwd = db.execute("SELECT * FROM strategy_scheme_record WHERE status='forwarding'").fetchall()
cycle_maps = main._load_cycle_maps(db)
rows = db.execute(
    "SELECT * FROM number_knowledge_record WHERE status=1 ORDER BY record_date, id").fetchall()
db.close()

if not fwd:
    print("无 forwarding 方案，跳过")
    sys.exit(0)

# 预计算每期标签（num, labels, zm）
seq_labels = []
for r in rows:
    zm = main._map_for(r, cycle_maps)
    num = int(r["source_number"])
    seq_labels.append((num, main.match_labels(num, zm), zm))

records = []  # (scheme_key, bet_date, picks_json, N, open_number, hit)

for s in fwd:
    key = s["scheme_key"]
    try:
        dims = json.loads(s["dims_json"]) if s["dims_json"] else []
    except Exception:
        dims = []
    off = s["offset"]
    w = s["window"] or 60
    srule = s["signal_rule"] or "high_gap"
    pr = "union" if srule == "high_gap" else srule.replace("high_gap_", "")
    if not dims:
        continue
    dimset = set(dims)
    tn_cache = {}

    def tag_nums(dim, tag, zm):
        if dim == "zodiac":
            return [n for n in range(1, 50) if main._num_to_zodiac(n, zm) == tag]
        k = (dim, tag)
        if k not in tn_cache:
            tn_cache[k] = [n for n in range(1, 50) if main.match_labels(n, main.DEFAULT_ZODIAC).get(dim) == tag]
        return tn_cache[k]

    last_seen = {}; sample = {}; gap_hist = {}
    for i in range(len(rows)):
        seq = i + 1
        open_num, labels, zm = seq_labels[i]
        # 1. 更新状态：计入第 i 期开奖号
        for dim, tag in labels.items():
            if not tag or dim not in dimset:
                continue
            k = (dim, tag)
            if k in last_seen:
                gap = seq - last_seen[k]
                gap_hist.setdefault(k, []).append((seq, gap))
                sample[k] = sample.get(k, 0) + 1
            else:
                sample[k] = 1
            last_seen[k] = seq
        # 2. 第 i+1 期买入 + 用第 i+1 期开奖结算（无前视：只用前 seq 期信息选号）
        if i + 1 < len(rows):
            nxt_open, nxt_labels, nxt_zm = seq_labels[i + 1]
            nxt_date = rows[i + 1]["record_date"]
            vote = {}
            for (dim, tag), ls in last_seen.items():
                if sample.get((dim, tag), 0) < 2:
                    continue
                hm = main._window_hist_max(gap_hist, (dim, tag), seq, w)
                if seq - ls >= hm - off:
                    for n in tag_nums(dim, tag, nxt_zm):
                        vote[n] = vote.get(n, 0) + 1
            if pr == "union":
                picks = sorted(vote.keys())
            else:
                try:
                    th = int(pr.replace("ge", ""))
                except Exception:
                    th = 1
                picks = sorted(n for n, c in vote.items() if c >= th)
            if picks:
                hit = 1 if nxt_open in picks else 0
                records.append(("scheme:" + key, nxt_date, json.dumps(picks), len(picks), nxt_open, hit))

# 写回：清空旧 scheme:，插入回填
db = main.get_db()
before = db.execute(
    "SELECT COUNT(*) c FROM dim_forward_track WHERE dim_key LIKE 'scheme:%'").fetchone()["c"]
db.execute("DELETE FROM dim_forward_track WHERE dim_key LIKE 'scheme:%' AND is_live=0")
now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
for key, bd, picks, N, open_num, hit in records:
    db.execute(
        "INSERT INTO dim_forward_track (dim_key, bet_date, picks_json, N, open_number, hit, is_live, create_time) VALUES (?,?,?,?,?,?,0,?)",
        (key, bd, picks, N, open_num, hit, now))
db.commit()
db.close()

# 回填 fwd_* 指标
main._update_scheme_forward_stats()

print(f"[回填] 清空旧 scheme: 记录 {before} 条，回填 {len(records)} 条")
print(f"[回填] 方案数 {len(fwd)}，数据 {rows[0]['record_date']} ~ {rows[-1]['record_date']} 共 {len(rows)} 期")

by_key = {}
for key, bd, picks, N, open_num, hit in records:
    k = key.replace("scheme:", "")
    a = by_key.setdefault(k, {"periods": 0, "hits": 0, "sum_n": 0})
    a["periods"] += 1
    a["hits"] += hit
    a["sum_n"] += N
for k, a in sorted(by_key.items(), key=lambda x: -x[1]["periods"]):
    avg_n = a["sum_n"] / a["periods"] if a["periods"] else 0
    rand = avg_n / 49
    print(f"  {k[:16]:16s} {a['periods']:4d}期 命中{a['hits']:3d} "
          f"({a['hits']/a['periods']*100:.1f}%) 均号{avg_n:.1f} 超额{(a['hits']/a['periods']-rand)*100:+.1f}%")
