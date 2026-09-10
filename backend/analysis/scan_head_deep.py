#!/usr/bin/env python3
"""头数参数稳健性深挖：offset × window 网格扫描。

背景：自主跟踪寻优发现「头数」是 walk-forward 前向验证出的唯一真信号（前向超额 +6.7%）。
本脚本对头数（单维 + 关键组合）做 offset × window 细网格扫描，判断：
① 回测 alpha 是否「跨参数稳健为正」——真信号应在多个相邻参数形成平滑正区域，孤立好点是过拟合
② 4 段 EV 时间稳健性（是否前后期都正，而非近期才走好）
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import main as M

data = M._load_backtest_data()
WINDOWS = [30, 45, 60, 90, 120]
OFFSETS = [-4, -3, -2, -1, 0, 1, 2]

DIM_SETS = [
    (["head_number"], "头数"),
    (["head_number", "zodiac_color_type"], "头数+红蓝绿肖"),
    (["head_number", "season_type"], "头数+春夏秋冬"),
    (["head_number", "wave_color"], "头数+号码波色"),
]

for dims, label in DIM_SETS:
    print(f"\n===== {label}（回测alpha% + 稳定性标记）=====")
    print(f"{'window':>7} | " + " ".join(f"off{o:+d} " for o in OFFSETS))
    for w in WINDOWS:
        cells = []
        for o in OFFSETS:
            bt = M._backtest_scheme(dims, o, w, M.SCHEME_ODDS, data)
            if bt.get("error"):
                cells.append("   -   ")
                continue
            alpha = bt.get("alpha", 0) or 0
            stable = bt.get("stable", 0)
            segs = bt.get("seg_evs", [])
            # 标记：stable=4段≥3正 ✓；alpha正但不稳定 △；alpha负 空格
            mark = "✓" if (alpha > 0 and stable) else ("△" if alpha > 0 else "·")
            cells.append(f"{alpha*100:+5.1f}{mark}")
        print(f"{w:>7} | " + " ".join(cells))

# 头数单维度：最细的 offset 扫描（window=60 固定），看正区域边界
print(f"\n===== 头数·window=60 · offset 最细扫描 =====")
print(f"{'offset':>7} | {'alpha%':>7} {'EV':>7} {'均号':>5} {'4段EV':>24} {'stable':>6}")
for o in range(-6, 4):
    bt = M._backtest_scheme(["head_number"], o, 60, M.SCHEME_ODDS, data)
    if bt.get("error"):
        continue
    segs = " ".join(f"{e:+.2f}" for e in bt.get("seg_evs", []))
    print(f"{o:+d}{'':>6} | {bt['alpha']*100:+7.2f} {bt['ev']:>7.3f} {bt['avg_n']:>5.1f} {segs:>24} {bt['stable']:>6}")
