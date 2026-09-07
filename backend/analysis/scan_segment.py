#!/usr/bin/env python3
"""第三轮：时间分段稳定性 + 破产重置影响分解 + 样本外验证"""
import sys, os, json, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import main as M

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

START_DATE = "2026-05-01"
ODDS = 47
START = 3000

start_idx = None
for i, r in enumerate(rows):
    if r["record_date"] >= START_DATE:
        start_idx = i
        break

last_seen_init = {}
for i in range(start_idx):
    r = rows[i]
    for dim, tag in M.match_labels(r["source_number"], zodiac_map).items():
        if tag:
            last_seen_init[(dim, tag)] = i + 1

def compute_daily(signal_top_n, pick_fn, start=None, end=None):
    last_seen = dict(last_seen_init)
    recs = []
    for i in range(start_idx, len(rows)):
        r = rows[i]
        d = r["record_date"]
        if start and d < start:
            continue
        if end and d > end:
            continue
        seq = i + 1
        open_num = int(r["source_number"])
        best = {}
        for (dim, tag), ls in last_seen.items():
            gap = seq - ls
            if dim not in best or gap > best[dim][1]:
                best[dim] = (tag, gap)
        ranked = sorted([(dim, tag, gap) for dim, (tag, gap) in best.items() if gap > 0],
                        key=lambda x: -x[2])
        top_signals = [(dim, tag) for dim, tag, gap in ranked[:signal_top_n]]
        signal_set = set(top_signals)
        vote_by_num = {}
        for n in range(1, 50):
            labels = M.match_labels(n, zodiac_map)
            cnt = sum(1 for dk, tv in labels.items() if tv and (dk, tv) in signal_set)
            vote_by_num[n] = cnt
        picks = pick_fn(vote_by_num, top_signals)
        N = len(picks)
        hit = (open_num in picks) if N > 0 else False
        recs.append((N, hit))
        for dim, tag in M.match_labels(open_num, zodiac_map).items():
            if tag:
                last_seen[(dim, tag)] = seq
    return recs

def pick_eq(x): return lambda v, s: [n for n, c in v.items() if c == x]
def pick_ge(x): return lambda v, s: [n for n, c in v.items() if c >= x]
def pick_lt(x): return lambda v, s: [n for n, c in v.items() if c < x]

def stats(recs):
    if not recs:
        return None
    p = sum(1 for _, h in recs if h) / len(recs)
    N = sum(n for n, _ in recs) / len(recs)
    ev = p * ODDS - N
    return {"p": p, "N": N, "ev": ev, "periods": len(recs)}

strategies = [
    ("eq1", pick_eq(1)), ("eq5", pick_eq(5)), ("ge5", pick_ge(5)),
    ("lt2", pick_lt(2)), ("ge4", pick_ge(4)), ("eq2", pick_eq(2)),
]

print("=== 时间分段稳定性（前后两半，看 EV 是否一致）===\n")
half = (start_idx + len(rows)) // 2
mid_date = rows[half]["record_date"]
print(f"前半：2026-05-01 ~ {mid_date}  后半：{mid_date} ~ 09-04\n")
print(f"{'策略':<8} {'前半EV':>8} {'后半EV':>8} {'前半命中':>9} {'后半命中':>9} {'判定':>6}")
print("-" * 60)
for name, fn in strategies:
    r1 = compute_daily(10, fn, end=mid_date)
    r2 = compute_daily(10, fn, start=mid_date)
    s1 = stats(r1)
    s2 = stats(r2)
    if s1 and s2:
        verdict = "稳定✓" if (s1["ev"] > 0) == (s2["ev"] > 0) else "翻转✗"
        print(f"{name:<8} {s1['ev']:>8.2f} {s2['ev']:>8.2f} {s1['p']*100:>7.1f}%/{s1['periods']:<3} {s2['p']*100:>7.1f}%/{s2['periods']:<3} {verdict:>6}")

print("\n=== 破产重置对账面收益的贡献（ge4，50%仓位，127期）===\n")
# 带破产重置（线上 order-track 逻辑：<100 回 3000 + 翻倍提25%）
def run_with_reset(recs, frac=0.5, reset_thr=100):
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
    return cash, withdraws, bankrupt, inject

# 不带破产重置（真实资金，归零即停）
def run_no_reset(recs, frac=0.5):
    cash = float(START)
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
        if cash <= 0:
            cash = 0.0
            break
    return cash

ge4 = compute_daily(10, pick_ge(4))
c1, wd1, b1, inj1 = run_with_reset(ge4)
c2 = run_no_reset(ge4)
print(f"ge4 带破产重置：期末资金 {c1:,.0f} + 提取 {wd1:,.0f} = 账面净值 {c1+wd1:,.0f}，破产 {b1} 次，累计注资 {inj1:,.0f} 元")
print(f"ge4 不带重置（真实）：期末资金 {c2:,.0f}（初始3000）")
print(f"→ 破产重置累计凭空注入 {inj1:,.0f} 元，账面净值里 {c1+wd1-3000:,.0f} 的\"盈利\"含 {inj1:,.0f} 元是假注资")

print("\n=== 结论性对比：各策略真实无重置 5% 凯利仓位（127期复利）===")
for name, fn in strategies:
    recs = compute_daily(10, fn)
    c = run_no_reset(recs, 0.05)
    s = stats(recs)
    print(f"{name:<8} EV={s['ev']:>6.2f}  5%仓位期末 {c:,.0f}（初始3000）")
