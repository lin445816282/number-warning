#!/usr/bin/env python3
"""回填 购买策略前3方案 真实下单台账（zodiac_bp_order，124期~262期）。
复用 main 内部函数：逐期读生肖投票 → 3方案 pick → INSERT → 开奖结算 → 止损状态机。"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import main as M

db = M.get_db()
M._ensure_zodiac_bp_order_table(db)
M._ensure_zodiac_bp_state_table(db)

# 清空重来
db.execute("DELETE FROM zodiac_bp_order")
db.execute("DELETE FROM zodiac_bp_state")
db.commit()

# 遍历所有有生肖投票数据的日期（124期起）
dates = [r["draw_date"] for r in db.execute(
    "SELECT DISTINCT draw_date FROM multi_group_summary2 WHERE draw_date >= '2026-05-04' ORDER BY draw_date").fetchall()]

n_gen = 0
for d in dates:
    vd = M._zodiac_bp_votes_db(db, d)
    if vd is None:
        continue
    # 判断是否有投票数据（4来源全空则跳过）
    if not any(vd["votes"].values()):
        continue
    period = vd["period"] or ""
    for key, name, _ in M.ZODIAC_BP_PLANS:
        zs = M._zodiac_bp_pick(key, vd)
        nums = sorted({n for z in zs for n in M.DEFAULT_ZODIAC.get(z, [])})
        N = len(nums)
        picks_str = ".".join(f"{n:02d}" for n in nums)
        invest = round(M.ZODIAC_BP_PER * N, 2)
        cur = db.execute("SELECT id FROM zodiac_bp_order WHERE bet_date=? AND plan_key=?", (d, key)).fetchone()
        if cur is None:
            db.execute("INSERT INTO zodiac_bp_order (bet_date, period, plan_key, plan_name, zodiacs, picks, num_count, per, invest, open_num, hit, profit, capital, create_time) VALUES (?,?,?,?,?,?,?,?,?,NULL,NULL,NULL,NULL,?)",
                       (d, period, key, name, "".join(zs), picks_str, N, M.ZODIAC_BP_PER, invest, "2026-09-20 00:00:00"))
            n_gen += 1
db.commit()
print(f"固化 {n_gen} 条下单记录，覆盖 {len(dates)} 期")

# 结算（开奖已出）
settled = M._settle_zodiac_bp_order()
print(f"结算 {settled} 条 pending")

# 汇总
db2 = M.get_db()
M._ensure_zodiac_bp_order_table(db2)
for key, name, _ in M.ZODIAC_BP_PLANS:
    rows = db2.execute("SELECT * FROM zodiac_bp_order WHERE plan_key=? ORDER BY bet_date", (key,)).fetchall()
    betting = [r for r in rows if r["num_count"] and r["num_count"] > 0]
    settled_rows = [r for r in betting if r["hit"] is not None]
    hits = sum(1 for r in settled_rows if r["hit"] == 1)
    tp = sum(r["profit"] or 0 for r in rows if r["profit"] is not None)
    print(f"  {name:10s} 下单{len(rows)} 结算{len(settled_rows)} 命中{hits} 盈亏{tp:+.1f} 本金{3000+tp:.1f}")
# 止损状态
for r in db2.execute("SELECT * FROM zodiac_bp_state ORDER BY plan_key").fetchall():
    print(f"  状态 {r['plan_key']}: {r['status']} stop_streak={r['stop_streak']} stop_date={r['stop_date']}")
db2.close()
print("DONE")
