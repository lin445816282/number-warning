#!/usr/bin/env python3
"""BH-FDR 多重比较校正 — 对 190 维度组合的共识信号做二项检验，筛出真信号。

每个组合：买 avg_n 号，命中 hits/periods，随机基准 p0 = avg_n/49。
二项检验（单侧：命中率 >= 随机基准）得 p 值，BH 校正得 q 值。
q < 0.05 = 在 190 次多重比较下仍显著（非随机波动）。
"""
import sys, os, json
from collections import defaultdict
from itertools import combinations

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)
import main

try:
    from scipy.stats import binom
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

ODDS = 47
VARIANTS = [(+2, 90), (+1, 60), (+2, 60), (+1, 90)]
rows, cycle_maps, seq_labels = main._load_backtest_data()
dates = [r["record_date"] for r in rows]
open_nums = [int(r["source_number"]) for r in rows]
N_TOTAL = len(rows)
tn_cache = {}

def tag_nums(dim, tag, zm):
    if dim == "zodiac":
        return [n for n in range(1, 50) if main._num_to_zodiac(n, zm) == tag]
    k = (dim, tag)
    if k not in tn_cache:
        tn_cache[k] = [n for n in range(1, 50) if main.match_labels(n, main.DEFAULT_ZODIAC).get(dim) == tag]
    return tn_cache[k]

def run_walkforward(dims, offset, window):
    dimset = set(dims)
    last_seen = {}; sample = {}; gap_hist = {}; out = []
    for i in range(N_TOTAL):
        seq = i + 1
        on, labels, zm = seq_labels[i]
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

def eval_pval(dims):
    var_picks = {v: run_walkforward(dims, *v) for v in VARIANTS}
    hits = 0; periods = 0; total_n = 0
    for i in range(N_TOTAL):
        votes = defaultdict(int)
        for v, pl in var_picks.items():
            for n in pl[i]:
                votes[n] += 1
        picks = [n for n, c in votes.items() if c >= 2]
        if not picks:
            continue
        periods += 1
        total_n += len(picks)
        if open_nums[i] in picks:
            hits += 1
    if periods == 0:
        return None
    avg_n = total_n / periods
    p0 = avg_n / 49.0
    # 二项检验：P(X >= hits)
    if HAS_SCIPY:
        p = binom.sf(hits - 1, periods, p0)
    else:
        # 正态近似（连续性校正）
        import math
        mu = periods * p0
        sigma = math.sqrt(periods * p0 * (1 - p0))
        z = (hits - 0.5 - mu) / sigma if sigma > 0 else 0
        p = 0.5 * math.erfc(z / math.sqrt(2))
    alpha = hits / periods - p0
    return {"hits": hits, "periods": periods, "avg_n": round(avg_n, 1),
            "hit_rate": round(hits / periods * 100, 1), "p0": round(p0 * 100, 2),
            "alpha": round(alpha * 100, 2), "p": p}


def bh_fdr(pvals):
    """BH 校正，返回 q 值列表（与 pvals 同序）。"""
    m = len(pvals)
    idx = sorted(range(m), key=lambda i: pvals[i])
    q = [0.0] * m
    prev = 1.0
    for rank in range(m - 1, -1, -1):
        i = idx[rank]
        qv = pvals[i] * m / (rank + 1)
        qv = min(qv, prev)
        q[i] = qv
        prev = qv
    return q


def scan():
    dims_all = list(main.DIM_NAMES.keys())
    combos = list(combinations(dims_all, 2))
    print(f"维度组合 {len(combos)} 种，scipy={HAS_SCIPY}")
    results = []
    for idx, combo in enumerate(combos):
        r = eval_pval(list(combo))
        if r:
            r["dims"] = list(combo)
            results.append(r)
        if (idx + 1) % 50 == 0:
            print(f"  进度 {idx+1}/{len(combos)} ...", flush=True)

    pvals = [r["p"] for r in results]
    qvals = bh_fdr(pvals)
    for r, q in zip(results, qvals):
        r["q"] = q

    results.sort(key=lambda x: x["q"])
    print("=" * 95)
    print("BH-FDR 校正后 q < 0.05 的组合（多重比较下仍显著）:")
    print(f"{'组合':<24} {'命中率':>7} {'均号':>5} {'随机p0':>7} {'超额':>7} {'p值':>9} {'q值':>9}")
    sig = [r for r in results if r["q"] < 0.05]
    for r in sig:
        name = f"{main.DIM_NAMES[r['dims'][0]]}+{main.DIM_NAMES[r['dims'][1]]}"
        print(f"{name:<24} {r['hit_rate']:>6}% {r['avg_n']:>5} {r['p0']:>6}% {r['alpha']:>6}% "
              f"{r['p']:>8.4f} {r['q']:>8.4f}")
    if not sig:
        print("  （无组合 q<0.05）")

    print("=" * 95)
    print("Top3 候选的 FDR 判定:")
    top3_sets = [{"前后肖", "白边黑中"}, {"白边黑中", "红肖蓝肖绿肖"}, {"五行", "白边黑中"}]
    for r in results:
        s = set(main.DIM_NAMES[d] for d in r["dims"])
        if s in top3_sets:
            name = f"{main.DIM_NAMES[r['dims'][0]]}+{main.DIM_NAMES[r['dims'][1]]}"
            verdict = "✅ 显著(真信号)" if r["q"] < 0.05 else "⚠️ 未过FDR(可能随机)"
            print(f"  {name:<22} p={r['p']:.4f} q={r['q']:.4f} → {verdict}")

    out = {
        "data_range": f"{dates[0]}~{dates[-1]}", "total_periods": N_TOTAL,
        "total_combos": len(combos), "scipy": HAS_SCIPY,
        "significant_q005": [
            {"dims": r["dims"], "hit_rate": r["hit_rate"], "avg_n": r["avg_n"],
             "alpha": r["alpha"], "p": r["p"], "q": r["q"]} for r in sig
        ],
    }
    json.dump(out, open(os.path.join(BACKEND, "analysis", "dim_combo_fdr.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"\n已写 analysis/dim_combo_fdr.json")


if __name__ == "__main__":
    scan()
