#!/usr/bin/env python3
"""维度遗漏跟踪扫描 — 各维度 × 各遗漏期数阈值，过后跟注，找盈利组合。

逻辑：标签 t 遗漏 >= N 期后，下一期跟注该标签覆盖的号码（单期结算）。
命中赚 47-号码数，未中亏号码数。评估命中率超额 + 净盈亏 + FDR 显著性。

无前视：只用当期之前的信息判断是否跟注。
"""
import sys, os, json
from collections import defaultdict

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
rows, cycle_maps, seq_labels = main._load_backtest_data()
dates = [r["record_date"] for r in rows]
open_nums = [int(r["source_number"]) for r in rows]
N_TOTAL = len(rows)

# 各维度的标签→号码映射（预计算，标签号码数固定）
def dim_tag_nums(dim):
    """返回 {标签: [号码]} """
    out = {}
    for n in range(1, 50):
        tag = main.match_labels(n, main.DEFAULT_ZODIAC).get(dim)
        if tag:
            out.setdefault(tag, []).append(n)
    return out

def scan_dim(dim, threshold):
    """遗漏 >= threshold 期后跟注一期，返回统计。"""
    tag_nums = dim_tag_nums(dim)
    if not tag_nums:
        return None
    # 记录每期开出的号码属于哪个标签
    # 先算每期每个标签是否开出
    last_seen = {}  # tag -> 上次开出的期号(1-indexed)
    bets = []  # (期号, 号码数, 是否命中)
    for i in range(N_TOTAL):
        seq = i + 1
        n = open_nums[i]
        # 本期开出的标签
        cur_tag = main.match_labels(n, main.DEFAULT_ZODIAC).get(dim)
        # 跟注判定：那些遗漏 >= threshold 的标签，本期跟注
        for tag, nums in tag_nums.items():
            ls = last_seen.get(tag, 0)
            gap = seq - ls if ls > 0 else seq  # 从开赛算的遗漏
            if ls > 0 and (seq - ls) >= threshold:
                # 遗漏达到 threshold 期，本期跟注该标签
                hit = 1 if n in nums else 0
                bets.append((seq, len(nums), hit))
        # 更新 last_seen
        if cur_tag:
            last_seen[cur_tag] = seq

    if not bets:
        return None
    m = len(bets)
    hits = sum(1 for _, _, h in bets if h)
    total_n = sum(cnt for _, cnt, _ in bets)
    avg_n = total_n / m
    p0 = avg_n / 49.0
    alpha = hits / m - p0
    pnl = sum((ODDS - cnt) if h else -cnt for _, cnt, h in bets)
    if HAS_SCIPY:
        p = binom.sf(hits - 1, m, p0)
    else:
        import math
        mu = m * p0
        sigma = math.sqrt(m * p0 * (1 - p0))
        z = (hits - 0.5 - mu) / sigma if sigma > 0 else 0
        p = 0.5 * math.erfc(z / math.sqrt(2))
    return {
        "dim": dim, "threshold": threshold,
        "bets": m, "hits": hits,
        "hit_rate": round(hits / m * 100, 1),
        "avg_n": round(avg_n, 1), "p0": round(p0 * 100, 2),
        "alpha": round(alpha * 100, 2),
        "net_pnl": round(pnl, 1),
        "roi": round(pnl / total_n * 100, 2) if total_n else 0.0,
        "p": p,
    }


def bh_fdr(pvals):
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
    dims = list(main.DIM_NAMES.keys())
    thresholds = [3, 5, 8, 10, 12, 15, 20, 25, 30, 40]
    print(f"维度 {len(dims)} 个 × 阈值 {len(thresholds)} 个 = {len(dims)*len(thresholds)} 组合")
    print(f"数据 {dates[0]} ~ {dates[-1]}, {N_TOTAL} 期, scipy={HAS_SCIPY}")

    results = []
    for dim in dims:
        for th in thresholds:
            r = scan_dim(dim, th)
            if r:
                results.append(r)

    pvals = [r["p"] for r in results]
    qvals = bh_fdr(pvals)
    for r, q in zip(results, qvals):
        r["q"] = q

    results.sort(key=lambda x: x["q"])
    print("=" * 100)
    print("FDR 校正后 q<0.05 的组合（显著超随机）:")
    print(f"{'维度':<12} {'阈值':>4} {'跟注':>5} {'命中率':>7} {'均号':>5} {'随机p0':>7} {'超额':>7} {'净盈亏':>8} {'p':>8} {'q':>8}")
    sig = [r for r in results if r["q"] < 0.05]
    for r in sig:
        print(f"{main.DIM_NAMES[r['dim']]:<12} {r['threshold']:>4} {r['bets']:>5} {r['hit_rate']:>6}% "
              f"{r['avg_n']:>5} {r['p0']:>6}% {r['alpha']:>6}% {r['net_pnl']:>8} {r['p']:>7.4f} {r['q']:>7.4f}")
    if not sig:
        print("  （无组合 q<0.05）")

    print("=" * 100)
    print("按净盈亏降序 Top 20（不校正，供参考）:")
    by_pnl = sorted(results, key=lambda x: -x["net_pnl"])[:20]
    for r in by_pnl:
        print(f"{main.DIM_NAMES[r['dim']]:<12} 遗漏≥{r['threshold']:>3}期跟注  命中率{r['hit_rate']:>6}% "
              f"超额{r['alpha']:>6}% 净盈亏{r['net_pnl']:>8} q={r['q']:.4f}")

    out = {
        "data_range": f"{dates[0]}~{dates[-1]}", "total_periods": N_TOTAL,
        "significant_q005": [
            {"dim": r["dim"], "threshold": r["threshold"], "bets": r["bets"],
             "hit_rate": r["hit_rate"], "alpha": r["alpha"], "net_pnl": r["net_pnl"],
             "p": r["p"], "q": r["q"]} for r in sig
        ],
    }
    json.dump(out, open(os.path.join(BACKEND, "analysis", "gap_track_scan.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"\n已写 analysis/gap_track_scan.json")


if __name__ == "__main__":
    scan()
