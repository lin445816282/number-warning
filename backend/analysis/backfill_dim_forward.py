#!/usr/bin/env python3
"""回填观察池维度前向验证记录（walk-forward，无前视偏差）。

背景：前向验证(dim_fwd_%)原本从部署日(09-07)才开始固化，样本仅1-3期，永远无法达标(100期)。
本脚本从数据最早(2025-01-01)开始逐期回放：第 i 期用前 i 期数据算「憋到高位」warning 信号，
选号(该维度号码并集)作为「第 i+1 期买入」，用第 i+1 期实际开奖号结算 hit，回填 algo_forward_track。

口径与 _compute_dim_forward_next 完全一致：warning 口径(憋到高位)、offset 读 sys_config(默认0)、
window=60、单次买1期。生肖号码按买入期(下一期)周期映射，其余维度用 DEFAULT_ZODIAC 缓存。
"""
import sys, os, json
from datetime import datetime

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # backend/
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)
import main

OFFSET = main._get_config_int('high_track_fwd_offset', 0)
WINDOW = 60
WATCH = main.DIM_ASSESS_WATCH

db = main.get_db()
cycle_maps = main._load_cycle_maps(db)
rows = db.execute(
    "SELECT * FROM number_knowledge_record WHERE status=1 ORDER BY record_date, id").fetchall()
db.close()

tn_cache = {}
def tag_nums(dim, tag, zm):
    if dim == "zodiac":
        return [n for n in range(1, 50) if main._num_to_zodiac(n, zm) == tag]
    k = (dim, tag)
    if k not in tn_cache:
        tn_cache[k] = [n for n in range(1, 50) if main.match_labels(n, main.DEFAULT_ZODIAC).get(dim) == tag]
    return tn_cache[k]

last_seen = {}; sample = {}; gap_hist = {}
records = []  # (algo_key, bet_date, picks_json, N, open_number, hit)

for i, r in enumerate(rows):
    seq = i + 1
    zm = main._map_for(r, cycle_maps)
    open_labels = main.match_labels(r["source_number"], zm)
    # 1. 更新状态：计入第 i 期开奖号
    for dim, tag in open_labels.items():
        if not tag:
            continue
        k = (dim, tag)
        if k in last_seen:
            gap = seq - last_seen[k]
            gap_hist.setdefault(k, []).append((seq, gap))
            sample[k] = sample.get(k, 0) + 1
        else:
            sample[k] = 1
        last_seen[k] = seq
    # 2. 下一期买入 + 用下一期开奖结算（无前视偏差：只用前 seq 期信息选号）
    if i + 1 < len(rows):
        nxt = rows[i + 1]
        nxt_zm = main._map_for(nxt, cycle_maps)
        nxt_open = int(nxt["source_number"])
        nxt_date = nxt["record_date"]
        total_seq = seq
        for dim in WATCH:
            picks = set()
            for (d, tag), ls in last_seen.items():
                if d != dim:
                    continue
                if sample.get((d, tag), 0) < 2:
                    continue
                hm = main._window_hist_max(gap_hist, (d, tag), total_seq, WINDOW)
                if total_seq - ls >= hm - OFFSET:
                    picks.update(tag_nums(dim, tag, nxt_zm))
            picks = sorted(picks)
            if picks:
                hit = 1 if nxt_open in picks else 0
                records.append(("dim_fwd_" + dim, nxt_date, json.dumps(picks), len(picks), nxt_open, hit))

# 写回：清空旧 dim_fwd_%，插入回填记录
db = main.get_db()
before = db.execute(
    "SELECT COUNT(*) c FROM algo_forward_track WHERE algo_key LIKE 'dim_fwd_%'").fetchone()["c"]
db.execute("DELETE FROM algo_forward_track WHERE algo_key LIKE 'dim_fwd_%'")
now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
for key, bd, picks, N, open_num, hit in records:
    db.execute(
        "INSERT INTO algo_forward_track (algo_key, bet_date, picks_json, N, open_number, hit, create_time) "
        "VALUES (?,?,?,?,?,?,?)", (key, bd, picks, N, open_num, hit, now))
db.commit()
db.close()

by_dim = {}
for key, bd, picks, N, open_num, hit in records:
    d = key.replace("dim_fwd_", "")
    a = by_dim.setdefault(d, {"periods": 0, "hits": 0, "sum_n": 0})
    a["periods"] += 1
    a["hits"] += hit
    a["sum_n"] += N

print(f"[回填] 清空旧记录 {before} 条，回填 {len(records)} 条 (offset={OFFSET}, window={WINDOW})")
print(f"[回填] 数据范围 {rows[0]['record_date']} ~ {rows[-1]['record_date']}，共 {len(rows)} 期")
for d, a in sorted(by_dim.items(), key=lambda x: -x[1]["periods"]):
    avg_n = a["sum_n"] / a["periods"]
    rand = avg_n / 49
    print(f"  {main.DIM_NAMES.get(d, d):10s} {a['periods']:4d}期 命中{a['hits']:3d} "
          f"({a['hits']/a['periods']*100:.1f}%) 均号{avg_n:.1f} 随机{rand*100:.1f}% 超额{(a['hits']/a['periods']-rand)*100:+.1f}%")
