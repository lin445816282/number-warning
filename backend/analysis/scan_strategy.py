#!/usr/bin/env python3
"""号码下单策略参数扫描 — 找更高盈利算法（复用 main.py 的 match_labels 与周期配置）"""
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

# 找起始索引
start_idx = None
for i, r in enumerate(rows):
    if r["record_date"] >= START_DATE:
        start_idx = i
        break
if start_idx is None:
    print("no data after", START_DATE)
    sys.exit(1)

# 初始化 last_seen
last_seen_init = {}
for i in range(start_idx):
    r = rows[i]
    for dim, tag in M.match_labels(r["source_number"], zodiac_map).items():
        if tag:
            last_seen_init[(dim, tag)] = i + 1

def run(signal_top_n, pick_fn, bet_ratio, bankrupt_threshold=100, withdraw_ratio=0.25, withdraw_mult=2.0):
    """回放。pick_fn(vote_by_num, top_signals) -> list[int]（要买的号码）。"""
    last_seen = dict(last_seen_init)
    cash = float(START)
    baseline = float(START)
    bankrupt = 0
    withdraws = 0.0
    daily = []
    for i in range(start_idx, len(rows)):
        r = rows[i]
        seq = i + 1
        d = r["record_date"]
        open_num = int(r["source_number"])
        # 每维度取遗漏最大标签
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
        bet = cash * bet_ratio
        if N == 0:
            hit = False
            actual = 0
            profit = 0.0
        else:
            per = int(bet / N)
            actual = per * N
            hit = open_num in picks
            profit = (ODDS * per - actual) if hit else (-actual)
        cash += profit
        event = ""
        if cash < bankrupt_threshold:
            bankrupt += 1
            cash = float(START)
            baseline = float(START)
            event = f"破产#{bankrupt}"
        elif cash >= baseline * withdraw_mult:
            wd = cash * withdraw_ratio
            withdraws += wd
            cash = cash * (1 - withdraw_ratio)
            baseline = cash
            event = f"提取{wd:.0f}"
        daily.append({"date": d, "N": N, "hit": hit, "actual": actual,
                      "profit": round(profit, 2), "cash": round(cash, 2), "event": event})
        for dim, tag in M.match_labels(open_num, zodiac_map).items():
            if tag:
                last_seen[(dim, tag)] = seq
    final = cash + withdraws
    net = final - START
    hit_count = sum(1 for x in daily if x["hit"])
    periods = len(daily)
    # 最大回撤（相对初始 3000 的净值曲线）
    equity = [START]
    for x in daily:
        equity.append(x["cash"] + withdraws)
    peak = equity[0]
    max_dd = 0.0
    for e in equity:
        peak = max(peak, e)
        dd = (e - peak) / peak if peak else 0
        max_dd = min(max_dd, dd)
    # 日均盈利 + 波动（用于粗略 sharpe）
    profits = [x["profit"] for x in daily]
    mean = sum(profits) / len(profits) if profits else 0
    var = sum((p - mean) ** 2 for p in profits) / len(profits) if profits else 0
    std = math.sqrt(var)
    sharpe = (mean / std * math.sqrt(periods)) if std > 0 else 0.0
    return {
        "net": round(net, 2), "final": round(final, 2), "hit": hit_count,
        "periods": periods, "bankrupt": bankrupt, "withdraw": round(withdraws, 2),
        "max_dd": round(max_dd * 100, 1), "sharpe": round(sharpe, 2),
        "avg_N": round(sum(x["N"] for x in daily) / periods, 1) if periods else 0,
    }

def pick_ge(x):
    return lambda v, s: [n for n, c in v.items() if c >= x]
def pick_lt(x):
    return lambda v, s: [n for n, c in v.items() if c < x]
def pick_eq(x):
    return lambda v, s: [n for n, c in v.items() if c == x]
def pick_top(k):
    def f(v, s):
        order = sorted(range(1, 50), key=lambda n: (-v[n], n))
        return order[:k]
    return f

results = []
for top_n in [5, 10, 15, 20]:
    for br in [0.25, 0.5, 0.75, 1.0]:
        # 票数阈值策略
        for x in range(1, 7):
            results.append((f"top{top_n}_ge{x}_br{br}", top_n, pick_ge(x), br))
        for x in range(2, 6):
            results.append((f"top{top_n}_lt{x}_br{br}", top_n, pick_lt(x), br))
        for x in range(0, 6):
            results.append((f"top{top_n}_eq{x}_br{br}", top_n, pick_eq(x), br))
        for k in [5, 10, 15, 20, 30]:
            results.append((f"top{top_n}_top{k}_br{br}", top_n, pick_top(k), br))

out = []
for name, top_n, fn, br in results:
    try:
        r = run(top_n, fn, br)
        r["name"] = name
        out.append(r)
    except Exception as e:
        out.append({"name": name, "net": None, "err": str(e)})

valid = [r for r in out if r.get("net") is not None]
valid.sort(key=lambda r: -r["net"])
print(f"=== 参数扫描完成：{len(valid)} 种组合（起始 {START_DATE}，共 {valid[0]['periods'] if valid else 0} 期）===\n")
print(f"{'算法':<28} {'净收益':>10} {'命中':>6} {'破产':>4} {'提取':>9} {'最大回撤%':>9} {'Sharpe':>7} {'均号数':>6}")
print("-" * 90)
for r in valid[:40]:
    print(f"{r['name']:<28} {r['net']:>10,.0f} {r['hit']:>4}/{r['periods']:<3} {r['bankrupt']:>4} {r['withdraw']:>9,.0f} {r['max_dd']:>8}% {r['sharpe']:>7} {r['avg_N']:>6}")

# 基准对比
print("\n=== 基准（当前线上）===")
for label, fn in [("ge4(买≥4票)", pick_ge(4)), ("lt4(买<4票)", pick_lt(4))]:
    r = run(10, fn, 0.5)
    print(f"{label:<28} {r['net']:>10,.0f} {r['hit']:>4}/{r['periods']:<3} {r['bankrupt']:>4} {r['withdraw']:>9,.0f} {r['max_dd']:>8}% {r['sharpe']:>7} {r['avg_N']:>6}")
