#!/usr/bin/env python3
"""共识信号真实前向历史回填（一次性脚本）。

背景：_generate_consensus_forward 原本只在 N>0 时固化，导致 cron 启动以来
共识信号空仓期（N=0）未记录，真实前向 periods 恒为 0。

本脚本 walk-forward 重放 cron 启动以来每一天的共识选号（无前视偏差），
补记缺失的 consensus 记录（含空仓 N=0），并结算已过去的期数。

用法：cd backend && python3 analysis/backfill_consensus_forward.py
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main as M
from datetime import datetime, timedelta

DIMS = ["season_type", "zodiac_color_type"]
VARIANTS = [(+2, 90), (+1, 60), (+2, 60), (+1, 90)]


def consensus_as_of(end_date):
    """基于截至 end_date 的数据算共识选号（4变体≥2票），无前视。"""
    votes = {}
    for off, w in VARIANTS:
        order = M._compute_current_picks(DIMS, off, w, "union", end_date=end_date)
        for n in order.get("picks", []):
            votes[n] = votes.get(n, 0) + 1
    return sorted(n for n, c in votes.items() if c >= 2)


def main():
    db = M.get_db()
    r = db.execute("SELECT MIN(bet_date) mn FROM dim_forward_track WHERE is_live=1").fetchone()
    if not r or not r["mn"]:
        print("无 is_live=1 记录，无法确定回填起点，退出")
        db.close()
        return
    start = r["mn"]
    lr = db.execute("SELECT MAX(record_date) d FROM number_knowledge_record WHERE status=1").fetchone()
    if not lr or not lr["d"]:
        db.close()
        return
    last_data_date = lr["d"]
    end = (datetime.strptime(last_data_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")

    existing = set(x["bet_date"] for x in db.execute(
        "SELECT bet_date FROM dim_forward_track WHERE dim_key='consensus'").fetchall())

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    added = 0
    d = datetime.strptime(start, "%Y-%m-%d")
    end_d = datetime.strptime(end, "%Y-%m-%d")
    while d <= end_d:
        ds = d.strftime("%Y-%m-%d")
        prev = (d - timedelta(days=1)).strftime("%Y-%m-%d")
        if ds not in existing:
            picks = consensus_as_of(prev)
            db.execute(
                "INSERT OR IGNORE INTO dim_forward_track "
                "(dim_key, bet_date, picks_json, N, open_number, hit, is_live, create_time) "
                "VALUES ('consensus', ?, ?, ?, NULL, NULL, 1, ?)",
                (ds, json.dumps(picks), len(picks), now))
            added += 1
        d += timedelta(days=1)
    db.commit()

    # 结算已过去的期数（bet_date <= 最新数据日 且 open_number IS NULL）
    settled = 0
    pending = db.execute(
        "SELECT id, bet_date, picks_json FROM dim_forward_track "
        "WHERE dim_key='consensus' AND open_number IS NULL AND bet_date <= ?",
        (last_data_date,)).fetchall()
    for p in pending:
        orow = db.execute(
            "SELECT source_number FROM number_knowledge_record WHERE record_date=? AND status=1",
            (p["bet_date"],)).fetchone()
        if not orow:
            continue
        open_num = int(orow["source_number"])
        picks = json.loads(p["picks_json"]) if p["picks_json"] else []
        hit = 1 if open_num in picks else 0
        db.execute("UPDATE dim_forward_track SET open_number=?, hit=? WHERE id=?",
                   (open_num, hit, p["id"]))
        settled += 1
    db.commit()

    # 回填后统计
    stats = M._consensus_forward_stats()
    db.close()
    print(f"回填完成：新增 {added} 条，结算 {settled} 期")
    print(f"真实前向：总运行 {stats['periods']} 期（触发 {stats['triggered']} · 空仓 {stats['empty']}）")


if __name__ == "__main__":
    main()
