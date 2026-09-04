#!/usr/bin/env python3
"""号码知识库全维度智能预警系统 — FastAPI + SQLite 单文件后端"""
import os
import json
import hmac
import hashlib
import base64
import sqlite3
import time
from datetime import datetime, date
from typing import Optional

from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "number_warning.db")
STATIC_DIR = os.path.join(BASE_DIR, "static")
os.makedirs(DATA_DIR, exist_ok=True)

app = FastAPI(title="号码知识库全维度智能预警系统")

# ============================================================
# 一、固定标签映射表（17 维度）
# ============================================================
DIM_NAMES = {
    "zodiac": "生肖", "odd_even": "单双", "big_small": "大小",
    "size_odd_even": "大小单双",
    "five_element": "五行", "wave_color": "号码波色", "he_sum": "合数单双",
    "animal_type": "家禽野兽", "zodiac_seq": "前后肖", "beauty_type": "吉美凶丑",
    "yin_yang": "阴阳", "stroke_type": "单笔双笔", "sky_earth": "天地肖",
    "edge_color": "白边黑中", "gender_zodiac": "男女肖", "qqsh_type": "琴棋书画",
    "season_type": "春夏秋冬", "zodiac_color_type": "红肖蓝肖绿肖",
    "head_number": "头数", "tail_number": "尾数",
}

# 核心关注维度（信号跟踪页单独归组置顶，2026-09-02 用户指定）
CORE_DIMS = ["tail_number", "head_number", "zodiac", "season_type", "wave_color", "zodiac_color_type"]

# 号码直接维度（1-49 数字 → 标签）
_ODD = {1,3,5,7,9,11,13,15,17,19,21,23,25,27,29,31,33,35,37,39,41,43,45,47,49}
_BIG = set(range(25, 50))

_FIVE = {
    "金": [4,5,12,13,26,27,34,35,42,43],
    "木": [8,9,16,17,24,25,38,39,46,47],
    "水": [1,14,15,22,23,30,31,44,45],
    "火": [2,3,10,11,18,19,32,33,40,41,48,49],
    "土": [6,7,20,21,28,29,36,37],
}
_WAVE = {
    "红波": [1,2,7,8,12,13,18,19,23,24,29,30,34,35,40,45,46],
    "蓝波": [3,4,9,10,14,15,20,25,26,31,36,37,41,42,47,48],
    "绿波": [5,6,11,16,17,21,22,27,28,32,33,38,39,43,44,49],
}
_HE_ODD = {1,3,5,7,9,10,12,14,16,18,21,23,25,27,29,30,32,34,36,38,41,43,45,47,49}
_HE_EVEN = {2,4,6,8,11,13,15,17,19,20,22,24,26,28,31,33,35,37,39,40,42,44,46,48}

# 生肖衍生维度（生肖 → 标签）
_ANIMAL = {"家禽": ["牛","马","羊","鸡","狗","猪"], "野兽": ["鼠","虎","兔","龙","蛇","猴"]}
_ZSEQ = {"前肖": ["鼠","牛","虎","兔","龙","蛇"], "后肖": ["马","羊","猴","鸡","狗","猪"]}
_BEAUTY = {"吉美": ["兔","龙","蛇","马","羊","鸡"], "凶丑": ["鼠","牛","虎","猴","狗","猪"]}
_YINYANG = {"阴性": ["鼠","龙","蛇","马","狗","猪"], "阳性": ["牛","虎","兔","羊","猴","鸡"]}
_STROKE = {"单笔": ["鼠","龙","马","蛇","鸡","猪"], "双笔": ["虎","猴","狗","兔","羊","牛"]}
_SKY = {"天肖": ["兔","马","猴","猪","牛","龙"], "地肖": ["蛇","羊","鸡","狗","鼠","虎"]}
_EDGE = {"白边": ["鼠","牛","虎","鸡","狗","猪"], "黑中": ["兔","龙","蛇","马","羊","猴"]}
_GENDER = {"女肖": ["兔","蛇","羊","鸡","猪"], "男肖": ["鼠","牛","虎","龙","马","猴","狗"]}
_QQSH = {"琴": ["蛇","兔","鸡"], "棋": ["牛","鼠","狗"], "书": ["龙","虎","马"], "画": ["猪","猴","羊"]}
_SEASON = {"春": ["龙","兔","虎"], "夏": ["蛇","羊","马"], "秋": ["狗","鸡","猴"], "冬": ["牛","鼠","猪"]}
_ZCOLOR = {"红肖": ["兔","鼠","鸡","马"], "蓝肖": ["蛇","虎","猪","猴"], "绿肖": ["龙","牛","狗","羊"]}

def _reverse_map(mapping):
    """{标签: [号码]} → {号码: 标签}"""
    out = {}
    for tag, nums in mapping.items():
        for n in nums:
            out[n] = tag
    return out

_NUM_FIVE = _reverse_map(_FIVE)
_NUM_WAVE = _reverse_map(_WAVE)
_NUM_HE = {**{n: "合数单" for n in _HE_ODD}, **{n: "合数双" for n in _HE_EVEN}}

def _zodiac_label(mapping, zodiac):
    """生肖衍生映射 {标签: [生肖]} → 给定生肖返回标签"""
    for tag, zs in mapping.items():
        if zodiac in zs:
            return tag
    return ""

# ============================================================
# 二、数据库连接 + Schema + 种子数据
# ============================================================
def get_db():
    db = sqlite3.connect(DB_PATH, timeout=15)
    db.row_factory = sqlite3.Row
    return db

SCHEMA = """
CREATE TABLE IF NOT EXISTS sys_user (
  id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL,
  password TEXT NOT NULL, real_name TEXT DEFAULT '', role_id INTEGER DEFAULT 0,
  status INTEGER DEFAULT 1, create_time TEXT, update_time TEXT
);
CREATE TABLE IF NOT EXISTS sys_role (
  id INTEGER PRIMARY KEY AUTOINCREMENT, role_name TEXT, role_code TEXT UNIQUE,
  remark TEXT DEFAULT '', create_time TEXT
);
CREATE TABLE IF NOT EXISTS sys_menu (
  id INTEGER PRIMARY KEY AUTOINCREMENT, parent_id INTEGER DEFAULT 0,
  menu_name TEXT, menu_type INTEGER DEFAULT 1, path TEXT DEFAULT '',
  perms TEXT DEFAULT '', sort INTEGER DEFAULT 0,
  UNIQUE(path)
);
CREATE TABLE IF NOT EXISTS sys_role_menu (
  id INTEGER PRIMARY KEY AUTOINCREMENT, role_id INTEGER, menu_id INTEGER,
  UNIQUE(role_id, menu_id)
);
CREATE TABLE IF NOT EXISTS sys_config (
  id INTEGER PRIMARY KEY AUTOINCREMENT, config_key TEXT UNIQUE,
  config_value TEXT, remark TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS zodiac_number_cycle_config (
  id INTEGER PRIMARY KEY AUTOINCREMENT, cycle_name TEXT, start_date TEXT,
  zodiac_mapping TEXT, is_enable INTEGER DEFAULT 1, create_time TEXT,
  UNIQUE(cycle_name, start_date)
);
CREATE TABLE IF NOT EXISTS number_knowledge_record (
  id INTEGER PRIMARY KEY AUTOINCREMENT, record_date TEXT, source_number TEXT,
  rank_value INTEGER, zodiac TEXT DEFAULT '', odd_even TEXT DEFAULT '',
  big_small TEXT DEFAULT '', size_odd_even TEXT DEFAULT '', five_element TEXT DEFAULT '', wave_color TEXT DEFAULT '',
  he_sum TEXT DEFAULT '', animal_type TEXT DEFAULT '', zodiac_seq TEXT DEFAULT '',
  beauty_type TEXT DEFAULT '', yin_yang TEXT DEFAULT '', stroke_type TEXT DEFAULT '',
  sky_earth TEXT DEFAULT '', edge_color TEXT DEFAULT '', gender_zodiac TEXT DEFAULT '',
  qqsh_type TEXT DEFAULT '', season_type TEXT DEFAULT '', zodiac_color_type TEXT DEFAULT '',
  head_number TEXT DEFAULT '', tail_number TEXT DEFAULT '',
  warn_json TEXT, status INTEGER DEFAULT 0, match_time TEXT, cycle_id INTEGER,
  create_time TEXT,
  UNIQUE(record_date)
);
CREATE TABLE IF NOT EXISTS number_match_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT, record_id INTEGER, cycle_id INTEGER,
  full_match_json TEXT, rank_value INTEGER, warn_json TEXT,
  match_result_status INTEGER DEFAULT 1, error_msg TEXT DEFAULT '',
  operate_user TEXT DEFAULT '', create_time TEXT
);
CREATE TABLE IF NOT EXISTS dim_tag_rank_max (
  id INTEGER PRIMARY KEY AUTOINCREMENT, dim_key TEXT, dim_name TEXT, tag_value TEXT,
  history_max_rank INTEGER DEFAULT 0, total_sample INTEGER DEFAULT 0,
  current_rank INTEGER DEFAULT 0,
  history_max_start_date TEXT, history_max_end_date TEXT,
  last_update_time TEXT,
  UNIQUE(dim_key, tag_value)
);
CREATE TABLE IF NOT EXISTS warn_signal_track (
  id INTEGER PRIMARY KEY AUTOINCREMENT, dim_key TEXT, dim_name TEXT, tag_value TEXT,
  signal_seq INTEGER, signal_date TEXT, signal_rank INTEGER,
  history_max_rank INTEGER DEFAULT 0,
  hit_interval INTEGER, hit_date TEXT,
  create_time TEXT
);
"""

# 默认生肖映射（丙午马年 2026-02-17）
DEFAULT_ZODIAC = {
    "马": [1,13,25,37,49], "蛇": [2,14,26,38], "龙": [3,15,27,39],
    "兔": [4,16,28,40], "虎": [5,17,29,41], "牛": [6,18,30,42],
    "鼠": [7,19,31,43], "猪": [8,20,32,44], "狗": [9,21,33,45],
    "鸡": [10,22,34,46], "猴": [11,23,35,47], "羊": [12,24,36,48],
}

MENUS = [
    (1, 0, "仪表盘", 1, "/dashboard", "dashboard:view", 1),
    (2, 0, "号码数据", 1, "/records", "record:view", 2),
    (3, 0, "周期配置", 1, "/cycles", "cycle:view", 3),
    (4, 0, "匹配历史", 1, "/history", "history:view", 4),
    (5, 0, "维度统计", 1, "/dimstats", "dim:view", 5),
    (6, 0, "系统参数", 1, "/config", "config:view", 6),
    (7, 0, "用户管理", 1, "/users", "user:view", 7),
    (8, 0, "角色权限", 1, "/roles", "role:view", 8),
    (9, 0, "信号跟踪", 1, "/signaltrack", "signal:view", 9),
]

def _sha256(pwd):
    return hashlib.sha256(("nw-salt-" + pwd).encode()).hexdigest()

def init_db():
    db = sqlite3.connect(DB_PATH, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript(SCHEMA)
    # 迁移：为已存在的 dim_tag_rank_max 补 current_rank / 历史最高起止日期 字段
    cols = [r[1] for r in db.execute("PRAGMA table_info(dim_tag_rank_max)").fetchall()]
    if "current_rank" not in cols:
        db.execute("ALTER TABLE dim_tag_rank_max ADD COLUMN current_rank INTEGER DEFAULT 0")
    if "history_max_start_date" not in cols:
        db.execute("ALTER TABLE dim_tag_rank_max ADD COLUMN history_max_start_date TEXT")
    if "history_max_end_date" not in cols:
        db.execute("ALTER TABLE dim_tag_rank_max ADD COLUMN history_max_end_date TEXT")
    # 迁移：number_knowledge_record 补 head_number / tail_number 字段（头数/尾数）
    ncols = [r[1] for r in db.execute("PRAGMA table_info(number_knowledge_record)").fetchall()]
    if "head_number" not in ncols:
        db.execute("ALTER TABLE number_knowledge_record ADD COLUMN head_number TEXT DEFAULT ''")
    if "tail_number" not in ncols:
        db.execute("ALTER TABLE number_knowledge_record ADD COLUMN tail_number TEXT DEFAULT ''")
    if "size_odd_even" not in ncols:
        db.execute("ALTER TABLE number_knowledge_record ADD COLUMN size_odd_even TEXT DEFAULT ''")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 角色
    roles = [
        ("超级管理员", "super_admin", "全部权限"),
        ("运营操作员", "operator", "数据查看/匹配/历史"),
        ("只读查看员", "viewer", "仅查看"),
    ]
    for name, code, remark in roles:
        db.execute("INSERT OR IGNORE INTO sys_role (role_name, role_code, remark, create_time) VALUES (?,?,?,?)",
                   (name, code, remark, now))

    # 默认账号 admin / 8283103（超级管理员）
    role_id = db.execute("SELECT id FROM sys_role WHERE role_code='super_admin'").fetchone()["id"]
    db.execute("INSERT OR IGNORE INTO sys_user (username, password, real_name, role_id, status, create_time, update_time) VALUES (?,?,?,?,?,?,?)",
               ("admin", _sha256("8283103"), "系统管理员", role_id, 1, now, now))

    # 菜单
    for mid, pid, name, mtype, path, perms, sort in MENUS:
        db.execute("INSERT OR IGNORE INTO sys_menu (id, parent_id, menu_name, menu_type, path, perms, sort) VALUES (?,?,?,?,?,?,?)",
                   (mid, pid, name, mtype, path, perms, sort))

    # 超级管理员拥有全部菜单；运营/只读拥有部分
    all_menu_ids = [m[0] for m in MENUS]
    for mid in all_menu_ids:
        db.execute("INSERT OR IGNORE INTO sys_role_menu (role_id, menu_id) VALUES (?,?)", (role_id, mid))
    # 运营操作员：仪表盘、号码数据、周期配置、匹配历史
    op_id = db.execute("SELECT id FROM sys_role WHERE role_code='operator'").fetchone()["id"]
    for mid in [1, 2, 3, 4]:
        db.execute("INSERT OR IGNORE INTO sys_role_menu (role_id, menu_id) VALUES (?,?)", (op_id, mid))
    # 只读：仪表盘、号码数据、匹配历史
    vw_id = db.execute("SELECT id FROM sys_role WHERE role_code='viewer'").fetchone()["id"]
    for mid in [1, 2, 4]:
        db.execute("INSERT OR IGNORE INTO sys_role_menu (role_id, menu_id) VALUES (?,?)", (vw_id, mid))

    # 系统配置
    db.execute("INSERT OR IGNORE INTO sys_config (config_key, config_value, remark) VALUES (?,?,?)",
               ("warn_rank_offset", "2", "高位预警偏移值"))
    db.execute("INSERT OR IGNORE INTO sys_config (config_key, config_value, remark) VALUES (?,?,?)",
               ("front_access_pwd", "8283103", "前台访问密码"))

    # 丙午马年周期配置
    db.execute("INSERT OR IGNORE INTO zodiac_number_cycle_config (cycle_name, start_date, zodiac_mapping, is_enable, create_time) VALUES (?,?,?,?,?)",
               ("丙午马年", "2026-02-17", json.dumps(DEFAULT_ZODIAC, ensure_ascii=False), 1, now))

    db.commit()
    db.close()

init_db()

# ============================================================
# 三、JWT 工具（stdlib 手写 HS256）
# ============================================================
SECRET = "number-warning-jwt-secret-2026"
TOKEN_TTL = 24 * 3600  # 24 小时

def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

def create_token(payload: dict) -> str:
    payload = dict(payload)
    payload["exp"] = int(time.time()) + TOKEN_TTL
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = _b64url(json.dumps(payload, ensure_ascii=False).encode())
    sig = _b64url(hmac.new(SECRET.encode(), f"{header}.{body}".encode(), hashlib.sha256).digest())
    return f"{header}.{body}.{sig}"

def verify_token(token: str):
    try:
        h, b, s = token.split(".")
        sig = _b64url(hmac.new(SECRET.encode(), f"{h}.{b}".encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, s):
            return None
        pad = "=" * (-len(b) % 4)
        payload = json.loads(base64.urlsafe_b64decode(b + pad))
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None

def require_user(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "未登录")
    payload = verify_token(authorization[7:])
    if not payload:
        raise HTTPException(401, "登录已过期，请重新登录")
    return payload

def require_admin(user=Header(None, alias="authorization")):
    p = require_user(user)
    if p.get("role_code") != "super_admin":
        raise HTTPException(403, "无权限，仅超级管理员可操作")
    return p

# ============================================================
# 四、标签匹配引擎
# ============================================================
def _num_to_zodiac(num: int, zodiac_mapping: dict) -> str:
    for z, nums in zodiac_mapping.items():
        if num in nums:
            return z
    return ""

def match_labels(source_number, zodiac_mapping):
    """给定号码 + 生肖映射，返回 17 维度标签 dict"""
    num = int(source_number)
    zodiac = _num_to_zodiac(num, zodiac_mapping)
    labels = {
        "zodiac": zodiac,
        "odd_even": "单数" if num in _ODD else "双数",
        "big_small": "大数" if num in _BIG else "小数",
        "size_odd_even": ("大" if num in _BIG else "小") + ("单" if num in _ODD else "双"),
        "five_element": _NUM_FIVE.get(num, ""),
        "wave_color": _NUM_WAVE.get(num, ""),
        "he_sum": _NUM_HE.get(num, ""),
        "animal_type": _zodiac_label(_ANIMAL, zodiac),
        "zodiac_seq": _zodiac_label(_ZSEQ, zodiac),
        "beauty_type": _zodiac_label(_BEAUTY, zodiac),
        "yin_yang": _zodiac_label(_YINYANG, zodiac),
        "stroke_type": _zodiac_label(_STROKE, zodiac),
        "sky_earth": _zodiac_label(_SKY, zodiac),
        "edge_color": _zodiac_label(_EDGE, zodiac),
        "gender_zodiac": _zodiac_label(_GENDER, zodiac),
        "qqsh_type": _zodiac_label(_QQSH, zodiac),
        "season_type": _zodiac_label(_SEASON, zodiac),
        "zodiac_color_type": _zodiac_label(_ZCOLOR, zodiac),
        "head_number": str(num // 10),  # 头数（十位）
        "tail_number": str(num % 10),   # 尾数（个位）
    }
    return labels

# ============================================================
# 五、统计表维护 + 预警引擎
# ============================================================
def get_warn_offset(db=None):
    own = db is None
    if own:
        db = get_db()
    row = db.execute("SELECT config_value FROM sys_config WHERE config_key='warn_rank_offset'").fetchone()
    if own:
        db.close()
    try:
        return int(row["config_value"]) if row else 2
    except Exception:
        return 2

def get_front_pwd(db=None):
    """前台访问密码（sys_config: front_access_pwd，默认 8283103）"""
    own = db is None
    if own:
        db = get_db()
    row = db.execute("SELECT config_value FROM sys_config WHERE config_key='front_access_pwd'").fetchone()
    if own:
        db.close()
    return (row["config_value"] if row else "8283103") or "8283103"

def front_token_valid(token: str) -> bool:
    """校验前台访问令牌（payload 带 front 标记）"""
    if not token:
        return False
    payload = verify_token(token)
    return bool(payload and payload.get("front"))

def _maintain_rank_max(db, labels, rank_value, gap_start_date=None, gap_end_date=None):
    """维护 dim_tag_rank_max，返回更新后的 (dim_key, tag_value, history_max_rank, total_sample) 列表。
    rank_value 打破历史最高时，记录该间隔的起止日期（gap_start_date=上次出现日期，gap_end_date=本次出现日期）。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    updated = []
    for dim_key, tag in labels.items():
        if not tag:
            continue
        row = db.execute("SELECT * FROM dim_tag_rank_max WHERE dim_key=? AND tag_value=?", (dim_key, tag)).fetchone()
        if row is None:
            db.execute("INSERT INTO dim_tag_rank_max (dim_key, dim_name, tag_value, history_max_rank, total_sample, history_max_start_date, history_max_end_date, last_update_time) VALUES (?,?,?,?,?,?,?,?)",
                       (dim_key, DIM_NAMES.get(dim_key, dim_key), tag, rank_value or 0, 1, gap_start_date, gap_end_date, now))
        else:
            rv = rank_value or 0
            new_max = max(row["history_max_rank"] or 0, rv)
            if rv > (row["history_max_rank"] or 0):
                # 打破历史最高，记录起止日期
                db.execute("UPDATE dim_tag_rank_max SET history_max_rank=?, total_sample=?, history_max_start_date=?, history_max_end_date=?, last_update_time=? WHERE id=?",
                           (new_max, row["total_sample"] + 1, gap_start_date, gap_end_date, now, row["id"]))
            else:
                db.execute("UPDATE dim_tag_rank_max SET history_max_rank=?, total_sample=?, last_update_time=? WHERE id=?",
                           (new_max, row["total_sample"] + 1, now, row["id"]))
        fresh = db.execute("SELECT * FROM dim_tag_rank_max WHERE dim_key=? AND tag_value=?", (dim_key, tag)).fetchone()
        updated.append((dim_key, tag, fresh["history_max_rank"], fresh["total_sample"]))
    return updated

def compute_warnings(updated, rank_value, offset):
    """根据更新后的统计表计算预警数组"""
    warns = []
    for dim_key, tag, hist_max, sample in updated:
        if sample < 2:
            continue
        threshold = (hist_max or 0) - offset
        if rank_value is not None and rank_value >= threshold:
            diff = (hist_max or 0) - rank_value
            warns.append({
                "dim_key": dim_key,
                "dim_name": DIM_NAMES.get(dim_key, dim_key),
                "tag_value": tag,
                "current_rank": rank_value,
                "history_max_rank": hist_max,
                "diff": diff,
                "warn_desc": f"{DIM_NAMES.get(dim_key, dim_key)}-{tag}，当前排位{rank_value}，历史最高排位{hist_max}，距离高位差{diff}位",
            })
    return warns

# ============================================================
# 六、匹配主流程
# ============================================================
def do_match(record_id, operate_user="", db=None):
    """执行单条匹配，返回 (ok, err_msg)"""
    own = db is None
    if own:
        db = get_db()
    try:
        rec = db.execute("SELECT * FROM number_knowledge_record WHERE id=?", (record_id,)).fetchone()
        if rec is None:
            return False, "记录不存在"
        # 幂等保护：已匹配过的记录跳过，避免重复累计统计样本
        if rec["status"] == 1:
            return True, "已匹配（跳过重复累计）"

        # 1. 找生效周期
        cycle = db.execute(
            "SELECT * FROM zodiac_number_cycle_config WHERE is_enable=1 AND start_date<=? ORDER BY start_date DESC LIMIT 1",
            (rec["record_date"],)).fetchone()
        if cycle is None:
            db.execute("UPDATE number_knowledge_record SET status=2 WHERE id=?", (record_id,))
            db.execute("INSERT INTO number_match_history (record_id, cycle_id, full_match_json, rank_value, warn_json, match_result_status, error_msg, operate_user, create_time) VALUES (?,?,?,?,?,?,?,?,?)",
                       (record_id, None, "{}", rec["rank_value"], "[]", 2, "未找到生效的生肖周期配置", operate_user, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            db.commit()
            return False, "未找到生效的生肖周期配置"

        zodiac_mapping = json.loads(cycle["zodiac_mapping"])
        labels = match_labels(rec["source_number"], zodiac_mapping)

        # 2. 维护统计表
        updated = _maintain_rank_max(db, labels, rec["rank_value"])

        # 3. 计算预警
        offset = get_warn_offset(db)
        warns = compute_warnings(updated, rec["rank_value"], offset)

        # 4. 组装快照
        full_match = {
            "cycle_id": cycle["id"], "cycle_name": cycle["cycle_name"],
            "source_number": rec["source_number"], "rank_value": rec["rank_value"],
            "labels": labels, "warn_count": len(warns),
        }
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        warn_json = json.dumps(warns, ensure_ascii=False)
        full_json = json.dumps(full_match, ensure_ascii=False)

        # 5. 更新主表
        db.execute("""UPDATE number_knowledge_record SET zodiac=?, odd_even=?, big_small=?, size_odd_even=?, five_element=?, wave_color=?, he_sum=?,
            animal_type=?, zodiac_seq=?, beauty_type=?, yin_yang=?, stroke_type=?, sky_earth=?, edge_color=?, gender_zodiac=?,
            qqsh_type=?, season_type=?, zodiac_color_type=?, head_number=?, tail_number=?, warn_json=?, status=1, match_time=?, cycle_id=? WHERE id=?""",
            (labels["zodiac"], labels["odd_even"], labels["big_small"], labels["size_odd_even"], labels["five_element"], labels["wave_color"], labels["he_sum"],
             labels["animal_type"], labels["zodiac_seq"], labels["beauty_type"], labels["yin_yang"], labels["stroke_type"],
             labels["sky_earth"], labels["edge_color"], labels["gender_zodiac"], labels["qqsh_type"], labels["season_type"],
             labels["zodiac_color_type"], labels["head_number"], labels["tail_number"], warn_json, now, cycle["id"], record_id))

        # 6. 写历史快照
        db.execute("INSERT INTO number_match_history (record_id, cycle_id, full_match_json, rank_value, warn_json, match_result_status, error_msg, operate_user, create_time) VALUES (?,?,?,?,?,?,?,?,?)",
                   (record_id, cycle["id"], full_json, rec["rank_value"], warn_json, 1, "", operate_user, now))
        db.commit()
        return True, ""
    except Exception as e:
        try:
            db.execute("UPDATE number_knowledge_record SET status=2 WHERE id=?", (record_id,))
            db.commit()
        except Exception:
            pass
        return False, str(e)
    finally:
        if own:
            db.close()

def rebuild_rank_max():
    """一键重建统计表：按日期遍历，计算每个标签的间隔期数(遗漏值)作为排位，逐条写回 + 重算预警"""
    db = get_db()
    db.execute("DELETE FROM dim_tag_rank_max")
    rows = db.execute("SELECT * FROM number_knowledge_record WHERE status=1 ORDER BY record_date, id").fetchall()
    offset = get_warn_offset(db)

    last_seen = {}  # (dim_key, tag_value) -> 上次出现的序号
    last_seen_date = {}  # (dim_key, tag_value) -> 上次出现的日期
    for idx, r in enumerate(rows):
        cycle = db.execute("SELECT * FROM zodiac_number_cycle_config WHERE id=?", (r["cycle_id"],)).fetchone()
        if cycle is None:
            continue
        labels = match_labels(r["source_number"], json.loads(cycle["zodiac_mapping"]))
        seq = idx + 1
        gaps = {}
        warns = []
        for dim_key, tag in labels.items():
            if not tag:
                continue
            key = (dim_key, tag)
            gap = None
            gap_start_date = None
            if key in last_seen:
                gap = seq - last_seen[key]
                gap_start_date = last_seen_date[key]  # 上次出现那期日期
            last_seen[key] = seq
            last_seen_date[key] = r["record_date"]
            gaps[dim_key] = gap
            updated = _maintain_rank_max(db, {dim_key: tag}, gap, gap_start_date, r["record_date"])
            # updated = [(dim_key, tag, history_max_rank(含当期), total_sample)]
            _, _, hist_max, sample = updated[0]
            # 预警条件：当期间隔期数 ≥ 历史最高 − 偏移值，且样本 ≥ 2
            if gap is not None and sample >= 2:
                threshold = (hist_max or 0) - offset
                if gap >= threshold:
                    warns.append({
                        "dim_key": dim_key,
                        "dim_name": DIM_NAMES.get(dim_key, dim_key),
                        "tag_value": tag,
                        "current_rank": gap,
                        "history_max_rank": hist_max,
                        "diff": hist_max - gap,
                        "warn_desc": f"{DIM_NAMES.get(dim_key, dim_key)}-{tag}，当前排位{gap}，历史最高排位{hist_max}，距离高位差{hist_max - gap}位",
                    })
        # 写回主表 warn_json + 头数/尾数/大小单双 + 历史快照 gaps/warn_json
        db.execute("UPDATE number_knowledge_record SET warn_json=?, head_number=?, tail_number=?, size_odd_even=? WHERE id=?",
                   (json.dumps(warns, ensure_ascii=False), labels["head_number"], labels["tail_number"], labels["size_odd_even"], r["id"]))
        _write_gaps_to_history(db, r["id"], gaps, warns)

    # 计算「当前遗漏期数」current_rank = 最新一期序号 - 该标签最后出现序号
    # 某标签刚在最新一期出现 → current_rank=0；连续 N 期没出 → current_rank=N
    if last_seen:
        total_seq = max(last_seen.values())  # 最新一期的序号
        for (dim_key, tag), seq in last_seen.items():
            db.execute("UPDATE dim_tag_rank_max SET current_rank=? WHERE dim_key=? AND tag_value=?",
                       (total_seq - seq, dim_key, tag))

    db.commit()
    cnt = db.execute("SELECT COUNT(*) c FROM dim_tag_rank_max").fetchone()["c"]
    db.close()
    return cnt


def rebuild_signal_track():
    """一键重建信号跟踪表：全量回放，记录每个标签「遗漏首次接近/超过历史高位」的信号，
    并跟踪后续几期内是否开出。首次触发口径：每个连续遗漏周期只记一次信号。"""
    db = get_db()
    db.execute("DELETE FROM warn_signal_track")
    rows = db.execute("SELECT * FROM number_knowledge_record WHERE status=1 ORDER BY record_date, id").fetchall()
    offset = get_warn_offset(db)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 维度字段（与 match_labels 输出的 key 一致）
    dim_cols = list(DIM_NAMES.keys())

    last_seen = {}        # (dim, tag) -> 上次出现序号
    hist_max = {}         # (dim, tag) -> 历史最大遗漏（含当前，动态增长）
    sample = {}           # (dim, tag) -> 出现次数
    pending = {}          # (dim, tag) -> {seq, date, rank, hist_max} 已触发未开出的信号
    all_keys = set()

    inserts = []

    for idx, r in enumerate(rows):
        seq = idx + 1
        present = set()
        # 1) 本期开出的标签：结算 pending 命中 + 更新 last_seen/hist_max/sample
        for dim in dim_cols:
            tag = r[dim]
            if not tag:
                continue
            key = (dim, tag)
            present.add(key)
            all_keys.add(key)
            if key in pending:
                sig = pending.pop(key)
                hit_interval = seq - sig["seq"]
                inserts.append((dim, DIM_NAMES.get(dim, dim), tag, sig["seq"], sig["date"],
                                sig["rank"], sig["hist_max"], hit_interval, r["record_date"], now))
            if key in last_seen:
                gap = seq - last_seen[key]
                hist_max[key] = max(hist_max.get(key, 0), gap)
            sample[key] = sample.get(key, 0) + 1
            last_seen[key] = seq
        # 2) 本期未开出的标签：检查是否首次触发信号（gap >= 历史最高 - offset 且样本 >= 2）
        for key in list(all_keys):
            if key in present or key in pending:
                continue
            if sample.get(key, 0) < 2:
                continue
            ls = last_seen.get(key)
            if ls is None:
                continue
            gap = seq - ls
            hm = hist_max.get(key, 0)
            if gap >= hm - offset:
                pending[key] = {"seq": seq, "date": r["record_date"], "rank": gap, "hist_max": hm}

    # 3) 回放结束仍未开出的信号 → 跟踪中（hit_interval=None）
    for key, sig in pending.items():
        inserts.append((key[0], DIM_NAMES.get(key[0], key[0]), key[1], sig["seq"], sig["date"],
                        sig["rank"], sig["hist_max"], None, None, now))

    db.executemany(
        "INSERT INTO warn_signal_track (dim_key, dim_name, tag_value, signal_seq, signal_date, signal_rank, history_max_rank, hit_interval, hit_date, create_time) VALUES (?,?,?,?,?,?,?,?,?,?)",
        inserts)
    db.commit()
    cnt = db.execute("SELECT COUNT(*) c FROM warn_signal_track").fetchone()["c"]
    db.close()
    return cnt


def _write_gaps_to_history(db, record_id, gaps, warns=None):
    """把每条记录的标签间隔期数(gaps)+预警(warns)写进其最新匹配历史快照"""
    hist = db.execute(
        "SELECT id, full_match_json FROM number_match_history WHERE record_id=? ORDER BY id DESC LIMIT 1",
        (record_id,)).fetchone()
    if not hist:
        return
    try:
        fm = json.loads(hist["full_match_json"])
    except Exception:
        fm = {}
    fm["gaps"] = gaps
    if warns is not None:
        fm["warn_count"] = len(warns)
    db.execute("UPDATE number_match_history SET full_match_json=?, warn_json=? WHERE id=?",
               (json.dumps(fm, ensure_ascii=False),
                json.dumps(warns if warns is not None else [], ensure_ascii=False),
                hist["id"]))

# ============================================================
# 七、API — 登录鉴权
# ============================================================
class LoginBody(BaseModel):
    username: str
    password: str

@app.post("/api/system/login")
def login(body: LoginBody):
    db = get_db()
    row = db.execute("SELECT * FROM sys_user WHERE username=?", (body.username,)).fetchone()
    if row is None or row["password"] != _sha256(body.password):
        db.close()
        raise HTTPException(400, "账号或密码错误")
    if row["status"] != 1:
        db.close()
        raise HTTPException(403, "账号已被禁用")
    role = db.execute("SELECT * FROM sys_role WHERE id=?", (row["role_id"],)).fetchone()
    menus = [dict(m) for m in db.execute(
        "SELECT m.* FROM sys_menu m JOIN sys_role_menu rm ON m.id=rm.menu_id WHERE rm.role_id=? ORDER BY m.sort",
        (row["role_id"],)).fetchall()]
    db.close()
    token = create_token({"user_id": row["id"], "username": row["username"], "role_code": role["role_code"] if role else ""})
    return {
        "token": token,
        "user": {"id": row["id"], "username": row["username"], "real_name": row["real_name"], "role_id": row["role_id"]},
        "role": {"role_code": role["role_code"] if role else "", "role_name": role["role_name"] if role else ""},
        "menus": menus,
    }

@app.post("/api/system/logout")
def logout(user=Header(None, alias="authorization")):
    return {"ok": True}

# ============================================================
# 八、API — 外部数据接收（无需鉴权）
# ============================================================
class ReceiveBody(BaseModel):
    record_date: str
    source_number: str
    rank_value: Optional[int] = None

@app.post("/api/number/receive")
def receive(body: ReceiveBody):
    """接收第三方推送，写入主表（status=待匹配）。同 record_date 覆盖更新。"""
    db = get_db()
    exists = db.execute(
        "SELECT id FROM number_knowledge_record WHERE record_date=?", (body.record_date,)
    ).fetchone()
    if exists:
        # 覆盖：更新开奖号 + 重置为待匹配，清空已匹配的 17 维度标签，等待重新匹配
        db.execute("""UPDATE number_knowledge_record SET
            source_number=?, rank_value=?, status=0,
            zodiac=NULL, odd_even=NULL, big_small=NULL, size_odd_even=NULL, five_element=NULL, wave_color=NULL, he_sum=NULL,
            animal_type=NULL, zodiac_seq=NULL, beauty_type=NULL, yin_yang=NULL, stroke_type=NULL, sky_earth=NULL,
            edge_color=NULL, gender_zodiac=NULL, qqsh_type=NULL, season_type=NULL, zodiac_color_type=NULL,
            head_number=NULL, tail_number=NULL,
            warn_json=NULL, match_time=NULL, cycle_id=NULL
            WHERE id=?""", (body.source_number, body.rank_value, exists["id"]))
        db.commit()
        db.close()
        return {"ok": True, "id": exists["id"], "updated": True, "message": f"{body.record_date} 已覆盖更新"}
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur = db.execute("INSERT INTO number_knowledge_record (record_date, source_number, rank_value, status, create_time) VALUES (?,?,?,?,?)",
                     (body.record_date, body.source_number, body.rank_value, 0, now))
    db.commit()
    rid = cur.lastrowid
    db.close()
    return {"ok": True, "id": rid, "message": "数据已接收，待匹配"}

# ============================================================
# 九、API — 匹配
# ============================================================
@app.post("/api/number/matchByKnowledge")
def match_by_knowledge(body: dict, authorization=Header(None)):
    payload = require_user(authorization)
    record_id = body.get("recordId")
    ok, err = do_match(record_id, operate_user=payload.get("username", ""))
    if not ok:
        raise HTTPException(400, f"匹配失败：{err}")
    # 单条匹配后重建统计表+预警（间隔期数口径），避免预警丢失
    rebuild_rank_max()
    rebuild_signal_track()
    return {"ok": True}

@app.post("/api/number/batchMatch")
def batch_match(body: dict, authorization=Header(None)):
    payload = require_user(authorization)
    ids = body.get("recordIdList", [])
    if not ids:
        # 一键匹配：recordIdList 为空时匹配所有待匹配(status=0)记录
        db = get_db()
        rows = db.execute("SELECT id FROM number_knowledge_record WHERE status=0 ORDER BY id").fetchall()
        db.close()
        ids = [r["id"] for r in rows]
    ok_cnt, fail_cnt, errors = 0, 0, []
    for rid in ids:
        ok, err = do_match(rid, operate_user=payload.get("username", ""))
        if ok:
            ok_cnt += 1
        else:
            fail_cnt += 1
            errors.append({"id": rid, "err": err})
    # 匹配完成后重建统计：计算每个标签的间隔期数(排位)，逐条写回 + 汇总历史最高
    rebuild_rank_max()
    rebuild_signal_track()
    return {"ok": True, "success": ok_cnt, "fail": fail_cnt, "errors": errors}

# ============================================================
# 十、API — 周期配置 CRUD
# ============================================================
@app.get("/api/zodiacCycle/list")
def cycle_list(user=Header(None, alias="authorization")):
    require_user(user)
    db = get_db()
    rows = db.execute("SELECT * FROM zodiac_number_cycle_config ORDER BY start_date DESC").fetchall()
    db.close()
    result = []
    for r in rows:
        d = dict(r)
        try:
            d["zodiac_mapping"] = json.loads(d["zodiac_mapping"])
        except Exception:
            pass
        result.append(d)
    return result

@app.post("/api/zodiacCycle/save")
def cycle_save(body: dict, user=Header(None, alias="authorization")):
    require_user(user)
    db = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    mapping = json.dumps(body.get("zodiac_mapping", {}), ensure_ascii=False)
    cur = db.execute("INSERT INTO zodiac_number_cycle_config (cycle_name, start_date, zodiac_mapping, is_enable, create_time) VALUES (?,?,?,?,?)",
                     (body.get("cycle_name", ""), body.get("start_date", ""), mapping, body.get("is_enable", 1), now))
    db.commit(); rid = cur.lastrowid; db.close()
    return {"ok": True, "id": rid}

@app.put("/api/zodiacCycle/update")
def cycle_update(body: dict, user=Header(None, alias="authorization")):
    require_user(user)
    db = get_db()
    cid = body.get("id")
    if "zodiac_mapping" in body:
        body["zodiac_mapping"] = json.dumps(body["zodiac_mapping"], ensure_ascii=False)
    fields = ["cycle_name", "start_date", "zodiac_mapping", "is_enable"]
    sets = ", ".join(f"{f}=?" for f in fields if f in body)
    vals = [body[f] for f in fields if f in body]
    if sets:
        db.execute(f"UPDATE zodiac_number_cycle_config SET {sets} WHERE id=?", (*vals, cid))
    db.commit(); db.close()
    return {"ok": True}

@app.delete("/api/zodiacCycle/remove")
def cycle_remove(body: dict, user=Header(None, alias="authorization")):
    require_user(user)
    db = get_db()
    db.execute("DELETE FROM zodiac_number_cycle_config WHERE id=?", (body.get("id"),))
    db.commit(); db.close()
    return {"ok": True}

# ============================================================
# 十一、API — 维度统计表
# ============================================================
@app.get("/api/dimTagRankMax/list")
def dim_list(user=Header(None, alias="authorization")):
    require_user(user)
    db = get_db()
    rows = db.execute("SELECT * FROM dim_tag_rank_max ORDER BY dim_key, tag_value").fetchall()
    db.close()
    return [dict(r) for r in rows]

@app.post("/api/dimTagRankMax/rebuild")
def dim_rebuild(user=Header(None, alias="authorization")):
    require_admin(user)
    cnt = rebuild_rank_max()
    return {"ok": True, "count": cnt}

# ============================================================
# 十一·四·五、API — 维度字典（各维度标签→号码映射）
# ============================================================
@app.get("/api/dimMatrix/dict")
def dim_matrix_dict(user=Header(None, alias="authorization")):
    """返回 17 维度各自的标签→号码列表，附当前遗漏/历史最高统计。
    纯只读，不影响任何现有数据。"""
    require_user(user)
    db = get_db()
    # 生效周期生肖映射
    today = datetime.now().strftime("%Y-%m-%d")
    cycle = db.execute(
        "SELECT zodiac_mapping FROM zodiac_number_cycle_config WHERE is_enable=1 AND start_date<=? ORDER BY start_date DESC LIMIT 1",
        (today,)).fetchone()
    zodiac_map = DEFAULT_ZODIAC
    if cycle:
        try:
            zm = json.loads(cycle["zodiac_mapping"])
            if zm:
                zodiac_map = zm
        except Exception:
            pass
    # 1-49 逐号匹配 17 维标签 → 反转成 维度→标签→号码列表
    dim_tags = {}
    for n in range(1, 50):
        labels = match_labels(n, zodiac_map)
        for dk, tv in labels.items():
            if not tv:
                continue
            dim_tags.setdefault(dk, {}).setdefault(tv, []).append(n)
    # 关联统计表
    rank_map = {}
    for r in db.execute("SELECT * FROM dim_tag_rank_max").fetchall():
        rank_map[(r["dim_key"], r["tag_value"])] = dict(r)
    db.close()
    # 组装
    dims = []
    for dk, dim_name in DIM_NAMES.items():
        tags = []
        for tv in sorted(dim_tags.get(dk, {}).keys()):
            nums = dim_tags[dk][tv]
            rr = rank_map.get((dk, tv), {})
            tags.append({
                "tag": tv,
                "numbers": nums,
                "count": len(nums),
                "current_rank": rr.get("current_rank", 0),
                "history_max_rank": rr.get("history_max_rank", 0),
                "total_sample": rr.get("total_sample", 0),
            })
        dims.append({
            "dim_key": dk,
            "dim_name": dim_name,
            "tag_count": len(tags),
            "tags": tags,
        })
    return {"dims": dims}

# ============================================================
# 十一·五、API — 信号跟踪（预警触发 → 后续开出）
# ============================================================
@app.get("/api/signalTrack/list")
def signal_track_list(user=Header(None, alias="authorization")):
    require_user(user)
    db = get_db()
    rows = db.execute(
        "SELECT * FROM warn_signal_track ORDER BY signal_seq DESC, dim_key, tag_value").fetchall()
    db.close()
    items = [dict(r) for r in rows]
    # 按维度聚合命中率（5/10/15期内）
    dim_agg = {}
    for it in items:
        dk = it["dim_key"]
        if dk not in dim_agg:
            dim_agg[dk] = {"dim_key": dk, "dim_name": it["dim_name"], "total": 0, "hit5": 0, "hit10": 0, "hit15": 0, "tracking": 0}
        dim_agg[dk]["total"] += 1
        if it["hit_interval"] is None:
            dim_agg[dk]["tracking"] += 1
        else:
            hi = it["hit_interval"]
            if hi <= 5:
                dim_agg[dk]["hit5"] += 1
            if hi <= 10:
                dim_agg[dk]["hit10"] += 1
            if hi <= 15:
                dim_agg[dk]["hit15"] += 1
    summary = []
    for dk, v in dim_agg.items():
        settled = v["total"] - v["tracking"]
        for w in (5, 10, 15):
            v[f"rate{w}"] = round(v[f"hit{w}"] / settled * 100, 1) if settled > 0 else None
        v["hit_rate"] = v["rate5"]  # 兼容旧字段
        v["group"] = "core" if dk in CORE_DIMS else "other"
        summary.append(v)
    # 核心维度组按用户指定顺序，其余按命中率降序
    core_order = {dk: i for i, dk in enumerate(CORE_DIMS)}
    summary.sort(key=lambda x: (0 if x["group"] == "core" else 1,
                                core_order.get(x["dim_key"], 99) if x["group"] == "core" else -(x["hit_rate"] if x["hit_rate"] is not None else -1)))
    # 汇总：1/2/3/4/5 期命中数
    hit_bucket = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    settled_total = 0
    for it in items:
        if it["hit_interval"] is not None:
            settled_total += 1
            for w in (1, 2, 3, 4, 5):
                if it["hit_interval"] <= w:
                    hit_bucket[w] += 1
    return {
        "items": items,
        "summary": summary,
        "total_signals": len(items),
        "settled": settled_total,
        "tracking": sum(1 for it in items if it["hit_interval"] is None),
        "hit_bucket": hit_bucket,
    }

@app.post("/api/signalTrack/rebuild")
def signal_track_rebuild(user=Header(None, alias="authorization")):
    require_admin(user)
    cnt = rebuild_signal_track()
    return {"ok": True, "count": cnt}

# ============================================================
# 十二、API — 系统配置
# ============================================================
@app.get("/api/sysConfig/get")
def config_get(user=Header(None, alias="authorization")):
    require_user(user)
    db = get_db()
    row = db.execute("SELECT * FROM sys_config WHERE config_key='warn_rank_offset'").fetchone()
    db.close()
    return dict(row) if row else {"config_key": "warn_rank_offset", "config_value": "2"}

@app.put("/api/sysConfig/update")
def config_update(body: dict, user=Header(None, alias="authorization")):
    require_admin(user)
    db = get_db()
    db.execute("UPDATE sys_config SET config_value=? WHERE config_key='warn_rank_offset'", (str(body.get("config_value", "2")),))
    db.commit(); db.close()
    return {"ok": True}

# ============================================================
# 十三、API — 业务数据查询
# ============================================================
@app.get("/api/numberRecord/page")
def record_page(page: int = 1, page_size: int = 20, record_date: str = "", source_number: str = "",
                warn_dim_key: str = "", warn_status: str = "", user=Header(None, alias="authorization")):
    require_user(user)
    db = get_db()
    where, params = [], []
    if record_date:
        where.append("record_date=?"); params.append(record_date)
    if source_number:
        where.append("source_number LIKE ?"); params.append(f"%{source_number}%")
    if warn_status == "warn":
        where.append("warn_json IS NOT NULL AND warn_json != '[]'")
    elif warn_status == "normal":
        where.append("(warn_json IS NULL OR warn_json = '[]')")
    if warn_dim_key:
        where.append("warn_json LIKE ?"); params.append(f'%"{warn_dim_key}"%')
    sql = "SELECT * FROM number_knowledge_record"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC"
    rows = db.execute(sql, params).fetchall()
    total = len(rows)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))
    start = (page - 1) * page_size
    items = rows[start:start + page_size]
    db.close()
    result = []
    for r in items:
        d = dict(r)
        try:
            d["warn_json"] = json.loads(d["warn_json"]) if d["warn_json"] else []
        except Exception:
            d["warn_json"] = []
        result.append(d)
    return {"items": result, "total": total, "page": page, "page_size": page_size, "total_pages": total_pages}

@app.get("/api/matchHistory/page")
def history_page(page: int = 1, page_size: int = 20, record_id: int = None, user=Header(None, alias="authorization")):
    require_user(user)
    db = get_db()
    where, params = [], []
    if record_id:
        where.append("record_id=?"); params.append(record_id)
    sql = "SELECT * FROM number_match_history"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC"
    rows = db.execute(sql, params).fetchall()
    total = len(rows)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))
    start = (page - 1) * page_size
    items = rows[start:start + page_size]
    db.close()
    result = []
    for r in items:
        d = dict(r)
        for k in ("full_match_json", "warn_json"):
            try:
                d[k] = json.loads(d[k]) if d[k] else ({} if k == "full_match_json" else [])
            except Exception:
                d[k] = {} if k == "full_match_json" else []
        result.append(d)
    return {"items": result, "total": total, "page": page, "page_size": page_size, "total_pages": total_pages}

# ============================================================
# 十四、API — 仪表盘统计
# ============================================================
@app.get("/api/dashboard/warnStat")
def dashboard(user=Header(None, alias="authorization")):
    require_user(user)
    db = get_db()
    total_warn_records = db.execute("SELECT COUNT(*) c FROM number_knowledge_record WHERE warn_json IS NOT NULL AND warn_json != '[]'").fetchone()["c"]
    dim_dist = {}
    rows = db.execute("SELECT warn_json FROM number_knowledge_record WHERE warn_json IS NOT NULL AND warn_json != '[]'").fetchall()
    for r in rows:
        try:
            warns = json.loads(r["warn_json"])
            for w in warns:
                k = w.get("dim_key", "?")
                dim_dist[k] = dim_dist.get(k, 0) + 1
        except Exception:
            pass
    warn_list = db.execute("SELECT id, record_date, source_number, rank_value, warn_json, match_time FROM number_knowledge_record WHERE warn_json IS NOT NULL AND warn_json != '[]' ORDER BY id DESC LIMIT 50").fetchall()
    active_cycle = db.execute("SELECT * FROM zodiac_number_cycle_config WHERE is_enable=1 ORDER BY start_date DESC LIMIT 1").fetchone()
    stat_cnt = db.execute("SELECT COUNT(*) c FROM number_knowledge_record").fetchone()["c"]
    matched_cnt = db.execute("SELECT COUNT(*) c FROM number_knowledge_record WHERE status=1").fetchone()["c"]
    # 维度遗漏概览：每个维度当前遗漏最久的标签（按 current_rank 取组内最大）
    dim_rows = db.execute(
        "SELECT dim_key, dim_name, tag_value, current_rank, history_max_rank, total_sample "
        "FROM dim_tag_rank_max WHERE current_rank > 0 ORDER BY dim_key, current_rank DESC").fetchall()
    rank_overview = {}
    for r in dim_rows:
        dk = r["dim_key"]
        if dk not in rank_overview:  # 已按 current_rank DESC 排序，首个即该维度遗漏最久
            rank_overview[dk] = dict(r)
    dim_rank_overview = sorted(rank_overview.values(), key=lambda x: -x["current_rank"])
    warn_offset = get_warn_offset(db)
    db.close()
    warn_list_out = []
    for r in warn_list:
        d = dict(r)
        try:
            d["warn_json"] = json.loads(d["warn_json"]) if d["warn_json"] else []
        except Exception:
            d["warn_json"] = []
        warn_list_out.append(d)
    dim_dist_out = [{"dim_key": k, "dim_name": DIM_NAMES.get(k, k), "count": v} for k, v in sorted(dim_dist.items(), key=lambda x: -x[1])]
    return {
        "total_warn_records": total_warn_records,
        "dim_distribution": dim_dist_out,
        "warn_list": warn_list_out,
        "active_cycle": dict(active_cycle) if active_cycle else None,
        "total_records": stat_cnt,
        "matched_records": matched_cnt,
        "dim_rank_overview": dim_rank_overview,
        "warn_rank_offset": warn_offset,
    }

# ============================================================
# 十五、API — 前台公开（访问密码鉴权）
# ============================================================
@app.post("/api/front/verify")
def front_verify(body: dict):
    """前台访问密码验证，通过返回临时访问令牌"""
    pwd = str(body.get("password", ""))
    if pwd != get_front_pwd():
        raise HTTPException(401, "密码错误")
    token = create_token({"front": True})
    return {"ok": True, "token": token}

@app.get("/api/front/numberData/list")
def front_list(record_date: str = "", page: int = 1, page_size: int = 50, token: str = ""):
    if not front_token_valid(token):
        raise HTTPException(401, "需要访问密码")
    db = get_db()
    where, params = [], []
    if record_date:
        where.append("record_date=?"); params.append(record_date)
    sql = "SELECT * FROM number_knowledge_record WHERE status=1"
    if where:
        sql += " AND " + " AND ".join(where)
    sql += " ORDER BY id DESC"
    rows = db.execute(sql, params).fetchall()
    total = len(rows)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))
    start = (page - 1) * page_size
    items = rows[start:start + page_size]
    dates = [r[0] for r in db.execute("SELECT DISTINCT record_date FROM number_knowledge_record WHERE status=1 ORDER BY record_date DESC").fetchall()]
    db.close()
    result = []
    for r in items:
        d = dict(r)
        try:
            d["warn_json"] = json.loads(d["warn_json"]) if d["warn_json"] else []
        except Exception:
            d["warn_json"] = []
        result.append(d)
    return {"items": result, "total": total, "page": page, "page_size": page_size, "total_pages": total_pages, "dates": dates}

@app.get("/api/front/dimRank/list")
def front_dim_rank(limit: int = 30, token: str = ""):
    """前台：当前遗漏榜（各标签当前连续遗漏期数，降序）"""
    if not front_token_valid(token):
        raise HTTPException(401, "需要访问密码")
    db = get_db()
    rows = db.execute(
        "SELECT dim_key, dim_name, tag_value, current_rank, history_max_rank, total_sample "
        "FROM dim_tag_rank_max WHERE current_rank > 0 ORDER BY current_rank DESC, history_max_rank DESC LIMIT ?",
        (limit,)).fetchall()
    db.close()
    return [dict(r) for r in rows]

# ============================================================
# 十六、API — 用户/角色/菜单管理（管理员）
# ============================================================
@app.get("/api/system/userList")
def user_list(user=Header(None, alias="authorization")):
    require_admin(user)
    db = get_db()
    rows = db.execute("SELECT u.*, r.role_name FROM sys_user u LEFT JOIN sys_role r ON u.role_id=r.id ORDER BY u.id").fetchall()
    db.close()
    return [dict(r) for r in rows]

@app.post("/api/system/userSave")
def user_save(body: dict, user=Header(None, alias="authorization")):
    require_admin(user)
    db = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    pwd = body.get("password", "")
    password = _sha256(pwd) if pwd else None
    if body.get("id"):
        if password:
            db.execute("UPDATE sys_user SET real_name=?, role_id=?, status=?, password=?, update_time=? WHERE id=?",
                       (body.get("real_name", ""), body.get("role_id"), body.get("status", 1), password, now, body["id"]))
        else:
            db.execute("UPDATE sys_user SET real_name=?, role_id=?, status=?, update_time=? WHERE id=?",
                       (body.get("real_name", ""), body.get("role_id"), body.get("status", 1), now, body["id"]))
    else:
        db.execute("INSERT INTO sys_user (username, password, real_name, role_id, status, create_time, update_time) VALUES (?,?,?,?,?,?,?)",
                   (body.get("username"), password or _sha256("123456"), body.get("real_name", ""), body.get("role_id"), body.get("status", 1), now, now))
    db.commit(); db.close()
    return {"ok": True}

@app.get("/api/system/roleList")
def role_list(user=Header(None, alias="authorization")):
    require_admin(user)
    db = get_db()
    rows = db.execute("SELECT * FROM sys_role ORDER BY id").fetchall()
    db.close()
    return [dict(r) for r in rows]

@app.get("/api/system/menuList")
def menu_list(user=Header(None, alias="authorization")):
    require_admin(user)
    db = get_db()
    rows = db.execute("SELECT * FROM sys_menu ORDER BY sort").fetchall()
    db.close()
    return [dict(r) for r in rows]

@app.get("/api/system/roleMenus")
def role_menus(role_id: int, user=Header(None, alias="authorization")):
    require_admin(user)
    db = get_db()
    rows = db.execute("SELECT menu_id FROM sys_role_menu WHERE role_id=?", (role_id,)).fetchall()
    db.close()
    return [r["menu_id"] for r in rows]

@app.post("/api/system/roleMenuSave")
def role_menu_save(body: dict, user=Header(None, alias="authorization")):
    require_admin(user)
    db = get_db()
    role_id = body.get("role_id")
    menu_ids = body.get("menu_ids", [])
    db.execute("DELETE FROM sys_role_menu WHERE role_id=?", (role_id,))
    for mid in menu_ids:
        db.execute("INSERT OR IGNORE INTO sys_role_menu (role_id, menu_id) VALUES (?,?)", (role_id, mid))
    db.commit(); db.close()
    return {"ok": True}

# ============================================================
# 十七、静态文件 + SPA
# ============================================================
@app.get("/")
def root():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8025)
