#!/usr/bin/env python3
"""时间分段稳健性审计：把 617 期切成前后两半，验证 top 信号在后半段是否依然有超额。

关键问题：候选信号（头数 union / 生肖+头数 ge2 等）是否只在前半段有效（结构突变前的伪信号）？
结论口径：后半段 alpha 必须 > 0 且不显著缩水，才算时间稳健真信号。
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import main as M

TOP = [
    ("头数 off-1 w90", ["head_number"], -1, 90, "union"),
    ("头数 off0 w90", ["head_number"], 0, 90, "union"),
    ("头数+红蓝绿肖 off0 w90", ["head_number", "zodiac_color_type"], 0, 90, "union"),
    ("头数+红蓝绿肖 off1 w90", ["head_number", "zodiac_color_type"], 1, 90, "union"),
    ("生肖+头数 ge2 off0 w90", ["zodiac", "head_number"], 0, 90, "ge2"),
    ("尾数+大小单双 ge2 off2 w120", ["tail_number", "size_odd_even"], 2, 120, "ge2"),
    ("头数+春夏秋冬 off2 w60", ["head_number", "season_type"], 2, 60, "union"),
    ("波色+红蓝绿肖 off1 w60", ["wave_color", "zodiac_color_type"], 1, 60, "union"),
    ("头数 off-1 w60", ["head_number"], -1, 60, "union"),
    ("头数+大小单双 off1 w120", ["head_number", "size_odd_even"], 1, 120, "union"),
]

data = M._load_backtest_data()
rows, cycle_maps, seq_labels = data
n = len(rows)
mid = n // 2
print(f"总期数 {n}，前半 {mid} 期，后半 {n - mid} 期")
print(f"前半: {rows[0]['record_date']} ~ {rows[mid-1]['record_date']}")
print(f"后半: {rows[mid]['record_date']} ~ {rows[-1]['record_date']}")
print()
print(f"{'方案':<28}{'| 全程alpha':>10}{'| 前半alpha':>10}{'| 后半alpha':>10}{'| 后半触发':>8}{'| 后半hit%':>8}{'| 随机%':>6}")
print("-" * 90)

for name, dims, off, w, pr in TOP:
    full = M._backtest_scheme(dims, off, w, data=data, pick_rule=pr)
    half1_data = (rows[:mid], cycle_maps, seq_labels[:mid])
    half2_data = (rows[mid:], cycle_maps, seq_labels[mid:])
    h1 = M._backtest_scheme(dims, off, w, data=half1_data, pick_rule=pr)
    h2 = M._backtest_scheme(dims, off, w, data=half2_data, pick_rule=pr)
    if full.get("error") or h1.get("error") or h2.get("error"):
        print(f"{name:<28} ERROR")
        continue
    print(f"{name:<28}|{full['alpha']:>10.4f}|{h1['alpha']:>10.4f}|{h2['alpha']:>10.4f}"
          f"|{h2['triggered']:>8}|{h2['hit_rate']*100:>7.1f}%|{h2['rand_base']*100:>5.1f}%")
