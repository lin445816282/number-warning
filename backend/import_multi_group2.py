# -*- coding: utf-8 -*-
"""导入「多组汇总2.xlsx」→ multi_group_summary2 表（5家预测数据：哪吒/中特/金算/聚宝/米老）。

与 multi_group_summary（鬼/大家/诸葛/好运）并列的第二份多组汇总。
关键差异：金算六肖/聚宝六肖 是「生肖+号码」混合格式（如 牛18,鸡22,狗09），
拆成两个字段：生肖串(zodiac) + 号码串(codes)，命中率可双口径统计。
"""
import sqlite3, os, re, sys, datetime

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "data", "number_warning.db")

ZODIACS = "鼠牛虎兔龙蛇马羊猴鸡狗猪"

# ── 列元数据：字段名 -> 中文名 / 家 / 类型 / 期望数量 ──
# 类型：zodiac=12生肖 tail=0-9尾 codes=1-49号码 size=大/小 wave=红/蓝/绿 oddeven=单/双
MULTI_GROUP2_COLS = [
    ("nezha_zodiac8", "哪吒八肖", "哪吒", "zodiac", 8),
    ("nezha_tail5", "哪吒五尾", "哪吒", "tail", 5),
    ("nezha_zodiac7", "哪吒七肖", "哪吒", "zodiac", 7),
    ("nezha_zodiac6", "哪吒六肖", "哪吒", "zodiac", 6),
    ("nezha_zodiac4", "哪吒四肖", "哪吒", "zodiac", 4),
    ("nezha_zodiac3", "哪吒三肖", "哪吒", "zodiac", 3),
    ("nezha_zodiac2", "哪吒二肖", "哪吒", "zodiac", 2),
    ("nezha_zodiac1", "哪吒一肖", "哪吒", "zodiac", 1),
    ("nezha_codes1", "哪吒①码", "哪吒", "codes", 1),
    ("nezha_codes3", "哪吒③码", "哪吒", "codes", 3),
    ("nezha_codes5", "哪吒⑤码", "哪吒", "codes", 5),
    ("nezha_codes10", "哪吒⑩码", "哪吒", "codes", 10),
    ("nezha_santou", "哪吒三头", "哪吒", "head", 3),
    ("nezha_juesha3", "哪吒绝杀三肖", "哪吒", "zodiac", 3),
    ("nezha_qianhou3", "哪吒前后主三肖", "哪吒", "zodiac", 3),
    ("nezha_qianhou6", "哪吒前后主六码", "哪吒", "codes", 6),
    ("nezha_qizhong7", "哪吒七肖中特", "哪吒", "zodiac", 7),
    ("nezha_neimu1", "哪吒内幕平特", "哪吒", "zodiac", 1),
    ("nezha_codes13", "哪吒5期13码", "哪吒", "codes", 13),
    ("zhongte_wave1", "中特波一", "中特", "wave", 1),
    ("zhongte_wave2", "中特波二", "中特", "wave", 1),
    ("zhongte_codes6", "中特六码", "中特", "codes", 6),
    ("zhongte_tail5", "中特五尾", "中特", "tail", 5),
    ("jinsuan_zodiac6", "金算六肖·肖", "金算", "zodiac", 6),
    ("jinsuan_zodiac6_codes", "金算六肖·码", "金算", "codes", 6),
    ("jinsuan_codes6", "金算六码", "金算", "codes", 6),
    ("jinsuan_tail5", "金算五尾", "金算", "tail", 5),
    ("jubao_zodiac8", "聚宝八肖", "聚宝", "zodiac", 8),
    ("jubao_zodiac6", "聚宝六肖·肖", "聚宝", "zodiac", 6),
    ("jubao_zodiac6_codes", "聚宝六肖·码", "聚宝", "codes", 6),
    ("jubao_wave1", "聚宝波一", "聚宝", "wave", 1),
    ("jubao_wave2", "聚宝波二", "聚宝", "wave", 1),
    ("jubao_tail6", "聚宝六尾", "聚宝", "tail", 6),
    ("milao_zodiac7", "米老七肖", "米老", "zodiac", 7),
    ("milao_zodiac2", "米老肖2", "米老", "zodiac", 7),
    ("milao_wave1", "米老波一", "米老", "wave", 1),
    ("milao_wave2", "米老波二", "米老", "wave", 1),
    ("milao_oddeven", "米老单双", "米老", "oddeven", 1),
    ("milao_size", "米老大小", "米老", "size", 1),
    ("milao_codes12", "米老十二", "米老", "codes", 12),
]

# 需要拆分的「生肖+号码」列：Excel列索引(0-based) -> (生肖字段, 号码字段)
SPLIT_COLS = {
    8: ("jinsuan_zodiac6", "jinsuan_zodiac6_codes"),   # 金算六肖
    12: ("jubao_zodiac6", "jubao_zodiac6_codes"),      # 聚宝六肖
}

# 普通列：Excel列索引(0-based) -> 字段名
PLAIN_COLS = {
    2: "nezha_zodiac8", 3: "nezha_tail5", 4: "zhongte_wave1", 5: "zhongte_wave2",
    6: "zhongte_codes6", 7: "zhongte_tail5",
    9: "jinsuan_codes6", 10: "jinsuan_tail5",
    11: "jubao_zodiac8", 13: "jubao_wave1", 14: "jubao_wave2", 15: "jubao_tail6",
    16: "milao_zodiac7", 17: "milao_zodiac2", 18: "milao_wave1", 19: "milao_wave2",
    20: "milao_oddeven", 21: "milao_size", 22: "milao_codes12",
}


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
    """号码列：空格/点/逗号/顿号/- 统一分隔，补零两位，拆解漏分隔符 token。返回 (规范化字符串, 号码列表)。"""
    if v is None:
        return "", []
    s = str(v).strip()
    s = re.sub(r"[，,\s.\-、]+", " ", s)
    nums = []
    for tok in s.split():
        if tok.isdigit():
            nums.extend(split_num_token(int(tok)))
    out = ".".join(f"{n:02d}" for n in nums)
    return out, nums


def split_zodiac_num(v):
    """「生肖+号码」混合列：正则匹配 生肖+数字 配对（容忍 蛇.14 / 猴11 蛇26 等格式），
    返回 (生肖串, 号码串)。"""
    if v is None:
        return "", ""
    s = str(v).strip()
    pairs = re.findall(r"([鼠牛虎兔龙蛇马羊猴鸡狗猪])\s*[.。,，、\-\s]*(\d+)", s)
    zodiacs = [z for z, _ in pairs]
    codes = []
    for _, num in pairs:
        n = int(num)
        if 1 <= n <= 49:
            codes.append(n)
    z_str = "".join(zodiacs)
    c_str = ".".join(f"{n:02d}" for n in codes)
    return z_str, c_str


def main():
    xlsx = sys.argv[1] if len(sys.argv) > 1 else "/home/xiaolin/.hermes/cache/documents/doc_7af0a6e866cf_多组汇总2.xlsx"
    import openpyxl
    wb = openpyxl.load_workbook(xlsx, data_only=True)
    ws = wb["多组汇总"]
    rows = list(ws.iter_rows(values_only=True))

    db = sqlite3.connect(DB_PATH)
    cols_sql = ", ".join([f"{f} TEXT" for f, _, _, _, _ in MULTI_GROUP2_COLS])
    db.execute(f"""CREATE TABLE IF NOT EXISTS multi_group_summary2 (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        draw_date TEXT NOT NULL UNIQUE,
        period TEXT NOT NULL,
        {cols_sql}
    )""")
    db.commit()

    fields = [f for f, _, _, _, _ in MULTI_GROUP2_COLS]
    inserted = 0
    skipped = 0

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
        # 跳过整行空数据（未来空期）
        if all(row[i] is None or str(row[i]).strip() == "" for i in range(2, 23)):
            skipped += 1
            continue

        vals = {}
        for field in fields:
            vals[field] = ""
        # 普通列
        for col_idx, field in PLAIN_COLS.items():
            raw = row[col_idx] if col_idx < len(row) else None
            if raw is None or str(raw).strip() == "":
                continue
            ctype = next(c[3] for c in MULTI_GROUP2_COLS if c[0] == field)
            if ctype == "codes":
                s, _ = clean_codes(raw)
                vals[field] = s
            else:
                vals[field] = str(raw).strip()
        # 拆分列
        for col_idx, (zf, cf) in SPLIT_COLS.items():
            raw = row[col_idx] if col_idx < len(row) else None
            z_str, c_str = split_zodiac_num(raw)
            vals[zf] = z_str
            vals[cf] = c_str

        db.execute(
            f"INSERT OR REPLACE INTO multi_group_summary2 (draw_date, period, {', '.join(fields)}) "
            f"VALUES (?, ?, {', '.join('?' * len(fields))})",
            [draw_date, period] + [vals[f] for f in fields],
        )
        inserted += 1

    db.commit()
    total = db.execute("SELECT COUNT(*) FROM multi_group_summary2").fetchone()[0]
    date_min, date_max = db.execute(
        "SELECT MIN(draw_date), MAX(draw_date) FROM multi_group_summary2").fetchone()
    db.close()

    print(f"✅ 导入完成：{inserted} 期（空行跳过 {skipped}），表内总 {total} 期")
    print(f"   日期范围：{date_min} ~ {date_max}")


if __name__ == "__main__":
    main()
