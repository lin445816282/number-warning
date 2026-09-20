"""回填 sizu_order（四组汇 ROI 前5 真实下单台账）：从 124 期起，5 方案逐期固化 + 开奖结算。

口径：每号 5 元、47 倍、每方案独立本金 3000。5 方案（ROI 前5）：
=3票 / ≥3票 / Top1号 / Top2号 / Top3号。
无前视偏差：picks 来自该期 draw_date 开奖前采集的 4 好运字段投票。
可重跑（先清空）。数据未采集（votes 全0）的期跳过。
"""
import os, sys

BACKEND = '/home/xiaolin/projects/number-warning/backend'
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)
import main

db = main.get_db()
main._ensure_sizu_order_table(db)
db.execute("DELETE FROM sizu_order")
db.commit()
db.close()

rows = main.get_db().execute("SELECT draw_date, period FROM multi_group_summary ORDER BY draw_date").fetchall()
main.get_db().close()

gen = 0
skip = []
for r in rows:
    d, period = r["draw_date"], r["period"]
    votes = main._sizu_votes_at(d)
    if votes is None or not any(votes.values()):
        skip.append(period)  # 数据未采集
        continue
    now = main.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for key, name, fn in main.SIZU_ORDER_PLANS:
        picks = fn(votes)
        N = len(picks)
        picks_str = ".".join(f"{x:02d}" for x in picks)
        invest = round(main.SIZU_ORDER_PER * N, 2)
        db = main.get_db()
        db.execute(
            "INSERT INTO sizu_order (bet_date, period, plan_key, plan_name, picks, num_count, per, invest, open_num, hit, profit, capital, create_time) VALUES (?,?,?,?,?,?,?,?,NULL,NULL,NULL,NULL,?)",
            (d, period, key, name, picks_str, N, main.SIZU_ORDER_PER, invest, now))
        db.commit()
        db.close()
        gen += 1

settled = main._settle_sizu_order()
print(f"生成 {gen} 条 跳过未采集 {len(skip)}({skip}) 结算 {settled}")

# 汇总
db = main.get_db()
print(f"\n{'方案':8s} {'下单':>5s} {'命中':>5s} {'命中率':>6s} {'盈亏':>8s} {'本金':>8s}")
for key, name, fn in main.SIZU_ORDER_PLANS:
    total = db.execute("SELECT COUNT(*) FROM sizu_order WHERE plan_key=?", (key,)).fetchone()[0]
    settled_n = db.execute("SELECT COUNT(*) FROM sizu_order WHERE plan_key=? AND hit IS NOT NULL", (key,)).fetchone()[0]
    hits = db.execute("SELECT COUNT(*) FROM sizu_order WHERE plan_key=? AND hit=1", (key,)).fetchone()[0]
    profit = db.execute("SELECT COALESCE(SUM(profit),0) FROM sizu_order WHERE plan_key=? AND profit IS NOT NULL", (key,)).fetchone()[0]
    hr = round(hits/settled_n*100, 1) if settled_n else 0
    print(f"{name:8s} {total:5d} {hits:3d}/{settled_n:<3d} {hr:5.1f}% {profit:8.1f} {main.SIZU_ORDER_CAPITAL+profit:8.1f}")
db.close()
