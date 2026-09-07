#!/usr/bin/env python3
"""正确口径策略扫描（全量回放）：
标签憋到历史高位(遗漏 gap >= hist_max - offset)终于开出 → 从开完后起算5期，看是否再开。
结算：命中赚(47-N)，未中亏N，每号1元。N=该标签覆盖的号码数。
新增：排除「命中率<55%」的维度（自动识别）。
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import main as M

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
ODDS = 47
HIT_RATE_FLOOR = 0.55

DIM_TAGS = {
    "zodiac": 12, "odd_even": 2, "big_small": 2, "size_odd_even": 4,
    "five_element": 5, "wave_color": 3, "he_sum": 2,
    "animal_type": 2, "zodiac_seq": 2, "beauty_type": 2, "yin_yang": 2,
    "stroke_type": 2, "sky_earth": 2, "edge_color": 2, "gender_zodiac": 2,
    "qqsh_type": 4, "season_type": 4, "zodiac_color_type": 3,
    "head_number": 5, "tail_number": 10,
}
ALL_DIMS = list(DIM_TAGS.keys())
CORE_DIMS = list(M.CORE_DIMS)
MULTI_DIMS = [d for d, t in DIM_TAGS.items() if t >= 3]

db = M.get_db()
cycle = db.execute(
    "SELECT zodiac_mapping FROM zodiac_number_cycle_config WHERE is_enable=1 ORDER BY start_date DESC LIMIT 1").fetchone()
zodiac_map = M.DEFAULT_ZODIAC
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
N_ROWS = len(rows)

_tagnum_cache = {}
def tag_numbers(dim, tag):
    k = (dim, tag)
    if k not in _tagnum_cache:
        _tagnum_cache[k] = [n for n in range(1, 50) if M.match_labels(n, zodiac_map).get(dim) == tag]
    return _tagnum_cache[k]

def run(dims, offset):
    """全量回放，返回 (总events, 总hits, 总profit, per_dim)。"""
    ls = {}; hm = {}; sm = {}
    dimset = set(dims)
    per_dim = {d: {"events": 0, "hits": 0, "profit": 0.0} for d in dims}
    total_events = total_hits = 0
    total_profit = 0.0
    for i, r in enumerate(rows):
        seq = i + 1
        open_num = int(r["source_number"])
        open_labels = M.match_labels(open_num, zodiac_map)
        # 1. 检测高位开出事件（当期开出的标签）
        events_now = []
        for d, t in open_labels.items():
            if not t or d not in dimset:
                continue
            k = (d, t)
            if k in ls:
                gap = seq - ls[k]
                if sm.get(k, 0) >= 2 and gap >= hm.get(k, 0) - offset:
                    events_now.append((d, t, len(tag_numbers(d, t))))
        # 2. 结算（开完后 i+1 .. i+5 共5期）
        for d, t, N in events_now:
            hit = False
            for j in range(i + 1, min(i + 6, N_ROWS)):
                if M.match_labels(rows[j]["source_number"], zodiac_map).get(d) == t:
                    hit = True
                    break
            total_events += 1
            per_dim[d]["events"] += 1
            if hit:
                total_hits += 1
                per_dim[d]["hits"] += 1
                total_profit += ODDS - N
                per_dim[d]["profit"] += ODDS - N
            else:
                total_profit -= N
                per_dim[d]["profit"] -= N
        # 3. 更新状态
        for d, t in open_labels.items():
            if not t:
                continue
            k = (d, t)
            if k in ls:
                gap = seq - ls[k]
                hm[k] = max(hm.get(k, 0), gap)
                sm[k] = sm.get(k, 0) + 1
            else:
                sm[k] = 1
            ls[k] = seq
    return total_events, total_hits, round(total_profit, 2), per_dim

def scheme_row(scheme, offset, ev, ht, pf):
    return {"scheme": scheme, "offset": offset, "profit": pf, "events": ev,
            "hits": ht, "hit_rate": round(ht / ev, 4) if ev else 0.0,
            "per_event": round(pf / ev, 2) if ev else 0.0}

if __name__ == "__main__":
    # 1. 各维度 offset=0 命中率 → 识别低命中维度
    dim_stats = {}
    low_dims = []
    for d in ALL_DIMS:
        ev, ht, pf, _ = run([d], 0)
        hr = ht / ev if ev else 0.0
        dim_stats[d] = (ev, ht, pf, hr)
        if hr < HIT_RATE_FLOOR:
            low_dims.append(d)

    # 2. 方案定义
    keep_high = [d for d in ALL_DIMS if d not in low_dims]
    schemes = [
        ("全维度19", ALL_DIMS),
        ("排除尾数18", [d for d in ALL_DIMS if d != "tail_number"]),
        ("排除低命中%d" % len(keep_high), keep_high),
        ("多标签维度", MULTI_DIMS),
        ("核心6维", CORE_DIMS),
    ]

    scheme_rows = []
    for name, dims in schemes:
        for off in [-2, -1, 0, 1, 2]:
            ev, ht, pf, _ = run(dims, off)
            scheme_rows.append(scheme_row(name, off, ev, ht, pf))

    # 3. dim_rows（offset=0，按 profit 降序）
    dim_rows = []
    for d in ALL_DIMS:
        ev, ht, pf, hr = dim_stats[d]
        dim_rows.append({
            "dim": M.DIM_NAMES.get(d, d), "dim_key": d, "tags": DIM_TAGS[d],
            "events": ev, "hits": ht, "profit": pf,
            "hit_rate": round(hr, 4),
            "per_event": round(pf / ev, 2) if ev else 0.0,
        })
    dim_rows.sort(key=lambda x: -x["profit"])

    # 4. conclusion
    best_profit = max(scheme_rows, key=lambda x: x["profit"])
    best_dim = dim_rows[0]  # profit 最高维度（保持与既有口径一致）

    out = {
        "generated": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "signal": "接近样本·高位开出后起算：标签遗漏≥历史最高−offset 时开出（高位开完）→ 买入该标签号码 → 从开完后5期内再开结算",
        "periods": N_ROWS,
        "odds": ODDS,
        "excluded_low_hit_dims": [M.DIM_NAMES.get(d, d) for d in low_dims],
        "hit_rate_floor": HIT_RATE_FLOOR,
        "scheme_rows": scheme_rows,
        "dim_rows": dim_rows,
        "conclusion": {
            "best_profit": best_profit,
            "best_dim": best_dim,
        },
    }

    path = os.path.join(OUT_DIR, "strategy_scan.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    print("排除的低命中(<%.0f%%)维度:" % (HIT_RATE_FLOOR * 100),
          [M.DIM_NAMES.get(d, d) for d in low_dims])
    print("保留高命中维度数:", len(keep_high))
    print()
    print("=== 各维度 offset=0 命中率 ===")
    for r in dim_rows:
        flag = " <-- 排除" if r["hit_rate"] < HIT_RATE_FLOOR else ""
        print(f"{r['dim']:8s} tags={r['tags']:2d} events={r['events']:3d} hits={r['hits']:3d} "
              f"hit_rate={r['hit_rate']*100:5.1f}% profit={r['profit']:7.1f} per_event={r['per_event']:6.2f}{flag}")
    print()
    print("=== 方案 × offset ===")
    for r in scheme_rows:
        print(f"{r['scheme']:14s} off={r['offset']:+d}: events={r['events']:3d} hits={r['hits']:3d} "
              f"hit_rate={r['hit_rate']*100:5.1f}% profit={r['profit']:7.1f} per_event={r['per_event']:6.2f}")
    print()
    print(f"best_profit: {best_profit['scheme']} offset={best_profit['offset']} profit={best_profit['profit']}")
    print(f"best_dim: {best_dim['dim']} per_event={best_dim['per_event']}")
    print("已写入", path)
