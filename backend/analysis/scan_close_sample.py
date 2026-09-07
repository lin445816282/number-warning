#!/usr/bin/env python3
"""「接近样本」下单策略演算 — 用「当前遗漏接近/超过历史最高」的标签作信号选号，找盈亏最大下单方式。
信号源：某标签 gap(当前遗漏) >= hist_max(历史最高遗漏) - offset 且 sample>=2 时触发。
与「建议号码」区别：建议号码用「每维度遗漏最久标签」，这里用「接近历史最高的标签」（预警口径）。
运行：cd backend && python3 analysis/scan_close_sample.py
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import main as M

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
START_DATE = "2026-05-01"
ODDS = 47
START = 3000

db = M.get_db()
cycle = db.execute(
    "SELECT zodiac_mapping FROM zodiac_number_cycle_config WHERE is_enable=1 ORDER BY start_date DESC LIMIT 1").fetchone()
zodiac_map = M.DEFAULT_ZODIAC
if cycle:
    try:
        zm = json.loads(cycle["zodiac_mapping"])
        if zm:
            zodiac_map = zm
    except Exception:
        pass
rows = db.execute(
    "SELECT * FROM number_knowledge_record WHERE status=1 ORDER BY record_date, id").fetchall()
db.close()

start_idx = None
for i, r in enumerate(rows):
    if r["record_date"] >= START_DATE:
        start_idx = i
        break
if start_idx is None:
    sys.exit("no data after " + START_DATE)

mid_date = rows[(start_idx + len(rows)) // 2]["record_date"]

def compute_close_sample(offset, sort_by, signal_top_n, pick_fn, end_date=None):
    """回放「接近样本」信号。返回 recs=[(N, hit)] + 信号统计。"""
    last_seen = {}   # (dim, tag) -> 上次出现 seq
    hist_max = {}    # (dim, tag) -> 历史最大 gap
    sample = {}      # (dim, tag) -> 出现次数
    # 初始化（start_idx 前数据）
    for i in range(start_idx):
        r = rows[i]
        for dim, tag in M.match_labels(r["source_number"], zodiac_map).items():
            if tag:
                k = (dim, tag)
                if k in last_seen:
                    gap = (i + 1) - last_seen[k]
                    hist_max[k] = max(hist_max.get(k, 0), gap)
                    sample[k] = sample.get(k, 0) + 1
                else:
                    sample[k] = 1
                last_seen[k] = i + 1
    recs = []
    sig_counts = []
    for i in range(start_idx, len(rows)):
        r = rows[i]
        d = r["record_date"]
        if end_date and d > end_date:
            break
        seq = i + 1
        open_num = int(r["source_number"])
        # 触发「接近样本」信号
        signals = []
        for (dim, tag), ls in last_seen.items():
            gap = seq - ls
            hm = hist_max.get((dim, tag), 0)
            if sample.get((dim, tag), 0) >= 2 and gap >= hm - offset:
                signals.append((dim, tag, gap, hm))
        if sort_by == 'gap':
            signals.sort(key=lambda x: -x[2])
        else:  # 'excess'：按超越历史最高幅度 gap-hm
            signals.sort(key=lambda x: -(x[2] - x[3]))
        sig_counts.append(len(signals))
        top_signals = [(dim, tag) for dim, tag, _, _ in signals[:signal_top_n]]
        signal_set = set(top_signals)
        vote_by_num = {}
        for n in range(1, 50):
            labels = M.match_labels(n, zodiac_map)
            cnt = sum(1 for dk, tv in labels.items() if tv and (dk, tv) in signal_set)
            vote_by_num[n] = cnt
        picks = pick_fn(vote_by_num)
        N = len(picks)
        hit = (open_num in picks) if N > 0 else False
        recs.append((N, hit))
        # 更新（本期开出标签）
        for dim, tag in M.match_labels(open_num, zodiac_map).items():
            if tag:
                k = (dim, tag)
                if k in last_seen:
                    gap = seq - last_seen[k]
                    hist_max[k] = max(hist_max.get(k, 0), gap)
                    sample[k] = sample.get(k, 0) + 1
                else:
                    sample[k] = 1
                last_seen[k] = seq
    return recs, sig_counts

def pick_ge(x): return lambda v: [n for n, c in v.items() if c >= x]
def pick_lt(x): return lambda v: [n for n, c in v.items() if c < x]
def pick_eq(x): return lambda v: [n for n, c in v.items() if c == x]
def pick_top(k): return lambda v: sorted(range(1, 50), key=lambda n: (-v[n], n))[:k]

def run_online(recs, frac, reset_thr=100):
    cash = float(START); baseline = float(START)
    bankrupt = 0; withdraws = 0.0; inject = 0.0
    for N, hit in recs:
        if N == 0:
            continue
        bet = cash * frac
        per = int(bet / N) if N else 0
        actual = per * N
        if actual <= 0:
            continue
        if hit:
            cash += (ODDS - N) * per
        else:
            cash -= actual
        if cash < reset_thr:
            inject += (START - cash)
            bankrupt += 1
            cash = float(START); baseline = float(START)
        elif cash >= baseline * 2:
            wd = cash * 0.25
            withdraws += wd
            cash *= 0.75
            baseline = cash
    return {"net": round(cash + withdraws - START - inject, 2),
            "inject": round(inject, 2), "bankrupt": bankrupt}

def ev_of(recs):
    if not recs:
        return 0.0
    p = sum(1 for _, h in recs if h) / len(recs)
    N = sum(n for n, _ in recs) / len(recs)
    return p * ODDS - N

# 先探索：信号分布
print("=== 「接近样本」信号分布（每期触发标签数）===")
for offset in [0, 1, 2]:
    recs, sc = compute_close_sample(offset, 'gap', 999, pick_top(49))
    n = len(sc)
    avg = sum(sc) / n if n else 0
    mx = max(sc) if sc else 0
    print(f"  offset={offset}: 平均每期 {avg:.1f} 个信号，最多 {mx} 个，共 {n} 期")

# 全参数扫描
print("\n=== 全参数扫描（接近样本 → 下单）===")
strategies = [("ge1", pick_ge(1)), ("ge2", pick_ge(2)), ("ge3", pick_ge(3)),
              ("ge4", pick_ge(4)), ("ge5", pick_ge(5)), ("ge6", pick_ge(6)),
              ("eq0", pick_eq(0)), ("eq1", pick_eq(1)), ("eq2", pick_eq(2)),
              ("eq3", pick_eq(3)), ("eq4", pick_eq(4)), ("eq5", pick_eq(5)),
              ("lt2", pick_lt(2)), ("lt3", pick_lt(3)), ("lt4", pick_lt(4))]

results = []
for offset in [0, 1, 2]:
    for sort_by in ['gap', 'excess']:
        for top_n in [5, 10, 20, 999]:
            for sname, fn in strategies:
                recs, _ = compute_close_sample(offset, sort_by, top_n, fn)
                p = sum(1 for _, h in recs if h) / len(recs)
                N = sum(n for n, _ in recs) / len(recs)
                ev = p * ODDS - N
                r50 = run_online(recs, 0.5)
                results.append({"offset": offset, "sort": sort_by, "top_n": top_n,
                                "strategy": sname, "hit_rate": round(p, 4),
                                "avg_N": round(N, 2), "ev": round(ev, 2),
                                "net50": r50["net"], "inject": r50["inject"],
                                "bankrupt": r50["bankrupt"]})
results.sort(key=lambda x: -x["net50"])

print(f"\n{'offset':<7}{'sort':<7}{'topN':<6}{'策略':<7}{'命中率':>7}{'均号':>6}{'EV':>7}{'净收益50%':>11}{'注资':>9}{'破产':>5}")
print("-" * 80)
for r in results[:30]:
    tn = 'ALL' if r['top_n'] == 999 else r['top_n']
    print(f"{r['offset']:<7}{r['sort']:<7}{tn:<6}{r['strategy']:<7}{r['hit_rate']*100:>6.1f}%{r['avg_N']:>6.1f}{r['ev']:>7.2f}{r['net50']:>11,.0f}{r['inject']:>9,.0f}{r['bankrupt']:>5}")

# 时间分段验证 Top10
print("\n=== 时间分段稳健性（净收益 Top10）===")
seen = set()
for r in results[:10]:
    key = (r['offset'], r['sort'], r['top_n'], r['strategy'])
    if key in seen:
        continue
    seen.add(key)
    fn = dict(strategies)[r['strategy']]
    recs_all, _ = compute_close_sample(r['offset'], r['sort'], r['top_n'], fn)
    recs_first, _ = compute_close_sample(r['offset'], r['sort'], r['top_n'], fn, end_date=mid_date)
    ev2 = ev_of(recs_all[len(recs_first):])
    ev1 = ev_of(recs_first)
    flip = (ev1 > 0) != (ev2 > 0)
    v = "翻转✗" if flip else "稳定✓"
    tn = 'ALL' if r['top_n'] == 999 else r['top_n']
    print(f"  off{r['offset']}_{r['sort']}_top{tn}_{r['strategy']}: 前半EV {ev1:+.2f} / 后半EV {ev2:+.2f} → {v} (净收益 {r['net50']:+,.0f})")

# 保存结果
out = {"generated": "2026-09-05", "start_date": START_DATE,
       "periods": len(rows) - start_idx, "odds": ODDS, "start_cash": START,
       "signal_method": "接近历史最高遗漏标签（gap >= hist_max - offset 且 sample>=2）",
       "results": results}
with open(os.path.join(OUT_DIR, "results_close_sample.json"), "w", encoding="utf-8") as fp:
    json.dump(out, fp, ensure_ascii=False, indent=1)
print(f"\n已保存 results_close_sample.json（{len(results)} 种组合）")
