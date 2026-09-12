#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对比「开在后3位」时：停(止损) vs 继续(追买3肖) vs 继续+满12期止损 三种口径"""
import sqlite3, json

DB = "/home/xiaolin/projects/number-warning/backend/data/number_warning.db"
DEFAULT_ZODIAC = {
    "马": [1,13,25,37,49], "蛇": [2,14,26,38], "龙": [3,15,27,39],
    "兔": [4,16,28,40], "虎": [5,17,29,41], "牛": [6,18,30,42],
    "鼠": [7,19,31,43], "猪": [8,20,32,44], "狗": [9,21,33,45],
    "鸡": [10,22,34,46], "猴": [11,23,35,47], "羊": [12,24,36,48],
}
THRESHOLD = 12
MAX_TRACK = 6
BET_N = 3
K = 12

db = sqlite3.connect(DB)
db.row_factory = sqlite3.Row
cycle_maps = {}
for c in db.execute("SELECT id, zodiac_mapping FROM zodiac_number_cycle_config WHERE is_enable=1"):
    try:
        m = json.loads(c["zodiac_mapping"])
        cycle_maps[c["id"]] = m if m else DEFAULT_ZODIAC
    except Exception:
        cycle_maps[c["id"]] = DEFAULT_ZODIAC
rows = db.execute("SELECT * FROM number_knowledge_record WHERE status=1 ORDER BY record_date, id").fetchall()
db.close()

def num_to_zodiac(n, m):
    for z, nums in m.items():
        if n in nums:
            return z
    return None

def run(strategy):
    """strategy: 'stop' | 'continue' | 'continue_k'"""
    last_seen = {z: -1 for z in DEFAULT_ZODIAC}
    nums = {z: len(DEFAULT_ZODIAC[z]) for z in DEFAULT_ZODIAC}
    positions = {}       # zodiac -> {"held","invest"}
    back_three = set()   # 建仓时记录的后3位冷肖
    events = []
    equity = 0.0
    peak = 0.0
    maxdd = 0.0
    for i in range(len(rows)):
        r = rows[i]
        zm = cycle_maps.get(r["cycle_id"], DEFAULT_ZODIAC)
        z_open = num_to_zodiac(int(r["source_number"]), zm)
        if not z_open:
            continue
        seq = i + 1
        if not positions:
            gap = {z: seq - last_seen[z] for z in DEFAULT_ZODIAC}
            cold = [z for z in DEFAULT_ZODIAC if gap[z] >= THRESHOLD]
            cold.sort(key=lambda z: -gap[z])
            if len(cold) >= MAX_TRACK:
                for z in cold[:BET_N]:
                    positions[z] = {"held": 0, "invest": 0.0}
                back_three = set(cold[BET_N:MAX_TRACK])
            else:
                back_three = set()
        if not positions:
            last_seen[z_open] = seq
            continue

        if z_open in positions:
            # 命中：买的3肖中1个开
            hit_z = z_open
            event_pnl = 0.0
            hit_held = None
            for z in list(positions.keys()):
                pos = positions[z]
                pos["held"] += 1
                N = nums[z]
                pos["invest"] += N * 1.0
                equity -= N * 1.0
                if z == hit_z:
                    equity += 47.0
                    event_pnl += 47.0 - pos["invest"]
                    hit_held = pos["held"]
                else:
                    event_pnl += -pos["invest"]
                del positions[z]
            events.append({"result": "hit", "held": hit_held, "pnl": round(event_pnl,2)})
        elif z_open in back_three:
            # 开出「后3位」→ 关键分支
            if strategy == "stop":
                # 停：认亏已投，止损结束
                event_pnl = 0.0
                for z in list(positions.keys()):
                    pos = positions[z]
                    pos["held"] += 1
                    N = nums[z]
                    pos["invest"] += N * 1.0
                    equity -= N * 1.0
                    event_pnl += -pos["invest"]
                    del positions[z]
                events.append({"result": "stop_back", "held": None, "pnl": round(event_pnl,2)})
            else:
                # continue / continue_k：后3位开出，无视，继续追买3肖
                for z in list(positions.keys()):
                    pos = positions[z]
                    pos["held"] += 1
                    N = nums[z]
                    pos["invest"] += N * 1.0
                    equity -= N * 1.0
        else:
            # 无关肖开出 → 正常继续持有
            for z in list(positions.keys()):
                pos = positions[z]
                pos["held"] += 1
                N = nums[z]
                pos["invest"] += N * 1.0
                equity -= N * 1.0
                if strategy == "continue_k" and pos["held"] >= K:
                    # 满K期止损（把同事件其余持仓一起平）
                    event_pnl = -pos["invest"]
                    del positions[z]
                    for z2 in list(positions.keys()):
                        p2 = positions[z2]
                        event_pnl += -p2["invest"]
                        del positions[z2]
                    events.append({"result": "stop_k", "held": K, "pnl": round(event_pnl,2)})
                    break
        peak = max(peak, equity)
        maxdd = min(maxdd, equity - peak)
        last_seen[z_open] = seq

    total = sum(e["pnl"] for e in events)
    hits = sum(1 for e in events if e["result"] == "hit")
    stops = len(events) - hits
    helds = [e["held"] for e in events if e["held"]]
    pnls = [e["pnl"] for e in events]
    max_streak = cur = 0
    for p in pnls:
        if p < 0:
            cur += 1; max_streak = max(max_streak, cur)
        else:
            cur = 0
    return {
        "strategy": strategy, "events": len(events), "hits": hits, "stops": stops,
        "hit_rate": round(hits/len(events)*100,1) if events else 0,
        "total_pnl": round(total,2), "avg_pnl": round(total/len(events),2) if events else 0,
        "avg_held": round(sum(helds)/len(helds),1) if helds else 0,
        "max_loss_streak": max_streak, "max_drawdown": round(maxdd,2),
        "detail": events,
    }

if __name__ == "__main__":
    results = {s: run(s) for s in ["stop", "continue", "continue_k"]}
    for s, r in results.items():
        print(f"[{s:11s}] 事件{r['events']:3d} 命中{r['hits']:3d} 止损{r['stops']:3d} "
              f"命中率{r['hit_rate']:5.1f}% 总盈亏{r['total_pnl']:+8.2f} 均盈亏{r['avg_pnl']:+7.2f} "
              f"均持有{r['avg_held']:4.1f}期 最大连亏{r['max_loss_streak']} 最大回撤{r['max_drawdown']}")
    # 停策略的事件明细：看有多少「开在后3位止损」
    stop_back = [e for e in results["stop"]["detail"] if e["result"] == "stop_back"]
    print(f"\n[stop] 开在后3位→止损 {len(stop_back)} 次 / 共 {results['stop']['events']} 事件")
    # 首开分布：命中 vs 后3位
    all_first = {"买3肖开": results["continue"]["hits"], "后3位开": results["stop"]["stops"]}
    print(f"首开分布（continue口径命中 vs stop口径止损）: {all_first}")
