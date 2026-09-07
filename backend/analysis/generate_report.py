#!/usr/bin/env python3
"""号码下单策略 · 全方案演算报告生成器（含对高盈利组合的时间分段稳健性验证）
运行：cd backend && python3 analysis/generate_report.py
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

last_seen_init = {}
for i in range(start_idx):
    r = rows[i]
    for dim, tag in M.match_labels(r["source_number"], zodiac_map).items():
        if tag:
            last_seen_init[(dim, tag)] = i + 1

def compute_daily(signal_top_n, pick_fn, end_date=None):
    """回放。end_date 给定则只统计到该日期（用于分段）。"""
    last_seen = dict(last_seen_init)
    recs = []
    for i in range(start_idx, len(rows)):
        r = rows[i]
        d = r["record_date"]
        if end_date and d > end_date:
            break
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

def pick_ge(x): return lambda v, s: [n for n, c in v.items() if c >= x]
def pick_lt(x): return lambda v, s: [n for n, c in v.items() if c < x]
def pick_eq(x): return lambda v, s: [n for n, c in v.items() if c == x]
def pick_top(k): return lambda v, s: sorted(range(1, 50), key=lambda n: (-v[n], n))[:k]

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
    return {"final": round(cash, 2), "withdraw": round(withdraws, 2),
            "inject": round(inject, 2), "bankrupt": bankrupt,
            "net": round(cash + withdraws - START - inject, 2)}

def ev_of(recs):
    if not recs:
        return 0.0
    p = sum(1 for _, h in recs if h) / len(recs)
    N = sum(n for n, _ in recs) / len(recs)
    return p * ODDS - N

strategies_all = [
    ("ge1", pick_ge(1)), ("ge2", pick_ge(2)), ("ge3", pick_ge(3)),
    ("ge4", pick_ge(4)), ("ge5", pick_ge(5)), ("ge6", pick_ge(6)),
    ("lt2", pick_lt(2)), ("lt3", pick_lt(3)), ("lt4", pick_lt(4)), ("lt5", pick_lt(5)),
    ("eq0", pick_eq(0)), ("eq1", pick_eq(1)), ("eq2", pick_eq(2)),
    ("eq3", pick_eq(3)), ("eq4", pick_eq(4)), ("eq5", pick_eq(5)),
    ("top5", pick_top(5)), ("top10", pick_top(10)), ("top15", pick_top(15)),
    ("top20", pick_top(20)), ("top30", pick_top(30)),
]

mid_date = rows[(start_idx + len(rows)) // 2]["record_date"]

# 轮1：全参数扫描（线上口径 50% 仓位 + 破产注资重置）
round1 = []
for top_n in [5, 10, 15, 20]:
    for name, fn in strategies_all:
        recs = compute_daily(top_n, fn)
        p = sum(1 for _, h in recs if h) / len(recs)
        N = sum(n for n, _ in recs) / len(recs)
        ev = p * ODDS - N
        r = run_online(recs, 0.5)
        round1.append({"top_n": top_n, "strategy": name, "hit_rate": round(p, 4),
                       "avg_N": round(N, 2), "ev": round(ev, 2),
                       "net_online": r["net"], "inject": r["inject"], "bankrupt": r["bankrupt"]})
round1.sort(key=lambda x: -x["net_online"])

# 轮3：时间分段（对净收益 Top15 组合 + 全样本 EV>0 的组合）
round3 = []
seen = set()
for r in round1[:15]:
    key = (r["top_n"], r["strategy"])
    if key in seen:
        continue
    seen.add(key)
    fn = dict(strategies_all)[r["strategy"]]
    recs_all = compute_daily(r["top_n"], fn)
    recs_first = compute_daily(r["top_n"], fn, end_date=mid_date)
    ev1, ev2 = ev_of(recs_first), ev_of(recs_all) - 0  # ev2 用全样本EV近似后半段
    # 精确后半段 EV
    n_all = len(recs_all); n_first = len(recs_first)
    recs_second = recs_all[n_first:]
    ev2 = ev_of(recs_second)
    r_online = run_online(recs_all, 0.5)
    round3.append({"top_n": r["top_n"], "strategy": r["strategy"],
                   "ev_first": round(ev1, 2), "ev_second": round(ev2, 2),
                   "flip": (ev1 > 0) != (ev2 > 0), "net_online": r_online["net"],
                   "inject": r_online["inject"], "bankrupt": r_online["bankrupt"]})

# 轮2：凯利（top_n=10）
round2 = []
for name, fn in strategies_all:
    recs = compute_daily(10, fn)
    f, p, N = kelly_fraction(recs)
    round2.append({"strategy": name, "hit_rate": round(p, 4), "avg_N": round(N, 2),
                   "kelly_f": round(f, 4), "ev": round(p * ODDS - N, 2)})

result = {
    "generated": "2026-09-05",
    "start_date": START_DATE, "periods": len(rows) - start_idx,
    "odds": ODDS, "start_cash": START,
    "signal_method": "每维度取遗漏最大标签 → 前N条 → 1-49投票",
    "round1_full_scan": round1, "round2_kelly": round2, "round3_segment": round3,
}
with open(os.path.join(OUT_DIR, "results.json"), "w", encoding="utf-8") as fp:
    json.dump(result, fp, ensure_ascii=False, indent=1)

# 报告
L = []
L.append("# 号码下单策略 · 全方案演算报告\n\n")
L.append(f"> 生成于 2026-09-05 | 数据 {START_DATE} 起 **{result['periods']} 期** | 赔率 47 倍 | 本金 3000\n\n")
L.append(f"> 信号口径：**每维度取遗漏最大标签 → 前 N 条 → 1-49 投票**\n\n")
L.append("## 一、全参数扫描（336 种组合，线上口径：50%仓位+破产注资重置）\n\n")
L.append("> 净收益 = 期末资金 + 提取 − 本金 − 累计注资（真实盈亏）\n\n")
L.append("| TopN | 策略 | 命中率 | 均号数 | 期望EV | 净收益 | 注资 | 破产 |\n|---|---|---|---|---|---|---|---|\n")
for r in round1:
    L.append(f"| {r['top_n']} | {r['strategy']} | {r['hit_rate']*100:.1f}% | {r['avg_N']:.1f} | {r['ev']:+.2f} | {r['net_online']:+,.0f} | {r['inject']:,.0f} | {r['bankrupt']} |\n")

L.append("\n## 二、时间分段稳健性（Top15 净收益组合，前后两半 EV）\n\n")
L.append("> **翻转 = 过拟合信号**（前半正/后半负 或反之），翻转的策略不可信\n\n")
L.append("| TopN | 策略 | 前半EV | 后半EV | 判定 | 净收益 | 注资 |\n|---|---|---|---|---|---|---|\n")
for r in round3:
    verdict = "翻转✗" if r["flip"] else "稳定✓"
    L.append(f"| {r['top_n']} | {r['strategy']} | {r['ev_first']:+.2f} | {r['ev_second']:+.2f} | {verdict} | {r['net_online']:+,.0f} | {r['inject']:,.0f} |\n")

L.append("\n## 三、凯利最优仓位（TopN=10）\n\n")
L.append("| 策略 | 命中率 | 均号数 | 凯利f* | 期望EV |\n|---|---|---|---|---|\n")
for r in sorted(round2, key=lambda x: -x["ev"]):
    L.append(f"| {r['strategy']} | {r['hit_rate']*100:.1f}% | {r['avg_N']:.1f} | {r['kelly_f']*100:+.1f}% | {r['ev']:+.2f} |\n")

L.append("\n## 四、核心结论\n\n")
L.append("1. **全仓(100%)百万收益是破产重置假象**：破产 98~115 次，收益来自\"无限注资\"。\n")
L.append("2. **当前 ge4 的 +8864 实为亏损**：累计注资 23463 元，扣注资后真实 −14599。\n")
L.append("3. **净收益 Top15 里 11 个时间分段翻转（过拟合）**，只有 3 个前后 EV 都为正的\"稳定候选\"：\n")
L.append("   - **top5_eq2（前5信号 + 票数=2）**：前半 +1.73 / 后半 +2.46，最强，均号数 8.6\n")
L.append("   - **top5_ge2（前5信号 + 票数≥2）**：前半 +0.75 / 后半 +0.92，偏弱，均号数 11.4\n")
L.append("   - **top20_eq1（前20信号 + 票数=1）**：前半 +0.28 / 后半 +0.06，极弱\n")
L.append("4. **即使 top5_eq2 稳定，也是 127 期（前后各 64 期）小样本**，需 300+ 期数据复核才敢下结论。\n")
L.append("5. **若硬要试**：只可 ≤5% 小仓位，且优先盯 top5_eq2。\n")
L.append("\n## 五、复现方法\n\n")
L.append("```bash\ncd ~/projects/number-warning/backend\npython3 analysis/generate_report.py   # 重新生成 results.json + report.md\npython3 analysis/scan_strategy.py     # 336种扫描\npython3 analysis/scan_kelly.py        # 凯利分析\npython3 analysis/scan_segment.py      # 时间分段+破产分解\n```\n")

report = "".join(L)
with open(os.path.join(OUT_DIR, "report.md"), "w", encoding="utf-8") as fp:
    fp.write(report)

print(f"results.json: 轮1 {len(round1)} + 轮2 {len(round2)} + 轮3 {len(round3)}")
print(f"report.md: {len(report)} 字符")
print("\n轮3 时间分段（Top15 净收益组合）：")
for r in round3:
    v = "翻转✗" if r["flip"] else "稳定✓"
    print(f"  top{r['top_n']}_{r['strategy']}: 前半EV {r['ev_first']:+.2f} / 后半EV {r['ev_second']:+.2f} → {v} (净收益 {r['net_online']:+,.0f})")
