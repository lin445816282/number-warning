#!/usr/bin/env python3
"""「接近样本」严格验证：纯复利（无提取无重置）+ 逐月 EV 稳定性 + 与建议号码对比"""
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

# 复用 scan_close_sample 的信号回放
sys.path.insert(0, OUT_DIR)
from scan_close_sample import compute_close_sample, pick_eq, pick_ge

def monthly_ev(recs, with_date):
    """按 (N,hit,date) 逐月聚合 EV"""
    monthly = {}
    for (N, hit), d in zip(recs, with_date):
        m = d[:7]
        p_hit = 1 if hit else 0
        b = monthly.setdefault(m, {"hits": 0, "Nsum": 0.0, "cnt": 0})
        b["hits"] += p_hit
        b["Nsum"] += N
        b["cnt"] += 1
    out = {}
    for m, b in monthly.items():
        p = b["hits"] / b["cnt"]
        N = b["Nsum"] / b["cnt"]
        out[m] = p * ODDS - N
    return out

def run_pure(recs, frac):
    """纯复利，无提取无重置"""
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

# 关键组合
candidates = [
    ("off0_eq1(接近样本·票数1)", 0, 'gap', 10, pick_eq(1)),
    ("off0_ge1(接近样本·票数≥1)", 0, 'gap', 10, pick_ge(1)),
    ("off2_eq2(接近样本·票数2)", 2, 'gap', 10, pick_eq(2)),
    ("off1_ge2(接近样本·票数≥2)", 1, 'excess', 5, pick_ge(2)),
]

print("=== 逐月 EV（接近样本候选策略）===\n")
print(f"{'策略':<26}" + "".join(f"{m:>10}" for m in ['2026-05','2026-06','2026-07','2026-08','2026-09']) + f"{'全样本':>10}")
print("-" * 90)
month_labels = ['2026-05', '2026-06', '2026-07', '2026-08', '2026-09']
for name, off, sb, tn, fn in candidates:
    recs, _ = compute_close_sample(off, sb, tn, fn)
    dates = [rows[start_idx + j]["record_date"] for j in range(len(recs))]
    mev = monthly_ev(recs, dates)
    cells = []
    for m in month_labels:
        cells.append(f"{mev.get(m, 0):>+10.2f}")
    all_ev = sum(mev.values()) / len(mev)
    cells.append(f"{all_ev:>+10.2f}")
    print(f"{name:<26}" + "".join(cells))

print("\n=== 纯复利对照（无提取无重置，看真实复利倍数）===\n")
for name, off, sb, tn, fn in candidates:
    recs, _ = compute_close_sample(off, sb, tn, fn)
    for frac in [0.05, 0.1, 0.2]:
        c = run_pure(recs, frac)
        print(f"{name:<26} 仓位{frac*100:>3.0f}%: {c:,.0f}（{c/START:.2f}x）")

print("\n=== 命中率 vs 随机基线 ===")
for name, off, sb, tn, fn in candidates:
    recs, _ = compute_close_sample(off, sb, tn, fn)
    p = sum(1 for _, h in recs if h) / len(recs)
    N = sum(n for n, _ in recs) / len(recs)
    baseline = N / 49
    print(f"{name:<26} 命中率 {p*100:.1f}% vs 随机基线 {baseline*100:.1f}% (超 {p*100-baseline*100:+.1f}pp, 均号 {N:.1f})")
