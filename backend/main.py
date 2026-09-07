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

# 各维度标签数（用于策略演算方案分组）
DIM_TAGS = {
    "zodiac": 12, "odd_even": 2, "big_small": 2, "size_odd_even": 4,
    "five_element": 5, "wave_color": 3, "he_sum": 2,
    "animal_type": 2, "zodiac_seq": 2, "beauty_type": 2, "yin_yang": 2,
    "stroke_type": 2, "sky_earth": 2, "edge_color": 2, "gender_zodiac": 2,
    "qqsh_type": 4, "season_type": 4, "zodiac_color_type": 3,
    "head_number": 5, "tail_number": 10,
}
ALL_DIMS = list(DIM_NAMES.keys())

# 策略演算方案的维度集合（下单卡片对应的方案）
STRATEGY_SCHEMES = {
    "全维度19": ALL_DIMS,
    "排除尾数18": [d for d in ALL_DIMS if d != "tail_number"],
    "排除低命中18": [d for d in ALL_DIMS if d not in ("zodiac", "tail_number")],
    "多标签维度": [d for d, t in DIM_TAGS.items() if t >= 3],
    "核心6维": list(CORE_DIMS),
}

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
CREATE TABLE IF NOT EXISTS algo_forward_track (
  id INTEGER PRIMARY KEY AUTOINCREMENT, algo_key TEXT, bet_date TEXT,
  picks_json TEXT, N INTEGER DEFAULT 0,
  open_number INTEGER, hit INTEGER, per REAL, profit REAL, cash REAL,
  create_time TEXT,
  UNIQUE(algo_key, bet_date)
);
CREATE TABLE IF NOT EXISTS strategy_order (
  id INTEGER PRIMARY KEY AUTOINCREMENT, scheme TEXT, offset INTEGER DEFAULT 0,
  dims_json TEXT, bet_date TEXT, picks_json TEXT, N INTEGER DEFAULT 0,
  per REAL DEFAULT 1, amount REAL DEFAULT 0, signals_json TEXT,
  open_number INTEGER, hit INTEGER, profit REAL,
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

# 4维稳定正信号（单期买回测验证：前后半增量均>+3%，全量增量+5~+10%，非过拟合）
# season_type=春夏秋冬 / size_odd_even=大小单双 / wave_color=号码波色 / edge_color=白边黑中
POS_DIMS = ["season_type", "size_odd_even", "wave_color", "edge_color"]

# 演算跟踪算法清单（「后续演算跟踪」的跟踪对象，参数与 order-track 一致）
TRACK_ALGOS = [
    {"key": "close_eq1_off0", "name": "接近样本·票数=1(创新高)", "mode": "eq1", "signal_source": "close_sample", "offset": 0, "signal_top_n": 10, "sort_by": "gap"},
    {"key": "close_ge2_off1", "name": "接近样本·票数≥2(off1)", "mode": "ge2", "signal_source": "close_sample", "offset": 1, "signal_top_n": 5, "sort_by": "excess"},
    {"key": "close_ge2_off2", "name": "接近样本·票数≥2(off2)", "mode": "ge2", "signal_source": "close_sample", "offset": 2, "signal_top_n": 5, "sort_by": "gap"},
    {"key": "close_eq2_off2", "name": "接近样本·票数=2(off2)", "mode": "eq2", "signal_source": "close_sample", "offset": 2, "signal_top_n": 10, "sort_by": "gap"},
    {"key": "dim_eq2_top5", "name": "建议号码·票数=2(前5)", "mode": "eq2", "signal_source": "dim_max", "signal_top_n": 5, "sort_by": "gap"},
    {"key": "dim_ge2_top5", "name": "建议号码·票数≥2(前5)", "mode": "ge2", "signal_source": "dim_max", "signal_top_n": 5, "sort_by": "gap"},
    {"key": "posdim_single_off2", "name": "4维正信号·单期买(off2)", "generator": "posdim_single", "offset": 2},
]

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
    db.execute("INSERT OR IGNORE INTO sys_config (config_key, config_value, remark) VALUES (?,?,?)",
               ("strategy_hist_window", "60", "历史最高遗漏滚动窗口(期)，0=全量历史，默认60≈2个月"))
    db.execute("INSERT OR IGNORE INTO sys_config (config_key, config_value, remark) VALUES (?,?,?)",
               ("engine_capital", "3000", "投入引擎本金(元)"))
    db.execute("INSERT OR IGNORE INTO sys_config (config_key, config_value, remark) VALUES (?,?,?)",
               ("engine_position_pct", "20", "投入引擎单期仓位比例(%)，进取=20"))
    db.execute("INSERT OR IGNORE INTO sys_config (config_key, config_value, remark) VALUES (?,?,?)",
               ("engine_safety_pct", "30", "投入引擎安全垫比例(%)，永不投入"))
    db.execute("INSERT OR IGNORE INTO sys_config (config_key, config_value, remark) VALUES (?,?,?)",
               ("engine_min_per", "10", "投入引擎最少单号金额(元)，低于则不再扩信号"))
    db.execute("INSERT OR IGNORE INTO sys_config (config_key, config_value, remark) VALUES (?,?,?)",
               ("engine_hit_floor", "70", "投入引擎命中率红线(%)，低于此维度的信号不投"))

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

def get_strategy_window(db=None):
    """历史最高遗漏滚动窗口（期）。sys_config: strategy_hist_window，0/空=全量历史，默认 60≈2个月。"""
    own = db is None
    if own:
        db = get_db()
    row = db.execute("SELECT config_value FROM sys_config WHERE config_key='strategy_hist_window'").fetchone()
    if own:
        db.close()
    try:
        return int(row["config_value"]) if row else 60
    except Exception:
        return 60


def _get_config_int(key, default):
    """通用整数配置读取（sys_config）。"""
    db = get_db()
    row = db.execute("SELECT config_value FROM sys_config WHERE config_key=?", (key,)).fetchone()
    db.close()
    try:
        return int(row["config_value"]) if row else default
    except Exception:
        return default


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
    # 匹配完成后，自动结算+生成「演算跟踪」的下一期选号（try 静默，不阻塞匹配主流程）
    _algo_track_settle_and_generate()
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
# 十一·四·六、API — 建议号码（多维度遗漏信号投票）
# ============================================================
@app.get("/api/suggestNumber/votes")
def suggest_number_votes(date: str = "", user=Header(None, alias="authorization")):
    """建议号码：每维度取「当前遗漏最久」的 1 个标签作为信号（共 N 维），
    统计每个号码命中几个信号标签（投票数），返回号码票数 + 命中明细。
    支持 date 参数（YYYY-MM-DD）查询历史某日的投票结果；默认今天。
    纯只读，不影响任何现有数据。"""
    require_user(user)
    db = get_db()
    # 生效周期生肖映射
    today = date or datetime.now().strftime("%Y-%m-%d")
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
    # 历史日期：用该日之前（不含当天）的记录重算投票（不依赖统计表）
    if date:
        votes, signals = _compute_votes_until(db, date, zodiac_map)
        db.close()
        max_vote = max((v["vote"] for v in votes), default=0)
        return {"votes": votes, "max_vote": max_vote, "signals": signals, "date": date}
    # 每维度取遗漏最久的标签（信号）
    rows = db.execute(
        "SELECT dim_key, dim_name, tag_value, current_rank, history_max_rank "
        "FROM dim_tag_rank_max WHERE current_rank > 0 ORDER BY current_rank DESC").fetchall()
    best = {}
    for r in rows:
        if r["dim_key"] not in best:
            best[r["dim_key"]] = dict(r)
    signals = list(best.values())
    # 仅取遗漏最久的前 10 条信号参与投票（2026-09 用户要求：投票依据 20→10 条）
    signals = sorted(signals, key=lambda s: -s["current_rank"])[:10]
    signal_set = set((s["dim_key"], s["tag_value"]) for s in signals)
    db.close()
    # 1-49 逐号统计命中信号数
    votes = []
    for n in range(1, 50):
        labels = match_labels(n, zodiac_map)
        hit_dims = []
        for dk, tv in labels.items():
            if tv and (dk, tv) in signal_set:
                hit_dims.append({"dim_key": dk, "dim_name": DIM_NAMES.get(dk, dk), "tag_value": tv})
        votes.append({"number": n, "vote": len(hit_dims), "hit_dims": hit_dims})
    max_vote = max((v["vote"] for v in votes), default=0)
    # 信号标签列表（供前端展示投票依据）
    signals_out = sorted(signals, key=lambda s: -s["current_rank"])
    return {"votes": votes, "max_vote": max_vote, "signals": signals_out}


def _compute_votes_until(db, end_date, zodiac_map):
    """截至 end_date 之前（不含当天）时点重算建议号码投票：逐期回放算每标签遗漏，取每维度遗漏最久标签作信号。
    返回 (votes, signals)：votes=[{number, vote, hit_dims}], signals=[{dim_key, dim_name, tag_value, current_rank}]"""
    rows = db.execute(
        "SELECT * FROM number_knowledge_record WHERE status=1 AND record_date < ? ORDER BY record_date, id",
        (end_date,)).fetchall()
    last_seen = {}
    for idx, r in enumerate(rows):
        labels = match_labels(r["source_number"], zodiac_map)
        for dim, tag in labels.items():
            if tag:
                last_seen[(dim, tag)] = idx + 1
    total_seq = len(rows)
    # 补未来天数差：查询日期晚于最后数据日时，遗漏按自然日累加
    extra = 0
    last_day_row = db.execute(
        "SELECT MAX(record_date) m FROM number_knowledge_record WHERE status=1").fetchone()
    last_data_day = last_day_row["m"] if last_day_row else None
    if last_data_day and end_date > last_data_day:
        extra = (datetime.strptime(end_date, "%Y-%m-%d").date()
                 - datetime.strptime(last_data_day, "%Y-%m-%d").date()).days
    best = {}
    for (dim, tag), ls in last_seen.items():
        gap = total_seq - ls + extra
        if dim not in best or gap > best[dim][1]:
            best[dim] = (tag, gap)
    signals = [{"dim_key": dim, "dim_name": DIM_NAMES.get(dim, dim),
                "tag_value": tag, "current_rank": gap}
               for dim, (tag, gap) in best.items() if gap > 0]
    signals = sorted(signals, key=lambda s: -s["current_rank"])[:10]
    signal_set = set((s["dim_key"], s["tag_value"]) for s in signals)
    votes = []
    for n in range(1, 50):
        labels = match_labels(n, zodiac_map)
        hit_dims = []
        for dk, tv in labels.items():
            if tv and (dk, tv) in signal_set:
                hit_dims.append({"dim_key": dk, "dim_name": DIM_NAMES.get(dk, dk), "tag_value": tv})
        votes.append({"number": n, "vote": len(hit_dims), "hit_dims": hit_dims})
    return votes, signals


# ============================================================
# 十一·四·七、API — 建议号码回测（按月统计票数 0-5 命中率 + 最长不出期数）
# ============================================================
@app.get("/api/suggestNumber/backtest")
def suggest_number_backtest(start_date: str = "2026-01-01", user=Header(None, alias="authorization")):
    """回测：从 start_date 起逐期回放，每期用「之前」的数据投票，看下期开出号码的票数，
    按月聚合票数 0-5 各档位的命中率（下期开出率）+ 最长不出期数（最大遗漏）。纯只读。"""
    require_user(user)
    db = get_db()
    cycle = db.execute(
        "SELECT zodiac_mapping FROM zodiac_number_cycle_config WHERE is_enable=1 ORDER BY start_date DESC LIMIT 1").fetchone()
    zodiac_map = DEFAULT_ZODIAC
    if cycle:
        try:
            zm = json.loads(cycle["zodiac_mapping"])
            if zm:
                zodiac_map = zm
        except Exception:
            pass
    rows = db.execute(
        "SELECT * FROM number_knowledge_record WHERE status=1 ORDER BY record_date, id").fetchall()
    db.close()

    start_idx = None
    for idx, r in enumerate(rows):
        if r["record_date"] >= start_date:
            start_idx = idx
            break
    if start_idx is None:
        return {"start_date": start_date, "months": []}

    # 用 start_idx 之前的数据初始化 last_seen / 号码上次开出序号
    last_seen = {}
    num_last_open = {}
    for idx in range(start_idx):
        r = rows[idx]
        labels = match_labels(r["source_number"], zodiac_map)
        for dim, tag in labels.items():
            if tag:
                last_seen[(dim, tag)] = idx + 1
        num_last_open[int(r["source_number"])] = idx + 1

    monthly = {}

    for idx in range(start_idx, len(rows)):
        r = rows[idx]
        seq = idx + 1
        month = r["record_date"][:7]
        open_num = int(r["source_number"])

        # 每维度取遗漏最久标签 → 按遗漏降序取前 10 条信号
        best = {}
        for (dim, tag), ls in last_seen.items():
            gap = seq - ls
            if dim not in best or gap > best[dim][1]:
                best[dim] = (tag, gap)
        ranked = sorted([(dim, tag, gap) for dim, (tag, gap) in best.items() if gap > 0],
                        key=lambda x: -x[2])
        top_signals = [(dim, tag) for dim, tag, gap in ranked[:10]]
        signal_set = set(top_signals)

        # 1-49 号码票数
        vote_by_num = {}
        for n in range(1, 50):
            labels = match_labels(n, zodiac_map)
            cnt = sum(1 for dk, tv in labels.items() if tv and (dk, tv) in signal_set)
            vote_by_num[n] = cnt

        open_vote = vote_by_num.get(open_num, 0)
        m = monthly.setdefault(month, {})
        # 累积阈值口径：每一档位 N 表示「票数 >= N」的号码
        # 1) 每个号码按票数 v，计入 >=0 .. >=v 所有档位（累计号码数 + 最大遗漏）
        for n in range(1, 50):
            v = min(vote_by_num[n], 5)
            miss = seq - num_last_open.get(n, start_idx)
            for N in range(0, v + 1):
                b = m.setdefault(N, {"sample": 0, "hit": 0, "max_miss": 0, "periods": 0})
                b["sample"] += 1
                if miss > b["max_miss"]:
                    b["max_miss"] = miss
        # 2) 每期计一次期数；本期开出号码票数 >= N 则命中该档位
        for N in range(0, 6):
            b = m.setdefault(N, {"sample": 0, "hit": 0, "max_miss": 0, "periods": 0})
            b["periods"] += 1
            if open_vote >= N:
                b["hit"] += 1

        # 更新 last_seen / num_last_open（本期开出）
        labels = match_labels(open_num, zodiac_map)
        for dim, tag in labels.items():
            if tag:
                last_seen[(dim, tag)] = seq
        num_last_open[open_num] = seq

    months_out = []
    for month in sorted(monthly.keys()):
        m = monthly[month]
        buckets = []
        for x in range(6):
            b = m.get(x, {"sample": 0, "hit": 0, "max_miss": 0, "periods": 0})
            periods = b.get("periods", 0)
            rate = round(b["hit"] / periods * 100, 1) if periods > 0 else 0
            buckets.append({"vote": x, "sample": b["sample"], "hit": b["hit"],
                            "hit_rate": rate, "max_miss": b["max_miss"]})
        months_out.append({"month": month, "buckets": buckets})

    return {"start_date": start_date, "end_date": rows[-1]["record_date"] if rows else "", "months": months_out}


@app.get("/api/suggestNumber/order-track")
def suggest_number_order_track(start_date: str = "2026-05-01", odds: int = 47,
                               bet_ratio: float = 0.5, bankrupt_threshold: float = 100,
                               mode: str = "ge4", signal_top_n: int = 10,
                               signal_source: str = "dim_max", offset: int = 0,
                               sort_by: str = "gap",
                               bet_scheme: str = "ratio", base_bet: float = 10,
                               user=Header(None, alias="authorization")):
    """实战下单跟踪：从 start_date 起逐期下单。mode 买法(ge/lt/eq)、signal_source 信号源。
    bet_scheme=ratio(资金比例下注，默认)/martingale(倍投叠加：不中翻倍、命中重置)/dalembert(达朗贝尔：不中加一注、命中减一注)。base_bet=基础注码。
    纯只读。"""
    require_user(user)
    db = get_db()
    cycle = db.execute(
        "SELECT zodiac_mapping FROM zodiac_number_cycle_config WHERE is_enable=1 ORDER BY start_date DESC LIMIT 1").fetchone()
    zodiac_map = DEFAULT_ZODIAC
    if cycle:
        try:
            zm = json.loads(cycle["zodiac_mapping"])
            if zm:
                zodiac_map = zm
        except Exception:
            pass
    rows = db.execute(
        "SELECT * FROM number_knowledge_record WHERE status=1 ORDER BY record_date, id").fetchall()
    db.close()

    START = 3000
    cash = float(START)
    baseline = float(START)
    bankrupt = 0
    inject = 0.0
    withdraws = []
    daily = []
    level = 1          # 倍投叠加法的当前注码倍数（base_bet × level），命中重置为 1
    max_level = 1      # 倍投达到的最高倍数

    if mode.startswith('ge'):
        _x = int(mode[2:])
        pick_cond = lambda v: v >= _x
    elif mode.startswith('lt'):
        _x = int(mode[2:])
        pick_cond = lambda v: v < _x
    elif mode.startswith('eq'):
        _x = int(mode[2:])
        pick_cond = lambda v: v == _x
    else:
        pick_cond = lambda v: v >= 4

    is_close = (signal_source == 'close_sample')
    hist_max = {}
    sample = {}

    def calc_signals(seq):
        """按信号源取前 signal_top_n 条信号标签"""
        if is_close:
            signals = []
            for (dim, tag), ls in last_seen.items():
                gap = seq - ls
                hm = hist_max.get((dim, tag), 0)
                if sample.get((dim, tag), 0) >= 2 and gap >= hm - offset:
                    signals.append((dim, tag, gap, hm))
            if sort_by == 'excess':
                signals.sort(key=lambda x: -(x[2] - x[3]))
            else:
                signals.sort(key=lambda x: -x[2])
            return [(dim, tag) for dim, tag, _, _ in signals[:signal_top_n]]
        best = {}
        for (dim, tag), ls in last_seen.items():
            gap = seq - ls
            if dim not in best or gap > best[dim][1]:
                best[dim] = (tag, gap)
        ranked = sorted([(dim, tag, gap) for dim, (tag, gap) in best.items() if gap > 0],
                        key=lambda x: -x[2])
        return [(dim, tag) for dim, tag, gap in ranked[:signal_top_n]]

    start_idx = None
    for idx, r in enumerate(rows):
        if r["record_date"] >= start_date:
            start_idx = idx
            break
    if start_idx is None:
        return {"start_date": start_date, "odds": odds, "bet_ratio": bet_ratio,
                "bankrupt_threshold": bankrupt_threshold, "summary": {}, "daily": [], "next_order": None}

    last_seen = {}
    for idx in range(start_idx):
        r = rows[idx]
        labels = match_labels(r["source_number"], zodiac_map)
        for dim, tag in labels.items():
            if tag:
                k = (dim, tag)
                if is_close and k in last_seen:
                    gap = (idx + 1) - last_seen[k]
                    hist_max[k] = max(hist_max.get(k, 0), gap)
                    sample[k] = sample.get(k, 0) + 1
                elif is_close:
                    sample[k] = 1
                last_seen[k] = idx + 1

    for idx in range(start_idx, len(rows)):
        r = rows[idx]
        seq = idx + 1
        d = r["record_date"]
        open_num = int(r["source_number"])

        top_signals = calc_signals(seq)
        signal_set = set(top_signals)
        vote_by_num = {}
        for n in range(1, 50):
            labels = match_labels(n, zodiac_map)
            cnt = sum(1 for dk, tv in labels.items() if tv and (dk, tv) in signal_set)
            vote_by_num[n] = cnt
        picks = sorted([n for n, v in vote_by_num.items() if pick_cond(v)])
        N = len(picks)

        bet = cash * bet_ratio
        event = ""
        if N == 0:
            hit = False
            per = 0
            actual = 0
            profit = 0.0
        elif bet_scheme in ('martingale', 'dalembert'):
            per = int(base_bet * level)
            actual = per * N
            if actual > cash:
                # 资金不足以覆盖当前注码 → 破产注资重置，本期不下单
                inject_amt = max(0, START - cash)
                inject += inject_amt
                bankrupt += 1
                cash = float(START)
                baseline = float(START)
                level = 1
                event = f"破产#{bankrupt}" + (f"注资{inject_amt:.0f}" if inject_amt > 0 else "(追不起)")
                per = 0; actual = 0; hit = False; profit = 0.0
            else:
                hit = open_num in picks
                profit = (odds * per - actual) if hit else (-actual)
                cash += profit
                if hit:
                    event = f"命中注码{per}"
                    # 马丁格尔：命中重置回1；达朗贝尔：赢减一注（不低于1）
                    level = 1 if bet_scheme == 'martingale' else max(1, level - 1)
                else:
                    # 马丁格尔：不中翻倍；达朗贝尔：不中加一注
                    if bet_scheme == 'martingale':
                        level *= 2
                        event = f"未中翻倍→{int(base_bet * level)}"
                    else:
                        level += 1
                        event = f"未中加注→{int(base_bet * level)}"
                    max_level = max(max_level, level)
        else:
            per = int(bet / N)  # 单注向下取整
            actual = per * N    # 实际总下注
            hit = open_num in picks
            profit = (odds * per - actual) if hit else (-actual)
            cash += profit

        if cash < bankrupt_threshold:
            inject_amt = START - cash
            inject += inject_amt
            bankrupt += 1
            cash = float(START)
            baseline = float(START)
            if bet_scheme in ('martingale', 'dalembert'):
                level = 1
            event = f"破产#{bankrupt}注资{inject_amt:.0f}"
        elif bet_scheme == 'ratio' and cash >= baseline * 2:
            wd = round(cash * 0.25, 2)
            cash = round(cash * 0.75, 2)
            baseline = cash
            withdraws.append({"date": d, "withdraw": wd, "cash_after": cash})
            event = f"提取{wd:.0f}"

        daily.append({
            "date": d, "picks": picks, "N": N, "open": open_num, "hit": hit,
            "bet": actual if N else 0, "per": per, "profit": round(profit, 2),
            "cash": round(cash, 2), "event": event,
        })

        labels = match_labels(open_num, zodiac_map)
        for dim, tag in labels.items():
            if tag:
                k = (dim, tag)
                if is_close and k in last_seen:
                    gap = seq - last_seen[k]
                    hist_max[k] = max(hist_max.get(k, 0), gap)
                    sample[k] = sample.get(k, 0) + 1
                elif is_close:
                    sample[k] = 1
                last_seen[k] = seq

    total_seq = len(rows)
    top_signals = calc_signals(total_seq)
    signal_set = set(top_signals)
    next_picks = []
    for n in range(1, 50):
        labels = match_labels(n, zodiac_map)
        cnt = sum(1 for dk, tv in labels.items() if tv and (dk, tv) in signal_set)
        if pick_cond(cnt):
            next_picks.append(n)
    next_N = len(next_picks)
    next_bet = cash * bet_ratio
    next_per = int(next_bet / next_N) if next_N else 0

    # 每月分别的盈利情况（按 YYYY-MM 聚合每日盈亏）
    monthly = {}
    for x in daily:
        m = x["date"][:7]
        b = monthly.setdefault(m, {"month": m, "profit": 0.0, "hit_count": 0, "periods": 0})
        b["profit"] += x["profit"]
        b["periods"] += 1
        if x["hit"]:
            b["hit_count"] += 1
    monthly_list = [monthly[k] for k in sorted(monthly)]
    for b in monthly_list:
        b["profit"] = round(b["profit"], 2)

    from datetime import timedelta
    last_date = rows[-1]["record_date"] if rows else ""
    next_date = (datetime.strptime(last_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d") if last_date else ""

    summary = {
        "final_cash": round(cash, 2),
        "total_withdraw": round(sum(w["withdraw"] for w in withdraws), 2),
        "bankrupt_count": bankrupt,
        "withdraw_count": len(withdraws),
        "total_inject": round(inject, 2),
        "total_net": round(cash + sum(w["withdraw"] for w in withdraws), 2),
        "net_profit": round(cash + sum(w["withdraw"] for w in withdraws) - START - inject, 2),
        "hit_count": sum(1 for x in daily if x["hit"]),
        "total_periods": len(daily),
        "bet_scheme": bet_scheme,
        "base_bet": base_bet,
        "max_level": max_level,
    }
    next_order = {
        "date": next_date,
        "picks": next_picks,
        "N": next_N,
        "cash": round(cash, 2),
        "bet": round(next_bet, 2),
        "per": next_per,
    }
    return {"start_date": start_date, "odds": odds, "bet_ratio": bet_ratio,
            "bankrupt_threshold": bankrupt_threshold, "mode": mode, "summary": summary,
            "daily": daily, "withdraws": withdraws, "monthly": monthly_list, "next_order": next_order}


# ============================================================
# 十一·五·甲、API — 策略演算报告（样本±2 × 5期窗口 全扫描）
# ============================================================
@app.get("/api/suggestNumber/strategy-scan")
def strategy_scan(user=Header(None, alias="authorization")):
    require_user(user)
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "analysis", "strategy_scan.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return {"error": str(e), "compound_top": [], "win5_top": [], "conclusion": {}}
    # 附加：每个方案×offset 当前演算的「对应号码数」（下单会买几个号）
    try:
        data["order_preview"] = _compute_strategy_preview()
    except Exception as e:
        data["order_preview"] = {"error": str(e)}
    return data


# ============================================================
# 十一·五·乙·1、API — 策略下单（方案卡片下单 + 按月下单记录）
# ============================================================
STRATEGY_ODDS = 47
SINGLE_BET = 25                      # 单次买：每号金额（元）
MULTI_BETS = [10, 20, 40, 80, 160]   # 连续买：5期每号金额（倍投），五期固定结束


def _compute_strategy_preview():
    """批量预演算所有方案×offset 的当前「对应号码数」+ 选号（下单预览，一次加载数据）。"""
    db = get_db()
    cycle = db.execute(
        "SELECT zodiac_mapping FROM zodiac_number_cycle_config WHERE is_enable=1 ORDER BY start_date DESC LIMIT 1").fetchone()
    zodiac_map = DEFAULT_ZODIAC
    if cycle:
        try:
            zm = json.loads(cycle["zodiac_mapping"])
            if zm:
                zodiac_map = zm
        except Exception:
            pass
    rows = db.execute(
        "SELECT * FROM number_knowledge_record WHERE status=1 ORDER BY record_date, id").fetchall()
    db.close()

    last_seen = {}; hist_max = {}; sample = {}
    for i, r in enumerate(rows):
        seq = i + 1
        for dim, tag in match_labels(r["source_number"], zodiac_map).items():
            if not tag:
                continue
            k = (dim, tag)
            if k in last_seen:
                gap = seq - last_seen[k]
                hist_max[k] = max(hist_max.get(k, 0), gap)
                sample[k] = sample.get(k, 0) + 1
            else:
                sample[k] = 1
            last_seen[k] = seq
    total_seq = len(rows)

    tn_cache = {}
    def tag_nums(dim, tag):
        k = (dim, tag)
        if k not in tn_cache:
            tn_cache[k] = [n for n in range(1, 50) if match_labels(n, zodiac_map).get(dim) == tag]
        return tn_cache[k]

    preview = {}
    for scheme, dims in STRATEGY_SCHEMES.items():
        dimset = set(dims)
        preview[scheme] = {}
        for off in (-2, -1, 0, 1, 2):
            picks = set()
            for (dim, tag), ls in last_seen.items():
                if dim not in dimset:
                    continue
                gap = total_seq - ls
                hm = hist_max.get((dim, tag), 0)
                if sample.get((dim, tag), 0) >= 2 and gap >= hm - off:
                    for n in tag_nums(dim, tag):
                        picks.add(n)
            picks = sorted(picks)
            preview[scheme][off] = {"N": len(picks), "picks": picks}
    return preview


def _window_hist_max(gap_hist, k, seq, window):
    """窗口内历史最高遗漏。window 为 0/None=全量历史；否则只统计 seq-window 之后发生的 gap。"""
    gh = gap_hist.get(k, [])
    if not window:
        return max((g for _, g in gh), default=0)
    return max((g for s, g in gh if seq - s <= window), default=0)


def _compute_strategy_order(dims, offset, window=None):
    """基于方案维度 + offset，演算当前应买入的号码。
    口径：标签当前遗漏 gap >= 历史最高 hist_max - offset（憋到高位）→ 买入该标签覆盖的号码并集。"""
    db = get_db()
    cycle = db.execute(
        "SELECT zodiac_mapping FROM zodiac_number_cycle_config WHERE is_enable=1 ORDER BY start_date DESC LIMIT 1").fetchone()
    zodiac_map = DEFAULT_ZODIAC
    if cycle:
        try:
            zm = json.loads(cycle["zodiac_mapping"])
            if zm:
                zodiac_map = zm
        except Exception:
            pass
    rows = db.execute(
        "SELECT * FROM number_knowledge_record WHERE status=1 ORDER BY record_date, id").fetchall()
    db.close()

    dimset = set(dims)

    def tag_nums(dim, tag):
        return [n for n in range(1, 50) if match_labels(n, zodiac_map).get(dim) == tag]

    last_seen = {}; sample = {}; gap_hist = {}
    for i, r in enumerate(rows):
        seq = i + 1
        for dim, tag in match_labels(r["source_number"], zodiac_map).items():
            if not tag:
                continue
            k = (dim, tag)
            if k in last_seen:
                gap = seq - last_seen[k]
                sample[k] = sample.get(k, 0) + 1
                gap_hist.setdefault(k, []).append((seq, gap))
            else:
                sample[k] = 1
            last_seen[k] = seq

    total_seq = len(rows)
    signals = []
    for (dim, tag), ls in last_seen.items():
        if dim not in dimset:
            continue
        gap = total_seq - ls
        hm = _window_hist_max(gap_hist, (dim, tag), total_seq, window)
        if sample.get((dim, tag), 0) >= 2 and gap >= hm - offset:
            signals.append({"dim": dim, "dim_name": DIM_NAMES.get(dim, dim), "tag": tag,
                            "gap": gap, "hist_max": hm})

    picks = set()
    for s in signals:
        for n in tag_nums(s["dim"], s["tag"]):
            picks.add(n)
    picks = sorted(picks)

    from datetime import timedelta
    last_date = rows[-1]["record_date"] if rows else ""
    next_date = (datetime.strptime(last_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d") if last_date else ""

    return {"date": next_date, "picks": picks, "N": len(picks), "signals": signals}


def _settle_strategy_orders():
    """结算 pending 的下单记录（bet_date <= 最新数据日 且 open_number 为 NULL）。"""
    db = get_db()
    last_row = db.execute(
        "SELECT MAX(record_date) AS d FROM number_knowledge_record WHERE status=1").fetchone()
    last_date = last_row["d"] if last_row else None
    if not last_date:
        db.close()
        return
    pending = db.execute(
        "SELECT id, bet_date, picks_json, N, per FROM strategy_order WHERE open_number IS NULL AND bet_date <= ?",
        (last_date,)).fetchall()
    for p in pending:
        orow = db.execute(
            "SELECT source_number FROM number_knowledge_record WHERE record_date=? AND status=1",
            (p["bet_date"],)).fetchone()
        if not orow:
            continue
        open_num = int(orow["source_number"])
        picks = json.loads(p["picks_json"]) if p["picks_json"] else []
        hit = 1 if open_num in picks else 0
        N = p["N"] or 0
        per = p["per"] or 1
        profit = (STRATEGY_ODDS - N) * per if hit else -N * per
        db.execute("UPDATE strategy_order SET open_number=?, hit=?, profit=? WHERE id=?",
                   (open_num, hit, round(profit, 2), p["id"]))
    db.commit()
    db.close()


def _order_row_to_dict(row):
    d = dict(row)
    try:
        d["picks"] = json.loads(row["picks_json"]) if row["picks_json"] else []
    except Exception:
        d["picks"] = []
    try:
        d["signals"] = json.loads(row["signals_json"]) if row["signals_json"] else []
    except Exception:
        d["signals"] = []
    return d


def _compute_rule_records(dims, offset, window=None):
    """回放历史，逐条生成「高位开出」触发规则记录 + 累计盈亏。
    口径：标签遗漏 gap >= 历史最高 hist_max - offset 时开出（高位开出）→ 下一期买入该标签号码（唯一买入点）→ 单期结算（下一期开出命中赚 47−N、未中亏 N）。
    window：历史最高遗漏滚动窗口（期），0/None=全量历史。"""
    db = get_db()
    cycle = db.execute(
        "SELECT zodiac_mapping FROM zodiac_number_cycle_config WHERE is_enable=1 ORDER BY start_date DESC LIMIT 1").fetchone()
    zodiac_map = DEFAULT_ZODIAC
    if cycle:
        try:
            zm = json.loads(cycle["zodiac_mapping"])
            if zm:
                zodiac_map = zm
        except Exception:
            pass
    rows = db.execute(
        "SELECT * FROM number_knowledge_record WHERE status=1 ORDER BY record_date, id").fetchall()
    db.close()

    dimset = set(dims)
    tn_cache = {}
    def tag_nums(dim, tag):
        k = (dim, tag)
        if k not in tn_cache:
            tn_cache[k] = [n for n in range(1, 50) if match_labels(n, zodiac_map).get(dim) == tag]
        return tn_cache[k]

    last_seen = {}; sample = {}; gap_hist = {}
    records = []
    cumulative_single = 0.0
    cumulative_multi = 0.0
    for i, r in enumerate(rows):
        seq = i + 1
        open_num = int(r["source_number"])
        open_labels = match_labels(open_num, zodiac_map)
        # 1. 检测高位开出事件
        events_now = []
        for dim, tag in open_labels.items():
            if not tag or dim not in dimset:
                continue
            k = (dim, tag)
            if k in last_seen:
                gap = seq - last_seen[k]
                hm = _window_hist_max(gap_hist, k, seq, window)
                if sample.get(k, 0) >= 2 and gap >= hm - offset:
                    events_now.append((dim, tag, len(tag_nums(dim, tag))))
        # 2. 结算 + 逐条记录（单次买 + 连续买两种模式）
        for dim, tag, N in events_now:
            # 单次买：每号 SINGLE_BET 元，下一期买入（唯一买入点），单期结算
            hit = False
            if i + 1 < len(rows):
                hit = match_labels(rows[i + 1]["source_number"], zodiac_map).get(dim) == tag
            profit_single = SINGLE_BET * (STRATEGY_ODDS - N) if hit else -SINGLE_BET * N
            cumulative_single += profit_single
            # 连续买：命中就停（马丁格尔），从高位开出下一期开始，五期固定结束
            profit_multi = 0.0
            multi_detail = []
            stopped = False
            for k in range(len(MULTI_BETS)):
                j = i + 1 + k
                if j >= len(rows):
                    break
                bet = MULTI_BETS[k]
                is_hit = match_labels(rows[j]["source_number"], zodiac_map).get(dim) == tag
                if is_hit:
                    # 命中：本期中奖 bet*47，扣掉累计投入 N*sum(bets[0..k])，停止
                    total_invest = N * sum(MULTI_BETS[0:k + 1])
                    p = bet * STRATEGY_ODDS - total_invest
                    profit_multi = p
                    multi_detail.append({"period": k + 1, "bet": bet, "hit": 1, "profit": round(p, 2)})
                    stopped = True
                    break
                else:
                    # 未中：本期亏 bet*N，继续下一期
                    multi_detail.append({"period": k + 1, "bet": bet, "hit": 0, "profit": round(-bet * N, 2)})
            if not stopped:
                # 五期都没命中：累计投入 N*sum(MULTI_BETS)
                profit_multi = -N * sum(MULTI_BETS)
            cumulative_multi += profit_multi
            records.append({
                "date": r["record_date"],
                "dim": dim, "dim_name": DIM_NAMES.get(dim, dim), "tag": tag,
                "picks": tag_nums(dim, tag), "N": N,
                "hit": 1 if hit else 0,
                "profit": round(profit_single, 2),
                "cumulative": round(cumulative_single, 2),
                "profit_multi": round(profit_multi, 2),
                "cumulative_multi": round(cumulative_multi, 2),
                "multi_detail": multi_detail,
            })
        # 3. 更新状态
        for dim, tag in open_labels.items():
            if not tag:
                continue
            k = (dim, tag)
            if k in last_seen:
                gap = seq - last_seen[k]
                gap_hist.setdefault(k, []).append((seq, gap))
                sample[k] = sample.get(k, 0) + 1
            else:
                sample[k] = 1
            last_seen[k] = seq

    hits = sum(1 for rec in records if rec["hit"])
    return {
        "records": records,
        "events": len(records),
        "hits": hits,
        "hit_rate": round(hits / len(records), 4) if records else 0.0,
        "total_profit": round(cumulative_single, 2),
        "total_profit_multi": round(cumulative_multi, 2),
        "single_bet": SINGLE_BET,
        "multi_bets": MULTI_BETS,
    }


@app.get("/api/strategyOrder/rules")
def strategy_order_rules(scheme: str = "全维度19", offset: int = 0, user=Header(None, alias="authorization")):
    require_user(user)
    dims = STRATEGY_SCHEMES.get(scheme)
    if not dims:
        raise HTTPException(400, "未知方案: " + scheme)
    out = {"scheme": scheme, "offset": offset}
    out.update(_compute_rule_records(dims, offset, get_strategy_window()))
    return out


@app.get("/api/strategyOrder/dim-report")
def strategy_order_dim_report(scheme: str = "全维度19", offset: int = 2, months: int = 6, user=Header(None, alias="authorization")):
    """单次跟踪 · 维度贡献统计报表（近 N 个月，单次买模式，按维度聚合盈亏）。"""
    require_user(user)
    dims = STRATEGY_SCHEMES.get(scheme)
    if not dims:
        raise HTTPException(400, "未知方案: " + scheme)
    full = _compute_rule_records(dims, offset, get_strategy_window())
    records = full["records"]
    if not records:
        return {"scheme": scheme, "offset": offset, "months": months,
                "window_start": "", "window_end": "", "summary": {}, "dims": [], "monthly": []}
    latest = max(r["date"] for r in records)
    try:
        latest_dt = datetime.strptime(latest, "%Y-%m-%d")
    except Exception:
        latest_dt = datetime.now()
    # 自然月窗口：以最新触发日期所在月往前 (months-1) 个月的第一天为起点
    total = latest_dt.year * 12 + (latest_dt.month - 1) - (months - 1)
    sy, sm = total // 12, total % 12 + 1
    window_start = date(sy, sm, 1).strftime("%Y-%m-%d")
    window_end = latest

    dim_agg = {}
    monthly = {}
    for r in records:
        if r["date"] < window_start:
            continue
        d = r["dim"]
        a = dim_agg.setdefault(d, {"dim": d, "dim_name": r["dim_name"],
                                  "events": 0, "hits": 0, "profit": 0.0, "N_sum": 0})
        a["events"] += 1
        a["hits"] += r["hit"]
        a["profit"] += r["profit"]
        a["N_sum"] += r["N"]
        mo = r["date"][:7]
        b = monthly.setdefault(mo, {"month": mo, "events": 0, "profit": 0.0})
        b["events"] += 1
        b["profit"] += r["profit"]

    dims_out = []
    for a in dim_agg.values():
        dims_out.append({
            "dim": a["dim"], "dim_name": a["dim_name"],
            "events": a["events"], "hits": a["hits"],
            "hit_rate": round(a["hits"] / a["events"], 4) if a["events"] else 0,
            "profit": round(a["profit"], 2),
            "per_event": round(a["profit"] / a["events"], 2) if a["events"] else 0,
            "avg_N": round(a["N_sum"] / a["events"], 1) if a["events"] else 0,
        })
    dims_out.sort(key=lambda x: -x["profit"])
    monthly_out = sorted(monthly.values(), key=lambda x: x["month"])

    ev = sum(a["events"] for a in dim_agg.values())
    hts = sum(a["hits"] for a in dim_agg.values())
    tp = sum(a["profit"] for a in dim_agg.values())
    summary = {
        "events": ev, "hits": hts,
        "hit_rate": round(hts / ev, 4) if ev else 0,
        "total_profit": round(tp, 2),
        "per_event": round(tp / ev, 2) if ev else 0,
    }
    return {"scheme": scheme, "offset": offset, "months": months,
            "window_start": window_start, "window_end": window_end,
            "summary": summary, "dims": dims_out, "monthly": monthly_out}


def _compute_current_signals(offset, window=None):
    """当前信号列表：区分「预警中」（憋到高位未开出）和「待买入」（最新一期高位开出）。
    口径：① 预警=遗漏≥历史最高−offset；② 高位开出；③ 开出后下一期买入。
    window：历史最高遗漏滚动窗口（期），0/None=全量历史。"""
    db = get_db()
    cycle = db.execute(
        "SELECT zodiac_mapping FROM zodiac_number_cycle_config WHERE is_enable=1 ORDER BY start_date DESC LIMIT 1").fetchone()
    zodiac_map = DEFAULT_ZODIAC
    if cycle:
        try:
            zm = json.loads(cycle["zodiac_mapping"])
            if zm:
                zodiac_map = zm
        except Exception:
            pass
    rows = db.execute(
        "SELECT * FROM number_knowledge_record WHERE status=1 ORDER BY record_date, id").fetchall()
    db.close()

    last_seen = {}; sample = {}; last_gap = {}; gap_hist = {}
    for i, r in enumerate(rows):
        seq = i + 1
        for dim, tag in match_labels(r["source_number"], zodiac_map).items():
            if not tag:
                continue
            k = (dim, tag)
            if k in last_seen:
                gap = seq - last_seen[k]
                gap_hist.setdefault(k, []).append((seq, gap))
                sample[k] = sample.get(k, 0) + 1
                last_gap[k] = gap
            else:
                sample[k] = 1
            last_seen[k] = seq
    total_seq = len(rows)

    tn_cache = {}
    def tag_nums(dim, tag):
        k = (dim, tag)
        if k not in tn_cache:
            tn_cache[k] = [n for n in range(1, 50) if match_labels(n, zodiac_map).get(dim) == tag]
        return tn_cache[k]

    warning = []   # 预警中：憋到高位，还没开出
    pending = []   # 待买入：最新一期高位开出
    for (dim, tag), ls in last_seen.items():
        hm = _window_hist_max(gap_hist, (dim, tag), total_seq, window)
        if sample.get((dim, tag), 0) < 2:
            continue
        picks = tag_nums(dim, tag)
        base = {"dim": dim, "dim_name": DIM_NAMES.get(dim, dim), "tag": tag,
                "hist_max": hm, "picks": picks, "N": len(picks)}
        gap = total_seq - ls
        # 待买入：最新一期开出该标签，且开出前遗漏 ≥ 历史最高 − offset（高位开出）
        if ls == total_seq and last_gap.get((dim, tag), 0) >= hm - offset:
            base.update({"status": "pending", "gap": 0, "last_gap": last_gap.get((dim, tag), 0)})
            pending.append(base)
        # 预警中：当前遗漏 ≥ 历史最高 − offset（还在憋）
        elif gap >= hm - offset:
            base.update({"status": "warning", "gap": gap, "last_gap": None})
            warning.append(base)
    warning.sort(key=lambda x: -x["gap"])
    pending.sort(key=lambda x: -x["last_gap"])
    return {"warning": warning, "pending": pending}


def _compute_posdim_single_next(offset=2, window=None):
    """4维正信号·单期买选号：最新一期高位开出的标签（仅 POS_DIMS 4维），下一期买入号码并集。
    用于 algo_forward_track 前向验证（方案A，样本外跑 20~30 期确认稳定后再切投入引擎）。"""
    from datetime import timedelta
    sig = _compute_current_signals(offset, window)
    db = get_db()
    last_date = db.execute(
        "SELECT MAX(record_date) d FROM number_knowledge_record WHERE status=1").fetchone()["d"]
    db.close()
    picks = set()
    detail = []
    for p in sig.get("pending", []):
        if p["dim"] not in POS_DIMS:
            continue
        picks.update(p["picks"])
        detail.append({"dim": p["dim"], "dim_name": p["dim_name"],
                       "tag": p["tag"], "N": p["N"]})
    picks = sorted(picks)
    next_date = ""
    if last_date:
        next_date = (datetime.strptime(last_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    return {"date": next_date, "picks": picks, "N": len(picks), "detail": detail}


def _compute_engine():
    """投入引擎：基于本金 + 当前待买入信号 + 历史命中率，输出每日下单资金指南。
    原则：① 安全垫永不投入；② 只投正期望且高命中(≥红线)的信号；③ 进取仓位按本金比例；④ 单号金额动态摊薄。"""
    capital = _get_config_int('engine_capital', 3000)
    position_pct = _get_config_int('engine_position_pct', 20)
    safety_pct = _get_config_int('engine_safety_pct', 30)
    min_per = _get_config_int('engine_min_per', 10)
    hit_floor = _get_config_int('engine_hit_floor', 70)
    offset = 2
    window = get_strategy_window()

    # 1. 当前信号（待买入 = 唯一买入点）
    signals = _compute_current_signals(offset, window)
    pending = signals['pending']

    # 2. 各维度历史命中率（滚动窗口，单次买）
    rec = _compute_rule_records(ALL_DIMS, offset, window)
    dim_stat = {}
    for r in rec['records']:
        a = dim_stat.setdefault(r['dim'], {'ev': 0, 'hit': 0})
        a['ev'] += 1
        a['hit'] += r['hit']

    # 3. 筛选候选：维度近3月逐月盈亏全正（近期持续盈利才计入，否则观望）+ 样本 ≥ 5
    monthly = {}
    for r in rec['records']:
        m = r['date'][:7]
        d = monthly.setdefault(r['dim'], {})
        d[m] = d.get(m, 0) + r['profit']
    all_months = sorted({r['date'][:7] for r in rec['records']})
    recent3 = all_months[-3:] if len(all_months) >= 3 else all_months

    candidates = []
    for s in pending:
        st = dim_stat.get(s['dim'])
        if not st or st['ev'] < 5:
            continue
        # 近3月逐月全正才计入，否则观望
        ms = monthly.get(s['dim'], {})
        if not all(ms.get(m, 0) > 0 for m in recent3):
            continue
        p = st['hit'] / st['ev']
        N = s['N']
        ev_per = p * (STRATEGY_ODDS - N) - (1 - p) * N
        candidates.append({
            'dim': s['dim'], 'dim_name': s['dim_name'], 'tag': s['tag'],
            'picks': s['picks'], 'N': N,
            'hit_rate': round(p, 4), 'ev_per': round(ev_per, 2),
        })

    # 4. 按单号期望降序
    candidates.sort(key=lambda x: -x['ev_per'])

    # 5. 资金分配：当天合格信号全买，单号金额动态摊薄（不砍信号）
    safety = round(capital * safety_pct / 100, 2)
    available = round(capital - safety, 2)

    total_N = sum(c['N'] for c in candidates)
    # 单号金额 = min(基准25元, 可用资金/总N)，信号多则摊薄；向下取整到分保证总投入 ≤ 可用资金
    base_per = SINGLE_BET  # 25 元基准
    per = min(base_per, available / total_N) if total_N else base_per
    per = int(per * 100) / 100

    picks = []
    for c in candidates:
        picks.append({**c, 'per': per, 'amount': round(c['N'] * per, 2)})
    total_amount = round(total_N * per, 2)

    # 6. 资金曲线（本金 + 已实现盈亏）+ 建议买入日（数据最新期 + 1 天）
    db = get_db()
    o = db.execute("SELECT COALESCE(SUM(profit),0) AS tp FROM strategy_order WHERE open_number IS NOT NULL").fetchone()
    lr = db.execute("SELECT MAX(record_date) AS d FROM number_knowledge_record WHERE status=1").fetchone()
    db.close()
    realized = round(o['tp'] or 0, 2)
    balance = round(capital + realized, 2)
    last_date = lr['d'] if lr else ''
    from datetime import timedelta
    bet_date = (datetime.strptime(last_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d") if last_date else ''

    # 7. 风险等级（按总投入占可用资金比例）
    ratio = total_amount / available if available else 0
    if not candidates:
        risk, risk_note = 'gray', f'当前无近3月逐月全正的待买入信号，{bet_date} 建议观望'
    elif ratio > 1:
        risk, risk_note = 'red', f'信号过多，总投入 {total_amount} 元已超可用资金 {available} 元，建议提高安全垫或降低单号金额'
    elif ratio >= 0.7:
        risk, risk_note = 'yellow', f'{bet_date} 建议买入 {len(picks)} 个信号，投入 {total_amount} 元占可用资金 {ratio * 100:.0f}%，接近满仓'
    else:
        risk, risk_note = 'green', f'{bet_date} 建议买入 {len(picks)} 个信号，投入 {total_amount} 元占可用资金 {ratio * 100:.0f}%'

    return {
        'capital': capital, 'safety': safety, 'available': available,
        'position_pct': position_pct, 'safety_pct': safety_pct,
        'hit_floor': hit_floor, 'min_per': min_per, 'window': window,
        'picks': picks, 'total_N': total_N, 'total_amount': total_amount,
        'candidates_total': len(candidates), 'pending_total': len(pending),
        'ratio': round(ratio, 4),
        'last_date': last_date, 'bet_date': bet_date,
        'realized': realized, 'balance': balance,
        'risk_level': risk, 'risk_note': risk_note,
    }


@app.get("/api/strategyOrder/signals")
def strategy_order_signals(offset: int = 2, user=Header(None, alias="authorization")):
    require_user(user)
    return {"offset": offset, "signals": _compute_current_signals(offset, get_strategy_window())}


@app.get("/api/strategyOrder/engine")
def strategy_order_engine(user=Header(None, alias="authorization")):
    """投入引擎：每日下单资金指南。"""
    require_user(user)
    return _compute_engine()


@app.post("/api/strategyOrder/place")
def strategy_order_place(body: dict, user=Header(None, alias="authorization")):
    require_user(user)
    scheme = body.get("scheme", "")
    offset = int(body.get("offset", 0))
    dims = STRATEGY_SCHEMES.get(scheme)
    if not dims:
        raise HTTPException(400, "未知方案: " + scheme)
    order = _compute_strategy_order(dims, offset, get_strategy_window())
    if not order.get("date"):
        raise HTTPException(400, "无开奖数据，无法演算")
    picks = order["picks"]
    N = order["N"]
    per = 1.0
    amount = round(N * per, 2)
    bet_date = order["date"]

    db = get_db()
    existing = db.execute(
        "SELECT * FROM strategy_order WHERE scheme=? AND offset=? AND bet_date=? AND open_number IS NULL ORDER BY id DESC LIMIT 1",
        (scheme, offset, bet_date)).fetchone()
    if existing:
        db.close()
        d = _order_row_to_dict(existing)
        return {"ok": True, "order": d, "duplicate": True}

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur = db.execute(
        "INSERT INTO strategy_order (scheme, offset, dims_json, bet_date, picks_json, N, per, amount, signals_json, create_time) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (scheme, offset, json.dumps(dims), bet_date, json.dumps(picks), N, per, amount,
         json.dumps(order["signals"], ensure_ascii=False), now))
    db.commit()
    oid = cur.lastrowid
    row = db.execute("SELECT * FROM strategy_order WHERE id=?", (oid,)).fetchone()
    db.close()
    d = _order_row_to_dict(row)
    return {"ok": True, "order": d, "duplicate": False}


@app.get("/api/strategyOrder/list")
def strategy_order_list(user=Header(None, alias="authorization")):
    require_user(user)
    _settle_strategy_orders()
    db = get_db()
    rows = db.execute("SELECT * FROM strategy_order ORDER BY bet_date DESC, id DESC").fetchall()
    db.close()
    items = [_order_row_to_dict(r) for r in rows]
    monthly = {}
    for it in items:
        m = (it["bet_date"] or "")[:7] or "未知"
        g = monthly.setdefault(m, {"month": m, "orders": [], "hit_count": 0, "settled": 0, "profit": 0.0})
        g["orders"].append(it)
        if it["hit"] is not None:
            g["settled"] += 1
            if it["hit"] == 1:
                g["hit_count"] += 1
            g["profit"] = round(g["profit"] + (it["profit"] or 0), 2)
    months = [monthly[k] for k in sorted(monthly, reverse=True)]
    return {"months": months, "total": len(items)}


@app.post("/api/strategyOrder/settle")
def strategy_order_settle(user=Header(None, alias="authorization")):
    require_user(user)
    _settle_strategy_orders()
    return {"ok": True}


# ============================================================
# 十一·五·乙、API — 演算跟踪（多算法前向跟踪）
# ============================================================
def _algo_track_settle_and_generate():
    """「后续演算跟踪」核心：①结算已开奖的 pending 记录 ②为每个算法生成下一期选号并固化。"""
    try:
        # 1. 结算 pending（bet_date <= 最新数据日 且 open_number 仍为 NULL）
        db = get_db()
        last_row = db.execute(
            "SELECT MAX(record_date) AS d FROM number_knowledge_record WHERE status=1").fetchone()
        last_date = last_row["d"] if last_row else None
        if not last_date:
            db.close()
            return
        pending = db.execute(
            "SELECT id, bet_date, picks_json, N FROM algo_forward_track "
            "WHERE open_number IS NULL AND bet_date <= ?", (last_date,)).fetchall()
        for p in pending:
            orow = db.execute(
                "SELECT source_number FROM number_knowledge_record WHERE record_date=? AND status=1",
                (p["bet_date"],)).fetchone()
            if not orow:
                continue
            open_num = int(orow["source_number"])
            picks = json.loads(p["picks_json"]) if p["picks_json"] else []
            hit = 1 if open_num in picks else 0
            db.execute("UPDATE algo_forward_track SET open_number=?, hit=? WHERE id=?",
                       (open_num, hit, p["id"]))
        db.commit()
        db.close()

        # 2. 生成下一期选号（对每个算法算 next_order，固化到 UNIQUE(algo_key, bet_date)）
        token = create_token({"username": "admin", "role_code": "super_admin"})
        auth = f"Bearer {token}"
        next_rows = []
        for algo in TRACK_ALGOS:
            if algo.get("generator") == "posdim_single":
                nxt = _compute_posdim_single_next(offset=algo.get("offset", 2), window=get_strategy_window())
            else:
                r = suggest_number_order_track(
                    mode=algo["mode"], signal_top_n=algo["signal_top_n"],
                    signal_source=algo["signal_source"], offset=algo.get("offset", 0),
                    sort_by=algo.get("sort_by", "gap"), user=auth)
                nxt = r.get("next_order") or {}
            if nxt.get("date"):
                next_rows.append((algo["key"], nxt["date"],
                                  json.dumps(nxt.get("picks", [])), nxt.get("N", 0)))
        db = get_db()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for key, bd, picks, N in next_rows:
            db.execute(
                "INSERT OR IGNORE INTO algo_forward_track "
                "(algo_key, bet_date, picks_json, N, open_number, hit, create_time) "
                "VALUES (?,?,?,?,NULL,NULL,?)", (key, bd, picks, N, now))
        db.commit()
        db.close()
    except Exception as e:
        print(f"[algo_track] settle_and_generate 失败: {e}")


@app.get("/api/algoTrack/list")
def algo_track_list(user=Header(None, alias="authorization")):
    require_user(user)
    db = get_db()
    rows = db.execute("SELECT * FROM algo_forward_track ORDER BY bet_date DESC, algo_key").fetchall()
    db.close()
    by_algo = {}
    for r in rows:
        d = dict(r)
        try:
            d["picks"] = json.loads(d["picks_json"]) if d["picks_json"] else []
        except Exception:
            d["picks"] = []
        by_algo.setdefault(r["algo_key"], []).append(d)
    algos = []
    for algo in TRACK_ALGOS:
        recs = by_algo.get(algo["key"], [])
        settled = [r for r in recs if r["hit"] is not None]
        hits = sum(1 for r in settled if r["hit"] == 1)
        algos.append({
            "key": algo["key"], "name": algo["name"],
            "pending": [r for r in recs if r["hit"] is None],
            "history": settled,
            "stats": {"hit": hits, "periods": len(settled),
                      "hit_rate": round(hits / len(settled), 4) if settled else None},
        })
    return {"algos": algos, "total": len(rows)}


@app.post("/api/algoTrack/refresh")
def algo_track_refresh(user=Header(None, alias="authorization")):
    require_admin(user)
    _algo_track_settle_and_generate()
    return {"ok": True}


# ============================================================
# 十一·五、API — 信号跟踪（预警触发 → 后续开出）
# ============================================================
@app.get("/api/signalTrack/list")
def signal_track_list(user=Header(None, alias="authorization")):
    require_user(user)
    db = get_db()
    rows = db.execute(
        "SELECT * FROM warn_signal_track ORDER BY signal_seq DESC, dim_key, tag_value").fetchall()
    offset = get_warn_offset(db)
    db.close()
    items = [dict(r) for r in rows]
    # 按维度聚合命中率（1/2/3/4/5/10/15期内）
    dim_agg = {}
    for it in items:
        dk = it["dim_key"]
        if dk not in dim_agg:
            dim_agg[dk] = {"dim_key": dk, "dim_name": it["dim_name"], "total": 0,
                           "hit1": 0, "hit2": 0, "hit3": 0, "hit4": 0,
                           "hit5": 0, "hit10": 0, "hit15": 0, "tracking": 0}
        dim_agg[dk]["total"] += 1
        if it["hit_interval"] is None:
            dim_agg[dk]["tracking"] += 1
        else:
            hi = it["hit_interval"]
            if hi <= 1:
                dim_agg[dk]["hit1"] += 1
            if hi <= 2:
                dim_agg[dk]["hit2"] += 1
            if hi <= 3:
                dim_agg[dk]["hit3"] += 1
            if hi <= 4:
                dim_agg[dk]["hit4"] += 1
            if hi <= 5:
                dim_agg[dk]["hit5"] += 1
            if hi <= 10:
                dim_agg[dk]["hit10"] += 1
            if hi <= 15:
                dim_agg[dk]["hit15"] += 1
    summary = []
    for dk, v in dim_agg.items():
        settled = v["total"] - v["tracking"]
        for w in (1, 2, 3, 4, 5, 10, 15):
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
        "trigger_rule": {
            "offset": offset,
            "min_sample": 2,
            "formula": "当前遗漏 ≥ 历史最高遗漏 − 偏移值",
        },
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
