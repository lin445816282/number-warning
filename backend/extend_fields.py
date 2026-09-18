# -*- coding: utf-8 -*-
"""扩展 multi_group_summary2 表：新增采集器将抓取的页面预测栏目字段。

字段命名 = 家名拼音 + 栏目缩写。类型：zodiac=生肖 codes=号码 wave=波色
tail=尾数 oddeven=单双 size=大小。
"""
import sqlite3, os

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "data", "number_warning.db")

# 新增字段：(字段名, 中文名, 家, 类型, 期望数量)
NEW_COLS = [
    # 中特网
    ("zhongte_zodiac6", "中特六肖", "中特", "zodiac", 6),
    ("zhongte_zodiac4", "中特四肖", "中特", "zodiac", 4),
    ("zhongte_zodiac2", "中特二肖", "中特", "zodiac", 2),
    ("zhongte_codes4", "中特四码", "中特", "codes", 4),
    ("zhongte_codes2", "中特二码", "中特", "codes", 2),
    ("zhongte_codes8", "中特八码", "中特", "codes", 8),
    ("zhongte_codes12", "中特精选12码", "中特", "codes", 12),
    ("zhongte_oddeven", "中特单双", "中特", "oddeven", 1),
    ("zhongte_size", "中特大小", "中特", "size", 1),
    # 金算盘
    ("jinsuan_zodiac5", "金算五肖", "金算", "zodiac", 5),
    ("jinsuan_zodiac3", "金算三肖", "金算", "zodiac", 3),
    ("jinsuan_zodiac1", "金算平特一肖", "金算", "zodiac", 1),
    ("jinsuan_codes4", "金算四码", "金算", "codes", 4),
    ("jinsuan_codes2", "金算二码", "金算", "codes", 2),
    ("jinsuan_codes3", "金算三码", "金算", "codes", 3),
    ("jinsuan_codes10", "金算精选10码", "金算", "codes", 10),
    # 聚宝盆
    ("jubao_zodiac7", "聚宝七肖", "聚宝", "zodiac", 7),
    ("jubao_zodiac4", "聚宝四肖", "聚宝", "zodiac", 4),
    ("jubao_zodiac2", "聚宝二肖", "聚宝", "zodiac", 2),
    ("jubao_codes7", "聚宝七码", "聚宝", "codes", 7),
    ("jubao_codes5", "聚宝五码", "聚宝", "codes", 5),
    ("jubao_codes3", "聚宝三码", "聚宝", "codes", 3),
    # 2026-09 第二轮新增：中特十三码/三期四肖 + 聚宝九栏目
    ("zhongte_codes13", "中特十三码", "中特", "codes", 13),
    ("zhongte_zodiac4_3q", "中特三期四肖", "中特", "zodiac", 4),
    ("jubao_jaye", "聚宝家野", "聚宝", "zodiac", 6),
    ("jubao_boduan", "聚宝波段", "聚宝", "wave", 1),
    ("jubao_danshuang", "聚宝单双", "聚宝", "oddeven", 1),
    ("jubao_sanqi12", "聚宝三期十二码", "聚宝", "codes", 16),
    ("jubao_heshu", "聚宝合数", "聚宝", "size", 1),
    ("jubao_sixiao3q", "聚宝三期四肖", "聚宝", "zodiac", 4),
    ("jubao_codes12", "聚宝12码", "聚宝", "codes", 12),
    ("jubao_santou", "聚宝三头", "聚宝", "head", 3),
    ("jubao_codes16", "聚宝16码", "聚宝", "codes", 16),
]

def main():
    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()
    # 现有列
    existing = {r[1] for r in cur.execute("PRAGMA table_info(multi_group_summary2)").fetchall()}
    added = []
    for f, cname, fam, ctype, expect in NEW_COLS:
        if f in existing:
            print(f"跳过（已存在）: {f}")
            continue
        cur.execute(f"ALTER TABLE multi_group_summary2 ADD COLUMN {f} TEXT DEFAULT ''")
        added.append(f)
    db.commit()
    print(f"✅ 新增 {len(added)} 个字段：")
    for f in added:
        print(f"  {f}")
    total = len(cur.execute("PRAGMA table_info(multi_group_summary2)").fetchall())
    print(f"表当前总列数：{total}")
    db.close()

if __name__ == "__main__":
    main()
