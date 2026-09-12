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
    print(f"[{now}] matched={matched} settled={settled} "
          f"generated={gen['generated']} date={gen['date']} "
          f"scheme_updated={upd} scheme_generated={sgen['generated']} "
          f"consensus_generated={cgen['generated']} consensus_N={cgen.get('N', 0)} "
          f"zodiac_track={zt}")


if __name__ == "__main__":
    main()
