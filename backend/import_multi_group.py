# -*- coding: utf-8 -*-
"""导入「多组汇总.xlsx」→ multi_group_summary 表（4家预测数据 + 约束校验）。"""
import sqlite3, os, re, json, sys, datetime

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "data", "number_warning.db")

# ── 列元数据：字段名 -> 中文名 / 家 / 类型 / 期望数量 ──
# 类型约束：zodiac=12生肖 tail=0-9尾 codes=1-49号码 size=大/小 wave=红/蓝/绿 oddeven=单/双
MULTI_GROUP_COLS = [
    ("gui_zodiac5", "鬼五肖", "鬼", "zodiac", 5),
    ("gui_tail5", "鬼5尾", "鬼", "tail", 5),
    ("gui_size", "鬼大小", "鬼", "size", 1),
    ("gui_wave1", "鬼波1", "鬼", "wave", 1),
    ("gui_wave2", "鬼波2", "鬼", "wave", 1),
    ("gui_oddeven", "鬼单双", "鬼", "oddeven", 1),
    ("gui_codes10", "鬼十码", "鬼", "codes", 10),
    ("dajia_zodiac6", "大家六肖", "大家", "zodiac", 6),
    ("dajia_codes10", "大家十码", "大家", "codes", 10),
    ("dajia_tail6", "大家六尾", "大家", "tail", 6),
    ("zhuge_wave1", "诸葛波1", "诸葛", "wave", 1),
    ("zhuge_wave2", "诸葛波2", "诸葛", "wave", 1),
    ("zhuge_tail4", "诸葛四尾", "诸葛", "tail", 4),
    ("zhuge_tail2", "诸葛二尾", "诸葛", "tail", 2),
    ("zhuge_zodiac2", "诸葛二肖", "诸葛", "zodiac", 2),
    ("zhuge_codes4", "诸葛四码", "诸葛", "codes", 4),
    ("zhuge_zodiac6", "诸葛六肖", "诸葛", "zodiac", 6),
    ("zhuge_codes10", "诸葛十码", "诸葛", "codes", 10),
    ("haoyun_81", "好运八一", "好运", "codes", 8),
    ("haoyun_82", "好运八二", "好运", "codes", 8),
    ("haoyun_83", "好运八三", "好运", "codes", 8),
    ("haoyun_84", "好运八四", "好运", "codes", 8),
    ("haoyun_tail6", "好运六尾", "好运", "tail", 6),
]

ZODIACS = set("鼠牛虎兔龙蛇马羊猴鸡狗猪")
WAVES = set("红蓝绿")
SIZE = set("大小")
ODDEVEN = set("单双")

def split_num_token(n):
    """拆解漏点分隔符的数字 token（如 59→5,9 / 3325→33,25）。"""
    if 1 <= n <= 49:
        return [n]
    s = str(n)
    for i in range(1, len(s)):
        a, b = int(s[:i]), int(s[i:])
        if 1 <= a <= 49 and 1 <= b <= 49:
            return [a, b]
    return [n]

def clean_codes(v):
    """号码列：去空格、补零两位、点分隔、拆解漏分隔符 token。返回 (规范化字符串, 号码列表)。"""
    if v is None:
        return "", []
    s = str(v).strip().replace(" ", "").replace("，", ".").replace(",", ".")
    nums = []
    for tok in re.split(r"[.\-、]+", s):
        tok = tok.strip()
        if not tok:
            continue
        if tok.isdigit():
            nums.extend(split_num_token(int(tok)))
        else:
            nums.append(tok)
    return s, nums

def clean_tail(v):
    """尾数列：'0-7-8-2-4尾' 或 '2.4.9.1.6.3' → 提取 0-9 数字列表。"""
    if v is None:
        return [], ""
    s = str(v).strip()
    toks = re.findall(r"\d+", s)
    return [int(t) for t in toks], s

def clean_zodiac(v):
    """生肖列：中文生肖串。"""
    if v is None:
        return []
    return [c for c in str(v).strip() if c in ZODIACS]

def validate(col, raw, field, cname, ctype, expect):
    """返回违规描述列表。"""
    errs = []
    if raw is None or str(raw).strip() == "":
        return errs  # 空值不报错（最后空期）
    if ctype == "codes":
        _, nums = clean_codes(raw)
        bad = [n for n in nums if not isinstance(n, int) or n < 1 or n > 49]
        if bad:
            errs.append(f"{cname} 含非法号码 {bad}")
        if expect and len([n for n in nums if isinstance(n, int)]) != expect:
            errs.append(f"{cname} 号码数 {len(nums)} ≠ 期望 {expect}")
    elif ctype == "tail":
        tails, _ = clean_tail(raw)
        bad = [t for t in tails if t < 0 or t > 9]
        if bad:
            errs.append(f"{cname} 含非法尾数 {bad}")
        if expect and len(tails) != expect:
            errs.append(f"{cname} 尾数 {len(tails)} ≠ 期望 {expect}")
    elif ctype == "zodiac":
        zs = clean_zodiac(raw)
        rest = [c for c in str(raw).strip() if c not in ZODIACS and c not in "、,，. "]
        if rest:
            errs.append(f"{cname} 含非生肖字符 {rest}")
        if expect and len(zs) != expect:
            errs.append(f"{cname} 生肖数 {len(zs)} ≠ 期望 {expect}")
    elif ctype == "size":
        if str(raw).strip() not in SIZE:
            errs.append(f"{cname} 非法值 '{raw}'（应为 大/小）")
    elif ctype == "wave":
        if str(raw).strip() not in WAVES:
            errs.append(f"{cname} 非法值 '{raw}'（应为 红/蓝/绿）")
    elif ctype == "oddeven":
        if str(raw).strip() not in ODDEVEN:
            errs.append(f"{cname} 非法值 '{raw}'（应为 单/双）")
    return errs

def main():
    import openpyxl
    xlsx = sys.argv[1] if len(sys.argv) > 1 else "/home/xiaolin/.hermes/cache/documents/doc_35e2255fda5a_多组汇总.xlsx"
    wb = openpyxl.load_workbook(xlsx, data_only=True)
    ws = wb["多组汇总"]
    rows = list(ws.iter_rows(values_only=True))

    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    cols_sql = ", ".join([f"{f} TEXT" for f, _, _, _, _ in MULTI_GROUP_COLS])
    db.execute(f"""CREATE TABLE IF NOT EXISTS multi_group_summary (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        draw_date TEXT NOT NULL UNIQUE,
        period TEXT NOT NULL,
        {cols_sql}
    )""")
    db.commit()

    # 字段名 → 索引（Excel 列）
    # Excel 列序：0日期 1期数 2鬼五肖 3鬼5尾 ... 对应 MULTI_GROUP_COLS 顺序
    col_idx = {f: i + 2 for i, (f, _, _, _, _) in enumerate(MULTI_GROUP_COLS)}

    inserted = 0
    skipped = 0
    all_errs = []

    for row in rows[1:]:  # 跳过表头
        if row is None or row[0] is None:
            continue
        dt = row[0]
        if isinstance(dt, datetime.datetime):
            draw_date = dt.strftime("%Y-%m-%d")
        else:
            draw_date = str(dt).strip()
        period = str(row[1]).strip() if row[1] else ""
        if not period:
            continue
        # 跳过整行空数据
        if all(row[i] is None or str(row[i]).strip() == "" for i in range(2, 25)):
            skipped += 1
            continue

        vals = {}
        errs = []
        for f, cname, fam, ctype, expect in MULTI_GROUP_COLS:
            raw = row[col_idx[f]]
            # 清洗：codes 去空格补零
            if ctype == "codes" and raw is not None:
                _, nums = clean_codes(raw)
                vals[f] = ".".join(f"{n:02d}" for n in nums if isinstance(n, int))
            else:
                vals[f] = str(raw).strip() if raw is not None else ""
            errs.extend(validate(raw, raw, f, cname, ctype, expect))

        if errs:
            all_errs.append((period, draw_date, errs))

        db.execute(
            f"INSERT OR REPLACE INTO multi_group_summary (draw_date, period, {', '.join(f for f,_,_,_,_ in MULTI_GROUP_COLS)}) "
            f"VALUES (?, ?, {', '.join('?' * len(MULTI_GROUP_COLS))})",
            [draw_date, period] + [vals[f] for f, _, _, _, _ in MULTI_GROUP_COLS],
        )
        inserted += 1

    db.commit()
    total = db.execute("SELECT COUNT(*) FROM multi_group_summary").fetchone()[0]
    db.close()

    print(f"✅ 导入完成：{inserted} 期（空行跳过 {skipped}），表内总 {total} 期")
    print(f"⚠️ 违规记录：{len(all_errs)} 条")
    for period, d, errs in all_errs[:30]:
        print(f"  {period} {d}: {errs}")

if __name__ == "__main__":
    main()
