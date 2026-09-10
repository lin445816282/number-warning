#!/usr/bin/env python3
"""真实用户模拟下单 · 样本外验证（Train/Test 切分，无前视偏差）。

核心：回答「这些方案在 2026-06-01 之后到底灵不灵」。

方法：
  Train 段 = 2025-01-01 ~ 2026-05-31（516 期）—— 只用这段数据扫描/精选方案（模拟 06-01 当天用户视角）
  Test  段 = 2026-06-01 ~ 2026-09-10（102 期）—— 真实开奖，逐日无前视模拟下单，结算

  1. Train 段扫描候选（维度子集 × window × offset × 选号规则），门槛：4段稳健 + 超额>0 + 后半段独立回测alpha>0 + 触发>=50
  2. 对每个 Train 入选方案，从数据第1期累积状态（含 Train），到 Test 段逐期「历史选号→当期开奖结算」，记录明细
  3. 写入 strategy_order 表（scheme/dims/bet_date/picks/N/open_number/hit/profit，等额每号1元赔率47）
  4. 验证报告：Train alpha vs Test alpha（看衰减）、Test 命中率/超额/累计盈亏/二项检验 p 值

口径与 main._backtest_scheme 完全一致（无前视：用截至上一期状态选号，当期开奖结算）。
"""
import sys, os, json, hashlib
from datetime import datetime

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # backend/
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)
import main

SPLIT_DATE = "2026-06-01"
ODDS = main.SCHEME_ODDS
WINDOWS = [60, 90, 120]
OFFSETS = main.SCHEME_OFFSETS


def simulate_test(dims, offset, window, pick_rule, rows, seq_labels, train_idx):
    """无前视 walk-forward：从第1期累积状态，Test 段（i>=train_idx）逐期选号+当期结算，返回明细列表。

    与 main._backtest_scheme 口径一致（选号→结算→更新），额外记录 bet_date/open_number。
    """
    dimset = set(dims)
    tn_cache = {}

    def tag_nums(dim, tag, zm):
        if dim == "zodiac":
            return [n for n in range(1, 50) if main._num_to_zodiac(n, zm) == tag]
        k = (dim, tag)
        if k not in tn_cache:
            tn_cache[k] = [n for n in range(1, 50) if main.match_labels(n, main.DEFAULT_ZODIAC).get(dim) == tag]
        return tn_cache[k]

    last_seen = {}; sample = {}; gap_hist = {}
    records = []
    for i in range(len(rows)):
        seq = i + 1
        open_num, labels, zm = seq_labels[i]
        # 1. 选号（基于截至上一期累积的 last_seen/gap_hist，无前视）
        vote = {}
        for (dim, tag), ls in last_seen.items():
            gap = seq - ls
            hm = main._window_hist_max(gap_hist, (dim, tag), seq, window)
            if sample.get((dim, tag), 0) >= 2 and gap >= hm - offset:
                for n in tag_nums(dim, tag, zm):
                    vote[n] = vote.get(n, 0) + 1
        if pick_rule == "union":
            picks = sorted(vote.keys())
        else:
            th = int(pick_rule.replace("ge", ""))
            picks = sorted(n for n, c in vote.items() if c >= th)
        N = len(picks)
        # 2. 结算 + 记录（仅 Test 段）
        if i >= train_idx:
            hit = 1 if (N > 0 and open_num in picks) else 0
            profit = (ODDS - N) if hit == 1 else (-N if N > 0 else 0)
            records.append({
                "bet_date": rows[i]["record_date"], "picks": picks, "N": N,
                "open_number": open_num, "hit": hit, "profit": profit,
            })
        # 3. 更新状态（把当前期算进去）
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
    return records


def summarize(records):
    """汇总明细：命中率/随机基准/超额/累计盈亏/二项检验。"""
    n = len(records)
    trig = [r for r in records if r["N"] > 0]
    t = len(trig)
    hits = sum(r["hit"] for r in trig)
    avg_n = sum(r["N"] for r in trig) / t if t else 0.0
    rand = avg_n / 49 if avg_n else 0.0
    hit_rate = hits / t if t else 0.0
    alpha = hit_rate - rand
    profit = round(sum(r["profit"] for r in records), 2)
    # 每期 EV（含空仓期）
    ev = round(sum(r["profit"] for r in records) / n, 4) if n else 0.0
    p = main._dim_forward_binomial_sf(hits, t, rand) if (t and rand > 0) else 1.0
    return {
        "periods": n, "triggered": t, "hits": hits, "avg_n": round(avg_n, 2),
        "rand_base": round(rand, 4), "hit_rate": round(hit_rate, 4),
        "alpha": round(alpha, 4), "profit": profit, "ev": ev,
        "binomial_p": round(p, 6),
    }


def main_run():
    print("=" * 70)
    print("真实用户模拟下单 · 样本外验证（Train/Test 切分）")
    print(f"  Train ≤ {SPLIT_DATE} | Test ≥ {SPLIT_DATE} | 赔率 {ODDS} | 每号1元等额")
    print("=" * 70)

    rows, cycle_maps, seq_labels = main._load_backtest_data()
    # 定位 Train/Test 分界
    train_idx = next(i for i, r in enumerate(rows) if r["record_date"] >= SPLIT_DATE)
    n_test = len(rows) - train_idx
    print(f"\n数据 {rows[0]['record_date']} ~ {rows[-1]['record_date']} 共 {len(rows)} 期")
    print(f"Train {train_idx} 期（~{rows[train_idx-1]['record_date']}） | Test {n_test} 期（{rows[train_idx]['record_date']}~{rows[-1]['record_date']}）")

    train_data = (rows[:train_idx], cycle_maps, seq_labels[:train_idx])
    half2_data = (rows[train_idx // 2:train_idx], cycle_maps, seq_labels[train_idx // 2:train_idx])

    # ---------- 阶段1：Train 段扫描选方案 ----------
    print("\n[阶段1] Train 段扫描方案（维度子集 × window × offset × 选号规则）...")
    cands = main._scheme_dim_candidates()
    selected = []
    scanned = 0
    for dims in cands:
        pick_rules = ["union"]
        if len(dims) >= 2:
            pick_rules.append("ge2")
        if len(dims) >= 3:
            pick_rules.append("ge3")
        for w in WINDOWS:
            for off in OFFSETS:
                for pr in pick_rules:
                    scanned += 1
                    bt = main._backtest_scheme(dims, off, w, ODDS, train_data, pick_rule=pr)
                    if bt.get("error"):
                        continue
                    if not (bt["stable"] and (bt["alpha"] or 0) > 0 and bt["triggered"] >= 50):
                        continue
                    # 后半段独立回测（Train 段内部 fresh start，排除单调衰竭伪信号）
                    h2 = main._backtest_scheme(dims, off, w, ODDS, half2_data, pick_rule=pr)
                    h2_alpha = (h2.get("alpha", 0) or 0) if not h2.get("error") else 0.0
                    if h2_alpha <= 0:
                        continue
                    srule = "high_gap" if pr == "union" else f"high_gap_{pr}"
                    key = main._scheme_key(dims, srule, off, w)
                    selected.append({
                        "dims": dims, "offset": off, "window": w, "pick_rule": pr,
                        "srule": srule, "key": key,
                        "name": main._scheme_name(dims, off),
                        "train": bt, "train_h2_alpha": h2_alpha,
                    })
    print(f"  扫描 {scanned} 候选，Train 段入选 {len(selected)} 方案")

    if not selected:
        print("  ⚠️ 无方案通过 Train 段门槛，无法继续验证")
        return

    # 按 Train 段 alpha 降序
    selected.sort(key=lambda s: -(s["train"]["alpha"] or 0))

    # ---------- 阶段2：Test 段模拟下单 ----------
    print(f"\n[阶段2] Test 段逐日模拟下单（{n_test} 期）...")
    db = main.get_db()
    # 清空旧的 paper trade 记录（source 标记用 scheme 前缀 'PT:' 区分）
    db.execute("DELETE FROM strategy_order WHERE scheme LIKE 'PT:%'")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    results = []
    for s in selected:
        records = simulate_test(s["dims"], s["offset"], s["window"], s["pick_rule"],
                                rows, seq_labels, train_idx)
        summ = summarize(records)
        # 写 strategy_order
        for r in records:
            db.execute(
                "INSERT INTO strategy_order (scheme, offset, dims_json, bet_date, picks_json, N, per, amount, open_number, hit, profit, create_time) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                ("PT:" + s["key"], s["offset"], json.dumps(s["dims"], ensure_ascii=False),
                 r["bet_date"], json.dumps(r["picks"]), r["N"], 1.0, float(r["N"]),
                 r["open_number"], r["hit"], float(r["profit"]), now))
        s["test"] = summ
        results.append(s)
    db.commit()
    db.close()
    print(f"  写入 strategy_order {sum(s['test']['periods'] for s in results)} 条明细")

    # ---------- 阶段3：验证报告 ----------
    print("\n" + "=" * 70)
    print("验证报告：Train 段选出 → Test 段真实样本外表现")
    print("=" * 70)
    print(f"\n{'方案':<28s} {'Trainα':>8s} {'Testα':>8s} {'衰减':>8s} {'Test命中':>8s} {'Test盈亏':>9s} {'p值':>8s}")
    print("-" * 80)
    correct = 0  # Test 段 alpha>0 且 profit>0
    for s in results:
        tr = s["train"]; te = s["test"]
        decay = te["alpha"] - tr["alpha"]
        flag = ""
        if te["alpha"] > 0 and te["profit"] > 0:
            correct += 1
            flag = " ✅样本外成立"
        elif te["alpha"] <= 0:
            flag = " ❌超额转负"
        print(f"{s['name'][:26]:<28s} {tr['alpha']:+.4f} {te['alpha']:+.4f} {decay:+.4f} "
              f"{te['hit_rate']*100:6.1f}% {te['profit']:+9.1f} {te['binomial_p']:.4f}{flag}")

    print("-" * 80)
    print(f"\n结论：Train 入选 {len(results)} 方案，Test 段样本外「超额为正且累计盈利」{correct} 个"
          f"（{correct/len(results)*100:.0f}%）")
    # 汇总统计：全体方案 Test 段 alpha 分布
    alphas = [s["test"]["alpha"] for s in results]
    profits = [s["test"]["profit"] for s in results]
    print(f"Test 段 alpha 均值 {sum(alphas)/len(alphas):+.4f} | 中位数 {sorted(alphas)[len(alphas)//2]:+.4f} "
          f"| 最大 {max(alphas):+.4f} | 最小 {min(alphas):+.4f}")
    print(f"Test 段盈亏合计 {sum(profits):+.1f} | 均值 {sum(profits)/len(profits):+.1f}")

    # 写报告 JSON
    report = {
        "split_date": SPLIT_DATE, "train_periods": train_idx, "test_periods": n_test,
        "odds": ODDS, "scanned": scanned, "selected": len(results),
        "correct_out_of_sample": correct,
        "summary": {"alpha_mean": round(sum(alphas)/len(alphas), 4),
                     "profit_sum": round(sum(profits), 1)},
        "schemes": [
            {"key": s["key"], "name": s["name"], "dims": s["dims"], "offset": s["offset"],
             "window": s["window"], "pick_rule": s["pick_rule"],
             "train": {"alpha": s["train"]["alpha"], "ev": s["train"]["ev"],
                        "hit_rate": s["train"]["hit_rate"], "stable": s["train"]["stable"],
                        "triggered": s["train"]["triggered"]},
             "test": s["test"]}
            for s in results
        ],
        "generated": now,
    }
    out_path = os.path.join(BACKEND, "analysis", "paper_trade_0601.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n报告已写 {out_path}")


if __name__ == "__main__":
    main_run()
