#!/usr/bin/env python3
"""多方案资金效率横向对比 — 等额归一化排名。

统一口径：每号1元等额，赔率47。对每个方案算：
  本金需求 / 本金收益率 / 最大回撤 / 收益回撤比 / 下注收益率 / 触发率。
按各指标独立标注最优值（不被绝对下注额误导）。
"""
import sys, os, json
from collections import defaultdict, OrderedDict

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)
import main

ODDS = 47
rows, cycle_maps, seq_labels = main._load_backtest_data()

# 方案定义：name, dims, offset, window, pick_rule（单变体）或 consensus(4变体)
SCHEMES = [
    {"name": "共识信号(4变体≥2票)", "consensus": True,
     "dims": ["season_type", "zodiac_color_type"]},
    {"name": "春夏秋冬单维", "dims": ["season_type"], "offset": 2, "window": 90, "rule": "union"},
    {"name": "头数单维", "dims": ["head_number"], "offset": -1, "window": 90, "rule": "union"},
    {"name": "生肖+头数", "dims": ["zodiac", "head_number"], "offset": -1, "window": 120, "rule": "ge2"},
    {"name": "核心6维", "dims": main.CORE_DIMS, "offset": 1, "window": 90, "rule": "ge2"},
    {"name": "五行+号码波色+红肖蓝肖绿肖", "dims": ["five_element", "wave_color", "zodiac_color_type"],
     "offset": 2, "window": 90, "rule": "union"},
]


def walkforward(dims, offset, window, pick_rule):
    dimset = set(dims)
    tn_cache = {}

    def tag_nums(dim, tag, zm):
        if dim == "zodiac":
            return [n for n in range(1, 50) if main._num_to_zodiac(n, zm) == tag]
        k = (dim, tag)
        if k not in tn_cache:
            tn_cache[k] = [n for n in range(1, 50) if main.match_labels(n, main.DEFAULT_ZODIAC).get(dim) == tag]
        return tn_cache[k]

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
        if pick_rule == "union":
            picks = sorted(vote.keys())
        else:
            th = int(pick_rule.replace("ge", ""))
            picks = sorted(n for n, c in vote.items() if c >= th)
        out.append(picks)
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


def consensus_walkforward(dims):
    variants = [(+2, 90), (+1, 60), (+2, 60), (+1, 90)]
    var_picks = {v: walkforward(dims, *v, "union") for v in variants}
    out = []
    for i in range(len(rows)):
        votes = defaultdict(int)
        for v, pl in var_picks.items():
            for n in pl[i]:
                votes[n] += 1
        out.append(sorted(n for n, c in votes.items() if c >= 2))
    return out


def analyze(name, picks_list):
    cum = 0.0; peak = 0.0; max_dd = 0.0
    max_N = 0; total_invest = 0.0; total_profit = 0.0
    trig = 0; hits = 0
    for i in range(len(rows)):
        open_num = int(rows[i]["source_number"])
        picks = picks_list[i]
        N = len(picks)
        if N == 0:
            continue
        trig += 1
        hit = 1 if open_num in picks else 0
        hits += hit
        profit = (ODDS - N) if hit else -N
        cum += profit
        total_invest += N
        total_profit += profit
        max_N = max(max_N, N)
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)
    capital_req = max_dd + max_N
    return {
        "name": name,
        "triggered": trig,
        "hit_rate": round(hits / trig * 100, 1) if trig else 0,
        "avg_N": round(total_invest / trig, 1) if trig else 0,
        "total_invest": round(total_invest, 0),
        "total_profit": round(total_profit, 0),
        "bet_roi": round(total_profit / total_invest * 100, 2) if total_invest else 0,
        "max_drawdown": round(max_dd, 0),
        "capital_required": round(capital_req, 0),
        "capital_roi": round(total_profit / capital_req * 100, 2) if capital_req else 0,
        "profit_dd_ratio": round(total_profit / max_dd, 2) if max_dd else 0,
    }


results = []
for s in SCHEMES:
    if s.get("consensus"):
        picks = consensus_walkforward(s["dims"])
    else:
        picks = walkforward(s["dims"], s["offset"], s["window"], s["rule"])
    results.append(analyze(s["name"], picks))

# 找各指标最优值（用于标注）
best = {
    "capital_roi": max(r["capital_roi"] for r in results),
    "profit_dd_ratio": max(r["profit_dd_ratio"] for r in results),
    "min_drawdown": min(r["max_drawdown"] for r in results),
    "min_capital": min(r["capital_required"] for r in results),
    "bet_roi": max(r["bet_roi"] for r in results),
}

print("=" * 100)
print("多方案资金效率横向对比（每号1元等额 · 赔率47 · 全历史 618 期）")
print("=" * 100)
print(f"{'方案':<22s} {'触发':>5s} {'命中':>6s} {'均号':>5s} {'下注额':>7s} {'净盈亏':>7s} "
      f"{'下注ROI':>7s} {'回撤':>6s} {'本金':>6s} {'本金ROI':>8s} {'收益/回撤':>8s}")
print("-" * 100)
for r in sorted(results, key=lambda x: -x["capital_roi"]):
    mk = lambda v, b: "★" if v == b else ""
    print(f"{r['name']:<22s} {r['triggered']:>5d} {r['hit_rate']:>5.1f}% {r['avg_N']:>5.1f} "
          f"{r['total_invest']:>7.0f} {r['total_profit']:>+7.0f} "
          f"{r['bet_roi']:>+6.2f}%{mk(r['bet_roi'], best['bet_roi'])} "
          f"{r['max_drawdown']:>6.0f} {r['capital_required']:>6.0f} "
          f"{r['capital_roi']:>+7.2f}%{mk(r['capital_roi'], best['capital_roi'])} "
          f"{r['profit_dd_ratio']:>+8.2f}{mk(r['profit_dd_ratio'], best['profit_dd_ratio'])}")

print("-" * 100)
print("★ = 该指标最优。本金ROI = 净盈亏/本金需求(最大回撤+单期最大投入)；收益/回撤 = 净盈亏/最大回撤。")
print()

# 结论
top = max(results, key=lambda x: x["capital_roi"])
top2 = max(results, key=lambda x: x["profit_dd_ratio"])
print(f"本金收益率最优：{top['name']}（{top['capital_roi']}%，本金仅 {top['capital_required']:.0f} 元）")
print(f"收益/回撤比最优：{top2['name']}（{top2['profit_dd_ratio']}）")

json.dump({"schemes": results, "best": best},
          open(os.path.join(BACKEND, "analysis", "compare_capital_efficiency.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)
print(f"\n已写 analysis/compare_capital_efficiency.json")
