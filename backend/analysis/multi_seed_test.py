# -*- coding: utf-8 -*-
"""固定下单 多种子批量回测 —— 验证「换随机种子」能否改变负期望。
复用主程序核心逻辑（不落库），跑 N 组种子，统计盈亏分布。
"""
import sqlite3, random, os
from collections import Counter

DB = os.path.join(os.path.dirname(__file__), "data", "number_warning.db")
START_DATE = "2022-01-01"
K, N, ODDS = 6, 8, 47
BET_PLAN = [10, 10, 10, 20, 20, 20]


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
    # 截取起始日期
    idx = 0
    for i, d in enumerate(dates):
        if d >= START_DATE:
            idx = i
            break
    return dates[idx:], nums[idx:]


def picks(round_no, seed):
    r = random.Random(seed * 100000 + round_no)
    return sorted(r.sample(range(1, 50), N))


def backtest(seed, dates, nums):
    """返回 (total_pnl, rounds, hits, stops, pauses)"""
    n = len(nums)
    i, round_no = 0, 0
    state = "NEW"
    ps, pset, held, invest = [], set(), 0, 0
    total_pnl, hits, stops, pauses = 0, 0, 0, 0
    while i < n:
        if state == "NEW":
            round_no += 1
            ps = picks(round_no, seed)
            pset = set(ps)
            held, invest = 0, 0
            state = "TRACKING"
        elif state == "TRACKING":
            held += 1
            bet = BET_PLAN[held - 1]
            invest += N * bet
            if nums[i] in pset:
                pnl = ODDS * bet - invest
                total_pnl += pnl
                hits += 1
                state = "NEW"
            elif held >= K:
                total_pnl -= invest
                stops += 1
                state = "PAUSED"
            i += 1
        elif state == "PAUSED":
            if nums[i] in pset:
                pauses += 1
                state = "NEW"
            i += 1
    return total_pnl, round_no, hits, stops, pauses


def main():
    dates, nums = load_draws()
    print(f"数据: {dates[0]} ~ {dates[-1]}, 共 {len(nums)} 期")
    print(f"方案: 随机8码 倍投{BET_PLAN} 6期周期 47赔率")
    print("=" * 60)

    results = []
    for seed in range(1, 101):   # 100 组种子
        pnl, rounds, hits, stops, pauses = backtest(seed, dates, nums)
        results.append((seed, pnl, rounds, hits, stops, pauses))

    pnls = [r[1] for r in results]
    pos = [r for r in results if r[1] > 0]
    zero = [r for r in results if r[1] == 0]
    neg = [r for r in results if r[1] < 0]

    print(f"种子数: {len(results)}")
    print(f"正收益: {len(pos)} 组 | 持平: {len(zero)} 组 | 负收益: {len(neg)} 组")
    print(f"平均盈亏: {sum(pnls)/len(pnls):.1f} 元")
    print(f"中位数: {sorted(pnls)[len(pnls)//2]:.1f} 元")
    print(f"最好: {max(pnls):.0f} 元 (seed={max(results, key=lambda x: x[1])[0]})")
    print(f"最差: {min(pnls):.0f} 元 (seed={min(results, key=lambda x: x[1])[0]})")
    print("-" * 60)
    print("正收益的种子明细（前20，按盈亏降序）:")
    pos_sorted = sorted(pos, key=lambda x: -x[1])
    for seed, pnl, rounds, hits, stops, pauses in pos_sorted[:20]:
        hr = hits / (hits + stops) * 100 if (hits + stops) else 0
        print(f"  seed={seed:>3}  盈亏={pnl:>6}  轮数={rounds:>3}  命中={hits}  止损={stops}  暂停={pauses}  命中率={hr:.1f}%")
    print("-" * 60)
    print("负收益最狠的5组:")
    for seed, pnl, rounds, hits, stops, pauses in sorted(neg, key=lambda x: x[1])[:5]:
        print(f"  seed={seed:>3}  盈亏={pnl:>6}  命中={hits}  止损={stops}")


if __name__ == "__main__":
    main()
