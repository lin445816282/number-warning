#!/usr/bin/env python3
"""号码知识库全维度智能预警系统 — FastAPI + SQLite 单文件后端"""
import os
import json
import hmac
import hashlib
import base64
import sqlite3
import time
import random
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

# 前向验证可跟踪维度分级（2026-09-01 演算：window=60 近2月约束下触发率，见 analysis/trackability_scan.py）
# 高频7 + 中频2 = 可跟踪9维（前向引擎每日固化，能攒够样本做统计判定）
# 低频11维 = 二元维度（触发率<7%，攒400期需4~22年，前向验证不可行 → 靠回测+事件级跟踪判定，不占前向判定名额）
TRACKABLE_DIMS = [
    "zodiac", "tail_number", "five_element", "head_number", "season_type",
    "size_odd_even", "qqsh_type", "wave_color", "zodiac_color_type",
]
LOW_FREQ_DIMS = [
    "animal_type", "edge_color", "he_sum", "zodiac_seq", "big_small",
    "gender_zodiac", "yin_yang", "sky_earth", "odd_even", "beauty_type", "stroke_type",
]

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
CREATE TABLE IF NOT EXISTS dim_forward_track (
  id INTEGER PRIMARY KEY AUTOINCREMENT, dim_key TEXT, bet_date TEXT,
  picks_json TEXT, N INTEGER DEFAULT 0,
  open_number INTEGER, hit INTEGER,
  create_time TEXT,
  UNIQUE(dim_key, bet_date)
);
CREATE TABLE IF NOT EXISTS strategy_order (
  id INTEGER PRIMARY KEY AUTOINCREMENT, scheme TEXT, offset INTEGER DEFAULT 0,
  dims_json TEXT, bet_date TEXT, picks_json TEXT, N INTEGER DEFAULT 0,
  per REAL DEFAULT 1, amount REAL DEFAULT 0, signals_json TEXT,
  open_number INTEGER, hit INTEGER, profit REAL,
  create_time TEXT
);
CREATE TABLE IF NOT EXISTS strategy_scheme_record (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  scheme_key TEXT UNIQUE,           -- 去重键：维度集合+信号口径+offset 规范化哈希
  scheme_name TEXT,                 -- 人类可读名称
  dims_json TEXT,                   -- 维度集合
  signal_rule TEXT DEFAULT 'high_gap',  -- 信号口径（high_gap=高位触发）
  offset INTEGER DEFAULT 0,         -- 高位触发 offset
  window INTEGER DEFAULT 60,        -- 历史最高遗漏滚动窗口
  bet_mode TEXT DEFAULT 'single',   -- single=单次买 / martingale=倍投
  bet_ratio REAL DEFAULT 0.5,       -- 仓位（仅仓位模拟口径用，等额回测固定每号1元）
  -- 回测指标（等额口径：每号1元，赔率47）
  bt_periods INTEGER DEFAULT 0,     -- 回测总期数
  bt_triggered INTEGER DEFAULT 0,   -- 触发期数（N>0）
  bt_hits INTEGER DEFAULT 0,        -- 命中次数
  bt_hit_rate REAL,                 -- 命中率
  bt_avg_n REAL,                    -- 平均选号数
  bt_rand_base REAL,                -- 随机基准 = avg_n/49
  bt_alpha REAL,                    -- 超额命中 = hit_rate - rand_base
  bt_net_profit REAL,               -- 净收益（每号1元累计）
  bt_ev REAL,                       -- 每期期望 = net/periods
  bt_front_alpha REAL,              -- 前半段超额
  bt_back_alpha REAL,               -- 后半段超额
  bt_front_ev REAL,                 -- 前半段 EV
  bt_back_ev REAL,                  -- 后半段 EV
  bt_stable INTEGER DEFAULT 0,      -- 时间分段稳健（4段≥3段EV正）
  bt_max_dd REAL,                   -- 最大回撤（净收益曲线，%）
  seg_evs_json TEXT,                -- 4 段 EV 明细（JSON 数组）
  -- 前向指标（样本外，每日固化结算累计）
  fwd_periods INTEGER DEFAULT 0,
  fwd_hits INTEGER DEFAULT 0,
  fwd_profit REAL DEFAULT 0,
  -- 状态与来源
  status TEXT DEFAULT 'backtested', -- backtested/forwarding/promoted/rejected/historical
  conclusion TEXT,                  -- 结论备注
  source TEXT DEFAULT 'auto',       -- auto=AI寻优 / manual=手工登记 / historical=历史已论证
  create_time TEXT, update_time TEXT
);
CREATE TABLE IF NOT EXISTS zodiac_track_account (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  capital REAL DEFAULT 3000,        -- 当前本金
  initial_capital REAL DEFAULT 3000,
  per REAL DEFAULT 4,               -- 每号下注金额（元）
  warn_threshold REAL DEFAULT 500,  -- 预警线
  status TEXT DEFAULT 'running',    -- running/warn/bankrupt
  tracking_zodiac TEXT DEFAULT '',  -- 当前跟踪的生肖（空=空仓）
  held INTEGER DEFAULT 0,           -- 已跟踪期数
  enter_date TEXT DEFAULT '',       -- 进场日期
  last_settle_date TEXT DEFAULT '', -- 最后结算日期
  create_time TEXT, update_time TEXT
);
CREATE TABLE IF NOT EXISTS zodiac_track_order (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  bet_date TEXT,                    -- 下单/结算日期
  zodiac TEXT,                      -- 跟踪生肖
  nums_json TEXT,                   -- 覆盖号码
  N INTEGER DEFAULT 0,
  held INTEGER DEFAULT 0,           -- 第几期
  result TEXT DEFAULT '',           -- hold/hit/stop
  open_zodiac TEXT DEFAULT '',      -- 当期开出生肖
  pnl REAL,                         -- 本轮盈亏（命中/止损时）
  capital_after REAL,               -- 结算后本金
  create_time TEXT
);
CREATE INDEX IF NOT EXISTS idx_zodiac_order_date ON zodiac_track_order(bet_date);
CREATE TABLE IF NOT EXISTS zodiac_track_position (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id INTEGER DEFAULT 0,      -- 关联源头事件(zodiac_track_source.id)
  zodiac TEXT,                      -- 跟踪生肖
  enter_date TEXT DEFAULT '',       -- 进场日期
  held INTEGER DEFAULT 0,           -- 已跟踪期数
  status TEXT DEFAULT 'holding',    -- holding/closed
  close_date TEXT DEFAULT '',       -- 清仓日期
  close_reason TEXT DEFAULT '',     -- hit/stop
  total_invest REAL DEFAULT 0,      -- 该持仓累计投入（元）
  create_time TEXT, update_time TEXT
);
CREATE INDEX IF NOT EXISTS idx_zodiac_pos_status ON zodiac_track_position(status);
CREATE TABLE IF NOT EXISTS zodiac_track_source (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_date TEXT DEFAULT '',      -- 触发日期（≥6肖同时遗漏≥12）
  end_date TEXT DEFAULT '',         -- 结束日期（6肖全部关闭）
  zodiacs_json TEXT DEFAULT '',     -- 6肖信息 [{zodiac,gap,nums}]
  status TEXT DEFAULT 'active',     -- active/closed
  hit_count INTEGER DEFAULT 0,      -- 命中肖数
  stop_count INTEGER DEFAULT 0,     -- 止损肖数
  total_pnl REAL DEFAULT 0,         -- 该事件总盈亏（元）
  create_time TEXT, update_time TEXT
);
CREATE INDEX IF NOT EXISTS idx_zodiac_source_status ON zodiac_track_source(status);
CREATE TABLE IF NOT EXISTS random8_round (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  round_no INTEGER,                 -- 轮次号（从1递增）
  numbers_json TEXT DEFAULT '',     -- 随机8码（逗号分隔字符串）
  start_date TEXT DEFAULT '',       -- 本轮开始日期
  end_date TEXT DEFAULT '',         -- 结束日期（命中或止损日）
  hit_period INTEGER DEFAULT 0,     -- 命中第几期(1~6)，0=6期未开止损
  hit_number INTEGER DEFAULT 0,     -- 命中号码
  result TEXT DEFAULT '',           -- hit/stop
  total_invest REAL DEFAULT 0,      -- 累计投入（每号1元×8码×期数）
  pnl REAL DEFAULT 0,               -- 盈亏（命中=47-投入，止损=-投入）
  create_time TEXT
);
CREATE INDEX IF NOT EXISTS idx_random8_round_no ON random8_round(round_no);
CREATE TABLE IF NOT EXISTS fixed_order_round (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  round_no INTEGER,                 -- 轮次号（从1递增）
  numbers_json TEXT DEFAULT '',     -- 随机8码（逗号分隔字符串）
  start_date TEXT DEFAULT '',       -- 本轮开始日期
  end_date TEXT DEFAULT '',         -- 结束日期（命中/止损/暂停解除日）
  hit_period INTEGER DEFAULT 0,     -- 命中第几期(1~6)，0=未命中
  hit_number INTEGER DEFAULT 0,     -- 命中号码
  result TEXT DEFAULT '',           -- hit/stop/pause(暂停等待)
  pause_len INTEGER DEFAULT 0,      -- 暂停等待期数（result=pause时）
  total_invest REAL DEFAULT 0,      -- 累计投入（每号金额×8码×期数）
  pnl REAL DEFAULT 0,               -- 盈亏（命中=47×该期每号金额-投入，止损=-投入）
  create_time TEXT
);
CREATE INDEX IF NOT EXISTS idx_fixed_order_round_no ON fixed_order_round(round_no);
"""

# 默认生肖映射（丙午马年 2026-02-17）
DEFAULT_ZODIAC = {
    "马": [1,13,25,37,49], "蛇": [2,14,26,38], "龙": [3,15,27,39],
    "兔": [4,16,28,40], "虎": [5,17,29,41], "牛": [6,18,30,42],
    "鼠": [7,19,31,43], "猪": [8,20,32,44], "狗": [9,21,33,45],
    "鸡": [10,22,34,46], "猴": [11,23,35,47], "羊": [12,24,36,48],
}

# 生肖倒序序列（六合彩规则：1号=当年生肖，此后按倒序排列；马年1-12号对应此序）
_ZODIAC_SEQ = ["马", "蛇", "龙", "兔", "虎", "牛", "鼠", "猪", "狗", "鸡", "猴", "羊"]


def _build_zodiac_mapping(seq):
    """由 1-12 号生肖序列生成完整生肖映射（首位生肖含49共5号，其余各4号）。"""
    m = {}
    for i, z in enumerate(seq):
        nums = [i + 1, i + 13, i + 25, i + 37]
        if i == 0:
            nums.append(49)
        m[z] = nums
    return m


def _load_cycle_maps(db):
    """加载 cycle_id → zodiac_mapping（is_enable=1），用于按记录周期匹配生肖，避免跨年错位。"""
    cycle_maps = {}
    for c in db.execute("SELECT id, zodiac_mapping FROM zodiac_number_cycle_config WHERE is_enable=1").fetchall():
        try:
            m = json.loads(c["zodiac_mapping"])
            cycle_maps[c["id"]] = m if m else DEFAULT_ZODIAC
        except Exception:
            cycle_maps[c["id"]] = DEFAULT_ZODIAC
    return cycle_maps


def _map_for(rec, cycle_maps):
    """按记录的 cycle_id 取对应周期生肖映射，缺省回落 DEFAULT_ZODIAC。"""
    return cycle_maps.get(rec["cycle_id"], DEFAULT_ZODIAC)


# season_type=春夏秋冬 / size_odd_even=大小单双 / wave_color=号码波色 / edge_color=白边黑中
POS_DIMS = ["season_type", "size_odd_even", "wave_color", "edge_color"]

# 高位跟踪（2026-09-07 新增）：高位触发（遗漏≥近2月hist_max−offset）→ 倍投10-20-40三期 / 单次买
HIGH_TRACK_BETS = [10, 20, 40]  # 倍投三期每号金额
HIGH_TRACK_CORE = ["qqsh_type", "yin_yang"]  # 稳定核心池：琴棋书画/阴阳（2026-09-07 从3维瘦身，生肖踢出进观察池待前向考核）

# 维度考核准入线（2026-09-07）：三关——①历史初筛 ②前向验证(20~30期) ③滚动复考(近3月连续2月负降级)
DIM_ASSESS_MIN_EV = 20      # 第1关：最小事件数（排除小样本运气）
DIM_ASSESS_MIN_HIT = 0.60   # 第1关：最小命中率（排除靠N小硬撑的低命中维度）
DIM_ASSESS_MIN_PER = 0.0    # 第1关：每事件盈利须为正（正期望）

# 第2关·前向验证（观察池维度，2026-09-07）：
# 每日固化「憋到高位」标签号码并集 → 开奖单次结算 → 攒够期数后按「超额命中」判定转正/淘汰
DIM_ASSESS_WATCH = ["big_small", "edge_color", "zodiac_color_type", "sky_earth", "odd_even",
                    "wave_color", "he_sum", "stroke_type", "size_odd_even", "zodiac_seq"]  # 当前观察池（转正/淘汰时手动更新）
DIM_ASSESS_FWD_MIN_PERIODS = 100  # 前向最小期数（够100期才判定：20期标准差11%无法识别5%超额，100期降至5%假阳性率16%）
DIM_ASSESS_FWD_MIN_ALPHA = 0.05   # 前向超额命中及格线：命中率须 ≥ 随机基准(N/49) + 5%（过滤纯随机维度）
HIGH_TRACK_POS15 = ["zodiac", "odd_even", "big_small", "size_odd_even", "wave_color", "he_sum",
                    "zodiac_seq", "beauty_type", "yin_yang", "stroke_type", "sky_earth",
                    "edge_color", "qqsh_type", "zodiac_color_type", "tail_number"]  # 15正盈利维度
HIGH_TRACK_SCHEMES = [
    {"key": "A", "name": "全维度 · 倍投10-20-40", "dims": "all", "bet": "martingale"},
    {"key": "B", "name": "15正盈利 · 倍投10-20-40", "dims": "pos15", "bet": "martingale"},
    {"key": "C", "name": "稳定核心2维 · 倍投10-20-40", "dims": "core", "bet": "martingale"},
    {"key": "D", "name": "全维度 · 单次买", "dims": "all", "bet": "single"},
]

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
    # 迁移：strategy_scheme_record 补 seg_evs_json 列（4 段 EV 明细）
    sscols = [r[1] for r in db.execute("PRAGMA table_info(strategy_scheme_record)").fetchall()]
    if sscols and "seg_evs_json" not in sscols:
        db.execute("ALTER TABLE strategy_scheme_record ADD COLUMN seg_evs_json TEXT")
    # 迁移：zodiac_track_position 补 source_id 列（关联源头事件）
    zpos_cols = [r[1] for r in db.execute("PRAGMA table_info(zodiac_track_position)").fetchall()]
    if zpos_cols and "source_id" not in zpos_cols:
        db.execute("ALTER TABLE zodiac_track_position ADD COLUMN source_id INTEGER DEFAULT 0")
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

    # 生肖周期配置：辛丑牛年(2021) / 壬寅虎年(2022) / 癸卯兔年(2023) / 甲辰龙年(2024) / 乙巳蛇年(2025) / 丙午马年(2026)
    ox_map = _build_zodiac_mapping(_ZODIAC_SEQ[5:] + _ZODIAC_SEQ[:5])      # 牛年：1号=牛
    tiger_map = _build_zodiac_mapping(_ZODIAC_SEQ[4:] + _ZODIAC_SEQ[:4])   # 虎年：1号=虎
    rabbit_map = _build_zodiac_mapping(_ZODIAC_SEQ[3:] + _ZODIAC_SEQ[:3])  # 兔年：1号=兔
    dragon_map = _build_zodiac_mapping(_ZODIAC_SEQ[2:] + _ZODIAC_SEQ[:2])  # 龙年：1号=龙
    snake_map = _build_zodiac_mapping(_ZODIAC_SEQ[1:] + _ZODIAC_SEQ[:1])   # 蛇年：1号=蛇
    db.execute("INSERT OR IGNORE INTO zodiac_number_cycle_config (cycle_name, start_date, zodiac_mapping, is_enable, create_time) VALUES (?,?,?,?,?)",
               ("辛丑牛年", "2021-02-12", json.dumps(ox_map, ensure_ascii=False), 1, now))
    db.execute("INSERT OR IGNORE INTO zodiac_number_cycle_config (cycle_name, start_date, zodiac_mapping, is_enable, create_time) VALUES (?,?,?,?,?)",
               ("壬寅虎年", "2022-02-01", json.dumps(tiger_map, ensure_ascii=False), 1, now))
    db.execute("INSERT OR IGNORE INTO zodiac_number_cycle_config (cycle_name, start_date, zodiac_mapping, is_enable, create_time) VALUES (?,?,?,?,?)",
               ("癸卯兔年", "2023-01-22", json.dumps(rabbit_map, ensure_ascii=False), 1, now))
    db.execute("INSERT OR IGNORE INTO zodiac_number_cycle_config (cycle_name, start_date, zodiac_mapping, is_enable, create_time) VALUES (?,?,?,?,?)",
               ("甲辰龙年", "2024-02-10", json.dumps(dragon_map, ensure_ascii=False), 1, now))
    db.execute("INSERT OR IGNORE INTO zodiac_number_cycle_config (cycle_name, start_date, zodiac_mapping, is_enable, create_time) VALUES (?,?,?,?,?)",
               ("乙巳蛇年", "2025-01-29", json.dumps(snake_map, ensure_ascii=False), 1, now))
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


def _get_config_json(key, default):
    """通用 JSON 配置读取（sys_config）。"""
    db = get_db()
    row = db.execute("SELECT config_value FROM sys_config WHERE config_key=?", (key,)).fetchone()
    db.close()
    try:
        return json.loads(row["config_value"]) if row else default
    except Exception:
        return default


def _set_config(key, value, remark=""):
    """通用配置写入（sys_config，JSON 自动序列化，UPSERT 保持 id 稳定）。"""
    db = get_db()
    if isinstance(value, (list, dict)):
        value = json.dumps(value, ensure_ascii=False)
    val = str(value)
    db.execute("UPDATE sys_config SET config_value=?, remark=? WHERE config_key=?", (val, remark, key))
    if db.execute("SELECT changes()").fetchone()[0] == 0:
        db.execute("INSERT INTO sys_config (config_key, config_value, remark) VALUES (?,?,?)",
                   (key, val, remark))
    db.commit()
    db.close()


def _get_high_track_core():
    """稳定核心池维度（配置化：sys_config high_track_core，默认常量 HIGH_TRACK_CORE）。"""
    return _get_config_json("high_track_core", HIGH_TRACK_CORE)


def _set_high_track_core(dims):
    """写入核心池维度（去重、过滤非法维度、保持顺序）。"""
    dims = [d for d in dims if d in DIM_NAMES]
    _set_config("high_track_core", dims, "稳定核心池维度（方案C）")
    return dims


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
        # 一键匹配：recordIdList 为空时匹配所有待匹配(status=0)+失败(status=2)记录
        # 失败记录纳入重试范围，解决「补周期后旧数据仍卡在失败态」的问题（2026-09 蛇年周期补齐后）
        db = get_db()
        rows = db.execute("SELECT id FROM number_knowledge_record WHERE status IN (0,2) ORDER BY id").fetchall()
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
    cycle_maps = _load_cycle_maps(db)
    rows = db.execute(
        "SELECT * FROM number_knowledge_record WHERE status=1 AND record_date < ? ORDER BY record_date, id",
        (end_date,)).fetchall()
    last_seen = {}
    for idx, r in enumerate(rows):
        labels = match_labels(r["source_number"], _map_for(r, cycle_maps))
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
    cycle_maps = _load_cycle_maps(db)
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
        labels = match_labels(r["source_number"], _map_for(r, cycle_maps))
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
            labels = match_labels(n, _map_for(r, cycle_maps))
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
        labels = match_labels(open_num, _map_for(r, cycle_maps))
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
    cycle_maps = _load_cycle_maps(db)
    rows = db.execute(
        "SELECT * FROM number_knowledge_record WHERE status=1 ORDER BY record_date, id").fetchall()
    db.close()
    latest_map = _map_for(rows[-1], cycle_maps) if rows else DEFAULT_ZODIAC  # 下一期选号用当前周期

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
        labels = match_labels(r["source_number"], _map_for(r, cycle_maps))
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
            labels = match_labels(n, _map_for(r, cycle_maps))
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

        labels = match_labels(open_num, _map_for(r, cycle_maps))
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
        labels = match_labels(n, latest_map)
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
    cycle_maps = _load_cycle_maps(db)
    rows = db.execute(
        "SELECT * FROM number_knowledge_record WHERE status=1 ORDER BY record_date, id").fetchall()
    db.close()
    latest_map = _map_for(rows[-1], cycle_maps) if rows else DEFAULT_ZODIAC  # 当前信号号码用当前周期

    last_seen = {}; hist_max = {}; sample = {}
    for i, r in enumerate(rows):
        seq = i + 1
        for dim, tag in match_labels(r["source_number"], _map_for(r, cycle_maps)).items():
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
        if dim == "zodiac":
            return [n for n in range(1, 50) if _num_to_zodiac(n, latest_map) == tag]
        k = (dim, tag)
        if k not in tn_cache:
            tn_cache[k] = [n for n in range(1, 50) if match_labels(n, DEFAULT_ZODIAC).get(dim) == tag]
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
    cycle_maps = _load_cycle_maps(db)
    rows = db.execute(
        "SELECT * FROM number_knowledge_record WHERE status=1 ORDER BY record_date, id").fetchall()
    db.close()
    latest_map = _map_for(rows[-1], cycle_maps) if rows else DEFAULT_ZODIAC  # 当前信号号码用当前周期

    dimset = set(dims)

    def tag_nums(dim, tag):
        if dim == "zodiac":
            return [n for n in range(1, 50) if _num_to_zodiac(n, latest_map) == tag]
        return [n for n in range(1, 50) if match_labels(n, DEFAULT_ZODIAC).get(dim) == tag]

    last_seen = {}; sample = {}; gap_hist = {}
    for i, r in enumerate(rows):
        seq = i + 1
        for dim, tag in match_labels(r["source_number"], _map_for(r, cycle_maps)).items():
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
    cycle_maps = _load_cycle_maps(db)
    rows = db.execute(
        "SELECT * FROM number_knowledge_record WHERE status=1 ORDER BY record_date, id").fetchall()
    db.close()

    dimset = set(dims)
    tn_cache = {}
    def tag_nums(dim, tag, zm):
        if dim == "zodiac":
            return [n for n in range(1, 50) if _num_to_zodiac(n, zm) == tag]
        k = (dim, tag)
        if k not in tn_cache:
            tn_cache[k] = [n for n in range(1, 50) if match_labels(n, DEFAULT_ZODIAC).get(dim) == tag]
        return tn_cache[k]

    last_seen = {}; sample = {}; gap_hist = {}
    records = []
    cumulative_single = 0.0
    cumulative_multi = 0.0
    for i, r in enumerate(rows):
        seq = i + 1
        zm = _map_for(r, cycle_maps)
        open_num = int(r["source_number"])
        open_labels = match_labels(open_num, zm)
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
                    events_now.append((dim, tag, len(tag_nums(dim, tag, zm))))
        # 2. 结算 + 逐条记录（单次买 + 连续买两种模式）
        for dim, tag, N in events_now:
            # 单次买：每号 SINGLE_BET 元，下一期买入（唯一买入点），单期结算
            hit = False
            if i + 1 < len(rows):
                hit = match_labels(rows[i + 1]["source_number"], _map_for(rows[i + 1], cycle_maps)).get(dim) == tag
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
                is_hit = match_labels(rows[j]["source_number"], _map_for(rows[j], cycle_maps)).get(dim) == tag
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
                "picks": tag_nums(dim, tag, zm), "N": N,
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
    # 按周期加载生肖映射：历史遍历用各记录 cycle_id 映射；当前信号号码用最新周期映射（2026-09 修复）
    cycle_maps = {}
    for c in db.execute("SELECT id, zodiac_mapping FROM zodiac_number_cycle_config WHERE is_enable=1").fetchall():
        try:
            m = json.loads(c["zodiac_mapping"])
            cycle_maps[c["id"]] = m if m else DEFAULT_ZODIAC
        except Exception:
            cycle_maps[c["id"]] = DEFAULT_ZODIAC
    rows = db.execute(
        "SELECT * FROM number_knowledge_record WHERE status=1 ORDER BY record_date, id").fetchall()
    db.close()

    def map_for(rec):
        return cycle_maps.get(rec["cycle_id"], DEFAULT_ZODIAC)
    latest_map = map_for(rows[-1]) if rows else DEFAULT_ZODIAC  # 当前周期映射（生成当前信号号码用）

    last_seen = {}; sample = {}; last_gap = {}; gap_hist = {}
    for i, r in enumerate(rows):
        seq = i + 1
        for dim, tag in match_labels(r["source_number"], map_for(r)).items():
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
        if dim == "zodiac":
            # 生肖维度：当前信号号码用最新周期映射
            return [n for n in range(1, 50) if _num_to_zodiac(n, latest_map) == tag]
        k = (dim, tag)
        if k not in tn_cache:
            tn_cache[k] = [n for n in range(1, 50) if match_labels(n, DEFAULT_ZODIAC).get(dim) == tag]
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
    原则：① 安全垫永不投入；② 只投正期望(ev_per>0)的信号（对齐维度考核 per_event>0 口径，
    固定命中率红线 hit_floor 已废弃——不同N盈亏平衡命中率不同，正期望已综合N与命中率）；
    ③ 进取仓位按本金比例；④ 单号金额动态摊薄。"""
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
        if ev_per <= 0:
            continue  # 负期望信号不投（正期望是硬门槛，避免劣质维度冒头）
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
        if pending:
            risk_note = f'{bet_date} 有 {len(pending)} 个待买入信号，但均为负期望或近3月非全正，建议观望'
        else:
            risk_note = f'{bet_date} 无待买入信号，建议观望'
        risk = 'gray'
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


def _compute_high_track(window=60, offset=0, dims=None, bet_mode="martingale"):
    """高位跟踪回测：标签遗漏 gap ≥ 近window期hist_max − offset（高位）→ 买入该标签号码。
    bet_mode: martingale=倍投10-20-40三期(命中即停) / single=单次买一期(10元/号)。"""
    db = get_db()
    # 按周期加载生肖映射：每条记录用其 cycle_id 对应映射，避免跨年错位（2026-09 修复高位跟踪生肖维度）
    cycle_maps = {}
    for c in db.execute("SELECT id, zodiac_mapping FROM zodiac_number_cycle_config WHERE is_enable=1").fetchall():
        try:
            m = json.loads(c["zodiac_mapping"])
            cycle_maps[c["id"]] = m if m else DEFAULT_ZODIAC
        except Exception:
            cycle_maps[c["id"]] = DEFAULT_ZODIAC
    rows = db.execute("SELECT * FROM number_knowledge_record WHERE status=1 ORDER BY record_date, id").fetchall()
    db.close()

    def map_for(rec):
        return cycle_maps.get(rec["cycle_id"], DEFAULT_ZODIAC)

    dimset = set(dims) if dims else set(DIM_NAMES.keys())
    tn_cache = {}
    def tag_nums(dim, tag, zm):
        if dim == "zodiac":
            # 生肖维度：号码覆盖随周期变化，按当期映射计算
            return [n for n in range(1, 50) if _num_to_zodiac(n, zm) == tag]
        k = (dim, tag)
        if k not in tn_cache:
            tn_cache[k] = [n for n in range(1, 50) if match_labels(n, DEFAULT_ZODIAC).get(dim) == tag]
        return tn_cache[k]

    last_seen = {}; sample = {}; gap_hist = {}
    dim_stats = {}; tag_stats = {}; monthly = {}
    total_profit = 0.0; events = 0; hits = 0
    period_hit = {1: 0, 2: 0, 3: 0}; period_miss = 0

    for i, r in enumerate(rows):
        seq = i + 1
        d = r["record_date"]
        zm = map_for(r)
        open_labels = match_labels(r["source_number"], zm)
        # 1. 检测高位触发（基于当前期之前的遗漏状态）
        for k, ls in list(last_seen.items()):
            dim, tag = k
            if dim not in dimset:
                continue
            if sample.get(k, 0) < 2:
                continue
            gap = seq - ls
            hm = _window_hist_max(gap_hist, k, seq, window)
            if gap >= hm - offset:
                N = len(tag_nums(dim, tag, zm))
                profit = None; hit_period = None; invested = 0
                if bet_mode == "single":
                    jj = i + 1
                    if jj < len(rows):
                        h = match_labels(rows[jj]["source_number"], map_for(rows[jj])).get(dim) == tag
                        profit = HIGH_TRACK_BETS[0] * (STRATEGY_ODDS - N) if h else -HIGH_TRACK_BETS[0] * N
                        hit_period = 1 if h else None
                    else:
                        profit = 0.0
                else:
                    for pi in range(3):
                        jj = i + 1 + pi
                        if jj >= len(rows):
                            break
                        bet = HIGH_TRACK_BETS[pi]
                        invested += bet * N
                        if match_labels(rows[jj]["source_number"], map_for(rows[jj])).get(dim) == tag:
                            profit = bet * STRATEGY_ODDS - invested
                            hit_period = pi + 1
                            break
                    if profit is None:
                        profit = -invested if invested else -sum(HIGH_TRACK_BETS) * N
                total_profit += profit; events += 1
                if hit_period:
                    hits += 1; period_hit[hit_period] += 1
                else:
                    period_miss += 1
                ds = dim_stats.setdefault(dim, {"dim": dim, "dim_name": DIM_NAMES.get(dim, dim), "ev": 0, "hit": 0, "profit": 0.0})
                ds["ev"] += 1; ds["hit"] += (1 if hit_period else 0); ds["profit"] += profit
                ts = tag_stats.setdefault(f"{dim}:{tag}", {"dim": dim, "dim_name": DIM_NAMES.get(dim, dim), "tag": tag, "N": N, "ev": 0, "hit": 0, "profit": 0.0})
                ts["ev"] += 1; ts["hit"] += (1 if hit_period else 0); ts["profit"] += profit
                mo = monthly.setdefault(d[:7], {"month": d[:7], "ev": 0, "hit": 0, "profit": 0.0})
                mo["ev"] += 1; mo["hit"] += (1 if hit_period else 0); mo["profit"] += profit
        # 2. 更新状态
        for dim, tag in open_labels.items():
            if not tag or dim not in dimset:
                continue
            k = (dim, tag)
            if k in last_seen:
                gap = seq - last_seen[k]
                gap_hist.setdefault(k, []).append((seq, gap))
                sample[k] = sample.get(k, 0) + 1
            else:
                sample[k] = 1
            last_seen[k] = seq

    return {
        "events": events, "hits": hits,
        "hit_rate": round(hits / events, 4) if events else 0.0,
        "period_hit": period_hit, "period_miss": period_miss,
        "total_profit": round(total_profit, 2),
        "dim_stats": dim_stats, "tag_stats": tag_stats, "monthly": monthly,
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


@app.get("/api/highTrack/backtest")
def high_track_backtest(window: int = 60, offset: int = 0, user=Header(None, alias="authorization")):
    """高位跟踪回测：四套方案 × 逐月 + 维度级 + 标签级 + 当前高位信号。"""
    require_user(user)
    out = {"window": window, "offset": offset, "schemes": [], "current_signals": []}
    for scheme in HIGH_TRACK_SCHEMES:
        dims = None
        if scheme["dims"] == "pos15":
            dims = HIGH_TRACK_POS15
        elif scheme["dims"] == "core":
            dims = _get_high_track_core()
        r = _compute_high_track(window, offset, dims, scheme["bet"])
        dim_list = sorted(r["dim_stats"].values(), key=lambda x: -x["profit"])
        for x in dim_list:
            x["profit"] = round(x["profit"], 2)
        tag_list = sorted(r["tag_stats"].values(), key=lambda x: -x["profit"])
        for x in tag_list:
            x["profit"] = round(x["profit"], 2)
        monthly_list = [r["monthly"][m] for m in sorted(r["monthly"])]
        for x in monthly_list:
            x["profit"] = round(x["profit"], 2)
        out["schemes"].append({
            "key": scheme["key"], "name": scheme["name"], "bet": scheme["bet"],
            "dims_count": len(dims) if dims is not None else len(DIM_NAMES),
            "total_profit": r["total_profit"], "events": r["events"], "hits": r["hits"],
            "hit_rate": r["hit_rate"], "period_hit": r["period_hit"], "period_miss": r["period_miss"],
            "dim_stats": dim_list, "tag_stats": tag_list, "monthly": monthly_list,
        })
    # 优秀方案上移：按累计盈亏降序（盈利方案置顶，亏损方案沉底），前端用 key 索引不受顺序影响
    out["schemes"].sort(key=lambda x: -x["total_profit"])
    sig = _compute_current_signals(offset, window)
    out["current_signals"] = sig.get("warning", [])
    # 稳定核心池（方案C）专属下单信号：仅琴棋书画/阴阳，憋到高位即买（与高位跟踪回测同口径）
    out["core_signals"] = [s for s in sig.get("warning", []) if s["dim"] in _get_high_track_core()]
    return out


def _compute_dim_assess(window=60, offset=0):
    """维度考核·第1关初筛：对每个维度单独跑倍投回测，按准入线分档（核心池/观察池/排除）。
    第2关前向验证、第3关滚动复考依赖样本外数据积累，此处返回 recent_neg_months 供复考参考。"""
    order_tier = {"core": 0, "watch": 1, "reject": 2}
    core_dims = _get_high_track_core()  # 提循环外，避免 19 次重复读 DB
    rows = []
    for dim in ALL_DIMS:
        r = _compute_high_track(window, offset, [dim], "martingale")
        ev = r["events"]
        per = r["total_profit"] / ev if ev else 0.0
        monthly = [x["profit"] for m, x in sorted(r["monthly"].items())]
        recent_neg = sum(1 for p in monthly[-3:] if p < 0)  # 近3月负月数（复考参考）
        in_core = dim in core_dims
        # 准入核心 = 正期望（每事件盈利>0）+ 样本足够。
        # 不再用固定命中率红线（0.60）：不同标签覆盖数N的盈亏平衡命中率不同——
        # 头数N=10命中率56%仍盈利（原被误杀），大小N=25命中率85%却亏（原被放过）。per_event 已综合N/命中率/倍投节奏。
        passed = (not in_core) and ev >= DIM_ASSESS_MIN_EV and per > DIM_ASSESS_MIN_PER
        tier = "core" if in_core else ("watch" if passed else "reject")
        ph = r.get("period_hit", {})
        # 尾部风险：三连miss数 + 最坏单次亏损（=倍投三期总额×该维度最大标签覆盖数）
        max_n = max((t["N"] for t in r.get("tag_stats", {}).values()), default=0)
        worst_loss = -sum(HIGH_TRACK_BETS) * max_n
        rows.append({
            "dim": dim, "dim_name": DIM_NAMES.get(dim, dim),
            "events": ev, "hit_rate": round(r["hit_rate"], 4),
            "profit": round(r["total_profit"], 2), "per_event": round(per, 2),
            "period_hit": {"p1": ph.get(1, 0), "p2": ph.get(2, 0), "p3": ph.get(3, 0)},
            "period_miss": r.get("period_miss", 0),
            "worst_loss": worst_loss,
            "monthly": [round(p, 2) for p in monthly],
            "recent_neg_months": recent_neg, "tier": tier,
        })
    # 统一按每事件期望值排名（tier 仅作标注，不再分组排序）
    rows.sort(key=lambda x: -x["per_event"])
    for i, x in enumerate(rows):
        x["rank"] = i + 1
    return {
        "rules": {"min_events": DIM_ASSESS_MIN_EV, "min_per_event": DIM_ASSESS_MIN_PER,
                  "min_hit_rate_deprecated": DIM_ASSESS_MIN_HIT,
                  "note": "准入以每事件期望利润>0为核心；固定命中率红线已废弃（不同N盈亏平衡命中率不同）"},
        "dims": rows,
        "core": [x for x in rows if x["tier"] == "core"],
        "watch": [x for x in rows if x["tier"] == "watch"],
        "reject": [x for x in rows if x["tier"] == "reject"],
    }


@app.get("/api/highTrack/dimAssess")
def high_track_dim_assess(window: int = 60, offset: int = 0, user=Header(None, alias="authorization")):
    """维度考核面板：三关准入初筛分档（核心池/观察池/排除）。"""
    require_user(user)
    return _compute_dim_assess(window, offset)


def _compute_dim_forward_next(dim, offset=0, window=60):
    """单维度前向验证选号：该维度当前「憋到高位」标签（warning）号码并集，下一期买入（单次买口径）。
    与方案C回测同触发口径（gap >= 近window期hist_max - offset），仅把倍投3期简化为单次买1期，便于前向结算命中率。"""
    from datetime import timedelta
    sig = _compute_current_signals(offset, window)
    db = get_db()
    last_date = db.execute(
        "SELECT MAX(record_date) d FROM number_knowledge_record WHERE status=1").fetchone()["d"]
    db.close()
    picks = set()
    detail = []
    for s in sig.get("warning", []):
        if s["dim"] != dim:
            continue
        picks.update(s["picks"])
        detail.append({"tag": s["tag"], "N": s["N"], "gap": s["gap"]})
    picks = sorted(picks)
    next_date = ""
    if last_date:
        next_date = (datetime.strptime(last_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    return {"date": next_date, "picks": picks, "N": len(picks), "detail": detail}


def _compute_dim_forward_status():
    """观察池各维度前向验证状态：已结算期数、前向命中率、随机基准(N/49)、超额命中(alpha)、达标判定。
    达标 = 期数≥阈值 且 超额命中 ≥ 及格线（命中率须显著高于随机基准，过滤纯随机维度）。"""
    db = get_db()
    rows = db.execute(
        "SELECT algo_key, N, hit FROM algo_forward_track WHERE algo_key LIKE 'dim_fwd_%' ORDER BY id").fetchall()
    db.close()
    by_dim = {}
    for r in rows:
        dim = r["algo_key"].replace("dim_fwd_", "")
        by_dim.setdefault(dim, []).append(r)
    result = []
    for dim in DIM_ASSESS_WATCH:
        recs = by_dim.get(dim, [])
        settled = [r for r in recs if r["hit"] is not None]
        # 滚动窗口：只统计最近 min_periods 期已结算记录（新增一期自动剔除最老一期，窗口恒定不累计）
        recent = settled[-DIM_ASSESS_FWD_MIN_PERIODS:]
        periods = len(recent)
        hits = sum(1 for r in recent if r["hit"] == 1)
        sum_n = sum((r["N"] or 0) for r in recent)
        hit_rate = round(hits / periods, 4) if periods else None
        avg_n = round(sum_n / periods, 2) if periods else 0.0
        rand_base = round(avg_n / 49, 4) if avg_n else None  # 随机基准 = 平均N/49
        alpha = round(hit_rate - rand_base, 4) if (hit_rate is not None and rand_base is not None) else None
        passed = (periods >= DIM_ASSESS_FWD_MIN_PERIODS and alpha is not None
                  and alpha >= DIM_ASSESS_FWD_MIN_ALPHA)
        result.append({
            "dim": dim, "dim_name": DIM_NAMES.get(dim, dim),
            "periods": periods, "hits": hits,
            "hit_rate": hit_rate, "avg_n": avg_n, "rand_base": rand_base, "alpha": alpha,
            "passed": passed,
            "min_periods": DIM_ASSESS_FWD_MIN_PERIODS, "min_alpha": DIM_ASSESS_FWD_MIN_ALPHA,
        })
    result.sort(key=lambda x: -(x["alpha"] if x["alpha"] is not None else -999))
    return {"watch": result,
            "rules": {"min_periods": DIM_ASSESS_FWD_MIN_PERIODS, "min_alpha": DIM_ASSESS_FWD_MIN_ALPHA}}


@app.get("/api/dimAssess/forward")
def dim_assess_forward(user=Header(None, alias="authorization")):
    """维度考核·第2关前向验证状态。"""
    require_user(user)
    return _compute_dim_forward_status()


@app.post("/api/dimAssess/promote")
def dim_assess_promote(body: dict, user=Header(None, alias="authorization")):
    """转正：观察池前向达标维度加入核心池（写入 sys_config，方案C下单自动生效）。"""
    require_user(user)
    dim = body.get("dim", "")
    if dim not in DIM_NAMES:
        raise HTTPException(400, "非法维度: " + dim)
    core = _get_high_track_core()
    if dim in core:
        return {"ok": True, "core": core, "note": "已在核心池"}
    st = _compute_dim_forward_status()
    fwd = next((w for w in st["watch"] if w["dim"] == dim), None)
    if not fwd or not fwd.get("passed"):
        raise HTTPException(400, f"「{DIM_NAMES[dim]}」前向验证未达标（需≥{DIM_ASSESS_FWD_MIN_PERIODS}期且超额命中≥{DIM_ASSESS_FWD_MIN_ALPHA:.0%}），不能转正")
    core = _set_high_track_core(core + [dim])
    return {"ok": True, "core": core, "note": f"「{DIM_NAMES[dim]}」已转正入核心池"}


@app.post("/api/dimAssess/demote")
def dim_assess_demote(body: dict, user=Header(None, alias="authorization")):
    """降级：核心池维度移除（写入 sys_config，方案C下单自动生效）。"""
    require_user(user)
    dim = body.get("dim", "")
    core = _get_high_track_core()
    if dim not in core:
        return {"ok": True, "core": core, "note": "不在核心池"}
    core = _set_high_track_core([d for d in core if d != dim])
    return {"ok": True, "core": core, "note": f"「{DIM_NAMES[dim]}」已移出核心池"}


# ============================================================
# 维度考核·真实前向验证引擎（2026-09-08 新增）
# 全 19 维度逐一样本外跟踪：每日固化选号→开奖结算→二项检验+FDR 论证
# ============================================================
def _dim_forward_binomial_sf(k, n, p):
    """精确二项上尾概率 P(X ≥ k)，X ~ Binomial(n, p)。用 log-gamma 避免溢出。"""
    import math
    if n <= 0:
        return 1.0
    if k <= 0:
        return 1.0
    if k > n:
        return 0.0
    if p <= 0:
        return 0.0
    if p >= 1:
        return 1.0 if k <= n else 0.0
    q = 1 - p
    log_p, log_q = math.log(p), math.log(q)
    total = 0.0
    for i in range(k, n + 1):
        log_term = math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1) \
                   + i * log_p + (n - i) * log_q
        total += math.exp(log_term)
    return min(total, 1.0)


def _dim_forward_bh_fdr(p_values, alpha=0.05):
    """Benjamini-Hochberg FDR 校正：返回每个 p 值是否拒绝 H0（显著）。"""
    m = len(p_values)
    if m == 0:
        return []
    order = sorted(range(m), key=lambda i: p_values[i])
    reject = [False] * m
    cutoff = None
    for rank, idx in enumerate(order, start=1):
        if p_values[idx] <= rank / m * alpha:
            cutoff = p_values[idx]
    if cutoff is not None:
        for i in range(m):
            if p_values[i] <= cutoff:
                reject[i] = True
    return reject


def _settle_dim_forward():
    """结算 dim_forward_track 中 pending（open_number IS NULL）且 bet_date <= 最新数据日的记录。"""
    db = get_db()
    last_row = db.execute(
        "SELECT MAX(record_date) d FROM number_knowledge_record WHERE status=1").fetchone()
    last_date = last_row["d"] if last_row else None
    if not last_date:
        db.close()
        return 0
    pending = db.execute(
        "SELECT id, bet_date, picks_json FROM dim_forward_track WHERE open_number IS NULL AND bet_date <= ?",
        (last_date,)).fetchall()
    settled = 0
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
    db.close()
    return settled


def _generate_dim_forward(offset=0, window=60):
    """为可跟踪 9 维度生成下一期选号并固化（低频 11 维不参与前向验证，见 LOW_FREQ_DIMS）。铁律：只用 bet_date 之前的数据。"""
    from datetime import timedelta
    db = get_db()
    last_row = db.execute(
        "SELECT MAX(record_date) d FROM number_knowledge_record WHERE status=1").fetchone()
    db.close()
    if not last_row or not last_row["d"]:
        return {"generated": 0, "date": ""}
    last_date = last_row["d"]
    next_date = (datetime.strptime(last_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    generated = 0
    for dim in TRACKABLE_DIMS:
        nxt = _compute_dim_forward_next(dim, offset=offset, window=window)
        if nxt.get("date") and nxt.get("N", 0) > 0:
            db = get_db()
            db.execute(
                "INSERT OR IGNORE INTO dim_forward_track (dim_key, bet_date, picks_json, N, open_number, hit, is_live, create_time) VALUES (?,?,?,?,NULL,NULL,1,?)",
                (dim, nxt["date"], json.dumps(nxt.get("picks", [])), nxt.get("N", 0), now))
            db.commit()
            db.close()
            generated += 1
    return {"generated": generated, "date": next_date}


def _compute_consensus_next():
    """共识信号「春夏秋冬+红肖蓝肖绿肖 4变体≥2票」下一期选号（与 consensus API 口径一致）。"""
    dims = ["season_type", "zodiac_color_type"]
    variants = [(+2, 90), (+1, 60), (+2, 60), (+1, 90)]
    votes = {}
    bet_date = ""
    for off, w in variants:
        order = _compute_current_picks(dims, off, w, "union")
        bet_date = bet_date or order.get("date", "")
        for n in order.get("picks", []):
            votes[n] = votes.get(n, 0) + 1
    picks = sorted(n for n, c in votes.items() if c >= 2)
    return {"date": bet_date, "picks": picks, "N": len(picks)}


def _generate_consensus_forward():
    """固化共识信号下一期选号到 dim_forward_track（dim_key='consensus'）。

    无论触发(N>0)还是空仓(N=0)都固化：空仓期也是有效决策，记录后让真实前向
    periods 反映「策略真实运行期数」而非「仅触发期数」。结算由 _settle_dim_forward 统一处理。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    nxt = _compute_consensus_next()
    if nxt.get("date"):
        db = get_db()
        db.execute(
            "INSERT OR IGNORE INTO dim_forward_track (dim_key, bet_date, picks_json, N, open_number, hit, is_live, create_time) VALUES (?,?,?,?,NULL,NULL,1,?)",
            ("consensus", nxt["date"], json.dumps(nxt.get("picks", [])), nxt.get("N", 0), now))
        db.commit()
        db.close()
        return {"generated": 1, "date": nxt["date"], "N": nxt.get("N", 0),
                "empty": nxt.get("N", 0) == 0}
    return {"generated": 0, "date": nxt.get("date", ""), "N": nxt.get("N", 0)}


def _consensus_forward_stats():
    """共识信号真实前向表现：从 dim_forward_track 聚合 dim_key='consensus' 的已结算记录。

    区分「总运行期(含空仓)」与「触发期(N>0)」：命中率/超额/二项检验只在触发期算，
    空仓期不计入（空仓是择时决策，不参与选号质量评估）。"""
    db = get_db()
    rows = db.execute(
        "SELECT N, hit FROM dim_forward_track WHERE dim_key='consensus' AND hit IS NOT NULL").fetchall()
    db.close()
    periods = len(rows)  # 总运行期（含空仓）
    triggered = [r for r in rows if (r["N"] or 0) > 0]  # 触发期
    n_triggered = len(triggered)
    empty = periods - n_triggered
    hits = sum(1 for r in triggered if r["hit"] == 1)
    sum_n = sum(r["N"] or 0 for r in triggered)
    avg_n = round(sum_n / n_triggered, 2) if n_triggered else 0.0
    hit_rate = round(hits / n_triggered, 4) if n_triggered else None
    rand_base = round(avg_n / 49, 4) if avg_n else None
    alpha = round(hit_rate - rand_base, 4) if (hit_rate is not None and rand_base is not None) else None
    p = None
    if n_triggered >= 10 and rand_base:
        p = round(_dim_forward_binomial_sf(hits, n_triggered, rand_base), 6)
    return {
        "periods": periods, "triggered": n_triggered, "empty": empty,
        "hits": hits, "avg_n": avg_n,
        "hit_rate": hit_rate, "rand_base": rand_base,
        "alpha": alpha, "p_value": p,
    }


def _compute_dim_forward_report():
    """前向验证报告：全 19 维度前向命中率 + 超额 + 二项检验 p 值 + FDR 校正 + 结论。"""
    db = get_db()
    rows = db.execute("SELECT dim_key, N, hit FROM dim_forward_track WHERE hit IS NOT NULL").fetchall()
    db.close()
    by_dim = {}
    for r in rows:
        d = by_dim.setdefault(r["dim_key"], {"periods": 0, "hits": 0, "sum_n": 0})
        d["periods"] += 1
        d["sum_n"] += (r["N"] or 0)
        if r["hit"] == 1:
            d["hits"] += 1
    result = []
    p_vals = []
    for dim in ALL_DIMS:
        d = by_dim.get(dim, {"periods": 0, "hits": 0, "sum_n": 0})
        periods = d["periods"]
        hits = d["hits"]
        avg_n = round(d["sum_n"] / periods, 2) if periods else 0.0
        hit_rate = round(hits / periods, 4) if periods else None
        rand_base = round(avg_n / 49, 4) if avg_n else None
        alpha = round(hit_rate - rand_base, 4) if (hit_rate is not None and rand_base is not None) else None
        p_val = None
        if periods >= 30 and rand_base:
            p_val = round(_dim_forward_binomial_sf(hits, periods, rand_base), 6)
        p_vals.append(p_val if p_val is not None else 1.0)
        result.append({
            "dim": dim, "dim_name": DIM_NAMES.get(dim, dim),
            "periods": periods, "hits": hits,
            "hit_rate": hit_rate, "avg_n": avg_n, "rand_base": rand_base,
            "alpha": alpha, "p_value": p_val,
        })
    rejects = _dim_forward_bh_fdr(p_vals, 0.05)
    for i, x in enumerate(result):
        if x["dim"] in LOW_FREQ_DIMS:
            x["significant"] = False
            x["verdict"] = "低频观察(前向验证不可行)"
            continue
        x["significant"] = bool(rejects[i]) if x["periods"] >= 30 else False
        if x["periods"] < 30:
            x["verdict"] = "观察中(样本不足)"
        elif x["significant"] and (x["alpha"] or 0) > 0:
            x["verdict"] = "显著·转正候选"
        elif x["periods"] >= 400:
            x["verdict"] = "淘汰(无预测力)"
        else:
            x["verdict"] = "继续观察"
    result.sort(key=lambda x: -(x["alpha"] if x["alpha"] is not None else -999))
    return {
        "rules": {"alpha": 0.05, "fdr": "benjamini-hochberg",
                  "min_periods_signal": 30, "min_periods_verdict": 400,
                  "trackable_dims": TRACKABLE_DIMS, "low_freq_dims": LOW_FREQ_DIMS},
        "dims": result,
    }


@app.get("/api/dimForward/report")
def dim_forward_report(user=Header(None, alias="authorization")):
    """前向验证报告（真实引擎统计论证）。"""
    require_user(user)
    return _compute_dim_forward_report()


@app.post("/api/dimForward/run")
def dim_forward_run(body: dict, user=Header(None, alias="authorization")):
    """手动触发：结算 + 固化（真实引擎每日 cron 调用的核心，测试也可手动跑）。"""
    require_user(user)
    settled = _settle_dim_forward()
    gen = _generate_dim_forward()
    return {"ok": True, "settled": settled, "generated": gen.get("generated", 0),
            "date": gen.get("date", "")}


# ============================================================
# 自主跟踪：方案论证记录库 + AI 寻优（2026-09-10 新增）
# 思路：AI 根据维度子集 × 高位触发 offset 枚举方案空间 → 统一回测（等额每号1元）
#       → 时间分段稳健性判定 → 记录入库（scheme_key 去重，避免重复论证）→ 稳定方案转前向跟踪
# ============================================================
SCHEME_ODDS = 47          # 赔率
SCHEME_OFFSETS = [-2, -1, 0, 1, 2]   # 高位触发 offset 扫描范围
SCHEME_WINDOWS = [60, 90, 120]       # 历史最高遗漏滚动窗口扫描范围（头数深挖发现 window=90/120 更强）


def _scheme_dim_candidates():
    """寻优维度子集候选：20 单维 + TRACKABLE_DIMS 9维的 2 维组合 + 3 维组合 + 5 现有 scheme。

    三维组合：时间分段审计发现二维组合（生肖+头数）比单维（头数）跨时间更稳健，
    三维是自然延伸（高共识号 ge2/ge3 需要 >=3 维才有意义）。"""
    cands = []
    seen = set()
    for d in ALL_DIMS:
        cands.append([d])
    td = list(TRACKABLE_DIMS)
    for i in range(len(td)):
        for j in range(i + 1, len(td)):
            cands.append([td[i], td[j]])
    # 三维组合（C(9,3)=84）
    for i in range(len(td)):
        for j in range(i + 1, len(td)):
            for k in range(j + 1, len(td)):
                cands.append([td[i], td[j], td[k]])
    for _name, dims in STRATEGY_SCHEMES.items():
        cands.append(list(dims))
    out = []
    for c in cands:
        k = ",".join(sorted(c))
        if k not in seen:
            seen.add(k)
            out.append(c)
    return out


def _scheme_key(dims, signal_rule, offset, window=60):
    """去重键：维度集合 + 信号口径 + offset 规范化哈希。仓位/倍投属资金管理参数，不参与去重。"""
    dims_norm = ",".join(sorted(dims))
    raw = f"{dims_norm}|{signal_rule}|{offset}|{window}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def _scheme_name(dims, offset, signal_rule="high_gap", window=60):
    if len(dims) == 1:
        base = DIM_NAMES.get(dims[0], dims[0])
    elif len(dims) >= 18:
        base = f"全维度{len(dims)}"
    elif set(dims) == set(CORE_DIMS):
        base = "核心6维"
    else:
        base = "+".join(DIM_NAMES.get(d, d) for d in dims[:4])
        if len(dims) > 4:
            base += f"等{len(dims)}维"
    name = f"{base}·高位触发(off{offset:+d})"
    # window != 60 时标注，避免 window=60/90/120 同 offset 方案名字重复（60 为默认主力窗口）
    if window and window != 60:
        name += f"·w{window}"
    return name


def _load_backtest_data():
    """加载回测数据 + 预计算每期标签（避免重复 match_labels）。返回 (rows, cycle_maps, seq_labels)。"""
    db = get_db()
    cycle_maps = _load_cycle_maps(db)
    rows = db.execute(
        "SELECT * FROM number_knowledge_record WHERE status=1 ORDER BY record_date, id").fetchall()
    db.close()
    seq_labels = []
    for r in rows:
        zm = _map_for(r, cycle_maps)
        num = int(r["source_number"])
        seq_labels.append((num, match_labels(num, zm), zm))
    return rows, cycle_maps, seq_labels


def _backtest_scheme(dims, offset=0, window=60, odds=SCHEME_ODDS, data=None, pick_rule="union"):
    """统一回测引擎（等额口径：每号1元，赔率47）。无前视偏差：用截至上一期数据选号，当期开奖结算。

    口径与 _compute_strategy_order 一致：标签当前遗漏 gap >= 近 window 期历史最高 - offset（憋到高位）
    → 按 pick_rule 选号（union=憋高位标签号码并集 / geN=只买被≥N个维度同时憋高位覆盖的高共识号）
    → 单期单次买。输出命中率/超额/净收益/时间分段前后半 EV/最大回撤。"""
    if data is None:
        rows, cycle_maps, seq_labels = _load_backtest_data()
    else:
        rows, cycle_maps, seq_labels = data
    if len(rows) < 100:
        return {"error": "数据不足", "periods": len(rows)}
    dimset = set(dims)
    tn_cache = {}

    def tag_nums(dim, tag, zm):
        if dim == "zodiac":
            return [n for n in range(1, 50) if _num_to_zodiac(n, zm) == tag]
        k = (dim, tag)
        if k not in tn_cache:
            tn_cache[k] = [n for n in range(1, 50) if match_labels(n, DEFAULT_ZODIAC).get(dim) == tag]
        return tn_cache[k]

    last_seen = {}; sample = {}; gap_hist = {}
    daily = []  # 每期 {N, hit, profit}
    for i in range(len(rows)):
        seq = i + 1
        open_num, labels, zm = seq_labels[i]
        # 1. 选号（基于截至上一期的 last_seen/gap_hist，无前视）
        vote = {}
        for (dim, tag), ls in last_seen.items():
            gap = seq - ls
            hm = _window_hist_max(gap_hist, (dim, tag), seq, window)
            if sample.get((dim, tag), 0) >= 2 and gap >= hm - offset:
                for n in tag_nums(dim, tag, zm):
                    vote[n] = vote.get(n, 0) + 1
        if pick_rule == "union":
            picks = sorted(vote.keys())
        else:
            try:
                th = int(pick_rule.replace("ge", ""))
            except Exception:
                th = 1
            picks = sorted(n for n, c in vote.items() if c >= th)
        N = len(picks)
        # 2. 结算（当期开奖验证）
        hit = (N > 0) and (open_num in picks)
        profit = (odds - N) if hit else (-N if N > 0 else 0)
        daily.append({"N": N, "hit": hit, "profit": profit})
        # 3. 更新 last_seen（把当前期算进去，仅保留 dimset 内维度）
        for dim, tag in labels.items():
            if not tag or dim not in dimset:
                continue
            k = (dim, tag)
            if k in last_seen:
                gap = seq - last_seen[k]
                sample[k] = sample.get(k, 0) + 1
                gap_hist.setdefault(k, []).append((seq, gap))
            else:
                sample[k] = 1
            last_seen[k] = seq

    periods = len(daily)
    triggered = [x for x in daily if x["N"] > 0]
    t_cnt = len(triggered)
    hits = sum(1 for x in triggered if x["hit"])
    hit_rate = round(hits / t_cnt, 4) if t_cnt else 0.0
    avg_n = round(sum(x["N"] for x in triggered) / t_cnt, 2) if t_cnt else 0.0
    rand_base = round(avg_n / 49, 4) if avg_n else 0.0
    alpha = round(hit_rate - rand_base, 4) if t_cnt else 0.0
    net = round(sum(x["profit"] for x in daily), 2)
    ev = round(net / periods, 4) if periods else 0.0

    mid = periods // 2
    front = daily[:mid]
    back = daily[mid:]

    def seg_ev(seg):
        return round(sum(x["profit"] for x in seg) / len(seg), 4) if seg else 0.0

    def seg_alpha(seg):
        sg = [x for x in seg if x["N"] > 0]
        if not sg:
            return 0.0
        h = sum(1 for x in sg if x["hit"])
        n = sum(x["N"] for x in sg) / len(sg)
        return round(h / len(sg) - n / 49, 4)

    front_ev = seg_ev(front)
    back_ev = seg_ev(back)
    front_alpha = seg_alpha(front)
    back_alpha = seg_alpha(back)

    # 4 段稳健性：4 段中 EV>0 的段数 >= 3 才算稳定（比 2 段更严格，抗单段波动/结构突变）
    q = periods // 4
    segs = [daily[i * q:(i + 1) * q] for i in range(4)]
    if periods % 4:
        segs[-1] = daily[3 * q:]
    seg_evs = [seg_ev(s) for s in segs]
    pos_segs = sum(1 for e in seg_evs if e > 0)

    # 最大回撤（累计净收益曲线）
    cum = 0.0; peak = 0.0; max_dd = 0.0
    for x in daily:
        cum += x["profit"]
        peak = max(peak, cum)
        if peak > 0:
            max_dd = max(max_dd, (peak - cum) / peak * 100)
    stable = 1 if pos_segs >= 3 else 0

    return {
        "periods": periods, "triggered": t_cnt, "hits": hits,
        "hit_rate": hit_rate, "avg_n": avg_n, "rand_base": rand_base, "alpha": alpha,
        "net_profit": net, "ev": ev,
        "front_ev": front_ev, "back_ev": back_ev,
        "front_alpha": front_alpha, "back_alpha": back_alpha,
        "seg_evs": seg_evs, "pos_segs": pos_segs,
        "stable": stable, "max_dd": round(max_dd, 2),
    }


def _register_scheme(dims, offset, signal_rule="high_gap", window=60, source="auto",
                     bt=None, conclusion="", status="backtested"):
    """登记方案到记录库（scheme_key 去重，已存在返回 skipped=True）。"""
    key = _scheme_key(dims, signal_rule, offset, window)
    db = get_db()
    exists = db.execute("SELECT 1 FROM strategy_scheme_record WHERE scheme_key=?", (key,)).fetchone()
    if exists:
        db.close()
        return {"key": key, "exists": True, "skipped": True}
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    name = _scheme_name(dims, offset, signal_rule, window)
    bt = bt or {}
    db.execute(
        "INSERT INTO strategy_scheme_record (scheme_key, scheme_name, dims_json, signal_rule, offset, window, "
        "bet_mode, bt_periods, bt_triggered, bt_hits, bt_hit_rate, bt_avg_n, bt_rand_base, bt_alpha, "
        "bt_net_profit, bt_ev, bt_front_alpha, bt_back_alpha, bt_front_ev, bt_back_ev, bt_stable, bt_max_dd, seg_evs_json, "
        "status, conclusion, source, create_time, update_time) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (key, name, json.dumps(dims, ensure_ascii=False), signal_rule, offset, window,
         "single", bt.get("periods", 0), bt.get("triggered", 0), bt.get("hits", 0),
         bt.get("hit_rate"), bt.get("avg_n"), bt.get("rand_base"), bt.get("alpha"),
         bt.get("net_profit"), bt.get("ev"), bt.get("front_alpha"), bt.get("back_alpha"),
         bt.get("front_ev"), bt.get("back_ev"), bt.get("stable", 0), bt.get("max_dd"),
         json.dumps(bt.get("seg_evs", [])),
         status, conclusion, source, now, now))
    db.commit()
    db.close()
    return {"key": key, "exists": False, "skipped": False}


def _scan_schemes(windows=None, odds=SCHEME_ODDS):
    """AI 寻优：枚举维度子集 × window × offset × 选号规则 → 去重 → 回测 → 二项检验+FDR 校正 → 记录。

    选号规则：union（憋高位标签号码并集，所有维度都扫）+ ge2（只买被≥2维同时憋高位覆盖的高共识号，仅多维度组合扫）。
    两阶段：① 全量回测收集结果 ② 对「4段稳健且触发≥100期」的方案做二项检验 + BH-FDR 校正，弱信号分级。"""
    data = _load_backtest_data()
    cands = _scheme_dim_candidates()
    offsets = SCHEME_OFFSETS
    windows = windows or SCHEME_WINDOWS
    scanned = 0
    skipped = 0
    results = []
    for dims in cands:
        pick_rules = ["union"]
        if len(dims) >= 2:
            pick_rules.append("ge2")
        if len(dims) >= 3:
            pick_rules.append("ge3")
        for w in windows:
            for off in offsets:
                for pr in pick_rules:
                    srule = "high_gap" if pr == "union" else f"high_gap_{pr}"
                    key = _scheme_key(dims, srule, off, w)
                    db = get_db()
                    exists = db.execute("SELECT 1 FROM strategy_scheme_record WHERE scheme_key=?", (key,)).fetchone()
                    db.close()
                    if exists:
                        skipped += 1
                        continue
                    bt = _backtest_scheme(dims, off, w, odds, data, pick_rule=pr)
                    if bt.get("error"):
                        continue
                    scanned += 1
                    results.append({"dims": dims, "offset": off, "window": w, "pick_rule": pr, "bt": bt})

    # 二项检验 + FDR 校正（对象：4段稳健 且 触发期数>=100 的方案——样本少的高 alpha 是波动假象）
    tested = [r for r in results if r["bt"].get("stable") and r["bt"].get("triggered", 0) >= 100]
    # 后半段独立回测（正确的时间稳健性口径：fresh start 无前半热身，最接近真实前向）
    rows_data, cycle_maps_data, seq_labels_data = data
    half2_data = (rows_data[len(rows_data) // 2:], cycle_maps_data, seq_labels_data[len(rows_data) // 2:])
    p_vals = []
    h2_alphas = {}
    for r in tested:
        bt = r["bt"]
        p = _dim_forward_binomial_sf(bt["hits"], bt["triggered"], bt["rand_base"]) if bt.get("rand_base") else 1.0
        p_vals.append(round(p, 6))
        key = _scheme_key(r["dims"], "high_gap" if r["pick_rule"] == "union" else f"high_gap_{r['pick_rule']}",
                          r["offset"], r["window"])
        h2 = _backtest_scheme(r["dims"], r["offset"], r["window"], odds, half2_data, pick_rule=r["pick_rule"])
        h2_alphas[key] = (h2.get("alpha", 0) or 0) if not h2.get("error") else 0.0
    rejects = _dim_forward_bh_fdr(p_vals, 0.05) if p_vals else []
    idx_map = {_scheme_key(r["dims"], "high_gap" if r["pick_rule"] == "union" else f"high_gap_{r['pick_rule']}",
                           r["offset"], r["window"]): i for i, r in enumerate(tested)}

    stable_list = []
    for r in results:
        dims, off, w, pr, bt = r["dims"], r["offset"], r["window"], r["pick_rule"], r["bt"]
        stable = bt.get("stable", 0)
        alpha = bt.get("alpha", 0) or 0
        srule = "high_gap" if pr == "union" else f"high_gap_{pr}"
        key = _scheme_key(dims, srule, off, w)
        ti = idx_map.get(key)
        if ti is not None:
            p = p_vals[ti]
            sig = bool(rejects[ti])
            avg_n = bt.get("avg_n", 0) or 0
            h2_alpha = h2_alphas.get(key, 0.0)
            # 时间分段门槛：后半段独立回测 alpha<=0 的一律淘汰（前半段伪信号，如头数单维单调衰竭）
            if h2_alpha <= 0:
                status = "backtested"
                conclusion = f"后半段独立回测alpha={h2_alpha:.4f}<=0，前半伪信号，淘汰"
            elif sig and alpha > 0 and avg_n < 20:
                status = "forwarding"
                conclusion = f"FDR显著(p={p})，转前向跟踪候选"
                stable_list.append({"name": _scheme_name(dims, off, window=w), "dims": dims,
                                    "offset": off, "window": w, "pick_rule": pr, **bt})
            elif p < 0.1 and alpha > 0 and avg_n < 20:
                # 未校正 p<0.1 但 FDR 校正后不显著：多重比较下的假阳性，不转前向（诚实原则）
                status = "backtested"
                conclusion = f"未校正p={p}<0.1但FDR校正后不显著，多重比较假阳性，淘汰"
            else:
                status = "backtested"
                conclusion = f"4段稳健但未显著或均号过大(p={p})，观察"
        elif stable:
            status = "backtested"
            conclusion = "4段稳健但样本不足100期，观察"
        else:
            status = "backtested"
            conclusion = "4段EV未达≥3正，暂不转前向"
        _register_scheme(dims, off, srule, w, "auto", bt, conclusion, status)

    stable_list.sort(key=lambda x: -(x.get("ev", 0) or 0))
    return {
        "scanned": scanned, "skipped": skipped,
        "total_candidates": len(cands) * len(windows) * len(offsets),
        "stable": stable_list,
        "fdr_tested": len(tested),
        "fdr_significant": sum(1 for x in rejects if x) if rejects else 0,
    }


@app.get("/api/strategyScheme/list")
def strategy_scheme_list(status: str = "", user=Header(None, alias="authorization")):
    """方案论证记录库列表（自主跟踪面板）。含过拟合识别（前向超额 vs 回测 alpha）。"""
    require_user(user)
    db = get_db()
    q = "SELECT * FROM strategy_scheme_record"
    args = []
    if status:
        q += " WHERE status=?"
        args.append(status)
    q += " ORDER BY bt_stable DESC, bt_ev DESC, id"
    rows = db.execute(q, args).fetchall()
    # 前向均号（dim_forward_track scheme: 记录）
    fwd_n = {}; fwd_cnt = {}
    for fr in db.execute(
            "SELECT dim_key, N FROM dim_forward_track WHERE dim_key LIKE 'scheme:%' AND hit IS NOT NULL").fetchall():
        key = fr["dim_key"].replace("scheme:", "")
        fwd_n[key] = fwd_n.get(key, 0) + (fr["N"] or 0)
        fwd_cnt[key] = fwd_cnt.get(key, 0) + 1
    db.close()
    result = []
    for r in rows:
        d = dict(r)
        try:
            d["dims"] = json.loads(r["dims_json"]) if r["dims_json"] else []
        except Exception:
            d["dims"] = []
        try:
            d["seg_evs"] = json.loads(r["seg_evs_json"]) if r["seg_evs_json"] else []
        except Exception:
            d["seg_evs"] = []
        # 过拟合识别：前向超额 vs 回测 alpha
        key = d["scheme_key"]
        cnt = fwd_cnt.get(key, 0)
        d["fwd_avg_n"] = round(fwd_n.get(key, 0) / cnt, 2) if cnt else 0.0
        fp = d["fwd_periods"] or 0
        fh = d["fwd_hits"] or 0
        fwd_alpha = None
        if fp >= 30 and d["fwd_avg_n"]:
            fwd_alpha = round(fh / fp - d["fwd_avg_n"] / 49, 4)
        bt_alpha = d["bt_alpha"] or 0
        d["fwd_alpha"] = fwd_alpha
        if fwd_alpha is not None:
            if fwd_alpha >= bt_alpha * 0.6:
                d["overfit"] = "ok"       # 前向≈回测（或更高）= 真信号
            elif fwd_alpha > 0:
                d["overfit"] = "partial"  # 前向正但明显缩水 = 部分过拟合
            else:
                d["overfit"] = "overfit"  # 前向翻负 = 严重过拟合
        else:
            d["overfit"] = "insufficient"  # 前向样本不足
        result.append(d)
    return {"schemes": result, "count": len(result)}


@app.post("/api/strategyScheme/scan")
def strategy_scheme_scan(body: dict, user=Header(None, alias="authorization")):
    """手动触发 AI 寻优：扫描方案空间 → 去重 → 回测 → 记录。"""
    require_user(user)
    windows = body.get("windows") or SCHEME_WINDOWS
    res = _scan_schemes(windows)
    return {"ok": True, **res}


def _compute_current_picks(dims, offset=0, window=60, pick_rule="union", end_date=None):
    """基于当前全部数据算下一期选号（支持 union/ge2 选号规则）。与 _backtest_scheme 口径一致。

    end_date：可选，指定数据截止日期（含），用于历史回填 walk-forward 重放，不传则用全量数据。"""
    db = get_db()
    cycle_maps = _load_cycle_maps(db)
    if end_date:
        rows = db.execute(
            "SELECT * FROM number_knowledge_record WHERE status=1 AND record_date <= ? ORDER BY record_date, id",
            (end_date,)).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM number_knowledge_record WHERE status=1 ORDER BY record_date, id").fetchall()
    db.close()
    if not rows:
        return {"date": "", "picks": [], "N": 0}
    dimset = set(dims)
    tn_cache = {}

    def tag_nums(dim, tag, zm):
        if dim == "zodiac":
            return [n for n in range(1, 50) if _num_to_zodiac(n, zm) == tag]
        k = (dim, tag)
        if k not in tn_cache:
            tn_cache[k] = [n for n in range(1, 50) if match_labels(n, DEFAULT_ZODIAC).get(dim) == tag]
        return tn_cache[k]

    last_seen = {}; sample = {}; gap_hist = {}
    for i, r in enumerate(rows):
        seq = i + 1
        zm = _map_for(r, cycle_maps)
        for dim, tag in match_labels(int(r["source_number"]), zm).items():
            if not tag or dim not in dimset:
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
    latest_map = _map_for(rows[-1], cycle_maps)
    vote = {}
    for (dim, tag), ls in last_seen.items():
        gap = total_seq - ls
        hm = _window_hist_max(gap_hist, (dim, tag), total_seq, window)
        if sample.get((dim, tag), 0) >= 2 and gap >= hm - offset:
            for n in tag_nums(dim, tag, latest_map):
                vote[n] = vote.get(n, 0) + 1
    if pick_rule == "union":
        picks = sorted(vote.keys())
    else:
        try:
            th = int(pick_rule.replace("ge", ""))
        except Exception:
            th = 1
        picks = sorted(n for n, c in vote.items() if c >= th)
    from datetime import timedelta
    last_date = rows[-1]["record_date"]
    next_date = (datetime.strptime(last_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    return {"date": next_date, "picks": picks, "N": len(picks)}


def _generate_scheme_forward():
    """对 status='forwarding' 方案固化下一期选号到 dim_forward_track（dim_key='scheme:<key>'）。"""
    db = get_db()
    fwd = db.execute("SELECT * FROM strategy_scheme_record WHERE status='forwarding'").fetchall()
    db.close()
    if not fwd:
        return {"generated": 0, "date": ""}
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    generated = 0
    bet_date = ""
    for s in fwd:
        try:
            dims = json.loads(s["dims_json"]) if s["dims_json"] else []
        except Exception:
            dims = []
        if not dims:
            continue
        srule = s["signal_rule"] or "high_gap"
        pr = "union" if srule == "high_gap" else srule.replace("high_gap_", "")
        order = _compute_current_picks(dims, s["offset"], s["window"] or get_strategy_window(), pr)
        picks = order.get("picks", [])
        bet_date = order.get("date", "")
        if not picks or not bet_date:
            continue
        dim_key = f"scheme:{s['scheme_key']}"
        db = get_db()
        db.execute(
            "INSERT OR IGNORE INTO dim_forward_track (dim_key, bet_date, picks_json, N, open_number, hit, is_live, create_time) VALUES (?,?,?,?,NULL,NULL,1,?)",
            (dim_key, bet_date, json.dumps(picks), len(picks), now))
        db.commit()
        db.close()
        generated += 1
    return {"generated": generated, "date": bet_date}


def _update_scheme_forward_stats():
    """结算后：从 dim_forward_track 读 scheme: 记录，回填 strategy_scheme_record 的 fwd_* 字段。"""
    db = get_db()
    rows = db.execute(
        "SELECT dim_key, N, hit FROM dim_forward_track WHERE dim_key LIKE 'scheme:%' AND is_live=1 AND hit IS NOT NULL").fetchall()
    by_key = {}
    for r in rows:
        key = r["dim_key"].replace("scheme:", "")
        d = by_key.setdefault(key, {"periods": 0, "hits": 0, "profit": 0.0})
        d["periods"] += 1
        if r["hit"] == 1:
            d["hits"] += 1
            d["profit"] += (SCHEME_ODDS - (r["N"] or 0))
        else:
            d["profit"] -= (r["N"] or 0)
    for key, d in by_key.items():
        db.execute(
            "UPDATE strategy_scheme_record SET fwd_periods=?, fwd_hits=?, fwd_profit=? WHERE scheme_key=?",
            (d["periods"], d["hits"], round(d["profit"], 2), key))
    db.commit()
    db.close()
    return len(by_key)


@app.post("/api/strategyScheme/forward")
def strategy_scheme_forward(body: dict, user=Header(None, alias="authorization")):
    """前向跟踪：结算昨日 scheme 选号 + 为 forwarding 方案固化下一期选号。"""
    require_user(user)
    settled = _settle_dim_forward()
    updated = _update_scheme_forward_stats()
    gen = _generate_scheme_forward()
    return {"ok": True, "settled": settled, "updated": updated,
            "generated": gen.get("generated", 0), "date": gen.get("date", "")}


@app.get("/api/strategyScheme/picks")
def strategy_scheme_picks(user=Header(None, alias="authorization")):
    """自主跟踪·今日可下单号码：对每个 forwarding 方案实时算下一期选号（无前视偏差）。

    返回：精准选号(ge2/ge3)置顶，union 大并集在后，组内按回测超额降序。
    featured 标记「今日精选」：精准选号(ge2/ge3) + 当前有号 + 均号≤6 + 回测超额>0。
    号码为 int 列表，前端 pad 补零 + 句点分隔后复制下单。"""
    require_user(user)
    db = get_db()
    fwd = db.execute("SELECT * FROM strategy_scheme_record WHERE status='forwarding'").fetchall()
    db.close()
    out = []
    for s in fwd:
        try:
            dims = json.loads(s["dims_json"]) if s["dims_json"] else []
        except Exception:
            dims = []
        if not dims:
            continue
        srule = s["signal_rule"] or "high_gap"
        pr = "union" if srule == "high_gap" else srule.replace("high_gap_", "")
        order = _compute_current_picks(dims, s["offset"], s["window"] or get_strategy_window(), pr)
        picks = order.get("picks", [])
        N = len(picks)
        bt_alpha = s["bt_alpha"] or 0
        bt_avg_n = s["bt_avg_n"] or 0
        # 今日精选：精准选号 + 当前有号 + 均号≤6 + 回测超额>0
        featured = (pr in ("ge2", "ge3") and N > 0 and bt_avg_n <= 6 and bt_alpha > 0)
        # 样本外验证强信号：红肖蓝肖绿肖+春夏秋冬 二维 union（06-01起102期命中45-48%/p<0.06）
        oos_strong = (pr == "union" and set(dims) == {"season_type", "zodiac_color_type"})
        recent = []
        recent_hit = 0
        sim = {"periods": 0, "hits": 0, "profit": 0.0, "hit_rate": None}
        live = {"periods": 0, "settled": 0, "hits": 0, "profit": 0.0, "hit_rate": None, "pending": 0}
        if featured:
            db2 = get_db()
            # 真实样本外（is_live=1，cron 每日固化 + 真实开奖结算）
            for x in db2.execute(
                "SELECT N, hit FROM dim_forward_track WHERE dim_key=? AND is_live=1",
                (f"scheme:{s['scheme_key']}",)).fetchall():
                live["periods"] += 1
                if x["hit"] is None:
                    live["pending"] += 1
                else:
                    live["settled"] += 1
                    if x["hit"] == 1:
                        live["hits"] += 1
                        live["profit"] += (SCHEME_ODDS - (x["N"] or 0))
                    else:
                        live["profit"] -= (x["N"] or 0)
            live["profit"] = round(live["profit"], 2)
            live["hit_rate"] = round(live["hits"] / live["settled"], 4) if live["settled"] else None
            # 回测模拟（is_live=0，walk-forward 无前视回填，非真实开奖）
            sr = db2.execute(
                "SELECT bet_date, N, open_number, hit FROM dim_forward_track "
                "WHERE dim_key=? AND is_live=0 AND hit IS NOT NULL ORDER BY bet_date DESC, id DESC",
                (f"scheme:{s['scheme_key']}",)).fetchall()
            for x in sr:
                sim["periods"] += 1
                if x["hit"] == 1:
                    sim["hits"] += 1
                    sim["profit"] += (SCHEME_ODDS - (x["N"] or 0))
                else:
                    sim["profit"] -= (x["N"] or 0)
            sim["profit"] = round(sim["profit"], 2)
            sim["hit_rate"] = round(sim["hits"] / sim["periods"], 4) if sim["periods"] else None
            recent = [{"date": x["bet_date"], "open": x["open_number"], "hit": x["hit"]} for x in sr[:15]]
            recent_hit = sum(1 for x in recent if x["hit"] == 1)
            db2.close()
        out.append({
            "scheme_key": s["scheme_key"],
            "scheme_name": s["scheme_name"],
            "dims": dims,
            "signal_rule": pr,
            "offset": s["offset"],
            "window": s["window"],
            "bet_date": order.get("date", ""),
            "picks": picks,
            "N": N,
            "bt_alpha": s["bt_alpha"],
            "bt_hit_rate": s["bt_hit_rate"],
            "bt_avg_n": s["bt_avg_n"],
            "fwd_periods": s["fwd_periods"],
            "fwd_hits": s["fwd_hits"],
            "fwd_profit": s["fwd_profit"],
            "featured": featured,
            "oos_strong": oos_strong,
            "recent": recent,
            "recent_hit": recent_hit,
            "sim": sim,
            "live": live,
        })
    # 精选最前，再样本外强信号，然后精准选号(ge2/ge3)，再 union；组内按超额降序
    def _rank(x):
        return (0 if x["featured"] else (1 if x["oos_strong"] else (2 if x["signal_rule"] in ("ge2", "ge3") else 3)),
                -(x["bt_alpha"] or 0))
    out.sort(key=_rank)
    return {"picks": out, "count": len(out), "date": out[0]["bet_date"] if out else ""}


@app.get("/api/strategyScheme/detail")
def strategy_scheme_detail(scheme_key: str, limit: int = 100, user=Header(None, alias="authorization")):
    """单方案前向明细：每天选号 + 开奖 + 命中 + 盈亏（倒序，最新在前）+ 汇总统计。"""
    require_user(user)
    db = get_db()
    rows = db.execute(
        "SELECT bet_date, picks_json, N, open_number, hit, is_live FROM dim_forward_track "
        "WHERE dim_key=? ORDER BY bet_date DESC, id DESC LIMIT ?",
        (f"scheme:{scheme_key}", limit)).fetchall()
    s = db.execute(
        "SELECT scheme_name, dims_json, signal_rule, offset, window, bt_alpha, bt_hit_rate "
        "FROM strategy_scheme_record WHERE scheme_key=?", (scheme_key,)).fetchone()
    db.close()
    detail = []
    hits = 0
    total_profit = 0.0
    sum_n = 0
    max_consec_miss = 0
    cur_miss = 0
    # 分口径统计：sim=回测模拟(is_live=0) / live=真实样本外(is_live=1)
    sim_s = {"periods": 0, "hits": 0, "profit": 0.0, "sum_n": 0}
    live_s = {"periods": 0, "hits": 0, "profit": 0.0, "sum_n": 0, "pending": 0}
    for r in rows:
        try:
            picks = json.loads(r["picks_json"]) if r["picks_json"] else []
        except Exception:
            picks = []
        N = r["N"] or 0
        hit = r["hit"]
        is_live = r["is_live"] or 0
        profit = (SCHEME_ODDS - N) if hit == 1 else (-N if N > 0 else 0)
        if is_live:
            live_s["periods"] += 1
            if hit is None:
                live_s["pending"] += 1
            else:
                live_s["sum_n"] += N
                if hit == 1:
                    live_s["hits"] += 1
                    live_s["profit"] += profit
                else:
                    live_s["profit"] += profit
        else:
            sim_s["periods"] += 1
            sum_n += N
            if hit == 1:
                hits += 1
                total_profit += profit
                sim_s["hits"] += 1
                sim_s["profit"] += profit
                sim_s["sum_n"] += N
                cur_miss = 0
            else:
                total_profit += profit
                sim_s["profit"] += profit
                sim_s["sum_n"] += N
                cur_miss += 1
                max_consec_miss = max(max_consec_miss, cur_miss)
        detail.append({
            "bet_date": r["bet_date"], "picks": picks, "N": N,
            "open_number": r["open_number"], "hit": hit, "profit": profit,
            "is_live": is_live,
        })
    cnt = len(detail)
    live_settled = live_s["periods"] - live_s["pending"]
    summary = {
        "periods": cnt,
        "hits": hits,
        "hit_rate": round(hits / sim_s["periods"], 4) if sim_s["periods"] else 0.0,
        "avg_n": round(sum_n / sim_s["periods"], 2) if sim_s["periods"] else 0.0,
        "total_profit": round(total_profit, 2),
        "max_consec_miss": max_consec_miss,
        "sim": {"periods": sim_s["periods"], "hits": sim_s["hits"], "profit": round(sim_s["profit"], 2)},
        "live": {"periods": live_s["periods"], "settled": live_settled, "pending": live_s["pending"],
                 "hits": live_s["hits"], "profit": round(live_s["profit"], 2),
                 "hit_rate": round(live_s["hits"] / live_settled, 4) if live_settled else None},
    }
    scheme = {}
    if s:
        try:
            dims = json.loads(s["dims_json"]) if s["dims_json"] else []
        except Exception:
            dims = []
        scheme = {
            "scheme_name": s["scheme_name"], "dims": dims, "signal_rule": s["signal_rule"],
            "offset": s["offset"], "window": s["window"],
            "bt_alpha": s["bt_alpha"], "bt_hit_rate": s["bt_hit_rate"],
        }
    return {"scheme": scheme, "summary": summary, "detail": detail, "count": cnt}


@app.get("/api/strategyScheme/paper-trade")
def strategy_scheme_paper_trade(user=Header(None, alias="authorization")):
    """样本外验证（真实用户模拟下单，2026-06-01 起）。

    读 analysis/paper_trade_0601.json（Train/Test 切分 + 无前视模拟下单的结果），
    返回：汇总 + 核心结论 + 最强稳健家族（红肖蓝肖绿肖+春夏秋冬）+ 头数衰减对比。"""
    require_user(user)
    import os as _os
    path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                         "analysis", "paper_trade_0601.json")
    if not _os.path.exists(path):
        return {"ready": False, "message": "尚未生成样本外验证报告（运行 analysis/paper_trade_0601.py）"}
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    schemes = d.get("schemes", [])
    test_alphas = [s["test"]["alpha"] for s in schemes]
    pos = sum(1 for a in test_alphas if a > 0)
    trig30 = [s for s in schemes if s["test"]["triggered"] >= 30]
    roi30_profit = sum(s["test"]["profit"] for s in trig30)
    roi30_invest = sum(s["test"]["avg_n"] * s["test"]["triggered"] for s in trig30)
    # Trainα vs Testα 相关系数
    def _pearson(x, y):
        n = len(x)
        if n < 2:
            return 0.0
        mx, my = sum(x) / n, sum(y) / n
        num = sum((a - mx) * (b - my) for a, b in zip(x, y))
        dx = sum((a - mx) ** 2 for a in x) ** 0.5
        dy = sum((b - my) ** 2 for b in y) ** 0.5
        return round(num / (dx * dy), 4) if dx * dy else 0.0
    train_alphas = [s["train"]["alpha"] for s in schemes]
    corr = _pearson(train_alphas, test_alphas)
    # 最强家族：红肖蓝肖绿肖+春夏秋冬（len<=3 含这两维）
    fam = [s for s in schemes
           if {"season_type", "zodiac_color_type"}.issubset(set(s["dims"])) and len(s["dims"]) <= 3]
    fam.sort(key=lambda s: -s["test"]["profit"])
    family = [{
        "name": "+".join(DIM_NAMES.get(d, d) for d in s["dims"]), "dims": s["dims"],
        "offset": s["offset"], "window": s["window"], "pick_rule": s["pick_rule"],
        "train_alpha": s["train"]["alpha"], "test_alpha": s["test"]["alpha"],
        "triggered": s["test"]["triggered"], "hit_rate": s["test"]["hit_rate"],
        "avg_n": s["test"]["avg_n"], "profit": s["test"]["profit"],
        "p": s["test"]["binomial_p"],
    } for s in fam[:6]]
    # 头数单维衰减对比
    head = [s for s in schemes if s["dims"] == ["head_number"] and s["pick_rule"] == "union"]
    head.sort(key=lambda s: -s["train"]["alpha"])
    head_decay = [{
        "offset": s["offset"], "window": s["window"],
        "train_alpha": s["train"]["alpha"], "test_alpha": s["test"]["alpha"],
        "triggered": s["test"]["triggered"], "profit": s["test"]["profit"],
    } for s in head[:6]]
    return {
        "ready": True,
        "meta": {
            "split_date": d.get("split_date"), "train_periods": d.get("train_periods"),
            "test_periods": d.get("test_periods"), "odds": d.get("odds"),
            "scanned": d.get("scanned"), "selected": len(schemes),
            "generated": d.get("generated"),
        },
        "summary": {
            "pos_out_of_sample": pos, "total": len(schemes),
            "pos_ratio": round(pos / len(schemes), 4) if schemes else 0.0,
            "alpha_mean": round(sum(test_alphas) / len(test_alphas), 4) if schemes else 0.0,
            "profit_sum": round(sum(s["test"]["profit"] for s in schemes), 1),
            "train_test_corr": corr,
            "stable_n": len(trig30),
            "stable_pos_ratio": round(sum(1 for s in trig30 if s["test"]["alpha"] > 0) / len(trig30), 4) if trig30 else 0.0,
            "stable_profit": round(roi30_profit, 1),
            "stable_roi": round(roi30_profit / roi30_invest * 100, 2) if roi30_invest else 0.0,
        },
        "family": family,
        "head_decay": head_decay,
        "report_md": "analysis/paper_trade_0601.md",
    }


def _consensus_health():
    """共识信号健康度：实时 walk-forward 回放，算当前连空 / 仓位建议 / 月度超额趋势 / 失效预警。

    复用 4 变体≥2票共识口径（同 paper_trade_rolling.py），无前视。
    连空降半仓依据：演算证实连空≥5期降半仓使收益/回撤比 +23%，≥8期应暂停观察。"""
    from collections import defaultdict, OrderedDict
    dims = ["season_type", "zodiac_color_type"]
    variants = [(+2, 90), (+1, 60), (+2, 60), (+1, 90)]
    rows, cycle_maps, seq_labels = _load_backtest_data()
    dimset = set(dims)
    tn_cache = {}

    def tag_nums(dim, tag, zm):
        if dim == "zodiac":
            return [n for n in range(1, 50) if _num_to_zodiac(n, zm) == tag]
        k = (dim, tag)
        if k not in tn_cache:
            tn_cache[k] = [n for n in range(1, 50) if match_labels(n, DEFAULT_ZODIAC).get(dim) == tag]
        return tn_cache[k]

    def run_walkforward(offset, window):
        last_seen = {}; sample = {}; gap_hist = {}; out = []
        for i in range(len(rows)):
            seq = i + 1
            open_num, labels, zm = seq_labels[i]
            vote = {}
            for (dim, tag), ls in last_seen.items():
                gap = seq - ls
                hm = _window_hist_max(gap_hist, (dim, tag), seq, window)
                if sample.get((dim, tag), 0) >= 2 and gap >= hm - offset:
                    for n in tag_nums(dim, tag, zm):
                        vote[n] = vote.get(n, 0) + 1
            out.append(sorted(vote.keys()))
            for dim, tag in labels.items():
                if not tag or dim not in dimset:
                    continue
                k = (dim, tag)
                if k in last_seen:
                    gap = seq - last_seen[k]
                    sample[k] = sample.get(k, 0) + 1
                    gap_hist.setdefault(k, []).append((seq, gap))
                else:
                    sample[k] = 1
                last_seen[k] = seq
        return out

    var_picks = {v: run_walkforward(*v) for v in variants}
    daily = []
    # 资金指标累计（等额每号1元，赔率47）
    cum_profit = 0.0; peak = 0.0; max_dd = 0.0
    max_N = 0; total_invest = 0.0; total_profit = 0.0
    for i in range(len(rows)):
        date = rows[i]["record_date"]
        open_num = int(rows[i]["source_number"])
        votes = defaultdict(int)
        for v, pl in var_picks.items():
            for n in pl[i]:
                votes[n] += 1
        picks = [n for n, c in votes.items() if c >= 2]
        if not picks:
            continue
        hit = 1 if open_num in picks else 0
        N = len(picks)
        daily.append((date, N, hit))
        profit = (SCHEME_ODDS - N) if hit else -N
        cum_profit += profit
        total_invest += N
        total_profit += profit
        max_N = max(max_N, N)
        peak = max(peak, cum_profit)
        max_dd = max(max_dd, peak - cum_profit)

    # 当前连空（末尾连续未命中）
    cur_streak = 0
    for _, _, hit in reversed(daily):
        if hit:
            break
        cur_streak += 1
    # 历史最大连空
    max_streak = 0; cur = 0
    for _, _, hit in daily:
        if hit:
            cur = 0
        else:
            cur += 1
            max_streak = max(max_streak, cur)

    # 仓位建议
    if cur_streak >= 8:
        advice = "暂停观察"
    elif cur_streak >= 5:
        advice = "半仓"
    else:
        advice = "等额"

    # 最近 6 个月超额
    monthly = OrderedDict()
    for date, N, hit in daily:
        m = monthly.setdefault(date[:7], {"n": 0, "hits": 0, "sum_n": 0})
        m["n"] += 1; m["hits"] += hit; m["sum_n"] += N
    recent = []
    for k, m in list(monthly.items())[-6:]:
        hr = m["hits"] / m["n"] * 100
        avg_n = m["sum_n"] / m["n"]
        recent.append({"month": k, "alpha": round(hr - avg_n / 49 * 100, 1), "periods": m["n"]})

    # 连续负超额月数（失效预警）
    neg_streak = 0
    for m in reversed(recent):
        if m["alpha"] > 0:
            break
        neg_streak += 1

    # 走坏监测：近2年→近3月→近一月→近一周，依次逻辑（从长到短判走坏等级）
    from datetime import timedelta
    latest_dt = datetime.strptime(rows[-1]["record_date"], "%Y-%m-%d")

    def _roll(days):
        if not daily:
            return None
        cutoff = (latest_dt - timedelta(days=days)).strftime("%Y-%m-%d")
        sub = [(d, N, h) for d, N, h in daily if d >= cutoff]
        if len(sub) < 5:
            return None
        n = len(sub)
        hits = sum(1 for _, _, h in sub if h)
        total_n = sum(N for _, N, _ in sub)
        avg_n = total_n / n
        pnl = sum((SCHEME_ODDS - N) if h else -N for _, N, h in sub)
        return {
            "days": days, "periods": n, "hits": hits,
            "hit_rate": round(hits / n * 100, 1),
            "avg_n": round(avg_n, 1),
            "alpha": round((hits / n - avg_n / 49) * 100, 2),
            "net_pnl": round(pnl, 1),
            "roi": round(pnl / total_n * 100, 2) if total_n else 0.0,
        }

    rolling_2y = _roll(730)
    rolling_3m = _roll(90)
    rolling_1m = _roll(30)
    rolling_1w = _roll(7)

    def _bad(r):
        return r is not None and (r["roi"] < 0 or r["alpha"] < 0)

    # 依次逻辑：近2年(长期基础)→近3月→近一月(重点监测)→近一周，越短越先暴露走坏
    if _bad(rolling_2y):
        status = "失效"
    elif _bad(rolling_3m):
        status = "走坏预警"
    elif _bad(rolling_1m):
        status = "警惕"
    elif _bad(rolling_1w):
        status = "注意"
    else:
        status = "健康"

    # 滚动 20 期超额（早期失效预警，比月度更及时；power 分析证明统计定论需3年，须靠软判断）
    W = 20
    recent_daily = daily[-W:]
    rolling_alpha = None
    rolling_periods = len(recent_daily)
    if rolling_periods >= 10:
        rh = sum(1 for _, _, h in recent_daily if h)
        rn = sum(N for _, N, _ in recent_daily) / rolling_periods
        rolling_alpha = round(rh / rolling_periods - rn / 49, 4)

    capital_req = max_dd + max_N
    capital = {
        "total_invest": round(total_invest, 1),
        "total_profit": round(total_profit, 1),
        "bet_roi": round(total_profit / total_invest * 100, 2) if total_invest else 0.0,
        "max_drawdown": round(max_dd, 1),
        "capital_required": round(capital_req, 1),
        "capital_roi": round(total_profit / capital_req * 100, 2) if capital_req else 0.0,
    }
    return {
        "current_streak": cur_streak,
        "max_streak": max_streak,
        "position_advice": advice,
        "recent_monthly": recent,
        "neg_month_streak": neg_streak,
        "health_status": status,
        "rolling_alpha": rolling_alpha,
        "rolling_periods": rolling_periods,
        "rolling_2y": rolling_2y,
        "rolling_3m": rolling_3m,
        "rolling_1m": rolling_1m,
        "rolling_1w": rolling_1w,
        "capital": capital,
    }


def _load_monte_carlo():
    """读蒙特卡洛 bootstrap 预计算结果（analysis/consensus_monte_carlo.json），无则返回 None。"""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "analysis", "consensus_monte_carlo.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


@app.get("/api/strategyScheme/consensus")
def strategy_scheme_consensus(user=Header(None, alias="authorization")):
    """样本外强信号「红肖蓝肖绿肖+春夏秋冬」4 变体共识选号。

    4 个变体（offset/window 不同）实时算当前选号，统计每个号码被几个变体选中。
    样本外验证：≥2 票共识命中率 50%（vs 单变体 47.3%）、超额 +12.5%。"""
    require_user(user)
    dims = ["season_type", "zodiac_color_type"]
    variants = [(+2, 90), (+1, 60), (+2, 60), (+1, 90)]
    votes = {}
    picks_by_var = []
    bet_date = ""
    for off, w in variants:
        order = _compute_current_picks(dims, off, w, "union")
        picks = order.get("picks", [])
        bet_date = bet_date or order.get("date", "")
        picks_by_var.append({"offset": off, "window": w, "picks": picks, "N": len(picks)})
        for n in picks:
            votes[n] = votes.get(n, 0) + 1
    consensus = {k: sorted(n for n, c in votes.items() if c >= k) for k in (2, 3, 4)}
    health = _consensus_health()
    forward = _consensus_forward_stats()
    monte_carlo = _load_monte_carlo()
    return {
        "dims": dims,
        "date": bet_date,
        "variants": picks_by_var,
        "votes": {str(n): c for n, c in sorted(votes.items())},
        "consensus2": consensus[2],
        "consensus3": consensus[3],
        "consensus4": consensus[4],
        "consensus2_count": len(consensus[2]),
        "health": health,
        "forward": forward,
        "monte_carlo": monte_carlo,
        "note": "≥2票共识：命中率50%(样本外102期) 超额+12.5% 最大连空8期",
    }


@app.get("/api/strategyScheme/rolling")
def strategy_scheme_rolling(user=Header(None, alias="authorization")):
    """滚动前向验证 · 月度稳定性序列（红肖蓝肖绿肖+春夏秋冬 ≥2票共识）。

    读 analysis/paper_trade_rolling.json：按月/半年聚合超额，监控时间结构突变。"""
    require_user(user)
    import os as _os
    path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                         "analysis", "paper_trade_rolling.json")
    if not _os.path.exists(path):
        return {"ready": False, "message": "尚未生成滚动验证数据（运行 analysis/paper_trade_rolling.py）"}
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    d["ready"] = True
    return d


@app.get("/api/strategyScheme/consensus-generalize")
def strategy_scheme_consensus_generalize(user=Header(None, alias="authorization")):
    """共识选号泛化结论 · 信号源单一性审计（85 家族 4变体≥2票共识全历史验证）。

    读 analysis/consensus_generalize.json：按是否含 season_type 分组统计 p<0.05 比例，
    证明信号源唯一（春夏秋冬），无独立备胎，避免重复扫描维度组合。"""
    require_user(user)
    import os as _os
    path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                         "analysis", "consensus_generalize.json")
    if not _os.path.exists(path):
        return {"ready": False, "message": "尚未生成泛化验证数据（运行 analysis/consensus_generalize.py）"}
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    families = d.get("families", [])
    with_season = [r for r in families if "season_type" in r["dims"]]
    without_season = [r for r in families if "season_type" not in r["dims"]]

    def p005_ratio(lst):
        if not lst:
            return 0.0
        return round(sum(1 for r in lst if r["overall"]["binomial_p"] < 0.05) / len(lst), 4)

    def avg_alpha(lst):
        if not lst:
            return 0.0
        return round(sum(r["overall"]["alpha"] for r in lst) / len(lst), 2)

    top = families[:10] if families else []
    # 三维升级候选（春夏秋冬+号码波色+红肖蓝肖绿肖）
    upgrade = next((r for r in families
                    if set(r["dims"]) == {"season_type", "wave_color", "zodiac_color_type"}), None)
    current = next((r for r in families
                    if set(r["dims"]) == {"season_type", "zodiac_color_type"}), None)
    d.update({
        "ready": True,
        "group": {
            "with_season_count": len(with_season),
            "without_season_count": len(without_season),
            "with_season_p005_ratio": p005_ratio(with_season),
            "without_season_p005_ratio": p005_ratio(without_season),
            "with_season_avg_alpha": avg_alpha(with_season),
            "without_season_avg_alpha": avg_alpha(without_season),
        },
        "top_families": [
            {"name": r["name"], "dims": r["dims"], "overall": r["overall"]} for r in top
        ],
        "current_signal": current,
        "upgrade_candidate": upgrade,
        "conclusion": {
            "source_unique": True,
            "source_dim": "season_type",
            "source_dim_name": "春夏秋冬",
            "summary": "信号源唯一=春夏秋冬憋高位触发，其他维度仅作共识交叉验证。无独立备胎信号，维度组合扫描已穷尽，无需重复论证。",
        },
    })
    return d


# ============================================================
# 尾数跟踪（5-9尾 / 买同上期尾数，达朗贝尔±5 演算）
# ============================================================
def _compute_tail_track(start_date="2025-01-01", odds=47, base=5, step=5, chip_cap=70):
    """尾数跟踪：两种策略达朗贝尔±5 演算。
    组1=5-9尾(25号，随机基线51%)；组2=买同上期尾数(4-5号，随机基线10%)。
    达朗贝尔：命中筹码-5(不低于base)、未中筹码+5；筹码封顶 chip_cap，超过即重置回 base。赔率47倍。纯只读。"""
    from datetime import timedelta
    db = get_db()
    rows = db.execute(
        "SELECT record_date, source_number FROM number_knowledge_record "
        "WHERE status=1 AND record_date >= ? ORDER BY record_date, id",
        (start_date,)
    ).fetchall()
    db.close()

    def tail_nums(t):
        return [n for n in range(1, 50) if n % 10 == t]
    tail_map = {t: tail_nums(t) for t in range(10)}

    g1_nums = set()
    for t in range(5, 10):
        g1_nums.update(tail_map[t])

    def run(strategy):
        chip = base
        daily = []
        for i, r in enumerate(rows):
            d = r["record_date"]
            open_num = int(r["source_number"])
            open_tail = open_num % 10
            if strategy == "g1":
                nums = g1_nums
            else:
                if i == 0:
                    daily.append({"date": d, "open": open_num, "tail": open_tail, "N": 0,
                                  "hit": False, "chip": chip, "chip_after": chip, "profit": 0.0})
                    continue
                prev_tail = int(rows[i - 1]["source_number"]) % 10
                nums = set(tail_map[prev_tail])
            N = len(nums)
            hit = open_num in nums
            chip_before = chip
            profit = (odds * chip - N * chip) if hit else (-N * chip)
            reset = False
            if hit:
                chip = max(base, chip - step)
            else:
                chip += step
                if chip > chip_cap:
                    chip = base
                    reset = True
            daily.append({"date": d, "open": open_num, "tail": open_tail, "N": N,
                          "hit": hit, "chip": chip_before, "chip_after": chip,
                          "profit": round(profit, 2), "reset": reset})
        return daily

    def aggregate(daily):
        total_profit = round(sum(x["profit"] for x in daily), 2)
        hits = sum(1 for x in daily if x["hit"] and x["N"] > 0)
        periods = sum(1 for x in daily if x["N"] > 0)
        max_chip = max(x["chip"] for x in daily) if daily else base
        cur_chip = daily[-1]["chip_after"] if daily else base
        reset_count = sum(1 for x in daily if x.get("reset"))
        total_bet = round(sum(x["chip"] * x["N"] for x in daily), 2)
        _cum = 0.0
        _peak = 0.0
        max_drawdown = 0.0
        for x in daily:
            _cum += x["profit"]
            if _cum > _peak:
                _peak = _cum
            if _peak - _cum > max_drawdown:
                max_drawdown = _peak - _cum
        max_drawdown = round(max_drawdown, 2)
        roi = round(total_profit / total_bet * 100, 2) if total_bet else 0.0
        rrr = round(total_profit / max_drawdown, 2) if max_drawdown else 0.0
        monthly = {}
        for x in daily:
            m = x["date"][:7]
            monthly.setdefault(m, {"month": m, "profit": 0.0, "hits": 0, "periods": 0})
            monthly[m]["profit"] += x["profit"]
            monthly[m]["hits"] += 1 if x["hit"] else 0
            monthly[m]["periods"] += 1
        monthly = [monthly[m] for m in sorted(monthly)]
        for m in monthly:
            m["profit"] = round(m["profit"], 2)
            m["hit_rate"] = round(m["hits"] / m["periods"] * 100, 1) if m["periods"] else 0.0
        weekly = {}
        for x in daily:
            dt = datetime.strptime(x["date"], "%Y-%m-%d")
            wk = (dt - timedelta(days=dt.weekday())).strftime("%Y-%m-%d")
            weekly.setdefault(wk, {"week": wk, "profit": 0.0, "hits": 0, "periods": 0})
            weekly[wk]["profit"] += x["profit"]
            weekly[wk]["hits"] += 1 if x["hit"] else 0
            weekly[wk]["periods"] += 1
        weekly = [weekly[w] for w in sorted(weekly)]
        for w in weekly:
            w["profit"] = round(w["profit"], 2)
            w["hit_rate"] = round(w["hits"] / w["periods"] * 100, 1) if w["periods"] else 0.0
        return {"total_profit": total_profit, "hits": hits, "periods": periods,
                "hit_rate": round(hits / periods * 100, 1) if periods else 0.0,
                "max_chip": max_chip, "cur_chip": cur_chip, "reset_count": reset_count,
                "total_bet": total_bet, "max_drawdown": max_drawdown,
                "roi": roi, "rrr": rrr,
                "monthly": monthly, "weekly": weekly}

    def guide(daily, agg, rand_base):
        loss_streak = 0
        for x in reversed(daily):
            if x["N"] > 0 and x["profit"] < 0:
                loss_streak += 1
            elif x["N"] > 0:
                break
        recent4 = [m["profit"] for m in agg["monthly"][-4:]]
        recent_total = round(sum(recent4), 2)
        cur_chip = agg["cur_chip"]
        if loss_streak >= 5:
            advice, level = "回避", "avoid"
            reason = f"连续亏损 {loss_streak} 天，达朗贝尔筹码已加至 {cur_chip}"
        elif recent_total > 0:
            advice, level = "可买入", "buy"
            reason = f"近4月累计 {recent_total:+.0f}，趋势走强"
        elif recent_total < 0:
            advice, level = "观望", "watch"
            reason = f"近4月累计 {recent_total:+.0f}，趋势走弱"
        else:
            advice, level = "观望", "watch"
            reason = "近4月盈亏平衡，方向不明"
        return {"advice": advice, "reason": reason, "level": level,
                "loss_streak": loss_streak, "cur_chip": cur_chip,
                "recent4_total": recent_total, "rand_base": rand_base}

    g1_daily = run("g1")
    g2_daily = run("g2")
    g1_agg = aggregate(g1_daily)
    g2_agg = aggregate(g2_daily)

    return {
        "start_date": rows[0]["record_date"] if rows else "",
        "end_date": rows[-1]["record_date"] if rows else "",
        "odds": odds, "base": base, "step": step, "cap": chip_cap,
        "g1": {"name": "5-9尾", "nums": sorted(g1_nums), "N": len(g1_nums),
               "summary": g1_agg, "daily": g1_daily,
               "guide": guide(g1_daily, g1_agg, round(25 / 49 * 100, 1))},
        "g2": {"name": "买同上期尾数", "nums": [], "N": 0,
               "summary": g2_agg, "daily": g2_daily,
               "guide": guide(g2_daily, g2_agg, round(5 / 49 * 100, 1))},
    }


@app.get("/api/tailTrack/calc")
def tail_track_calc(start_date: str = "2025-01-01", user=Header(None, alias="authorization")):
    """尾数跟踪演算：两种策略达朗贝尔±5，返回逐期列表 + 按月/按周汇总 + 是否购买指南。"""
    require_user(user)
    return _compute_tail_track(start_date)


# ============================================================
# 尾数跟踪·智能（连续失败 fail_stop 次停手 → 等待命中再恢复，依次循环）
# ============================================================
def _compute_tail_track_smart(start_date="2025-01-01", odds=47, base=5, step=5, chip_cap=70, fail_stop=3):
    """尾数跟踪·智能：两种策略各自独立，连续失败(未命中)fail_stop次就停手下注，
    等待命中(赢)后再恢复下注，依次循环。达朗贝尔±5 筹码，封顶 chip_cap，恢复时筹码重置回 base。
    纯只读，零影响现有功能。"""
    from datetime import timedelta
    db = get_db()
    rows = db.execute(
        "SELECT record_date, source_number FROM number_knowledge_record "
        "WHERE status=1 AND record_date >= ? ORDER BY record_date, id",
        (start_date,)
    ).fetchall()
    db.close()

    def tail_nums(t):
        return [n for n in range(1, 50) if n % 10 == t]
    tail_map = {t: tail_nums(t) for t in range(10)}

    g1_nums = set()
    for t in range(5, 10):
        g1_nums.update(tail_map[t])

    g_small_nums = set()
    for t in range(5):
        g_small_nums.update(tail_map[t])

    def run(strategy):
        chip = base
        loss_streak = 0
        paused = False
        daily = []
        for i, r in enumerate(rows):
            d = r["record_date"]
            open_num = int(r["source_number"])
            open_tail = open_num % 10
            if strategy == "g1":
                nums = g1_nums
            else:
                if i == 0:
                    daily.append({"date": d, "open": open_num, "tail": open_tail, "N": 0,
                                  "hit": False, "chip": 0, "chip_after": chip,
                                  "profit": 0.0, "paused": False, "resume": False,
                                  "state": "betting", "loss_streak": 0})
                    continue
                prev_tail = int(rows[i - 1]["source_number"]) % 10
                # 跟随大小尾：上期小尾(0-4)→买0-4尾(24号)；上期大尾(5-9)→买5-9尾(25号)
                nums = g_small_nums if prev_tail <= 4 else g1_nums
            N = len(nums)
            hit = open_num in nums

            if paused:
                # 停手观察：不下注，盈亏为 0；命中即"赢"，下一期恢复下注
                resume = hit
                daily.append({"date": d, "open": open_num, "tail": open_tail, "N": N,
                              "hit": hit, "chip": 0, "chip_after": chip,
                              "profit": 0.0, "paused": True, "resume": resume,
                              "state": "paused", "loss_streak": loss_streak})
                if resume:
                    paused = False
                    loss_streak = 0
                    chip = base
                continue

            # 正常下注
            chip_before = chip
            profit = (odds * chip - N * chip) if hit else (-N * chip)
            if hit:
                chip = max(base, chip - step)
                loss_streak = 0
            else:
                chip += step
                loss_streak += 1
                if chip > chip_cap:
                    chip = base
            pause_now = (not hit) and loss_streak >= fail_stop
            daily.append({"date": d, "open": open_num, "tail": open_tail, "N": N,
                          "hit": hit, "chip": chip_before, "chip_after": chip,
                          "profit": round(profit, 2), "paused": False,
                          "pause_now": pause_now, "resume": False,
                          "state": "betting", "loss_streak": loss_streak})
            if pause_now:
                paused = True
        return daily

    def aggregate(daily):
        total_profit = round(sum(x["profit"] for x in daily), 2)
        bets = [x for x in daily if x["state"] == "betting" and x["N"] > 0]
        hits = sum(1 for x in bets if x["hit"])
        periods = len(bets)
        pause_count = sum(1 for x in daily if x.get("pause_now"))
        pause_periods = sum(1 for x in daily if x["state"] == "paused")
        missed_hits = sum(1 for x in daily if x["state"] == "paused" and x["hit"])
        max_chip = max(x["chip"] for x in bets) if bets else base
        cur_chip = daily[-1]["chip_after"] if daily else base
        cur_state = daily[-1]["state"] if daily else "betting"
        cur_loss_streak = daily[-1]["loss_streak"] if daily else 0
        total_bet = round(sum(x["chip"] * x["N"] for x in daily), 2)
        _cum = 0.0
        _peak = 0.0
        max_drawdown = 0.0
        for x in daily:
            _cum += x["profit"]
            if _cum > _peak:
                _peak = _cum
            if _peak - _cum > max_drawdown:
                max_drawdown = _peak - _cum
        max_drawdown = round(max_drawdown, 2)
        roi = round(total_profit / total_bet * 100, 2) if total_bet else 0.0
        rrr = round(total_profit / max_drawdown, 2) if max_drawdown else 0.0
        monthly = {}
        for x in daily:
            m = x["date"][:7]
            monthly.setdefault(m, {"month": m, "profit": 0.0, "hits": 0, "periods": 0})
            monthly[m]["profit"] += x["profit"]
            if x["state"] == "betting" and x["N"] > 0:
                monthly[m]["hits"] += 1 if x["hit"] else 0
                monthly[m]["periods"] += 1
        monthly = [monthly[m] for m in sorted(monthly)]
        for m in monthly:
            m["profit"] = round(m["profit"], 2)
            m["hit_rate"] = round(m["hits"] / m["periods"] * 100, 1) if m["periods"] else 0.0
        weekly = {}
        for x in daily:
            dt = datetime.strptime(x["date"], "%Y-%m-%d")
            wk = (dt - timedelta(days=dt.weekday())).strftime("%Y-%m-%d")
            weekly.setdefault(wk, {"week": wk, "profit": 0.0, "hits": 0, "periods": 0})
            weekly[wk]["profit"] += x["profit"]
            if x["state"] == "betting" and x["N"] > 0:
                weekly[wk]["hits"] += 1 if x["hit"] else 0
                weekly[wk]["periods"] += 1
        weekly = [weekly[w] for w in sorted(weekly)]
        for w in weekly:
            w["profit"] = round(w["profit"], 2)
            w["hit_rate"] = round(w["hits"] / w["periods"] * 100, 1) if w["periods"] else 0.0
        return {"total_profit": total_profit, "hits": hits, "periods": periods,
                "hit_rate": round(hits / periods * 100, 1) if periods else 0.0,
                "max_chip": max_chip, "cur_chip": cur_chip,
                "pause_count": pause_count, "pause_periods": pause_periods,
                "missed_hits": missed_hits, "cur_state": cur_state,
                "cur_loss_streak": cur_loss_streak,
                "total_bet": total_bet, "max_drawdown": max_drawdown,
                "roi": roi, "rrr": rrr,
                "monthly": monthly, "weekly": weekly}

    g1_daily = run("g1")
    g2_daily = run("g2")
    g1_agg = aggregate(g1_daily)
    g2_agg = aggregate(g2_daily)

    return {
        "start_date": rows[0]["record_date"] if rows else "",
        "end_date": rows[-1]["record_date"] if rows else "",
        "odds": odds, "base": base, "step": step, "cap": chip_cap, "fail_stop": fail_stop,
        "g1": {"name": "5-9尾", "nums": sorted(g1_nums), "N": len(g1_nums),
               "summary": g1_agg, "daily": g1_daily},
        "g2": {"name": "跟随大小尾", "nums": [], "N": 0,
               "summary": g2_agg, "daily": g2_daily},
    }


@app.get("/api/tailTrack/smart")
def tail_track_smart(start_date: str = "2025-01-01", user=Header(None, alias="authorization")):
    """尾数跟踪·智能演算：两种策略独立，连续失败3次停手、等待命中再恢复，依次循环。"""
    require_user(user)
    return _compute_tail_track_smart(start_date)


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
        # 观察池维度前向验证：独立 try（失败不影响演算跟踪），仅 N>0 固化，跳过已转正维度
        # offset 从 sys_config 读（默认0，对齐方案C下单口径）；空仓不计入前向样本
        try:
            fwd_offset = _get_config_int('high_track_fwd_offset', 0)
            core = _get_high_track_core()
            for wdim in DIM_ASSESS_WATCH:
                if wdim in core:
                    continue  # 已转正入核心池，无需再前向验证
                nxt = _compute_dim_forward_next(wdim, offset=fwd_offset, window=60)
                if nxt.get("date") and nxt.get("N", 0) > 0:
                    next_rows.append(("dim_fwd_" + wdim, nxt["date"],
                                      json.dumps(nxt.get("picks", [])), nxt.get("N", 0)))
        except Exception as e:
            print(f"[dim_fwd] 观察池前向固化失败: {e}")
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
    sql += " ORDER BY record_date DESC, id DESC"
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
# 十七、肖跟踪（生肖遗漏≥12期 → 单肖跟踪持有下单 + 预警）
# ============================================================
# 口径：生肖遗漏（连续未开期数）≥ threshold(12) 视为冷肖；
# 锁定「遗漏最久」的冷肖跟踪 K(12) 期：命中该肖号码 = (47 - N*held)*per，止损 = -N*K*per。
# N = 该生肖覆盖号码数（马5个含49，其余4个）。本金 3000，每号 per 元。

ZODIAC_TRACK_THRESHOLD = 12   # 冷肖信号：遗漏≥12期
ZODIAC_TRACK_K = 12           # 跟踪期数（满K期止损）
ZODIAC_MAX_TRACK = 6          # 源头事件触发条件：≥6肖同时遗漏≥阈值
ZODIAC_BET_N = 3              # 下单策略：只买遗漏最久的N个冷肖（回测最优=3）


def _zodiac_track_load(db):
    """加载生肖→号码映射 + 全部开奖记录（按日期序）。"""
    cycle_maps = _load_cycle_maps(db)
    rows = db.execute(
        "SELECT * FROM number_knowledge_record WHERE status=1 ORDER BY record_date, id").fetchall()
    return cycle_maps, rows


def _zodiac_gap_series(rows, cycle_maps):
    """逐期回放，返回每个生肖的当前遗漏 + 历史最高遗漏 + 覆盖号数。"""
    last_seen = {z: -1 for z in DEFAULT_ZODIAC}
    hist_max = {z: 0 for z in DEFAULT_ZODIAC}
    for i, r in enumerate(rows):
        zm = _map_for(r, cycle_maps)
        z = _num_to_zodiac(int(r["source_number"]), zm)
        if not z:
            continue
        seq = i + 1
        if last_seen[z] >= 0:
            gap = seq - last_seen[z]
            hist_max[z] = max(hist_max[z], gap)
        last_seen[z] = seq
    total_seq = len(rows)
    cur = {}
    for z in DEFAULT_ZODIAC:
        cur[z] = total_seq - last_seen[z] if last_seen[z] >= 0 else total_seq
    nums = {z: len(DEFAULT_ZODIAC[z]) for z in DEFAULT_ZODIAC}
    return cur, hist_max, nums


def _zodiac_cold_list(cur, hist_max, nums, threshold=ZODIAC_TRACK_THRESHOLD):
    """当前冷肖列表（遗漏≥threshold），按遗漏降序。"""
    cold = []
    for z in DEFAULT_ZODIAC:
        if cur[z] >= threshold:
            cold.append({
                "zodiac": z, "gap": cur[z], "hist_max": hist_max[z],
                "nums": DEFAULT_ZODIAC[z], "N": nums[z],
                "diff_to_max": hist_max[z] - cur[z],
            })
    cold.sort(key=lambda x: -x["gap"])
    return cold


def _zodiac_backtest(theta=ZODIAC_TRACK_THRESHOLD, K=ZODIAC_TRACK_K, max_track=ZODIAC_MAX_TRACK, bet_n=ZODIAC_BET_N, per=1.0):
    """6肖全冷事件回测（per 元/号口径，默认1元）：开始=≥max_track肖同时遗漏≥theta，下单买最冷bet_n个肖，任意1个开或满K期结束。"""
    db = get_db()
    cycle_maps, rows = _zodiac_track_load(db)
    db.close()
    last_seen = {z: -1 for z in DEFAULT_ZODIAC}
    nums = {z: len(DEFAULT_ZODIAC[z]) for z in DEFAULT_ZODIAC}
    positions = {}  # zodiac -> {"held": int, "invest": float}
    cold6 = set()   # 当前事件的6肖全集（口径A：任意1个开出即结束）
    rounds = []     # 每事件一条
    equity = 0.0
    peak = 0.0
    maxdd = 0.0
    for i in range(len(rows)):
        r = rows[i]
        zm = _map_for(r, cycle_maps)
        z_open = _num_to_zodiac(int(r["source_number"]), zm)
        if not z_open:
            continue
        seq = i + 1
        # 空仓期扫描建仓（必须≥max_track个肖同时遗漏≥theta才触发，下单锁定最冷bet_n个）
        if not positions:
            cold6 = set()   # 空仓先清空，防止残留上一轮6肖
            gap = {z: seq - last_seen[z] for z in DEFAULT_ZODIAC}
            cold = [z for z in DEFAULT_ZODIAC if gap[z] >= theta]
            cold.sort(key=lambda z: -gap[z])
            if len(cold) >= max_track:
                cold6 = set(cold[:max_track])   # 6肖全集（买的最冷bet_n个 + 后3位）
                for z in cold[:bet_n]:
                    positions[z] = {"held": 0, "invest": 0.0}
        # 推进：任意1个冷肖开出 → 整个事件结算
        if z_open in positions:
            hit_z = z_open
            event_pnl = 0.0
            hit_held = None
            for z in list(positions.keys()):
                pos = positions[z]
                pos["held"] += 1
                N = nums[z]
                cost = N * per
                pos["invest"] += cost
                equity -= cost
                if z == hit_z:
                    payout = 47 * per
                    equity += payout
                    event_pnl += payout - pos["invest"]
                    hit_held = pos["held"]
                else:
                    event_pnl += -pos["invest"]
                del positions[z]
            rounds.append({"zodiac": hit_z, "held": hit_held, "result": "hit",
                           "pnl": round(event_pnl, 2), "date": r["record_date"]})
        elif z_open in cold6:
            # 口径A：6肖中后3位开出（未买）→ 持仓全部止损平仓
            event_pnl = 0.0
            end_held = None
            for z in list(positions.keys()):
                pos = positions[z]
                pos["held"] += 1
                N = nums[z]
                cost = N * per
                pos["invest"] += cost
                equity -= cost
                event_pnl += -pos["invest"]
                end_held = pos["held"]
                del positions[z]
            rounds.append({"zodiac": z_open, "held": end_held, "result": "stop",
                           "pnl": round(event_pnl, 2), "date": r["record_date"]})
        else:
            for z in positions:
                pos = positions[z]
                pos["held"] += 1
                N = nums[z]
                cost = N * per
                pos["invest"] += cost
                equity -= cost
            # 满K期止损：任一持仓肖 held >= K，整个事件止损结束（防御极尾）
            if positions and any(pos["held"] >= K for pos in positions.values()):
                event_pnl = 0.0
                for z in list(positions.keys()):
                    pos = positions[z]
                    event_pnl += -pos["invest"]
                    del positions[z]
                rounds.append({"zodiac": None, "held": K, "result": "stop",
                               "pnl": round(event_pnl, 2), "date": r["record_date"]})
        peak = max(peak, equity)
        maxdd = min(maxdd, equity - peak)
        last_seen[z_open] = seq

    hits = sum(1 for x in rounds if x["result"] == "hit")  # 命中事件数（满K止损不计入命中）
    total = sum(x["pnl"] for x in rounds)
    pnls = [x["pnl"] for x in rounds]
    max_streak = cur_streak = 0
    for p in pnls:
        if p < 0:
            cur_streak += 1; max_streak = max(max_streak, cur_streak)
        else:
            cur_streak = 0
    helds = [x["held"] for x in rounds if x["held"]]
    return {
        "threshold": theta, "K": K, "max_track": max_track, "bet_n": bet_n, "per": per,
        "rounds": len(rounds), "hits": hits,
        "hit_rate": round(hits / len(rounds) * 100, 2) if rounds else 0,
        "total_pnl": round(total, 2),
        "avg_pnl": round(total / len(rounds), 2) if rounds else 0,
        "avg_held": round(sum(helds) / len(helds), 1) if helds else 0,
        "max_loss_streak": max_streak, "max_drawdown": round(maxdd, 2),
        "detail": rounds,
    }


@app.get("/api/zodiacTrack/overview")
def zodiac_track_overview(user=Header(None, alias="authorization")):
    """肖跟踪总览：当前冷肖列表 + 6肖全跟踪回测 + 账户/持仓 + 下单指南。"""
    require_user(user)
    db = get_db()
    cycle_maps, rows = _zodiac_track_load(db)
    cur, hist_max, nums = _zodiac_gap_series(rows, cycle_maps)
    cold = _zodiac_cold_list(cur, hist_max, nums)
    # 账户 + 持仓（先读账户以对齐回测 per 口径，与源头事件/账户统一）
    acc = db.execute("SELECT * FROM zodiac_track_account ORDER BY id LIMIT 1").fetchone()
    bt = _zodiac_backtest(per=(acc["per"] if acc else 4))
    positions = db.execute(
        "SELECT * FROM zodiac_track_position WHERE status='holding' ORDER BY id").fetchall()
    source_rows = db.execute(
        "SELECT * FROM zodiac_track_source ORDER BY source_date DESC LIMIT 50").fetchall()
    pos_rows = db.execute(
        "SELECT source_id, zodiac, held, close_reason, status FROM zodiac_track_position").fetchall()
    db.close()
    account = dict(acc) if acc else None
    holding = [dict(p) for p in positions]
    # 按 source_id 分组持仓，用于回填解冻期数（命中=第几期开，止损=None，持有=-1跟踪中）
    pos_by_source = {}
    for p in pos_rows:
        pos_by_source.setdefault(p["source_id"], []).append(p)
    sources = []
    for s in source_rows:
        sd = dict(s)
        try:
            zodiacs = json.loads(s["zodiacs_json"]) if s["zodiacs_json"] else []
        except Exception:
            zodiacs = []
        pmap = {p["zodiac"]: p for p in pos_by_source.get(s["id"], [])}
        for z in zodiacs:
            p = pmap.get(z["zodiac"])
            if p and p["close_reason"] == "hit":
                z["unfreeze"] = p["held"]          # 从源头起第几期开
            elif p and p["status"] == "holding":
                z["unfreeze"] = -1                 # 跟踪中（未开）
            else:
                z["unfreeze"] = None               # 止损（12期内未开）
        # 首个开的肖 + 持续期数（任意1个开即结束，hit恒1个）
        hit_pos = [p for p in pmap.values() if p["close_reason"] == "hit"]
        sd["first_open"] = hit_pos[0]["zodiac"] if hit_pos else None
        sd["dur"] = hit_pos[0]["held"] if hit_pos else None
        # active 事件：已跟踪期数（还未开）
        if sd["status"] == "active":
            holding_pos = [p for p in pmap.values() if p["status"] == "holding"]
            sd["cur_dur"] = holding_pos[0]["held"] if holding_pos else 0
        sd["zodiacs"] = zodiacs
        sources.append(sd)
    holding_set = {p["zodiac"] for p in holding}
    for c in cold:
        c["tracking"] = c["zodiac"] in holding_set
    # 下单指南：持仓中显示当前持仓，空仓显示下一轮候选 Top6
    guide = {}
    if account:
        per = account["per"] or 4
        cold_map = {c["zodiac"]: c for c in cold}
        if holding:
            mode = "holding"
            targets = []
            for h in holding:
                c = cold_map.get(h["zodiac"])
                if c:
                    targets.append({"zodiac": c["zodiac"], "gap": c["gap"], "hist_max": c["hist_max"],
                                    "nums": c["nums"], "N": c["N"], "held": h["held"]})
                else:
                    znums = DEFAULT_ZODIAC.get(h["zodiac"], [])
                    targets.append({"zodiac": h["zodiac"], "gap": None, "hist_max": None,
                                    "nums": znums, "N": len(znums), "held": h["held"]})
        else:
            mode = "ready"
            targets = [{"zodiac": c["zodiac"], "gap": c["gap"], "hist_max": c["hist_max"],
                        "nums": c["nums"], "N": c["N"], "held": 0} for c in cold[:ZODIAC_BET_N]]
        total_N = sum(t["N"] for t in targets)
        guide = {
            "per": per, "mode": mode,
            "target_zodiacs": [t["zodiac"] for t in targets],
            "target_count": len(targets),
            "targets": targets,
            "total_N": total_N,
            "per_round_invest": total_N * per,               # 每期总投入（全部持仓）
            "stop_loss": total_N * ZODIAC_TRACK_K * per,     # 单轮全止损
            "capital": account["capital"],
            "risk_ratio": round(total_N * ZODIAC_TRACK_K * per / account["capital"] * 100, 1) if account["capital"] else 0,
        }
    return {
        "threshold": ZODIAC_TRACK_THRESHOLD, "K": ZODIAC_TRACK_K, "max_track": ZODIAC_MAX_TRACK, "bet_n": ZODIAC_BET_N,
        "cold": cold, "cold_count": len(cold),
        "backtest": bt,
        "account": account,
        "holding": holding, "holding_count": len(holding),
        "sources": sources, "source_count": len(sources),
        "guide": guide,
    }


@app.post("/api/zodiacTrack/init")
def zodiac_track_init(capital: float = 3000, per: float = 4, user=Header(None, alias="authorization")):
    """初始化/重置肖跟踪账户（清空账户、订单、持仓）。"""
    require_admin(user)
    db = get_db()
    db.execute("DELETE FROM zodiac_track_account")
    db.execute("DELETE FROM zodiac_track_order")
    db.execute("DELETE FROM zodiac_track_position")
    db.execute("DELETE FROM zodiac_track_source")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    warn_th = max(500.0, round(capital * 0.05, 2))  # 预警线：本金5%，最低500
    db.execute(
        "INSERT INTO zodiac_track_account (capital, initial_capital, per, warn_threshold, status, tracking_zodiac, held, enter_date, last_settle_date, create_time, update_time) VALUES (?,?,?,?,'running','',0,'','',?,?)",
        (capital, capital, per, warn_th, now, now))
    db.commit()
    row = db.execute("SELECT * FROM zodiac_track_account ORDER BY id LIMIT 1").fetchone()
    db.close()
    return {"ok": True, "account": dict(row)}


@app.post("/api/zodiacTrack/settle")
def zodiac_track_settle(user=Header(None, alias="authorization")):
    """每日结算：6肖全跟踪，推进账户到最新开奖日期。"""
    require_user(user)
    db = get_db()
    acc = db.execute("SELECT * FROM zodiac_track_account ORDER BY id LIMIT 1").fetchone()
    if not acc:
        db.close()
        raise HTTPException(400, "账户未初始化，请先 init")
    cycle_maps, rows = _zodiac_track_load(db)
    last_date = rows[-1]["record_date"] if rows else ""
    last_settle = acc["last_settle_date"] or ""
    nums = {z: len(DEFAULT_ZODIAC[z]) for z in DEFAULT_ZODIAC}

    # 从 last_settle 之后逐期推进
    start_idx = 0
    if last_settle:
        for i, r in enumerate(rows):
            if r["record_date"] > last_settle:
                start_idx = i
                break
        else:
            start_idx = len(rows)
    # 重建 last_seen（截至 start_idx 之前）
    last_seen = {z: -1 for z in DEFAULT_ZODIAC}
    for i in range(start_idx):
        zm = _map_for(rows[i], cycle_maps)
        z = _num_to_zodiac(int(rows[i]["source_number"]), zm)
        if z:
            last_seen[z] = i + 1

    # 加载当前持仓（6肖并行）
    positions = {}  # zodiac -> {"id", "held", "invest", "enter_date"}
    for p in db.execute("SELECT * FROM zodiac_track_position WHERE status='holding'").fetchall():
        positions[p["zodiac"]] = {"id": p["id"], "held": p["held"] or 0,
                                  "invest": p["total_invest"] or 0.0,
                                  "enter_date": p["enter_date"] or ""}
    # 重建 cold6（当前 active 源头的6肖全集，口径A：任意1个开出即结束）
    cold6 = set()
    for s in db.execute("SELECT zodiacs_json FROM zodiac_track_source WHERE status='active'").fetchall():
        try:
            for zitem in (json.loads(s["zodiacs_json"]) if s["zodiacs_json"] else []):
                cold6.add(zitem["zodiac"])
        except Exception:
            pass
    capital = acc["capital"]
    per = acc["per"] or 4
    new_orders = 0
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for i in range(start_idx, len(rows)):
        r = rows[i]
        zm = _map_for(r, cycle_maps)
        z_open = _num_to_zodiac(int(r["source_number"]), zm)
        if not z_open:
            continue
        seq = i + 1
        d = r["record_date"]
        # 空仓期扫描建仓（必须≥6肖同时遗漏≥阈值才触发，记录源头事件）
        if not positions:
            cold6 = set()   # 空仓先清空，防止残留上一轮6肖
            gap = {z: seq - last_seen[z] for z in DEFAULT_ZODIAC}
            cold = [z for z in DEFAULT_ZODIAC if gap[z] >= ZODIAC_TRACK_THRESHOLD]
            cold.sort(key=lambda z: -gap[z])
            if len(cold) >= ZODIAC_MAX_TRACK:
                cold6 = set(cold[:ZODIAC_MAX_TRACK])   # 6肖全集（买的最冷bet_n个 + 后3位）
                source_zodiacs = [{"zodiac": z, "gap": gap[z], "nums": DEFAULT_ZODIAC.get(z, [])} for z in cold[:ZODIAC_MAX_TRACK]]
                source_id = db.execute(
                    "INSERT INTO zodiac_track_source (source_date, zodiacs_json, status, create_time, update_time) VALUES (?,?,?,?,?)",
                    (d, json.dumps(source_zodiacs, ensure_ascii=False), 'active', now, now)).lastrowid
                for z in cold[:ZODIAC_BET_N]:
                    cur = db.execute(
                        "INSERT INTO zodiac_track_position (source_id, zodiac, enter_date, held, status, total_invest, create_time, update_time) VALUES (?,?,?,0,'holding',0,?,?)",
                        (source_id, z, d, now, now)).lastrowid
                    positions[z] = {"id": cur, "held": 0, "invest": 0.0, "enter_date": d, "source_id": source_id}
        # 推进：每期买6肖全部号；任意1个6肖开出 → 整个事件结算结束
        if z_open in positions:
            # 本期开出买的冷肖 → 命中1个 + 其余平仓
            hit_z = z_open
            for z in list(positions.keys()):
                pos = positions[z]
                pos["held"] += 1
                N = nums[z]
                cost = N * per
                pos["invest"] += cost
                capital -= cost
                held_now = pos["held"]
                if z == hit_z:
                    payout = 47 * per
                    capital += payout
                    pnl = payout - pos["invest"]
                    result = "hit"
                else:
                    pnl = -pos["invest"]
                    result = "stop"
                db.execute(
                    "INSERT INTO zodiac_track_order (bet_date, zodiac, nums_json, N, held, result, open_zodiac, pnl, capital_after, create_time) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (d, z, json.dumps(DEFAULT_ZODIAC.get(z, [])), N, held_now, result, z_open, round(pnl, 2), round(capital, 2), now))
                db.execute(
                    "UPDATE zodiac_track_position SET held=?, status='closed', close_date=?, close_reason=?, total_invest=?, update_time=? WHERE id=?",
                    (held_now, d, result, round(pos["invest"], 2), now, pos["id"]))
                new_orders += 1
                del positions[z]
        elif z_open in cold6:
            # 口径A：6肖中后3位开出（未买）→ 持仓全部止损平仓
            for z in list(positions.keys()):
                pos = positions[z]
                pos["held"] += 1
                N = nums[z]
                cost = N * per
                pos["invest"] += cost
                capital -= cost
                held_now = pos["held"]
                pnl = -pos["invest"]
                db.execute(
                    "INSERT INTO zodiac_track_order (bet_date, zodiac, nums_json, N, held, result, open_zodiac, pnl, capital_after, create_time) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (d, z, json.dumps(DEFAULT_ZODIAC.get(z, [])), N, held_now, "stop", z_open, round(pnl, 2), round(capital, 2), now))
                db.execute(
                    "UPDATE zodiac_track_position SET held=?, status='closed', close_date=?, close_reason='stop', total_invest=?, update_time=? WHERE id=?",
                    (held_now, d, round(pos["invest"], 2), now, pos["id"]))
                new_orders += 1
                del positions[z]
        else:
            # 本期无冷肖开出 → 继续持有（满K期止损：任一肖 held>=K 则整个事件止损结束）
            stop_all = any(pos["held"] + 1 >= ZODIAC_TRACK_K for pos in positions.values())
            for z in list(positions.keys()):
                pos = positions[z]
                pos["held"] += 1
                N = nums[z]
                cost = N * per
                pos["invest"] += cost
                capital -= cost
                held_now = pos["held"]
                if stop_all:
                    pnl = -pos["invest"]
                    db.execute(
                        "INSERT INTO zodiac_track_order (bet_date, zodiac, nums_json, N, held, result, open_zodiac, pnl, capital_after, create_time) VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (d, z, json.dumps(DEFAULT_ZODIAC.get(z, [])), N, held_now, "stop", z_open, round(pnl, 2), round(capital, 2), now))
                    db.execute(
                        "UPDATE zodiac_track_position SET held=?, status='closed', close_date=?, close_reason='stop', total_invest=?, update_time=? WHERE id=?",
                        (held_now, d, round(pos["invest"], 2), now, pos["id"]))
                    del positions[z]
                else:
                    db.execute(
                        "INSERT INTO zodiac_track_order (bet_date, zodiac, nums_json, N, held, result, open_zodiac, pnl, capital_after, create_time) VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (d, z, json.dumps(DEFAULT_ZODIAC.get(z, [])), N, held_now, "hold", z_open, None, round(capital, 2), now))
                    db.execute(
                        "UPDATE zodiac_track_position SET held=?, total_invest=?, update_time=? WHERE id=?",
                        (held_now, round(pos["invest"], 2), now, pos["id"]))
                new_orders += 1
        last_seen[z_open] = seq

    # 清理已结束的源头事件（active 且所有持仓都关闭）
    for s in db.execute("SELECT * FROM zodiac_track_source WHERE status='active'").fetchall():
        sid = s["id"]
        open_cnt = db.execute(
            "SELECT COUNT(*) FROM zodiac_track_position WHERE source_id=? AND status='holding'", (sid,)).fetchone()[0]
        if open_cnt == 0:
            hit = db.execute(
                "SELECT COUNT(*) FROM zodiac_track_position WHERE source_id=? AND close_reason='hit'", (sid,)).fetchone()[0]
            stop = db.execute(
                "SELECT COUNT(*) FROM zodiac_track_position WHERE source_id=? AND close_reason='stop'", (sid,)).fetchone()[0]
            hit_pnl = db.execute(
                "SELECT COALESCE(SUM(47*? - total_invest),0) FROM zodiac_track_position WHERE source_id=? AND close_reason='hit'", (per, sid)).fetchone()[0]
            stop_pnl = db.execute(
                "SELECT COALESCE(SUM(-total_invest),0) FROM zodiac_track_position WHERE source_id=? AND close_reason='stop'", (sid,)).fetchone()[0]
            end_dt = db.execute(
                "SELECT MAX(close_date) FROM zodiac_track_position WHERE source_id=?", (sid,)).fetchone()[0] or last_date
            db.execute(
                "UPDATE zodiac_track_source SET status='closed', end_date=?, hit_count=?, stop_count=?, total_pnl=?, update_time=? WHERE id=?",
                (end_dt, hit, stop, round(hit_pnl + stop_pnl, 2), now, sid))

    # 更新账户
    if capital <= 0:
        status = "bankrupt"
    elif capital < (acc["warn_threshold"] or 500):
        status = "warn"
    else:
        status = "running"
    db.execute(
        "UPDATE zodiac_track_account SET capital=?, tracking_zodiac=?, held=?, enter_date=?, last_settle_date=?, status=?, update_time=? WHERE id=?",
        (round(capital, 2), "", 0, "", last_date, status, now, acc["id"]))
    db.commit()
    fresh = db.execute("SELECT * FROM zodiac_track_account WHERE id=?", (acc["id"],)).fetchone()
    holding_count = db.execute("SELECT COUNT(*) FROM zodiac_track_position WHERE status='holding'").fetchone()[0]
    db.close()
    return {"ok": True, "new_orders": new_orders, "account": dict(fresh), "holding_count": holding_count}


@app.get("/api/zodiacTrack/orders")
def zodiac_track_orders(limit: int = 200, user=Header(None, alias="authorization")):
    """肖跟踪订单明细。"""
    require_user(user)
    db = get_db()
    rows = db.execute("SELECT * FROM zodiac_track_order ORDER BY bet_date DESC, id DESC LIMIT ?", (limit,)).fetchall()
    db.close()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["nums"] = json.loads(r["nums_json"]) if r["nums_json"] else []
        except Exception:
            d["nums"] = []
        out.append(d)
    return {"orders": out}


@app.post("/api/zodiacTrack/deposit")
def zodiac_track_deposit(amount: float, user=Header(None, alias="authorization")):
    """破产后追加本金。"""
    require_admin(user)
    if amount <= 0:
        raise HTTPException(400, "金额需大于0")
    db = get_db()
    acc = db.execute("SELECT * FROM zodiac_track_account ORDER BY id LIMIT 1").fetchone()
    if not acc:
        db.close()
        raise HTTPException(404, "账户未初始化")
    after = round(acc["capital"] + amount, 2)
    status = "bankrupt" if after <= 0 else ("warn" if after < (acc["warn_threshold"] or 500) else "running")
    db.execute("UPDATE zodiac_track_account SET capital=?, status=?, update_time=? WHERE id=?",
               (after, status, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), acc["id"]))
    db.commit()
    fresh = db.execute("SELECT * FROM zodiac_track_account WHERE id=?", (acc["id"],)).fetchone()
    db.close()
    return {"ok": True, "account": dict(fresh)}


# ============================================================
# 十五·五、随机8码·6期跟踪（随机8码，跟踪6期，命中即下一轮，6期未开止损）
# ============================================================
RANDOM8_SEED = 42          # 随机种子（固定，保证可复现）
RANDOM8_K = 6              # 跟踪期数
RANDOM8_N = 8              # 随机选号数
RANDOM8_ODDS = 47          # 命中赔率（买N号命中只赔1个号=47）


def _random8_load_draws():
    """加载开奖数据（date, number 列表）。"""
    db = get_db()
    rows = db.execute(
        "SELECT record_date, source_number FROM number_knowledge_record WHERE status=1 ORDER BY record_date"
    ).fetchall()
    db.close()
    dates, nums = [], []
    for r in rows:
        try:
            n = int(r["source_number"])
        except (ValueError, TypeError):
            continue
        if 1 <= n <= 49:
            dates.append(r["record_date"])
            nums.append(n)
    return dates, nums


def _random8_picks(round_no, seed=RANDOM8_SEED):
    """按轮次号生成确定性随机8码（可复现）。"""
    r = random.Random(seed * 100000 + round_no)
    return sorted(r.sample(range(1, 50), RANDOM8_N))


def _random8_backtest(seed=RANDOM8_SEED, per=1.0):
    """随机8码·6期跟踪 回测：逐轮随机8码，跟踪6期，命中(8码中1个开出)即结束，6期未开止损。
    落库 random8_round，返回汇总 + 最新一轮 + 下一轮预告。"""
    dates, draws = _random8_load_draws()
    if not dates:
        return {"rounds": 0, "hits": 0, "stops": 0, "hit_rate": 0, "total_pnl": 0,
                "avg_pnl": 0, "hit_dist": {}, "profit_rounds": 0, "loss_rounds": 0,
                "detail": [], "latest": None, "next": None}
    N = len(draws)
    rounds = []
    i = 0
    round_no = 0
    while i < N:
        round_no += 1
        picks = _random8_picks(round_no, seed)
        picks_set = set(picks)
        start_date = dates[i]
        hit_period = 0
        hit_number = 0
        result = "stop"
        max_periods = min(RANDOM8_K, N - i)
        for k in range(1, max_periods + 1):
            if draws[i + k - 1] in picks_set:
                hit_period = k
                hit_number = draws[i + k - 1]
                result = "hit"
                break
        if result == "hit":
            pnl = RANDOM8_ODDS * per - RANDOM8_N * per * hit_period
            invest = RANDOM8_N * per * hit_period
            end_date = dates[i + hit_period - 1]
            rounds.append({"round": round_no, "start": start_date, "end": end_date,
                           "picks": picks, "hit_period": hit_period, "hit_number": hit_number,
                           "result": "hit", "invest": round(invest, 2), "pnl": round(pnl, 2)})
            i += hit_period
        else:
            # 未命中
            if max_periods < RANDOM8_K:
                # 数据不足6期（最后一批数据），本轮进行中，未结束
                invest = RANDOM8_N * per * max_periods
                end_date = dates[i + max_periods - 1]
                rounds.append({"round": round_no, "start": start_date, "end": end_date,
                               "picks": picks, "hit_period": 0, "hit_number": 0,
                               "result": "ongoing", "periods": max_periods,
                               "invest": round(invest, 2), "pnl": round(-invest, 2)})
            else:
                # 完整6期未开，止损
                pnl = -RANDOM8_N * per * max_periods
                invest = RANDOM8_N * per * max_periods
                end_date = dates[i + max_periods - 1]
                rounds.append({"round": round_no, "start": start_date, "end": end_date,
                               "picks": picks, "hit_period": 0, "hit_number": 0,
                               "result": "stop", "invest": round(invest, 2), "pnl": round(pnl, 2)})
            i += max_periods
    # 落库
    db = get_db()
    db.execute("DELETE FROM random8_round")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for r in rounds:
        db.execute(
            "INSERT INTO random8_round (round_no, numbers_json, start_date, end_date, hit_period, hit_number, result, total_invest, pnl, create_time) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (r["round"], ",".join(str(n) for n in r["picks"]), r["start"], r["end"],
             r["hit_period"], r["hit_number"], r["result"], r["invest"], r["pnl"], now))
    db.commit()
    db.close()
    # 汇总
    total = sum(r["pnl"] for r in rounds)
    hits = sum(1 for r in rounds if r["result"] == "hit")
    stops = sum(1 for r in rounds if r["result"] == "stop")
    ongoing = sum(1 for r in rounds if r["result"] == "ongoing")
    from collections import Counter
    hit_dist = Counter(r["hit_period"] for r in rounds if r["hit_period"] > 0)
    profit_rounds = sum(1 for r in rounds if r["pnl"] > 0)
    loss_rounds = sum(1 for r in rounds if r["pnl"] <= 0)
    latest = rounds[-1] if rounds else None
    # 下一步预告
    nxt = None
    if latest:
        if latest["result"] == "ongoing":
            # 进行中：下一期继续同一组8码
            nxt = {"type": "continue", "round": latest["round"], "picks": latest["picks"],
                   "next_period": latest.get("periods", 0) + 1,
                   "note": f"本轮进行中，第{latest.get('periods', 0)}期未开，继续买同一组8码"}
        else:
            # 已结束（命中/止损）：下一轮重新随机8码
            next_round_no = round_no + 1
            next_picks = _random8_picks(next_round_no, seed)
            nxt = {"type": "new_round", "round": next_round_no, "picks": next_picks,
                   "start_hint": latest["end"] + " 之后",
                   "note": "上一轮已结束，下一轮重新随机8码"}
    return {
        "seed": seed, "K": RANDOM8_K, "N": RANDOM8_N, "odds": RANDOM8_ODDS, "per": per,
        "date_range": f"{dates[0]} ~ {dates[-1]}", "total_days": N,
        "rounds": len(rounds), "hits": hits, "stops": stops, "ongoing": ongoing,
        "hit_rate": round(hits / (len(rounds) - ongoing) * 100, 2) if len(rounds) > ongoing else 0,
        "total_pnl": round(total, 2),
        "avg_pnl": round(total / len(rounds), 2) if rounds else 0,
        "hit_dist": dict(sorted(hit_dist.items())),
        "profit_rounds": profit_rounds, "loss_rounds": loss_rounds,
        "detail": rounds, "latest": latest, "next": nxt,
    }


@app.get("/api/random8/overview")
def random8_overview(user=Header(None, alias="authorization")):
    """随机8码·6期跟踪 总览：回测汇总 + 最新一轮 + 下一轮预告。"""
    require_user(user)
    return _random8_backtest()


@app.post("/api/random8/backtest")
def random8_backtest(user=Header(None, alias="authorization")):
    """手动触发回测（重新落库）。"""
    require_admin(user)
    return _random8_backtest()


# ============================================================
# 十五·六、固定下单（随机8码，倍投10/10/10/20/20/20，6期周期，6期未中暂停等开出再继续）
# ============================================================
FIXED_SEED = 42          # 随机种子（固定，保证可复现）
FIXED_K = 6              # 跟踪期数
FIXED_N = 8              # 选号数
FIXED_ODDS = 47          # 命中赔率
FIXED_BET_PLAN = [10, 10, 10, 20, 20, 20]   # 每期每号下注金额
FIXED_START_DATE = "2022-01-01"  # 回测起始日期


def _fixed_order_picks(round_no, seed=FIXED_SEED):
    """按轮次号生成确定性随机8码（可复现）。"""
    r = random.Random(seed * 100000 + round_no)
    return sorted(r.sample(range(1, 50), FIXED_N))


def _fixed_order_backtest(seed=FIXED_SEED, start_date=FIXED_START_DATE):
    """固定下单回测：随机8码，6期周期，倍投 10/10/10/20/20/20。

    命中（6期内8码开出1个）→ 下一轮重新随机8码；
    6期未中 → 止损，暂停等待这8码里开出1个 → 下一轮重新随机。
    落库 fixed_order_round，返回汇总 + 最新一轮 + 下一轮预告。
    """
    dates, nums = _random8_load_draws()
    if not dates:
        return {"rounds": 0, "hits": 0, "stops": 0, "pauses": 0, "hit_rate": 0, "total_pnl": 0,
                "avg_pnl": 0, "hit_dist": {}, "profit_rounds": 0, "loss_rounds": 0,
                "detail": [], "latest": None, "next": None}
    start_idx = 0
    for i, d in enumerate(dates):
        if d >= start_date:
            start_idx = i
            break
    dates = dates[start_idx:]
    nums = nums[start_idx:]
    N = len(nums)

    rounds = []
    i = 0
    round_no = 0
    state = "NEW"   # NEW / TRACKING / PAUSED
    picks = []
    picks_set = set()
    held = 0
    invest = 0
    start = None
    last_stop_end = None
    pause_count = 0

    while i < N:
        if state == "NEW":
            round_no += 1
            picks = _fixed_order_picks(round_no, seed)
            picks_set = set(picks)
            held = 0
            invest = 0
            start = dates[i]
            state = "TRACKING"

        if state == "TRACKING":
            held += 1
            bet = FIXED_BET_PLAN[held - 1]
            invest += FIXED_N * bet
            actual = nums[i]
            if actual in picks_set:
                pnl = FIXED_ODDS * bet - invest
                rounds.append({"round": round_no, "start": start, "end": dates[i],
                               "picks": picks, "hit_period": held, "hit_number": actual,
                               "result": "hit", "invest": invest, "pnl": pnl})
                state = "NEW"
            elif held >= FIXED_K:
                pnl = -invest
                last_stop_end = dates[i]
                rounds.append({"round": round_no, "start": start, "end": dates[i],
                               "picks": picks, "hit_period": 0, "hit_number": 0,
                               "result": "stop", "invest": invest, "pnl": pnl})
                state = "PAUSED"
                pause_count = 0
            i += 1
            continue

        if state == "PAUSED":
            pause_count += 1
            if nums[i] in picks_set:
                rounds.append({"round": round_no, "start": last_stop_end, "end": dates[i],
                               "picks": picks, "hit_period": 0, "hit_number": nums[i],
                               "result": "pause", "invest": 0, "pnl": 0,
                               "pause_len": pause_count})
                state = "NEW"
            i += 1
            continue

    # 落库
    db = get_db()
    db.execute("DELETE FROM fixed_order_round")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for r in rounds:
        db.execute(
            "INSERT INTO fixed_order_round (round_no, numbers_json, start_date, end_date, hit_period, hit_number, result, pause_len, total_invest, pnl, create_time) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (r["round"], ",".join(f"{n:02d}" for n in r["picks"]), r["start"], r["end"],
             r["hit_period"], r["hit_number"], r["result"], r.get("pause_len", 0),
             r["invest"], r["pnl"], now))
    db.commit()
    db.close()

    # 汇总
    total = sum(r["pnl"] for r in rounds)
    hits = sum(1 for r in rounds if r["result"] == "hit")
    stops = sum(1 for r in rounds if r["result"] == "stop")
    pauses = sum(1 for r in rounds if r["result"] == "pause")
    from collections import Counter
    hit_dist = Counter(r["hit_period"] for r in rounds if r["hit_period"] > 0)
    profit_rounds = sum(1 for r in rounds if r["pnl"] > 0)
    loss_rounds = sum(1 for r in rounds if r["pnl"] <= 0)
    done = [r for r in rounds if r["result"] in ("hit", "stop")]
    latest = rounds[-1] if rounds else None
    nxt = None
    if latest:
        if latest["result"] == "hit":
            nxt = {"type": "new_round", "round": round_no + 1,
                   "picks": _fixed_order_picks(round_no + 1, seed),
                   "note": "上一轮命中，下一轮重新随机8码"}
        elif latest["result"] == "stop":
            nxt = {"type": "pause", "round": round_no, "picks": latest["picks"],
                   "note": "6期未中已止损，暂停等待这8码开出1个再继续"}
        else:
            nxt = {"type": "pause", "round": round_no, "picks": latest["picks"],
                   "note": "暂停中，等待8码开出"}
    return {
        "seed": seed, "K": FIXED_K, "N": FIXED_N, "odds": FIXED_ODDS,
        "bet_plan": FIXED_BET_PLAN,
        "date_range": f"{dates[0]} ~ {dates[-1]}", "total_days": N,
        "rounds": len(rounds), "hits": hits, "stops": stops, "pauses": pauses,
        "hit_rate": round(hits / len(done) * 100, 2) if done else 0,
        "total_pnl": round(total, 2),
        "avg_pnl": round(total / len(done), 2) if done else 0,
        "hit_dist": dict(sorted(hit_dist.items())),
        "profit_rounds": profit_rounds, "loss_rounds": loss_rounds,
        "detail": rounds, "latest": latest, "next": nxt,
    }


@app.get("/api/fixed-order/overview")
def fixed_order_overview(user=Header(None, alias="authorization")):
    """固定下单 总览：回测汇总 + 最新一轮 + 下一轮预告。"""
    require_user(user)
    return _fixed_order_backtest()


@app.post("/api/fixed-order/backtest")
def fixed_order_backtest(user=Header(None, alias="authorization")):
    """手动触发固定下单回测（重新落库）。"""
    require_admin(user)
    return _fixed_order_backtest()


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
# 十七·五、多组汇总（4家预测数据：鬼/大家/诸葛/好运）
# ============================================================
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

MULTI_GROUP_CONSTRAINTS = {
    "zodiac": "12生肖（鼠牛虎兔龙蛇马羊猴鸡狗猪）",
    "tail": "尾数 0-9",
    "codes": "号码 1-49",
    "size": "大 / 小",
    "wave": "红 / 蓝 / 绿",
    "oddeven": "单 / 双",
}


@app.get("/api/multiGroup/meta")
def multi_group_meta(user=Header(None, alias="authorization")):
    """多组汇总：4家列定义 + 约束规则。"""
    require_user(user)
    fam_map = {}
    for f, cname, fam, ctype, expect in MULTI_GROUP_COLS:
        fam_map.setdefault(fam, []).append({"field": f, "label": cname, "type": ctype, "expect": expect})
    families = [{"key": fam, "cols": cols} for fam, cols in fam_map.items()]
    return {"families": families, "constraints": MULTI_GROUP_CONSTRAINTS}


@app.get("/api/multiGroup/list")
def multi_group_list(family: str = "鬼", page: int = 1, size: int = 20, period: str = "",
                     date_from: str = "", date_to: str = "", user=Header(None, alias="authorization")):
    """多组汇总：按家分页查询，支持期数/日期范围筛选。"""
    require_user(user)
    db = get_db()
    cols = [c[0] for c in MULTI_GROUP_COLS if c[2] == family]
    if not cols:
        cols = [c[0] for c in MULTI_GROUP_COLS if c[2] == "鬼"]
    where = ["1=1"]
    args = []
    if period:
        where.append("period LIKE ?")
        args.append(f"%{period}%")
    if date_from:
        where.append("draw_date >= ?")
        args.append(date_from)
    if date_to:
        where.append("draw_date <= ?")
        args.append(date_to)
    w = " AND ".join(where)
    total = db.execute(f"SELECT COUNT(*) FROM multi_group_summary WHERE {w}", args).fetchone()[0]
    select_cols = "draw_date, period, " + ", ".join(cols)
    offset = (max(1, page) - 1) * size
    rows = db.execute(
        f"SELECT {select_cols} FROM multi_group_summary WHERE {w} ORDER BY draw_date DESC LIMIT ? OFFSET ?",
        args + [size, offset]).fetchall()
    db.close()
    col_meta = [{"field": c[0], "label": c[1], "type": c[3], "expect": c[4]} for c in MULTI_GROUP_COLS if c[2] == family]
    return {
        "rows": [dict(r) for r in rows],
        "cols": col_meta,
        "total": total, "page": page, "size": size,
        "pages": (total + size - 1) // size if size else 0,
    }


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
