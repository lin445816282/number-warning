"""回填双台账（多组肖汇真实下单）：从 124 期起逐期固化 + 开奖结算。

口径1「买 Top1 单肖」→ zodiac_order 表（zodiac=单肖，votes=票数，num_count=单肖号码数）
口径2「买满票肖（≥4票）」→ zodiac_order_full 表（zodiac=满票肖拼接，votes=肖数，num_count=总号码数）

两口径：每号 5 元、47 倍、本金 3000。无前视偏差（预测来自该期开奖前采集）。
数据未采集（今日最新期）跳过，留给 cron 采集后固化。可重跑（先清空）。
"""
import os, sys

BACKEND = '/home/xiaolin/projects/number-warning/backend'
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)
import main

db = main.get_db()
main._ensure_zodiac_order_table(db)
main._ensure_zodiac_full_order_table(db)
db.execute("DELETE FROM zodiac_order")
db.execute("DELETE FROM zodiac_order_full")
db.commit()
db.close()

rows = main.get_db().execute("SELECT draw_date, period FROM multi_group_summary2 ORDER BY draw_date").fetchall()
main.get_db().close()

gen_top1 = 0
gen_full = 0
skip_uncoll = []

for r in rows:
    d, period = r["draw_date"], r["period"]
    top1 = main._zodiac_top1_vote(d)
    if top1 is None:
        skip_uncoll.append(period)  # 数据未采集，留给 cron
        continue
    z, v = top1
    # 口径1：Top1 单肖
    N1 = len(main.DEFAULT_ZODIAC.get(z, []))
    invest1 = round(main.ZODIAC_ORDER_PER * N1, 2)
    # 口径2：满票肖
    full = main._zodiac_full_vote(d)
    zodiac_full = "".join(full)
    N2 = sum(len(main.DEFAULT_ZODIAC.get(x, [])) for x in full)
    invest2 = round(main.ZODIAC_FULL_ORDER_PER * N2, 2)
    now = main.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db = main.get_db()
    db.execute(
        "INSERT INTO zodiac_order (bet_date, period, zodiac, votes, per, num_count, invest, open_num, open_zodiac, hit, profit, capital, create_time) VALUES (?,?,?,?,?,?,?,NULL,NULL,NULL,NULL,NULL,?)",
        (d, period, z, v, main.ZODIAC_ORDER_PER, N1, invest1, now))
    db.execute(
        "INSERT INTO zodiac_order_full (bet_date, period, zodiac, votes, per, num_count, invest, open_num, open_zodiac, hit, profit, capital, create_time) VALUES (?,?,?,?,?,?,?,NULL,NULL,NULL,NULL,NULL,?)",
        (d, period, zodiac_full, len(full), main.ZODIAC_FULL_ORDER_PER, N2, invest2, now))
    db.commit()
    db.close()
    gen_top1 += 1
    gen_full += 1

settled_top1 = main._settle_zodiac_order()
settled_full = main._settle_zodiac_full_order()

print(f"生成 top1={gen_top1} full={gen_full} 跳过未采集={len(skip_uncoll)}({skip_uncoll})")
print(f"结算 top1={settled_top1} full={settled_full}")

# 汇总
db = main.get_db()
for label, tbl, cap in [("Top1单肖", "zodiac_order", main.ZODIAC_ORDER_CAPITAL),
                        ("满票肖", "zodiac_order_full", main.ZODIAC_FULL_ORDER_CAPITAL)]:
    total = db.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
    if tbl == "zodiac_order":
        settled_n = db.execute(f"SELECT COUNT(*) FROM {tbl} WHERE hit IS NOT NULL").fetchone()[0]
        hits = db.execute(f"SELECT COUNT(*) FROM {tbl} WHERE hit=1").fetchone()[0]
    else:
        settled_n = db.execute(f"SELECT COUNT(*) FROM {tbl} WHERE num_count>0 AND hit IS NOT NULL").fetchone()[0]
        hits = db.execute(f"SELECT COUNT(*) FROM {tbl} WHERE num_count>0 AND hit=1").fetchone()[0]
    profit = db.execute(f"SELECT COALESCE(SUM(profit),0) FROM {tbl} WHERE profit IS NOT NULL").fetchone()[0]
    print(f"{label}: 总{total} 已结算{settled_n} 命中{hits} 命中率{round(hits/settled_n*100,1) if settled_n else 0}% 盈亏{round(profit,2)} 本金{round(cap+profit,2)}")
db.close()
