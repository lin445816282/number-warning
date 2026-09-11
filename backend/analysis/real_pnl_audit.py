#!/usr/bin/env python3
"""真实盈亏口径审计 — 共识信号的资金真相。

回答一个被账面数字掩盖的问题：共识信号「+9382 账面盈亏」背后，
到底需要多少本金？最大会亏多少？真实的年化/本金收益率是多少？

口径（等额每号1元，赔率47）：
  每期买 N 号投入 N 元；命中净赚 47-N；未命中净亏 N。
  累计盈亏曲线 → 最大回撤 → 本金需求 = 最大回撤 + 单期最大投入。
"""
import sys, os, json
from collections import defaultdict, OrderedDict

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)
import main

ODDS = 47
dims = ["season_type", "zodiac_color_type"]
VARIANTS = [(+2, 90), (+1, 60), (+2, 60), (+1, 90)]

rows, cycle_maps, seq_labels = main._load_backtest_data()
dimset = set(dims)
tn_cache = {}

def tag_nums(dim, tag, zm):
    if dim == "zodiac":
        return [n for n in range(1, 50) if main._num_to_zodiac(n, zm) == tag]
    k = (dim, tag)
    if k not in tn_cache:
        tn_cache[k] = [n for n in range(1, 50) if main.match_labels(n, main.DEFAULT_ZODIAC).get(dim) == tag]
    return tn_cache[k]

def run_walkforward(offset, window):
    last_seen = {}; sample = {}; gap_hist = {}; out = []
    for i in range(len(rows)):
        seq = i + 1
        open_num, labels, zm = seq_labels[i]
        vote = {}
        for (dim, tag), ls in last_seen.items():
            gap = seq - ls
            hm = main._window_hist_max(gap_hist, (dim, tag), seq, window)
            if sample.get((dim, tag), 0) >= 2 and gap >= hm - offset:
                for n in tag_nums(dim, tag, zm):
                    vote[n] = vote.get(n, 0) + 1
        out.append(sorted(vote.keys()))
        for dim, tag in labels.items():
            if not tag or dim not in dimset:
                continue
            k = (dim, tag)
            if k in last_seen:
                gap = seq - last_seen[k]
                sample[k] = sample.get(k, 0) + 1
                gap_hist.setdefault(k, []).append((seq, gap))
            else:
                sample[k] = 1
            last_seen[k] = seq
    return out

var_picks = {v: run_walkforward(*v) for v in VARIANTS}
daily = []  # (date, N, profit, cum)
for i in range(len(rows)):
    date = rows[i]["record_date"]
    open_num = int(rows[i]["source_number"])
    votes = defaultdict(int)
    for v, pl in var_picks.items():
        for n in pl[i]:
            votes[n] += 1
    picks = [n for n, c in votes.items() if c >= 2]
    if not picks:
        continue
    N = len(picks)
    hit = 1 if open_num in picks else 0
    profit = (ODDS - N) if hit else -N
    daily.append((date, N, profit))

# 累计盈亏曲线
cum = 0.0
peak = 0.0
max_dd = 0.0
max_N = 0
total_invest = 0.0
total_profit = 0.0
wins = 0
for date, N, profit in daily:
    cum += profit
    total_invest += N
    total_profit += profit
    max_N = max(max_N, N)
    if profit > 0:
        wins += 1
    peak = max(peak, cum)
    max_dd = max(max_dd, peak - cum)

trig = len(daily)
hit_cnt = sum(1 for _, N, p in daily if p > 0)
capital_req = max_dd + max_N  # 本金需求 = 最大回撤 + 单期最大投入

# 按年折算（数据跨度）
from datetime import datetime
d0 = datetime.strptime(rows[0]["record_date"], "%Y-%m-%d")
d1 = datetime.strptime(rows[-1]["record_date"], "%Y-%m-%d")
years = (d1 - d0).days / 365.25

# 按月盈亏
monthly = OrderedDict()
for date, N, p in daily:
    m = monthly.setdefault(date[:7], {"invest": 0, "profit": 0, "n": 0})
    m["invest"] += N; m["profit"] += p; m["n"] += 1

print("=" * 70)
print("真实盈亏口径审计 · 共识信号「春夏秋冬+红肖蓝肖绿肖 4变体≥2票」")
print(f"数据 {rows[0]['record_date']} ~ {rows[-1]['record_date']}（{years:.1f} 年）")
print("=" * 70)
print(f"触发期数         : {trig} 期（命中 {hit_cnt} 期，命中率 {hit_cnt/trig*100:.1f}%）")
print(f"单期买号         : 平均 {total_invest/trig:.1f} 号，最大 {max_N} 号")
print()
print(f"累计下注额(总投入): {total_invest:,.0f} 元")
print(f"累计净盈亏       : {total_profit:+,.0f} 元")
print(f"下注收益率       : {total_profit/total_invest*100:+.2f}%")
print()
print(f"最大回撤         : {max_dd:,.0f} 元")
print(f"本金需求         : {capital_req:,.0f} 元（= 最大回撤 {max_dd:,.0f} + 单期最大投入 {max_N}）")
print(f"本金收益率       : {total_profit/capital_req*100:+.2f}%")
print(f"年化本金收益率   : {total_profit/capital_req/years*100:+.2f}% / 年")
print()
print("=" * 70)
print("月度盈亏（下注额 → 净盈亏）")
print("=" * 70)
for k, m in monthly.items():
    bar = "█" * max(1, int(abs(m["profit"]) / 50))
    sign = "+" if m["profit"] >= 0 else "-"
    print(f"{k}  投入{m['invest']:>5.0f}  {sign}{abs(m['profit']):>6.0f}  {bar}")

out = {
    "signal": "共识信号 4变体≥2票",
    "data_range": f"{rows[0]['record_date']}~{rows[-1]['record_date']}",
    "years": round(years, 2),
    "triggered": trig, "hits": hit_cnt, "hit_rate": round(hit_cnt/trig, 4),
    "avg_N": round(total_invest/trig, 2), "max_N": max_N,
    "total_invest": round(total_invest, 2),
    "total_profit": round(total_profit, 2),
    "bet_roi": round(total_profit/total_invest, 4),
    "max_drawdown": round(max_dd, 2),
    "capital_required": round(capital_req, 2),
    "capital_roi": round(total_profit/capital_req, 4),
    "annual_capital_roi": round(total_profit/capital_req/years, 4),
}
json.dump(out, open(os.path.join(BACKEND, "analysis", "real_pnl_audit.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"\n已写 analysis/real_pnl_audit.json")
