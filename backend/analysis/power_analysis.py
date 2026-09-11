#!/usr/bin/env python3
"""前向验证统计功效（power）分析 — 回答「还要等多久才有定论」。

共识信号前向跟踪已启动（cron 每日固化），但样本积累慢。
本脚本算：以 80% 功效、5% 显著性，检测不同超额水平所需的前向样本量，
再按触发率折算成「日历天数」，给出诚实的时间预期。

二项检验功效近似（单侧）：
  n ≈ (z_α·√(p0(1-p0)) + z_β·√(p1(1-p1)))² / (p1-p0)²
"""
import json, math, os
from scipy import stats

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

Z_ALPHA = stats.norm.ppf(0.95)   # 单侧 5% = 1.645
Z_BETA = stats.norm.ppf(0.80)    # 80% 功效 = 0.842


def required_periods(p0, p1):
    """检测 p0 -> p1 所需样本量（单侧二项，80%功效）。"""
    diff = p1 - p0
    if diff <= 0:
        return float("inf")
    num = (Z_ALPHA * math.sqrt(p0 * (1 - p0)) + Z_BETA * math.sqrt(p1 * (1 - p1))) ** 2
    return num / (diff ** 2)


# 共识信号参数（全历史 rolling：命中率42.8%，均号18.7，触发率58%）
avg_n = 18.7
rand_base = avg_n / 49          # 0.3816
hit_rate = 0.428                # 0.428
trigger_rate = 362 / 618        # 0.586 触发率

print("=" * 72)
print("前向验证统计功效分析 · 共识信号（春夏秋冬+红肖蓝肖绿肖 4变体≥2票）")
print("=" * 72)
print(f"随机基线 p0 = {rand_base:.4f}（均号 {avg_n}/49）")
print(f"回测命中率 p1 = {hit_rate:.4f}（超额 {hit_rate-rand_base:+.4f}）")
print(f"触发率 = {trigger_rate:.1%}（362/618 期）")
print()

scenarios = [
    ("+4.7%（回测全历史超额）", rand_base + 0.047),
    ("+7%（近期半年段）", rand_base + 0.07),
    ("+10%（样本外单段）", rand_base + 0.10),
    ("+12.5%（样本外高点）", rand_base + 0.125),
]

rows_out = []
print(f"{'超额水平':<24s} {'需触发期数':>10s} {'需日历天数':>10s} {'时间预期':>10s}")
print("-" * 72)
for label, p1 in scenarios:
    n = required_periods(rand_base, p1)
    days = n / trigger_rate if n != float("inf") else float("inf")
    if days >= 365:
        time_est = f"{days/365:.1f} 年"
    else:
        time_est = f"{days/30:.1f} 月"
    print(f"{label:<24s} {n:>10.0f} {days:>10.0f} {time_est:>10s}")
    rows_out.append({"alpha_label": label, "p1": round(p1, 4),
                     "periods": round(n), "days": round(days), "time_est": time_est})

# 检测「失效」（前向无超额，alpha=0，即 p1=rand_base 附近）——反向：要多久才能确认"没信号"
print()
print("反向场景：前向若「失效」（真实超额≈0），要多久才能确认淘汰？")
print("-" * 72)
# 检测 alpha=+2% 这个"微弱但非零"的阈值，若达不到说明没信号
n_fail = required_periods(rand_base, rand_base + 0.02)
days_fail = n_fail / trigger_rate
print(f"检测「超额 < +2%（视为失效）」需 {n_fail:.0f} 期 ≈ {days_fail:.0f} 天 ≈ {days_fail/365:.1f} 年")

out = {
    "signal": "共识信号 4变体≥2票",
    "p0": round(rand_base, 4), "p1_backtest": hit_rate,
    "trigger_rate": round(trigger_rate, 4),
    "scenarios": rows_out,
    "fail_detection": {"threshold": "+2%", "periods": round(n_fail), "days": round(days_fail)},
    "conclusion": "共识信号超额+4.7%太小，统计定论需1.8年(按触发率折2.8年)；"
                  "若真实超额达+10%仍需5个月。短期内前向无法统计定论，"
                  "必须依赖月度超额趋势做软判断(连续2-3月负超额→降仓)。",
}
path = os.path.join(BACKEND, "analysis", "power_analysis.json")
json.dump(out, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"\n已写 {path}")
