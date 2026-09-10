#!/usr/bin/env python3
"""存量前向方案时间稳健性重审（正确口径：后半段独立回测）。

关键区别：
- back_alpha（全量回测 2 分段）是弱口径，会把「第3段正+第4段衰竭」平均掉，掩盖单调衰竭
- 后半段独立回测 = fresh start（无前半热身），最接近「现在才开始用这策略」的真实前向模拟

淘汰标准：后半段独立回测 alpha <= 0 → 前半伪信号（如头数单维单调衰竭）。
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import main as M

rows, cycle_maps, seq_labels = M._load_backtest_data()
n = len(rows)
mid = n // 2
half2_data = (rows[mid:], cycle_maps, seq_labels[mid:])
print(f"总 {n} 期，后半独立回测 = {n - mid} 期（{rows[mid]['record_date']} ~ {rows[-1]['record_date']}）")

db = M.get_db()
fwd = db.execute("SELECT * FROM strategy_scheme_record WHERE status='forwarding'").fetchall()
db.close()

downgraded = []
kept = []
for s in fwd:
    dims = json.loads(s["dims_json"]) if s["dims_json"] else []
    if not dims:
        continue
    srule = s["signal_rule"] or "high_gap"
    pr = "union" if srule == "high_gap" else srule.replace("high_gap_", "")
    off = s["offset"]
    w = s["window"]
    bt2 = M._backtest_scheme(dims, off, w, data=half2_data, pick_rule=pr)
    if bt2.get("error"):
        continue
    h2_alpha = bt2.get("alpha", 0) or 0
    name = M._scheme_name(dims, off, srule)
    if h2_alpha <= 0:
        db = M.get_db()
        db.execute(
            "UPDATE strategy_scheme_record SET status='backtested', conclusion=?, update_time=? WHERE id=?",
            (f"后半段独立回测alpha={h2_alpha:.4f}<=0，前半伪信号，淘汰",
             M.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), s["id"]))
        db.commit()
        db.close()
        downgraded.append((name, round(h2_alpha, 4)))
    else:
        kept.append((name, round(h2_alpha, 4)))

print(f"\n=== 存量前向 {len(fwd)} 个 → 降级 {len(downgraded)} 个，保留 {len(kept)} 个 ===")
print("\n[降级（后半独立回测翻负=伪信号）]")
for name, ba in sorted(downgraded, key=lambda x: x[1]):
    print(f"  {name}: 后半alpha={ba}")
print("\n[保留（后半独立回测仍正=真信号候选）]")
for name, ba in sorted(kept, key=lambda x: -x[1]):
    print(f"  {name}: 后半alpha={ba}")
