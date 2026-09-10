#!/usr/bin/env python3
"""共识选号泛化 · 把「4变体≥2票共识」框架推广到所有正超额家族。

背景：当前唯一共识信号「春夏秋冬+红肖蓝肖绿肖」(season_type+zodiac_color_type)
用 4 个 (offset,window) 参数变体投票≥2票，全历史 362 期超额 +4.7% p=0.039 显著。

本脚本：固定同一套 4 变体共识框架（不重新调参，避免过拟合），
对 paper_trade_0601 单变体 Test 段正超额的 69 个维度家族逐一做全历史 walk-forward，
统计 ≥2 票共识的整体超额 / 命中率 / 月度稳定性 / 半年分段，
并对全家族 p 值做 BH-FDR 多重比较校正，找出「参数鲁棒 + 时间稳定」的共识信号。

共识口径与 paper_trade_rolling.py 完全一致（同一 4 变体 + ≥2票）。
"""
import sys, os, json, hashlib
from collections import defaultdict, OrderedDict

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)
import main

# 固定 4 变体共识框架（与 paper_trade_rolling.py 一致，不针对家族调参）
VARIANTS = [(+2, 90), (+1, 60), (+2, 60), (+1, 90)]


def run_walkforward(dims, offset, window):
    """对给定维度集合，跑单一 (offset,window) 变体的全历史无前视选号，返回每期选号列表。"""
    dimset = set(dims)
    tn_cache = {}

    def tag_nums(dim, tag, zm):
        if dim == "zodiac":
            return [n for n in range(1, 50) if main._num_to_zodiac(n, zm) == tag]
        k = (dim, tag)
        if k not in tn_cache:
            tn_cache[k] = [n for n in range(1, 50) if main.match_labels(n, main.DEFAULT_ZODIAC).get(dim) == tag]
        return tn_cache[k]

    last_seen = {}; sample = {}; gap_hist = {}; out = []
    for i in range(len(rows)):
        seq = i + 1
        open_num, labels, zm = seq_labels[i]
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


def consensus_daily(dims):
    """4 变体投票 ≥2 票共识，返回 [(date, N, hit), ...]。"""
    var_picks = {v: run_walkforward(dims, *v) for v in VARIANTS}
    daily = []
    for i in range(len(rows)):
        date = rows[i]["record_date"]
        votes = defaultdict(int)
        for v, pl in var_picks.items():
            for n in pl[i]:
                votes[n] += 1
        picks = [n for n, c in votes.items() if c >= 2]
        if not picks:
            continue
        hit = 1 if open_by_date[date] in picks else 0
        daily.append((date, len(picks), hit))
    return daily


def agg(seg):
    n = len(seg)
    if not n:
        return None
    hits = sum(h for _, _, h in seg)
    sn = sum(N for _, N, _ in seg)
    hr = hits / n * 100
    avg_n = sn / n
    rand = avg_n / 49 * 100
    return {
        "periods": n, "hits": hits, "hit_rate": round(hr, 1),
        "avg_n": round(avg_n, 1), "rand_base": round(rand, 1),
        "alpha": round(hr - rand, 1),
    }


def half_yearly(daily):
    out = []
    for label, s, e in [
        ("2025上半年", "2025-01-01", "2025-06-30"),
        ("2025下半年", "2025-07-01", "2025-12-31"),
        ("2026上半年", "2026-01-01", "2026-06-30"),
        ("2026下半年至今", "2026-07-01", "2026-12-31"),
    ]:
        seg = [(d, n, h) for d, n, h in daily if s <= d <= e]
        a = agg(seg)
        if a:
            a["label"] = label
            out.append(a)
    return out


def bh_fdr(pvals):
    """BH-FDR 校正，返回 [(index, p, q), ...] 按 p 升序。"""
    n = len(pvals)
    idx_sorted = sorted(range(n), key=lambda i: pvals[i])
    out = [None] * n
    prev_q = 1.0
    for rank, i in enumerate(idx_sorted, start=1):
        q = min(pvals[i] * n / rank, 1.0)
        q = max(q, prev_q)  # 单调化
        out[i] = q
        prev_q = q
    return out


# ============================================================
rows, cycle_maps, seq_labels = main._load_backtest_data()
open_by_date = {rows[i]["record_date"]: int(rows[i]["source_number"]) for i in range(len(rows))}

# 家族池：paper_trade_0601 单变体 Test 段正超额维度组合（去重）
paper = json.load(open(os.path.join(BACKEND, "analysis", "paper_trade_0601.json")))
family_map = {}
for s in paper["schemes"]:
    if s["test"]["alpha"] > 0:
        key = ",".join(sorted(s["dims"]))
        family_map[key] = sorted(s["dims"])
# 补充单维正超额家族（season_type 等单维也在池内）
for dim in main.ALL_DIMS:
    if dim not in family_map:
        family_map[dim] = [dim]

families = sorted(family_map.items())
print(f"候选家族池：{len(families)} 个")

results = []
for key, dims in families:
    daily = consensus_daily(dims)
    if not daily:
        continue
    overall = agg(daily)
    p = main._dim_forward_binomial_sf(overall["hits"], overall["periods"], overall["avg_n"] / 49)
    overall["binomial_p"] = round(p, 6)
    hy = half_yearly(daily)
    results.append({
        "dims": dims, "dims_key": key,
        "name": "+".join(main.DIM_NAMES.get(d, d) for d in dims[:5]),
        "overall": overall, "half_yearly": hy,
    })

# BH-FDR 校正
pvals = [r["overall"]["binomial_p"] for r in results]
qvals = bh_fdr(pvals)
for r, q in zip(results, qvals):
    r["overall"]["fdr_q"] = round(q, 6)

# 排序：先 fdr_q<0.05，再 alpha 降序
results.sort(key=lambda r: (r["overall"]["fdr_q"], -r["overall"]["alpha"]))

print(f"\n=== 共识框架下全历史验证结果（按 FDR 校正 q 值排序）===")
print(f"{'家族':<38s} {'触发':>5s} {'命中':>6s} {'均号':>5s} {'超额':>6s} {'p':>8s} {'FDR-q':>8s}")
print("-" * 80)
sig_fdr = 0
for r in results:
    o = r["overall"]
    mark = ""
    if o["fdr_q"] < 0.05:
        sig_fdr += 1
        mark = " ✅"
    elif o["fdr_q"] < 0.10:
        mark = " ~"
    print(f"{r['name']:<38s} {o['periods']:>5d} {o['hit_rate']:>6.1f} {o['avg_n']:>5.1f} "
          f"{o['alpha']:>+6.1f} {o['binomial_p']:>8.4f} {o['fdr_q']:>8.4f}{mark}")

print(f"\nFDR q<0.05 显著共识信号：{sig_fdr} 个 / 共 {len(results)} 家族")

out_path = os.path.join(BACKEND, "analysis", "consensus_generalize.json")
json.dump({
    "framework": "4变体≥2票共识（offset/window=[(+2,90),(+1,60),(+2,60),(+1,90)]，与现有信号同框架）",
    "data_range": f"{rows[0]['record_date']}~{rows[-1]['record_date']}",
    "total_families": len(results),
    "sig_fdr_005": sig_fdr,
    "families": results,
}, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"\n已写 {out_path}")
