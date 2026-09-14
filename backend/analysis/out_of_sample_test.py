# -*- coding: utf-8 -*-
"""样本外验证：前半段(2022-2024)选种子 → 后半段(2025-2026)验证，看样本内冠军是否真能盈利。"""
import sqlite3, random, os

DB = os.path.join(os.path.dirname(__file__), "data", "number_warning.db")
SPLIT_DATE = "2025-01-01"
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
    return dates, nums


def picks(round_no, seed):
    r = random.Random(seed * 100000 + round_no)
    return sorted(r.sample(range(1, 50), N))


def backtest_range(seed, dates, nums):
    """在给定 date/nums 序列上跑回测，返回 (pnl, rounds, hits, stops)"""
    n = len(nums)
    i, round_no = 0, 0
    state = "NEW"
    ps, pset, held, invest = [], set(), 0, 0
    total, hits, stops = 0, 0, 0
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
                total += ODDS * bet - invest
                hits += 1
                state = "NEW"
            elif held >= K:
                total -= invest
                stops += 1
                state = "PAUSED"
            i += 1
        elif state == "PAUSED":
            if nums[i] in pset:
                state = "NEW"
            i += 1
    return total, round_no, hits, stops


def main():
    dates, nums = load_draws()
    split_idx = 0
    for i, d in enumerate(dates):
        if d >= SPLIT_DATE:
            split_idx = i
            break
    train_dates, train_nums = dates[:split_idx], nums[:split_idx]
    test_dates, test_nums = dates[split_idx:], nums[split_idx:]
    print(f"训练段: {train_dates[0]} ~ {train_dates[-1]}, {len(train_nums)} 期")
    print(f"验证段: {test_dates[0]} ~ {test_dates[-1]}, {len(test_nums)} 期")
    print("=" * 70)

    # 训练段：跑100组种子，记录盈亏
    train = {}
    for seed in range(1, 101):
        pnl, rnd, hits, stops = backtest_range(seed, train_dates, train_nums)
        train[seed] = pnl

    # 训练段选出冠军、前10、中位数
    ranked = sorted(train.items(), key=lambda x: -x[1])
    champ = ranked[0]
    top10 = ranked[:10]
    print(f"训练段冠军: seed={champ[0]} 盈亏={champ[1]:.0f}")
    print(f"训练段 Top10 种子: {[s for s, p in top10]}")
    print(f"训练段平均: {sum(train.values())/100:.0f} | 正收益种子: {sum(1 for p in train.values() if p>0)}/100")
    print("-" * 70)

    # 验证段：用训练段选出的种子跑
    print("验证段（样本外）结果:")
    print(f"{'种子':>5} {'训练段盈亏':>10} {'验证段盈亏':>10} {'验证段命中率':>10}")
    test_results = []
    for seed, train_pnl in top10:
        pnl, rnd, hits, stops = backtest_range(seed, test_dates, test_nums)
        hr = hits / (hits + stops) * 100 if (hits + stops) else 0
        test_results.append((seed, train_pnl, pnl, hr))
        print(f"{seed:>5} {train_pnl:>10.0f} {pnl:>10.0f} {hr:>9.1f}%")

    # 全100组的验证段表现
    all_test = []
    for seed in range(1, 101):
        pnl, rnd, hits, stops = backtest_range(seed, test_dates, test_nums)
        all_test.append(pnl)
    pos_test = sum(1 for p in all_test if p > 0)
    print("-" * 70)
    print(f"全100组验证段: 正收益 {pos_test}/100, 平均 {sum(all_test)/100:.0f}, "
          f"中位数 {sorted(all_test)[50]:.0f}")
    champ_test = backtest_range(champ[0], test_dates, test_nums)[0]
    print(f"训练段冠军 seed={champ[0]} 在验证段盈亏 = {champ_test:.0f} 元")


if __name__ == "__main__":
    main()
