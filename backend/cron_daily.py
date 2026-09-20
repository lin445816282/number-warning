#!/usr/bin/env python3
"""number-warning 每日自动化：匹配新数据 + 前向验证引擎（结算+固化）。
由 cron 每日调用，保证真实前向引擎持续积累样本外数据。
铁律：固化选号只用 bet_date 之前的数据（引擎函数内部已保证，无数据泄漏）。"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import main as M
from datetime import datetime


def main():
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # 1. 匹配所有待匹配(status=0) + 失败(status=2)记录
    db = M.get_db()
    rows = db.execute(
        "SELECT id FROM number_knowledge_record WHERE status IN (0,2) ORDER BY id").fetchall()
    db.close()
    matched = 0
    for r in rows:
        ok, err = M.do_match(r["id"], operate_user="cron")
        if ok:
            matched += 1
    if rows:
        M.rebuild_rank_max()
        M.rebuild_signal_track()
    # 2. 前向验证引擎：结算昨日选号 + 固化明日选号
    settled = M._settle_dim_forward()
    gen = M._generate_dim_forward()
    # 3. 自主跟踪方案前向：结算后回填指标 + 固化下一期选号
    upd = M._update_scheme_forward_stats()
    sgen = M._generate_scheme_forward()
    # 4. 共识信号前向：固化下一期选号（结算已由上面 _settle_dim_forward 统一处理）
    cgen = M._generate_consensus_forward()
    # 5. 肖跟踪：结算账户到最新开奖日期
    zt = {"status": "no_account"}
    try:
        db2 = M.get_db()
        acc = db2.execute("SELECT id FROM zodiac_track_account ORDER BY id LIMIT 1").fetchone()
        db2.close()
        if acc:
            token = M.create_token({"username": "admin", "role_code": "super_admin"})
            zr = M.zodiac_track_settle(user=f"Bearer {token}")
            zt = {"status": "ok", "new_orders": zr.get("new_orders", 0),
                  "capital": zr["account"]["capital"], "account_status": zr["account"]["status"]}
    except Exception as e:
        zt = {"status": "error", "msg": str(e)}
    # 6. 随机8码·6期跟踪：重新回测并固化到 random8_round（开奖数据更新后自动跟进）
    r8 = {"status": "ok"}
    try:
        rr = M._random8_backtest()
        r8 = {"status": "ok", "rounds": rr.get("rounds", 0), "hit_rate": rr.get("hit_rate", 0),
              "total_pnl": rr.get("total_pnl", 0)}
    except Exception as e:
        r8 = {"status": "error", "msg": str(e)}
    # 7. Top1 肖样本外前向：结算已固化 + 固化最新采集期（开奖前采集的预测）
    zt1 = {"status": "ok"}
    try:
        s1 = M._settle_zodiac_top1_forward()
        g1 = M._generate_zodiac_top1_forward()
        zt1 = {"status": "ok", "settled": s1, "generated": g1}
    except Exception as e:
        zt1 = {"status": "error", "msg": str(e)}
    # 8. Top1 肖真实下单：结算 pending + 固化最新采集期下单
    zo = {"status": "ok"}
    try:
        so = M._settle_zodiac_order()
        go = M._generate_zodiac_order()
        zo = {"status": "ok", "settled": so, "generated": go}
    except Exception as e:
        zo = {"status": "error", "msg": str(e)}
    # 8.5 满票肖（≥4票）真实下单：结算 pending + 固化最新采集期下单
    zof = {"status": "ok"}
    try:
        sof = M._settle_zodiac_full_order()
        gof = M._generate_zodiac_full_order()
        zof = {"status": "ok", "settled": sof, "generated": gof}
    except Exception as e:
        zof = {"status": "error", "msg": str(e)}
    # 9. 前24/后25 真实下单：结算 pending + 固化最新采集期下单
    fb = {"status": "ok"}
    try:
        sf = M._settle_frontback_order()
        gf = M._generate_frontback_order()
        fb = {"status": "ok", "settled": sf, "generated": gf}
    except Exception as e:
        fb = {"status": "error", "msg": str(e)}
    # 10. 四组汇 ROI 前5 真实下单：结算 pending + 固化最新采集期下单
    sz = {"status": "ok"}
    try:
        ss = M._settle_sizu_order()
        gs = M._generate_sizu_order()
        sz = {"status": "ok", "settled": ss, "generated": gs}
    except Exception as e:
        sz = {"status": "error", "msg": str(e)}
    # 11. 购买策略前3方案 真实下单：结算 pending + 固化最新采集期下单（含止损状态机）
    zbp = {"status": "ok"}
    try:
        sbp = M._settle_zodiac_bp_order()
        gbp = M._generate_zodiac_bp_order()
        zbp = {"status": "ok", "settled": sbp, "generated": gbp}
    except Exception as e:
        zbp = {"status": "error", "msg": str(e)}
    # 12. 反向筹码真实下单：结算 pending + 固化最新采集期下单
    rc = {"status": "ok"}
    try:
        src = M._settle_reverse_chip_order()
        grc = M._generate_reverse_chip_order()
        rc = {"status": "ok", "settled": src, "generated": grc}
    except Exception as e:
        rc = {"status": "error", "msg": str(e)}
    print(f"[{now}] matched={matched} settled={settled} "
          f"generated={gen['generated']} date={gen['date']} "
          f"scheme_updated={upd} scheme_generated={sgen['generated']} "
          f"consensus_generated={cgen['generated']} consensus_N={cgen.get('N', 0)} "
          f"zodiac_track={zt} random8={r8} zodiac_top1_forward={zt1} zodiac_order={zo} zodiac_order_full={zof} frontback_order={fb} sizu_order={sz} zodiac_bp_order={zbp} reverse_chip_order={rc}")


if __name__ == "__main__":
    main()
