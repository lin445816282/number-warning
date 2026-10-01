import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datetime import datetime
import main as M


def rebackfill():
    db = M.get_db()
    M._ensure_high_excess_order_table(db)
    db.execute("DELETE FROM high_excess_order")
    db.commit()
    dates = sorted({r["draw_date"] for r in db.execute("SELECT draw_date FROM multi_group_summary WHERE draw_date IS NOT NULL").fetchall()})
    opens = {}
    for r in db.execute("SELECT record_date, source_number FROM number_knowledge_record WHERE status=1 AND source_number IS NOT NULL AND source_number != ''").fetchall():
        try:
            opens[r["record_date"]] = int(r["source_number"])
        except Exception:
            continue
    field_meta = M._high_excess_field_meta()
    n_gen = 0
    n_settle = 0
    n_skip = 0
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for d in dates:
        prev_dates = [x for x in dates if x < d and x in opens]
        if not prev_dates:
            n_skip += 1
            continue
        prev = max(prev_dates)
        sel = M._high_excess_order_select(db, prev)
        if not sel:
            n_skip += 1
            continue
        t1 = db.execute("SELECT * FROM multi_group_summary WHERE draw_date=?", (d,)).fetchone()
        t2 = db.execute("SELECT * FROM multi_group_summary2 WHERE draw_date=?", (d,)).fetchone()
        period = ""
        if t1 and t1["period"]:
            period = t1["period"]
        elif t2 and t2["period"]:
            period = t2["period"]
        fields = []
        total_invest = 0.0
        for it in sel:
            row2 = t1 if field_meta[it["field"]]["table"] == "multi_group_summary" else t2
            if row2 is None:
                continue
            raw = row2[it["field"]]
            if raw is None or str(raw).strip() == "":
                continue
            nums = M._field_to_nums(raw, it["type"])
            n = len(nums)
            if n == 0:
                continue
            invest = round(n * M.HE_ORDER_PER, 2)
            fields.append({"field": it["field"], "label": it["label"], "source": it["source"], "family": it["family"], "type": it["type"],
                           "nums": nums, "num_count": n, "invest": invest, "hit": None, "win": None, "profit": None})
            total_invest += invest
        open_num = opens.get(d)
        hit_count = None
        win = None
        profit = None
        if open_num is not None:
            hit_count = 0
            win = 0.0
            profit = 0.0
            for f in fields:
                hit = 1 if open_num in f["nums"] else 0
                w = 235.0 if hit else 0.0
                pr = round(w - f["invest"], 2)
                f["hit"] = hit
                f["win"] = round(w, 2)
                f["profit"] = pr
                if hit:
                    hit_count += 1
                win += w
                profit += pr
            n_settle += 1
        db.execute("INSERT INTO high_excess_order (bet_date, period, fields_json, invest, hit_count, win, profit, open_num, create_time) VALUES (?,?,?,?,?,?,?,?,?)",
                   (d, period, json.dumps(fields, ensure_ascii=False), round(total_invest, 2), hit_count, round(win, 2) if win is not None else None, round(profit, 2) if profit is not None else None, open_num, now))
        n_gen += 1
    db.commit()
    db.close()
    print(f"回填完成：固化 {n_gen} 期，已结算 {n_settle} 期，跳过 {n_skip} 期")


if __name__ == "__main__":
    rebackfill()
