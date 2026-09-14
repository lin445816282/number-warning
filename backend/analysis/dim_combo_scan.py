#!/usr/bin/env python3
"""维度组合「憋高位共识」系统扫描 — 寻找稳定盈利信号。

目标：穷举 20 维度两两组合 × 4变体(offset/window) ≥2票共识，
用 1717 期数据 walk-forward（无前视），算全历史 + 前半段 + 后半段的
超额/净盈亏/收益率，筛选「时间稳定正超额」的组合（避免过拟合陷阱）。

判定标准（铁律）：
  1. 全历史超额 alpha > 0
  2. 前半段 alpha > 0 且 后半段 alpha > 0（时间稳定，非单段运气）
  3. 触发期数 >= 100（排除小样本）
  4. 净盈亏 > 0
"""
import sys, os, json
from collections import defaultdict
from itertools import combinations

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


def eval_combo(dims):
    """跑 4 变体 ≥2票共识，返回统计 dict。"""
    var_picks = {v: run_walkforward(dims, *v) for v in VARIANTS}
    daily = []  # (idx, N, hit)
    for i in range(N_TOTAL):
        votes = defaultdict(int)
        for v, pl in var_picks.items():
            for n in pl[i]:
                votes[n] += 1
        picks = [n for n, c in votes.items() if c >= 2]
        if not picks:
            continue
        hit = 1 if open_nums[i] in picks else 0
        daily.append((i, len(picks), hit))

    if not daily:
        return None

    def stats(sub):
        if not sub:
            return None
        n = len(sub)
        hits = sum(1 for _, _, h in sub if h)
        total_n = sum(N for _, N, _ in sub)
        avg_n = total_n / n
        pnl = sum((ODDS - N) if h else -N for _, N, h in sub)
        return {
            "periods": n, "hits": hits,
            "hit_rate": round(hits / n * 100, 1),
            "avg_n": round(avg_n, 1),
            "alpha": round((hits / n - avg_n / 49) * 100, 2),
            "net_pnl": round(pnl, 1),
            "roi": round(pnl / total_n * 100, 2) if total_n else 0.0,
        }

    mid = N_TOTAL // 2
    front = [d for d in daily if d[0] < mid]
    back = [d for d in daily if d[0] >= mid]
    return {
        "dims": dims,
        "full": stats(daily),
        "front": stats(front),
        "back": stats(back),
    }


def scan():
    dims_all = list(main.DIM_NAMES.keys())
    print(f"维度全集: {len(dims_all)} 个")
    print(f"两两组合: {len(dims_all) * (len(dims_all) - 1) // 2} 种")
    print(f"数据: {dates[0]} ~ {dates[-1]}, {N_TOTAL} 期")
    print("=" * 90)

    results = []
    combos = list(combinations(dims_all, 2))
    for idx, combo in enumerate(combos):
        r = eval_combo(list(combo))
        if r and r["full"]:
            results.append(r)
        if (idx + 1) % 50 == 0:
            print(f"  进度 {idx+1}/{len(combos)} ...")

    # 排序：按全历史超额降序
    results.sort(key=lambda x: -x["full"]["alpha"])

    print("=" * 90)
    print("全部组合（按全历史超额降序，前 30）:")
    print(f"{'组合':<28} {'全历史超额':>8} {'前半':>7} {'后半':>7} {'净盈亏':>8} {'收益率':>7} {'触发':>5}")
    for r in results[:30]:
        f = r["full"]; fr = r["front"] or {}; bk = r["back"] or {}
        name = f"{main.DIM_NAMES[r['dims'][0]]}+{main.DIM_NAMES[r['dims'][1]]}"
        print(f"{name:<28} {f['alpha']:>7}% {fr.get('alpha','-'):>6}% {bk.get('alpha','-'):>6}% "
              f"{f['net_pnl']:>8} {f['roi']:>6}% {f['periods']:>5}")

    # 筛选：时间稳定正超额
    print("=" * 90)
    print("✅ 通过铁律筛选（全历史+前半+后半 都正超额，触发≥100，净盈亏>0）:")
    passed = []
    for r in results:
        f = r["full"]; fr = r["front"]; bk = r["back"]
        if not (f and fr and bk):
            continue
        if (f["alpha"] > 0 and fr["alpha"] > 0 and bk["alpha"] > 0
                and f["periods"] >= 100 and f["net_pnl"] > 0):
            passed.append(r)
    if not passed:
        print("  （无组合通过全部铁律）")
    for r in passed:
        f = r["full"]; fr = r["front"]; bk = r["back"]
        name = f"{main.DIM_NAMES[r['dims'][0]]}+{main.DIM_NAMES[r['dims'][1]]}"
        print(f"  {name:<24} 全历史α={f['alpha']}% 前半={fr['alpha']}% 后半={bk['alpha']}% "
              f"净盈亏={f['net_pnl']} 收益率={f['roi']}% 触发={f['periods']}")

    # 存 JSON
    out = {
        "data_range": f"{dates[0]}~{dates[-1]}",
        "total_periods": N_TOTAL,
        "total_combos": len(combos),
        "top30": [
            {"dims": r["dims"],
             "full": r["full"], "front": r["front"], "back": r["back"]}
            for r in results[:30]
        ],
        "passed": [
            {"dims": r["dims"],
             "full": r["full"], "front": r["front"], "back": r["back"]}
            for r in passed
        ],
    }
    path = os.path.join(BACKEND, "analysis", "dim_combo_scan.json")
    json.dump(out, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n已写 analysis/dim_combo_scan.json")


if __name__ == "__main__":
    scan()
