#!/usr/bin/env python3
"""正交信号源扫描 — 在「憋高位」机制之外寻找独立盈利信号。

背景：共识泛化已证「信号源唯一=春夏秋冬憋高位」，无独立备胎。
本脚本扫描 4 个与「憋高位」正交的机制，验证是否存在独立正超额信号：
  1. 热号追涨（momentum）—— 与憋冷相反：追近期活跃标签
  2. 重号（repeat）—— 上期号码/同尾/同生肖重复出现
  3. 大小趋势（big_small）—— 大(25-49)/小(1-24)序列的延续/反转
  4. 生肖转移（zodiac_transition）—— 相邻期生肖转移概率偏离

全部无前视 walk-forward，输出命中率/超额/二项检验 p/前后半段稳定性。
"""
import sys, os, json
from collections import defaultdict

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)
import main

rows, cycle_maps, seq_labels = main._load_backtest_data()
N = len(rows)
open_nums = [int(r["source_number"]) for r in rows]


def binomial_sf(k, n, p):
    return main._dim_forward_binomial_sf(k, n, p)


def summarize(daily):
    """daily = [(date, picks(list), hit)]"""
    trig = [d for d in daily if d[1]]
    t = len(trig)
    hits = sum(d[2] for d in trig)
    avg_n = sum(len(d[1]) for d in trig) / t if t else 0.0
    rand = avg_n / 49
    hr = hits / t if t else 0.0
    alpha = hr - rand
    p = binomial_sf(hits, t, rand) if (t and rand > 0) else 1.0
    return {
        "triggered": t, "hits": hits, "hit_rate": round(hr, 4),
        "avg_n": round(avg_n, 2), "alpha": round(alpha, 4),
        "binomial_p": round(p, 6),
    }


def half_split(daily):
    """前后半段 alpha，检测单调衰竭。"""
    mid = len(daily) // 2
    a = summarize(daily[:mid])
    b = summarize(daily[mid:])
    return a, b


def zodiac_transition_picks(seq_labels, window=120, top_k=3):
    """生肖转移：用近 window 期转移频率，买「上期生肖 → 最可能下期生肖」的号码。

    无前视：每期只用截至上一期的转移计数。
    """
    trans = defaultdict(lambda: defaultdict(int))  # prev_zodiac -> cur_zodiac -> count
    out = []
    for i in range(N):
        num, labels, zm = seq_labels[i]
        cur_z = main._num_to_zodiac(num, zm) if num else ""
        if i > 0:
            prev_num, prev_labels, prev_zm = seq_labels[i - 1]
            prev_z = main._num_to_zodiac(prev_num, prev_zm) if prev_num else ""
            # 用截至上一期的转移计数，预测本期生肖
            cand = trans.get(prev_z, {})
            if cand:
                ranked = sorted(cand.items(), key=lambda x: -x[1])[:top_k]
                target_z = [z for z, _ in ranked]
                picks = sorted(set(
                    n for z in target_z
                    for n in range(1, 50) if main._num_to_zodiac(n, zm) == z
                ))
            else:
                picks = []
            out.append(picks)
        else:
            out.append([])
        # 更新转移计数（把本期加入）
        if i > 0:
            prev_num, _, prev_zm = seq_labels[i - 1]
            prev_z = main._num_to_zodiac(prev_num, prev_zm)
            trans[prev_z][cur_z] += 1
    return out


def run_momentum(seq_labels, gap_threshold=3, top_k=8):
    """热号追涨：当前遗漏 gap <= gap_threshold 的标签（近期活跃），取 gap 最小的 top_k 个标签买号码。"""
    last_seen = {}
    out = []
    for i in range(N):
        num, labels, zm = seq_labels[i]
        seq = i + 1
        # 用截至上一期的 last_seen 选号
        hot = []
        for (dim, tag), ls in last_seen.items():
            gap = seq - ls
            if gap <= gap_threshold:
                hot.append((gap, dim, tag))
        hot.sort()
        picks = set()
        for _, dim, tag in hot[:top_k]:
            if dim == "zodiac":
                for n in range(1, 50):
                    if main._num_to_zodiac(n, zm) == tag:
                        picks.add(n)
            else:
                for n in range(1, 50):
                    if main.match_labels(n, main.DEFAULT_ZODIAC).get(dim) == tag:
                        picks.add(n)
        out.append(sorted(picks))
        # 更新 last_seen
        for dim, tag in labels.items():
            if tag:
                last_seen[(dim, tag)] = seq
    return out


def run_repeat(seq_labels, mode="same_num"):
    """重号：上期号码（same_num）/ 上期同尾（same_tail）/ 上期同生肖（same_zodiac）。"""
    out = []
    for i in range(N):
        num, labels, zm = seq_labels[i]
        if i == 0:
            out.append([])
            continue
        prev_num, _, prev_zm = seq_labels[i - 1]
        if mode == "same_num":
            picks = [prev_num]
        elif mode == "same_tail":
            t = prev_num % 10
            picks = [n for n in range(1, 50) if n % 10 == t]
        elif mode == "same_zodiac":
            z = main._num_to_zodiac(prev_num, prev_zm)
            picks = [n for n in range(1, 50) if main._num_to_zodiac(n, zm) == z]
        out.append(sorted(picks))
    return out


def run_big_small(seq_labels, mode="reverse", run_len=3):
    """大小趋势：连续 run_len 期大(25-49)/小(1-24)后，reverse=反转 / continue=延续。"""
    out = []
    run = 0
    cur_side = None
    for i in range(N):
        num, labels, zm = seq_labels[i]
        big = num >= 25
        side = "big" if big else "small"
        if side == cur_side:
            run += 1
        else:
            cur_side = side
            run = 1
        # 选号基于当前 run（本期已知，但预测的是"下期"，这里用本期状态买下期）
        # 为保持 walk-forward 语义，这里记录本期的选号决策 = 基于上期 run 状态
        # 简化：用 run 状态判断是否触发，触发时买"反转/延续"方向的号码
        pass
    # 重新实现正确的 walk-forward
    out = []
    run = 0
    cur_side = None
    for i in range(N):
        num, labels, zm = seq_labels[i]
        seq = i + 1
        # 基于截至上一期的 run 状态选号（用上一期结束时更新的 run/cur_side）
        picks = []
        if cur_side is not None and run >= run_len:
            if mode == "reverse":
                target = "small" if cur_side == "big" else "big"
            else:
                target = cur_side
            if target == "big":
                picks = list(range(25, 50))
            else:
                picks = list(range(1, 25))
        out.append(picks)
        # 更新 run（把本期算进去）
        big = num >= 25
        side = "big" if big else "small"
        if side == cur_side:
            run += 1
        else:
            cur_side = side
            run = 1
    return out


def evaluate(name, picks_list):
    """picks_list[i] = 第 i 期选号列表。结算：当期开奖是否命中。"""
    daily = []
    for i in range(N):
        date = rows[i]["record_date"]
        open_num = open_nums[i]
        picks = picks_list[i]
        hit = 1 if picks and open_num in picks else 0
        daily.append((date, picks, hit))
    s = summarize(daily)
    a, b = half_split(daily)
    return {"name": name, "summary": s, "first_half": a, "second_half": b}


results = []

# 1. 热号追涨
for gap in [2, 3, 5]:
    for topk in [5, 8, 12]:
        picks = run_momentum(seq_labels, gap_threshold=gap, top_k=topk)
        results.append(evaluate(f"热号追涨(gap<={gap},top{topk})", picks))

# 2. 重号
for mode in ["same_num", "same_tail", "same_zodiac"]:
    picks = run_repeat(seq_labels, mode=mode)
    results.append(evaluate(f"重号({mode})", picks))

# 3. 大小趋势
for mode in ["reverse", "continue"]:
    for rl in [2, 3, 4]:
        picks = run_big_small(seq_labels, mode=mode, run_len=rl)
        results.append(evaluate(f"大小趋势({mode},连{rl})", picks))

# 4. 生肖转移
for topk in [1, 2, 3]:
    picks = zodiac_transition_picks(seq_labels, top_k=topk)
    results.append(evaluate(f"生肖转移(top{topk})", picks))


print("=" * 90)
print("正交信号源扫描（全历史 walk-forward · 命中率 vs 随机基线 · 二项检验）")
print(f"数据 {rows[0]['record_date']} ~ {rows[-1]['record_date']} 共 {N} 期")
print("=" * 90)
print(f"{'机制':<28s} {'触发':>5s} {'命中率':>7s} {'均号':>6s} {'超额':>7s} {'p':>8s} {'前半α':>8s} {'后半α':>8s}")
print("-" * 90)

sig = []
for r in results:
    s = r["summary"]
    mark = ""
    if s["alpha"] > 0 and s["binomial_p"] < 0.05 and s["triggered"] >= 30:
        sig.append(r)
        mark = " ⭐"
    print(f"{r['name']:<28s} {s['triggered']:>5d} {s['hit_rate']*100:>6.1f}% {s['avg_n']:>6.2f} "
          f"{s['alpha']*100:>+6.2f}% {s['binomial_p']:>8.4f} "
          f"{r['first_half']['alpha']*100:>+7.2f}% {r['second_half']['alpha']*100:>+7.2f}%{mark}")

print("-" * 90)
print(f"\n通过初筛（超额>0 且 p<0.05 且触发≥30）：{len(sig)} 个")
for r in sig:
    s = r["summary"]
    a, b = r["first_half"], r["second_half"]
    print(f"  ⭐ {r['name']}: 超额 {s['alpha']*100:+.2f}% p={s['binomial_p']} "
          f"前半 {a['alpha']*100:+.2f}% 后半 {b['alpha']*100:+.2f}%")

out_path = os.path.join(BACKEND, "analysis", "scan_orthogonal_signals.json")
json.dump(results, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"\n已写 {out_path}")
