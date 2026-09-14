#!/usr/bin/env python3
"""滚动窗口验证 — 对 dim_combo_scan 通过铁律的 top 组合做多窗口稳定性检验。

把 1718 期按季度（~143期）切成 12 个滚动窗口，看每个组合在各窗口的超额
是否持续为正。判定「稳定」= 正超额窗口占比高 + 无连续长段负超额。
"""
import sys, os, json
from collections import defaultdict

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)
import main

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

def daily_picks(dims):
    var_picks = {v: run_walkforward(dims, *v) for v in VARIANTS}
    daily = []
    for i in range(N_TOTAL):
        votes = defaultdict(int)
        for v, pl in var_picks.items():
            for n in pl[i]:
                votes[n] += 1
        picks = [n for n, c in votes.items() if c >= 2]
        if not picks:
            daily.append((i, 0, 0, dates[i]))  # 空仓也记录
            continue
        hit = 1 if open_nums[i] in picks else 0
        daily.append((i, len(picks), hit, dates[i]))
    return daily

def main2():
    scan = json.load(open(os.path.join(BACKEND, "analysis", "dim_combo_scan.json")))
    top = scan["passed"][:6]  # 前6个通过组合
    # 追加对照：春夏秋冬+红肖蓝肖绿肖
    top.append({"dims": ["season_type", "zodiac_color_type"]})

    # 季度窗口
    WIN = N_TOTAL // 12
    print(f"数据 {N_TOTAL} 期，切成 12 个季度窗口（每窗 ~{WIN} 期）")
    print("=" * 100)

    for p in top:
        dims = p["dims"]
        name = f"{main.DIM_NAMES[dims[0]]}+{main.DIM_NAMES[dims[1]]}"
        daily = daily_picks(dims)
        # 分窗口算超额
        windows = []
        for w in range(12):
            lo = w * WIN
            hi = (w + 1) * WIN if w < 11 else N_TOTAL
            sub = [d for d in daily if lo <= d[0] < hi and d[1] > 0]  # 只算触发期
            if not sub:
                windows.append(("空仓", 0, 0))
                continue
            n = len(sub)
            hits = sum(1 for _, N, h, _ in sub if h)
            total_n = sum(N for _, N, _, _ in sub)
            avg_n = total_n / n
            alpha = round((hits / n - avg_n / 49) * 100, 2)
            pnl = sum((ODDS - N) if h else -N for _, N, h, _ in sub)
            windows.append((dates[lo], alpha, round(pnl, 1)))
        pos = sum(1 for _, a, _ in windows if a != "空仓" and a > 0)
        neg = sum(1 for _, a, _ in windows if a != "空仓" and a < 0)
        # 连续负窗口最大长度
        max_neg_run = cur = 0
        for _, a, _ in windows:
            if a != "空仓" and a < 0:
                cur += 1
                max_neg_run = max(max_neg_run, cur)
            else:
                cur = 0
        alphas = " ".join(f"{a:>5}%" if isinstance(a, float) else f"{a:>5}" for _, a, _ in windows)
        print(f"{name:<20} 正窗{pos}/负窗{neg} 最长连负{max_neg_run}窗")
        print(f"  窗口超额: {alphas}")
        print()

if __name__ == "__main__":
    main2()
