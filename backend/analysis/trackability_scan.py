#!/usr/bin/env python3
"""演算：各维度"可跟踪性"（修正版）。
口径修正：① hist_max 用 window=60 近2月滚动约束（引擎正确口径，非全量历史憋高）；
② 样本单位 = 「维度-期」（每期该维度有≥1标签憋高位=固化1条前向记录），非「标签-期」。"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import main as M

rows = M.get_db().execute(
    "SELECT * FROM number_knowledge_record WHERE status=1 ORDER BY record_date, id").fetchall()

cycle_maps = {}
for c in M.get_db().execute("SELECT id, zodiac_mapping FROM zodiac_number_cycle_config WHERE is_enable=1").fetchall():
    try:
        m = json.loads(c["zodiac_mapping"])
        cycle_maps[c["id"]] = m if m else M.DEFAULT_ZODIAC
    except Exception:
        cycle_maps[c["id"]] = M.DEFAULT_ZODIAC

def map_for(rec):
    return cycle_maps.get(rec["cycle_id"], M.DEFAULT_ZODIAC)

def run(window, offset):
    last_seen = {}; sample = {}; gap_hist = {}
    trig = {d: 0 for d in M.ALL_DIMS}          # 触发期数（每期该维度最多计1次=1条前向记录）
    total = len(rows)
    for i, r in enumerate(rows):
        seq = i + 1
        for dim, tag in M.match_labels(r["source_number"], map_for(r)).items():
            if not tag:
                continue
            k = (dim, tag)
            if k in last_seen:
                gap = seq - last_seen[k]
                gap_hist.setdefault(k, []).append((seq, gap))
                sample[k] += 1
            else:
                sample[k] = 1
            last_seen[k] = seq
        # 本期末各维度是否有 warning（至少1标签憋高位）
        fired = set()
        for (dim, tag), ls in last_seen.items():
            if sample.get((dim, tag), 0) < 2:
                continue
            hm = M._window_hist_max(gap_hist, (dim, tag), seq, window)
            gap = seq - ls
            if gap >= hm - offset:
                fired.add(dim)
        for d in fired:
            trig[d] += 1
    return trig, total

print("### 可跟踪性演算（window=60 近2月约束 · 维度-期样本）")
print("样本单位 = 每期该维度有≥1标签憋到高位就固化1条前向记录；触发率 = 有信号期数/总期数")
for offset in (0, 1, 2):
    trig, total = run(60, offset)
    print(f"\n===== window=60 · offset={offset} (历史{total}期) =====")
    out = []
    for d in M.ALL_DIMS:
        c = trig[d]
        freq = c / total * 100
        out.append((d, c, freq))
    out.sort(key=lambda x: -x[1])
    print(f"{'维度':<14}{'有信号期数':>10}{'触发率%':>10}{'攒30期(期)':>12}{'攒100期(期)':>12}")
    for d, c, freq in out:
        need30 = int(30 / (c / total)) if c else 99999
        need100 = int(100 / (c / total)) if c else 99999
        if freq >= 15:
            mark = "◀高频可跟踪"
        elif freq >= 8:
            mark = "◆中频"
        else:
            mark = "✕低频难跟踪"
        print(f"{M.DIM_NAMES[d]:<14}{c:>10}{freq:>9.2f}%{need30:>12}期{need100:>12}期  {mark}")

# 对比：全量历史 window=None 下（错误口径，展示为何会憋高熄火）
print("\n\n===== 对照：window=None 全量历史（错误口径，憋高熄火）offset=0 =====")
trig, total = run(None, 0)
out = sorted(((d, trig[d], trig[d]/total*100) for d in M.ALL_DIMS), key=lambda x: -x[1])
for d, c, freq in out:
    print(f"{M.DIM_NAMES[d]:<14}{c:>10}{freq:>9.2f}%")
