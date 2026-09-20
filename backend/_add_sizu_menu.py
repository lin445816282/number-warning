"""新增「四组汇」顶层菜单（/sizu），插在多组肖汇(sort=13)之后、号码跟踪(sort=14)之前。"""
import sqlite3

db = sqlite3.connect('data/number_warning.db')
db.row_factory = sqlite3.Row

# 1. 腾位：号码跟踪 14->15，预测采集 15->16
db.execute("UPDATE sys_menu SET sort=16 WHERE id=11")   # 预测采集
db.execute("UPDATE sys_menu SET sort=15 WHERE id=14")   # 号码跟踪

# 2. 插入四组汇菜单 sort=14
cur = db.execute("SELECT id FROM sys_menu WHERE path='/sizu'").fetchone()
if cur:
    menu_id = cur['id']
    print(f"菜单已存在 id={menu_id}")
else:
    cur = db.execute(
        "INSERT INTO sys_menu (parent_id, menu_name, menu_type, path, perms, sort) VALUES (0, '四组汇', 1, '/sizu', '', 14)"
    )
    menu_id = cur.lastrowid
    print(f"新增菜单 id={menu_id}")

# 3. 授权给超管 role_id=1
db.execute("INSERT OR IGNORE INTO sys_role_menu (role_id, menu_id) VALUES (1, ?)", (menu_id,))

db.commit()

# 验证
print("\n=== 调整后顶层菜单 ===\n")
for m in db.execute("SELECT id, menu_name, path, sort FROM sys_menu WHERE parent_id=0 ORDER BY sort"):
    print(f"id={m['id']:3d} sort={m['sort']:3d} path={m['path']:20s} {m['menu_name']}")
db.close()
