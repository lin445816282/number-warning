#!/usr/bin/env python3
"""8码下注方案系统扫描 — 各种下注比例 × 方式 × 周期，多种子取平均。

目标：对比「随机8码」在不同下注比例序列、周期长度、暂停方式下的真实表现。
多种子(20)取平均，过滤单种子的随机运气，看方案的真实期望与波动。

关键：数学上赔率47<49期望恒为-4.08%，下注比例只改方差不改期望。
本扫描用真实演算验证这点，并找出「波动最小/亏得最稳」的方案。
"""
import sqlite3, random, os, json
from collections import Counter

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "number_warning.db")
START_DATE = "2022-01-01"
N, ODDS = 8, 47
SEEDS = list(range(1, 21))  # 20 个种子取平均

# 各种下注比例序列（6期，每号每期金额）
BET_PLANS = {
    "等额10": [10, 10, 10, 10, 10, 10],
    "当前10-10-20": [10, 10, 10, 20, 20, 20],
    "温和递增": [10, 10, 15, 15, 20, 20],
    "倍投折中": [10, 20, 30, 40, 50, 60],
    "激进倍投": [10, 20, 40, 80, 160, 320],
    "递减": [30, 25, 20, 15, 10, 5],
    "前重后轻": [20, 20, 20, 10, 10, 10],
    "斐波那契": [10, 10, 20, 30, 50, 80],
}


def load_draws():
    db = sqlite3.connect(DB, timeout=15)
    db.row_factory = sqlite3.Row
    rows = db.execute(
        "SELECT record_date, source_number FROM number_knowledge_record WHERE status=1 ORDER BY record_date"
    ).fetchall()
    db.close()
    dates, nums = [], []
    for r in rows:
        try:
            n = int(r["source_number"])
        except (ValueError, TypeError):
            continue
        if 1 <= n <= 49:
            dates.append(r["record_date"])
            nums.append(n)
    idx = 0
    for i, d in enumerate(dates):
        if d >= START_DATE:
            idx = i
            break
    return dates[idx:], nums[idx:]


def picks(round_no, seed):
    r = random.Random(seed * 100000 + round_no)
    return sorted(r.sample(range(1, 50), N))


def backtest(seed, nums, bet_plan, K, pause):
    """返回 (pnl, rounds, hits, stops, max_dd)"""
    n = len(nums)
    i, round_no = 0, 0
    state = "NEW"
    ps, pset, held, invest = [], set(), 0, 0
    pnl, hits, stops, cum, peak = 0, 0, 0, 0, 0
    max_dd = 0
    while i < n:
        if state == "NEW":
            round_no += 1
            ps = picks(round_no, seed)
            pset = set(ps)
            held, invest = 0, 0
            state = "TRACKING"
        elif state == "TRACKING":
            held += 1
            bet = bet_plan[held - 1] if held - 1 < len(bet_plan) else bet_plan[-1]
            invest += N * bet
            if nums[i] in pset:
                pnl += ODDS * bet - invest
                hits += 1
                cum += ODDS * bet - invest
                peak = max(peak, cum)
                max_dd = max(max_dd, peak - cum)
                state = "NEW"
            elif held >= K:
                pnl -= invest
                stops += 1
                cum -= invest
                peak = max(peak, cum)
                max_dd = max(max_dd, peak - cum)
                if pause:
                    state = "PAUSED"
                else:
                    state = "NEW"
            i += 1
        elif state == "PAUSED":
            if nums[i] in pset:
                state = "NEW"
            i += 1
    return pnl, round_no, hits, stops, max_dd


def scan():
    dates, nums = load_draws()
    print(f"数据 {dates[0]} ~ {dates[-1]}, {len(nums)} 期, {len(SEEDS)} 种子")
    print("=" * 100)

    # 方案空间：bet_plan × K × pause
    configs = []
    for bname, plan in BET_PLANS.items():
        for K in [4, 6, 8]:
            for pause in [True, False]:
                configs.append((bname, plan, K, pause))

    results = []
    for bname, plan, K, pause in configs:
        pnls = []
        for seed in SEEDS:
            pnl, rounds, hits, stops, mdd = backtest(seed, nums, plan, K, pause)
            pnls.append(pnl)
        avg = sum(pnls) / len(pnls)
        best = max(pnls)
        worst = min(pnls)
        pos = sum(1 for p in pnls if p > 0)
        # 标准差
        import math
        var = sum((p - avg) ** 2 for p in pnls) / len(pnls)
        std = math.sqrt(var)
        results.append({
            "bet": bname, "K": K, "pause": pause,
            "avg": round(avg, 0), "std": round(std, 0),
            "best": best, "worst": worst, "pos": pos,
        })

    # 排序：按平均盈亏降序
    results.sort(key=lambda x: -x["avg"])

    print(f"{'方案':<16} {'周期':>4} {'暂停':>4} {'平均盈亏':>9} {'标准差':>8} {'最好':>7} {'最差':>8} {'正种子':>6}")
    for r in results:
        pn = "✓" if r["pause"] else "✗"
        print(f"{r['bet']:<16} {r['K']:>4} {pn:>4} {r['avg']:>9.0f} {r['std']:>8.0f} "
              f"{r['best']:>7} {r['worst']:>8} {r['pos']:>4}/{len(SEEDS)}")

    # 总结
    print("=" * 100)
    all_avg = [r["avg"] for r in results]
    print(f"全部 {len(results)} 种方案：平均盈亏范围 {min(all_avg):.0f} ~ {max(all_avg):.0f}")
    pos_plans = [r for r in results if r["avg"] > 0]
    print(f"平均为正的方案：{len(pos_plans)} 个 {'（存在！但需看是否种子运气）' if pos_plans else '（0个，全部负期望）'}")

    out = {
        "data_range": f"{dates[0]}~{dates[-1]}", "seeds": len(SEEDS),
        "results": results,
    }
    json.dump(out, open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                     "analysis", "bet_plan_scan.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"\n已写 analysis/bet_plan_scan.json")


if __name__ == "__main__":
    scan()
