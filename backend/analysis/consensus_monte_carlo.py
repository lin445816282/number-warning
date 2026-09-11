#!/usr/bin/env python3
"""共识信号蒙特卡洛 bootstrap：把点估计升级成概率分布。

回答三个之前没回答的硬问题：
1. 这个超额(+4.7%)有多大可能是运气？→ 参数化 bootstrap p 值（H0=纯随机）
2. 净收益的真实区间？→ 非参数 bootstrap 95% CI + 亏损概率
3. 最坏回撤到底多坏？→ 块 bootstrap 回撤分布

口径：共识信号「春夏秋冬+红肖蓝肖绿肖 4变体≥2票」，等额每号1元，赔率47，
只统计触发期(N>0)，空仓期不计入。与 _consensus_health 完全一致。

用法：cd backend && python3 analysis/consensus_monte_carlo.py
输出：analysis/consensus_monte_carlo.json + .md
"""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import main as M

DIMS = ["season_type", "zodiac_color_type"]
VARIANTS = [(+2, 90), (+1, 60), (+2, 60), (+1, 90)]
ODDS = M.SCHEME_ODDS  # 47
N_SIM = 20000
SEED = 20260911
BLOCK = 10  # 块 bootstrap 块长（保持连空/连中的时序结构）


def build_daily():
    """复用 _consensus_health 的 walk-forward 逻辑，提取共识信号历史触发序列 (N, hit)。"""
    dims = DIMS
    rows, cycle_maps, seq_labels = M._load_backtest_data()
    dimset = set(dims)
    tn_cache = {}

    def tag_nums(dim, tag, zm):
        if dim == "zodiac":
            return [n for n in range(1, 50) if M._num_to_zodiac(n, zm) == tag]
        k = (dim, tag)
        if k not in tn_cache:
            tn_cache[k] = [n for n in range(1, 50) if M.match_labels(n, M.DEFAULT_ZODIAC).get(dim) == tag]
        return tn_cache[k]

    def run_walkforward(offset, window):
        last_seen = {}; sample = {}; gap_hist = {}; out = []
        for i in range(len(rows)):
            seq = i + 1
            open_num, labels, zm = seq_labels[i]
            vote = {}
            for (dim, tag), ls in last_seen.items():
                gap = seq - ls
                hm = M._window_hist_max(gap_hist, (dim, tag), seq, window)
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
    from collections import defaultdict
    daily = []
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
        daily.append((date, N, hit))
    return daily


def max_drawdown(profits):
    """给定收益序列，算最大回撤。"""
    peak = 0.0
    dd = 0.0
    cum = 0.0
    for p in profits:
        cum += p
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    return dd


def block_bootstrap_indices(n, block, rng):
    """块 bootstrap：把序列切成块，有放回重采样块，保持块内时序。"""
    n_blocks = (n + block - 1) // block
    block_starts = list(range(0, n, block))
    chosen = rng.integers(0, len(block_starts), size=n_blocks)
    idx = []
    for c in chosen:
        s = block_starts[c]
        idx.extend(range(s, min(s + block, n)))
    return np.array(idx[:n])


def main():
    t0 = time.time()
    daily = build_daily()
    n = len(daily)
    dates = [d[0] for d in daily]
    Ns = np.array([d[1] for d in daily], dtype=float)
    hits = np.array([d[2] for d in daily], dtype=float)

    # 观察值
    actual_profit = float(np.where(hits == 1, ODDS - Ns, -Ns).sum())
    actual_hit_rate = float(hits.mean())
    actual_avg_n = float(Ns.mean())
    actual_rand = actual_avg_n / 49.0
    actual_alpha = actual_hit_rate - actual_rand
    actual_dd = max_drawdown(np.where(hits == 1, ODDS - Ns, -Ns))

    rng = np.random.default_rng(SEED)

    # ===== 1. 参数化 bootstrap（H0 = 纯随机）：P(随机能赚这么多) =====
    p_i = Ns / 49.0  # 每期随机命中概率（随机基准）
    sim_hits = rng.random((N_SIM, n)) < p_i
    sim_profits_h0 = np.where(sim_hits, ODDS - Ns, -Ns).sum(axis=1)
    p_random = float((sim_profits_h0 >= actual_profit).mean())
    # 随机策略的净收益分布（用于对比）
    h0_profit_ci = np.percentile(sim_profits_h0, [2.5, 50, 97.5])
    # 随机策略的亏损概率
    h0_p_loss = float((sim_profits_h0 < 0).mean())

    # ===== 2. 非参数 bootstrap（实际策略）：净收益分布 =====
    idx = rng.integers(0, n, size=(N_SIM, n))
    boot_hits = hits[idx]
    boot_Ns = Ns[idx]
    boot_profits = np.where(boot_hits == 1, ODDS - boot_Ns, -boot_Ns).sum(axis=1)
    profit_ci = np.percentile(boot_profits, [2.5, 50, 97.5])
    p_loss = float((boot_profits < 0).mean())

    # ===== 3. 超额 alpha 的 bootstrap 95% CI =====
    boot_hr = boot_hits.mean(axis=1)
    boot_avg_n = boot_Ns.mean(axis=1)
    boot_alpha = boot_hr - boot_avg_n / 49.0
    alpha_ci = np.percentile(boot_alpha, [2.5, 50, 97.5])
    p_alpha_le0 = float((boot_alpha <= 0).mean())

    # ===== 4. 块 bootstrap：最大回撤分布 =====
    dd_samples = np.empty(N_SIM)
    for s in range(N_SIM):
        bi = block_bootstrap_indices(n, BLOCK, rng)
        seq_profits = np.where(hits[bi] == 1, ODDS - Ns[bi], -Ns[bi])
        dd_samples[s] = max_drawdown(seq_profits)
    dd_ci = np.percentile(dd_samples, [50, 90, 95, 99])

    # ===== 5. 年化口径 =====
    # 362 期 ≈ 20 个月（2025-01 ~ 2026-09），年化因子 = 12/20
    yrs = (len(dates) and (M.datetime.strptime(dates[-1], "%Y-%m-%d") - M.datetime.strptime(dates[0], "%Y-%m-%d")).days / 365.0) or 1.0
    annual_factor = 1.0 / yrs if yrs else 1.0

    result = {
        "meta": {
            "periods": n, "n_sim": N_SIM, "seed": SEED, "block": BLOCK,
            "odds": ODDS, "date_range": [dates[0], dates[-1]], "years": round(yrs, 2),
        },
        "observed": {
            "total_profit": round(actual_profit, 1),
            "hit_rate": round(actual_hit_rate, 4),
            "avg_n": round(actual_avg_n, 2),
            "rand_base": round(actual_rand, 4),
            "alpha": round(actual_alpha, 4),
            "max_drawdown": round(actual_dd, 1),
        },
        "luck_test": {
            "p_random_at_least_this_profit": round(p_random, 6),
            "interpretation": "P(纯随机策略净收益 ≥ 观察值)。<0.05 说明超额显著非运气；>0.1 说明可能是运气",
            "h0_profit_ci": [round(x, 1) for x in h0_profit_ci],
            "h0_p_loss": round(h0_p_loss, 4),
        },
        "profit_distribution": {
            "ci_95": [round(x, 1) for x in profit_ci],
            "median": round(float(profit_ci[1]), 1),
            "p_loss": round(p_loss, 4),
            "p_loss_interpretation": "P(该策略净收益 < 0)，即亏损概率",
        },
        "alpha_distribution": {
            "ci_95": [round(x, 4) for x in alpha_ci],
            "p_alpha_le0": round(p_alpha_le0, 4),
        },
        "drawdown_distribution": {
            "median": round(float(dd_ci[0]), 1),
            "p90": round(float(dd_ci[1]), 1),
            "p95": round(float(dd_ci[2]), 1),
            "p99": round(float(dd_ci[3]), 1),
        },
        "elapsed_sec": round(time.time() - t0, 1),
    }

    out_dir = os.path.dirname(os.path.abspath(__file__))
    os.makedirs(out_dir, exist_ok=True)
    json_path = os.path.join(out_dir, "consensus_monte_carlo.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # 打印关键结论
    print(f"=== 共识信号蒙特卡洛 bootstrap（{n} 期触发，{N_SIM} 次模拟）===")
    print(f"观察值：净收益 +{actual_profit:.0f} · 命中率 {actual_hit_rate*100:.1f}% · 超额 +{actual_alpha*100:.1f}% · 回撤 {actual_dd:.0f}")
    print(f"\n[1] 运气检验：P(纯随机赚这么多) = {p_random:.4f}  → {'✅ 显著非运气' if p_random < 0.05 else ('⚠️ 边缘' if p_random < 0.1 else '❌ 可能是运气')}")
    print(f"    随机策略净收益 95%区间: {h0_profit_ci[0]:.0f} ~ {h0_profit_ci[2]:.0f}（随机亏损概率 {h0_p_loss*100:.1f}%）")
    print(f"\n[2] 净收益分布 95% CI: {profit_ci[0]:.0f} ~ {profit_ci[2]:.0f}（中位数 {profit_ci[1]:.0f}）· 亏损概率 {p_loss*100:.1f}%")
    print(f"\n[3] 超额 alpha 95% CI: {alpha_ci[0]*100:+.2f}% ~ {alpha_ci[2]*100:+.2f}% · P(alpha≤0) = {p_alpha_le0*100:.1f}%")
    print(f"\n[4] 最大回撤分布：中位数 {dd_ci[0]:.0f} · P90 {dd_ci[1]:.0f} · P95 {dd_ci[2]:.0f} · P99 {dd_ci[3]:.0f}")
    print(f"\n耗时 {result['elapsed_sec']}s，已写 {json_path}")


if __name__ == "__main__":
    main()
