#!/usr/bin/env python3
"""第二轮：凯利最优仓位 + 稳健性验证（区分真盈利 vs 破产重置假象）"""
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

def compute_daily(signal_top_n, pick_fn):
    last_seen = dict(last_seen_init)
    recs = []
    for i in range(start_idx, len(rows)):
        r = rows[i]
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

def kelly_fraction(recs):
    if not recs:
        return 0.0, 0.0, 0.0
    p = sum(1 for _, h in recs if h) / len(recs)
    N = sum(n for n, _ in recs) / len(recs)
    if N == 0 or N >= ODDS:
        return 0.0, p, N
    b = (ODDS - N) / N
    q = 1 - p
    f = (b * p - q) / b if b > 0 else 0.0
    return f, p, N

def run_with_fraction(recs, frac, cap=None):
    if cap is not None:
        frac = min(frac, cap)
    frac = max(0.0, frac)
    cash = float(START)
    equity = [cash]
    bankrupt = 0
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
        if cash < 1:
            bankrupt += 1
            cash = 1.0
        equity.append(cash)
    peak = equity[0]
    max_dd = 0.0
    for e in equity:
        peak = max(peak, e)
        if peak > 0:
            max_dd = min(max_dd, (e - peak) / peak)
    return {"final": cash, "net": cash - START, "bankrupt": bankrupt,
            "max_dd": max_dd * 100, "multi": cash / START}

def pick_ge(x): return lambda v, s: [n for n, c in v.items() if c >= x]
def pick_lt(x): return lambda v, s: [n for n, c in v.items() if c < x]
def pick_eq(x): return lambda v, s: [n for n, c in v.items() if c == x]
def pick_top(k): return lambda v, s: sorted(range(1, 50), key=lambda n: (-v[n], n))[:k]

strategies = [
    ("ge1", pick_ge(1)), ("ge2", pick_ge(2)), ("ge3", pick_ge(3)),
    ("ge4", pick_ge(4)), ("ge5", pick_ge(5)), ("ge6", pick_ge(6)),
    ("eq0", pick_eq(0)), ("eq1", pick_eq(1)), ("eq2", pick_eq(2)),
    ("eq3", pick_eq(3)), ("eq4", pick_eq(4)), ("eq5", pick_eq(5)),
    ("lt2", pick_lt(2)), ("lt3", pick_lt(3)), ("lt4", pick_lt(4)),
    ("top5", pick_top(5)), ("top10", pick_top(10)), ("top15", pick_top(15)),
]

print("=== 各策略：命中率 / 号数 / 凯利最优仓位 / 期望（TOP_N=10 信号，127期）===\n")
print(f"{'策略':<8} {'命中率':>7} {'均号数':>7} {'凯利f*':>8} {'每元期望':>8} {'凯利净值':>9} {'凯利回撤%':>9} {'破产':>5}")
print("-" * 82)

cache = {}
for name, fn in strategies:
    recs = compute_daily(10, fn)
    cache[name] = recs
    f, p, N = kelly_fraction(recs)
    ev = p * ODDS - N
    rk = run_with_fraction(recs, f, cap=0.4)
    print(f"{name:<8} {p*100:>6.1f}% {N:>7.1f} {f*100:>7.1f}% {ev:>8.2f} {rk['multi']:>8.2f}x {rk['max_dd']:>8.1f}% {rk['bankrupt']:>5}")

print("\n=== 半凯利对照（更稳健，cap 20%）===")
print(f"{'策略':<8} {'半凯利净值':>10} {'回撤%':>8} {'破产':>5}")
for name, recs in cache.items():
    f, p, N = kelly_fraction(recs)
    if f > 0:
        rh = run_with_fraction(recs, f / 2, cap=0.2)
        print(f"{name:<8} {rh['multi']:>9.2f}x {rh['max_dd']:>7.1f}% {rh['bankrupt']:>5}")

print("\n=== 固定仓位扫描（TOP_N=10，选号=eq2 票数=2，看最优仓位）===")
eq2 = cache["eq2"]
for fr in [0.05, 0.1, 0.15, 0.2, 0.3, 0.5]:
    r = run_with_fraction(eq2, fr)
    print(f"仓位 {fr*100:>3.0f}%: 净值 {r['multi']:.2f}x  回撤 {r['max_dd']:.1f}%  破产 {r['bankrupt']}")
