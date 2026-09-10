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
    print(f"[{now}] matched={matched} settled={settled} "
          f"generated={gen['generated']} date={gen['date']} "
          f"scheme_updated={upd} scheme_generated={sgen['generated']}")


if __name__ == "__main__":
    main()
