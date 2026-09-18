# -*- coding: utf-8 -*-
"""扩展 multi_group_summary（V1）表：新增 4 家页面「其他预测栏目」字段。

聚焦正向预测栏目（多级生肖/多级码/平特一肖/尾/单双/大小），
跳过杀号（绝杀X肖/稳杀X尾，命中口径不同）与营销文案。
"""
import sqlite3, os

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "data", "number_warning.db")

NEW_COLS = [
    # 鬼谷子
    ("gui_pingte_zodiac1", "鬼谷平特一肖", "鬼", "zodiac", 1),
    ("gui_pingte_tail", "鬼谷平特一尾", "鬼", "tail", 5),
    ("gui_tail6", "鬼谷六尾中特", "鬼", "tail", 6),
    ("gui_zodiac4", "鬼谷内部四肖", "鬼", "zodiac", 4),
    # 诸葛
    ("zhuge_zodiac9", "诸葛九肖", "诸葛", "zodiac", 9),
    ("zhuge_zodiac7", "诸葛七肖", "诸葛", "zodiac", 7),
    ("zhuge_zodiac5", "诸葛五肖", "诸葛", "zodiac", 5),
    ("zhuge_zodiac3", "诸葛三肖", "诸葛", "zodiac", 3),
    ("zhuge_pingte_tail", "诸葛平特一尾", "诸葛", "tail", 5),
    ("zhuge_size", "诸葛大小中特", "诸葛", "size", 1),
    ("zhuge_oddeven", "诸葛单双中特", "诸葛", "oddeven", 1),
    # 大家发
    ("dajia_pingte_zodiac1", "大家平特一肖", "大家", "zodiac", 1),
    ("dajia_pingte_tail", "大家平特一尾", "大家", "tail", 5),
    # 好运通
    ("haoyun_zodiac7", "好运七肖", "好运", "zodiac", 7),
    ("haoyun_zodiac5", "好运五肖", "好运", "zodiac", 5),
    ("haoyun_zodiac1", "好运一肖", "好运", "zodiac", 1),
    ("haoyun_codes6", "好运六码", "好运", "codes", 6),
    ("haoyun_codes5", "好运五码", "好运", "codes", 5),
    # 2026-09 第二轮新增：鬼谷12码/三期四肖 + 大家24码/家野/三期四肖 + 好运六肖/24码/16码/三头
    ("gui_zodiac4_3q", "鬼谷三期四肖", "鬼", "zodiac", 4),
    ("gui_codes12", "鬼谷极限12码", "鬼", "codes", 12),
    ("dajia_codes24", "大家24码", "大家", "codes", 24),
    ("dajia_jaye", "大家家野", "大家", "zodiac", 1),
    ("dajia_sixiao3q", "大家三期四肖", "大家", "zodiac", 4),
    ("haoyun_zodiac6", "好运六肖", "好运", "zodiac", 6),
    ("haoyun_codes24", "好运24码", "好运", "codes", 24),
    ("haoyun_codes16", "好运16码", "好运", "codes", 16),
    ("haoyun_santou", "好运三头", "好运", "head", 3),
]

def main():
    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()
    existing = {r[1] for r in cur.execute("PRAGMA table_info(multi_group_summary)").fetchall()}
    added = []
    for f, cname, fam, ctype, expect in NEW_COLS:
        if f in existing:
            print(f"跳过（已存在）: {f}")
            continue
        cur.execute(f"ALTER TABLE multi_group_summary ADD COLUMN {f} TEXT DEFAULT ''")
        added.append(f)
    db.commit()
    print(f"✅ 新增 {len(added)} 个字段：")
    for f in added:
        print(f"  {f}")
    total = len(cur.execute("PRAGMA table_info(multi_group_summary)").fetchall())
    print(f"表当前总列数：{total}")
    db.close()

if __name__ == "__main__":
    main()
