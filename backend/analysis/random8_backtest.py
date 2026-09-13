#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""随机8码·6期跟踪 回测：随机选8码，跟踪最多6期，命中(8码中1个开出)即结束，6期未开止损。
每号1元，命中赔47(买8码命中只赔1个号=47)，未中亏当期投入8元。
数据源：number-warning 开奖数据 number_knowledge_record。
"""
import sqlite3, random, json

DB = "/home/xiaolin/projects/number-warning/backend/data/number_warning.db"

def load_draws():
    db = sqlite3.connect(DB)
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

def backtest(seed=42, per=1.0):
    """随机8码6期跟踪回测。返回 rounds 列表 + 汇总。"""
    dates, draws = load_draws()
    N = len(draws)
    rounds = []
    i = 0
    round_no = 0
    rng = random.Random(seed)
    while i < N:
        round_no += 1
        # 随机8码（用 round_no 做种子保证可复现）
        r = random.Random(seed * 100000 + round_no)
        picks = sorted(r.sample(range(1, 50), 8))
        picks_set = set(picks)
        start_date = dates[i]
        hit_period = 0
        hit_number = None
        result = "stop"
        # 跟踪最多6期
        max_periods = min(6, N - i)
        for k in range(1, max_periods + 1):
            d = draws[i + k - 1]
            if d in picks_set:
                hit_period = k
                hit_number = d
                result = "hit"
                break
        # 盈亏：命中赚 47*per - 8*per*hit_period，止损亏 8*per*6
        if result == "hit":
            pnl = 47 * per - 8 * per * hit_period
            end_date = dates[i + hit_period - 1]
            rounds.append({
                "round": round_no, "start": start_date, "end": end_date,
                "picks": picks, "hit_period": hit_period, "hit_number": hit_number,
                "result": "hit", "pnl": round(pnl, 2),
            })
            i += hit_period  # 命中后，下一轮从命中后一天开始
        else:
            pnl = -8 * per * max_periods
            end_date = dates[i + max_periods - 1]
            rounds.append({
                "round": round_no, "start": start_date, "end": end_date,
                "picks": picks, "hit_period": 0, "hit_number": None,
                "result": "stop", "pnl": round(pnl, 2),
            })
            i += max_periods  # 止损后，下一轮从6期后开始
    # 汇总
    total = sum(r["pnl"] for r in rounds)
    hits = sum(1 for r in rounds if r["result"] == "hit")
    stops = len(rounds) - hits
    hit_rate = hits / len(rounds) * 100 if rounds else 0
    # 命中分布（第几期）
    from collections import Counter
    hit_dist = Counter(r["hit_period"] for r in rounds if r["hit_period"] > 0)
    # 盈利分布
    profit_rounds = sum(1 for r in rounds if r["pnl"] > 0)
    loss_rounds = sum(1 for r in rounds if r["pnl"] <= 0)
    return {
        "dates": dates, "total_days": N,
        "date_range": f"{dates[0]} ~ {dates[-1]}" if dates else "",
        "rounds": len(rounds), "hits": hits, "stops": stops,
        "hit_rate": round(hit_rate, 2),
        "total_pnl": round(total, 2),
        "avg_pnl": round(total / len(rounds), 2) if rounds else 0,
        "hit_dist": dict(sorted(hit_dist.items())),
        "profit_rounds": profit_rounds, "loss_rounds": loss_rounds,
        "detail": rounds,
    }

if __name__ == "__main__":
    r = backtest()
    print(f"数据范围: {r['date_range']}  共 {r['total_days']} 天")
    print(f"总轮数: {r['rounds']}  命中 {r['hits']} 轮  止损 {r['stops']} 轮")
    print(f"命中率: {r['hit_rate']}%  (理论 8码6期 = 65.7%)")
    print(f"总盈亏: {r['total_pnl']:+} 元 (每号1元)  平均每轮 {r['avg_pnl']:+} 元")
    print(f"盈利轮 {r['profit_rounds']} / 亏损轮 {r['loss_rounds']}")
    print(f"命中分布(第几期开): {r['hit_dist']}")
    # 理论期望
    print(f"\n理论单轮期望(8码6期, 每号1元赔47) ≈ -1.31 元")
