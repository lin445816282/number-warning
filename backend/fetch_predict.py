# -*- coding: utf-8 -*-
"""预测站采集器：Edge CDP → 导航 → 递归 iframe 提取渲染文本 → 解析下一期字段 → 落库 multi_group_summary2。

三家站（中特/金算/聚宝）都是「0149 导航」系统，能直接访问（无验证码）。
采集目标 = 下一期（最新开奖期 + 1）的预测值；占位符字段跳过。
哪吒/米老有滑块验证码，暂不支持（待后续）。
"""
import json, time, re, sqlite3, os, subprocess, urllib.request, urllib.parse
import websocket
from datetime import date, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "data", "number_warning.db")
CDP_HTTP = "http://172.23.128.1:9224"
RESTART_PS1 = r"C:\Temp\restart_cdp_nw.ps1"


def ensure_cdp(timeout=3):
    """确保 CDP Edge 实例存活：9224 不通则拉起独立实例（幂等）。返回 True/False。"""
    try:
        urllib.request.urlopen(CDP_HTTP + "/json/version", timeout=timeout)
        return True
    except Exception:
        pass
    # 拉起独立 CDP 实例（不 taskkill，9222 已监听则脚本内跳过）
    try:
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", RESTART_PS1],
            capture_output=True, timeout=60,
        )
    except Exception:
        pass
    # 等 Edge 就绪（最多 ~14 秒）
    for _ in range(7):
        try:
            urllib.request.urlopen(CDP_HTTP + "/json/version", timeout=3)
            return True
        except Exception:
            time.sleep(2)
    return False


def close_cdp():
    """Browser.close 优雅关闭 CDP 实例（只关独立实例，不影响用户其它 Edge 窗口）。"""
    try:
        req = urllib.request.Request(CDP_HTTP + "/json/version", method="GET")
        info = json.loads(urllib.request.urlopen(req, timeout=5).read())
        ws_url = info.get("webSocketDebuggerUrl")
        if not ws_url:
            return False
        ws = websocket.create_connection(ws_url, timeout=10, suppress_origin=True)
        ws.send(json.dumps({"id": 1, "method": "Browser.close"}))
        # Browser.close 后连接会断开，recv/close 抛异常属正常，send 成功即视为已关闭
        try:
            ws.recv()
        except Exception:
            pass
        try:
            ws.close()
        except Exception:
            pass
        return True
    except Exception:
        return False

ZODIACS = "鼠牛虎兔龙蛇马羊猴鸡狗猪"
WAVES = {"红波": "红", "蓝波": "蓝", "绿波": "绿"}


# ── CDP 工具 ──────────────────────────────────────────────
def new_tab(url):
    req = urllib.request.Request(CDP_HTTP + f"/json/new?{urllib.parse.quote(url)}", method="PUT")
    return json.loads(urllib.request.urlopen(req, timeout=10).read())["webSocketDebuggerUrl"]


def cdp_call(ws, method, params=None, msg_id=1):
    ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
    while True:
        msg = json.loads(ws.recv())
        if msg.get("id") == msg_id:
            return msg


def eval_js(ws, expression, msg_id=100):
    r = cdp_call(ws, "Runtime.evaluate", {"expression": expression, "returnByValue": True}, msg_id)
    return r.get("result", {}).get("result", {}).get("value")


COLLECT_JS = """
(() => {
  function collect(doc) {
    let out = [doc.body ? doc.body.innerText : ''];
    doc.querySelectorAll('iframe').forEach(f => {
      try { if (f.contentDocument) out = out.concat(collect(f.contentDocument)); } catch(e) {}
    });
    return out;
  }
  return JSON.stringify(collect(document).join('\\n'));
})()
"""


def fetch_text(url, wait=10):
    """CDP 导航到 url，等待渲染，返回页面全部表格文本（递归 iframe）。"""
    ws_url = new_tab(url)
    ws = websocket.create_connection(ws_url, timeout=60, suppress_origin=True)
    time.sleep(wait)
    raw = eval_js(ws, COLLECT_JS)
    ws.close()
    if not raw:
        return ""
    # COLLECT_JS 返回 JSON.stringify 的结果，这里反序列化一次，换行符才还原成真换行
    try:
        return json.loads(raw)
    except Exception:
        return raw


# ── 字段解析工具 ───────────────────────────────────────────
def extract_codes(s):
    """'47 34 17 11 46 23' → '47.34.17.11.46.23'（占位符/非数字返回空）"""
    nums = [int(n) for n in re.findall(r'\d+', s or '') if 1 <= int(n) <= 49]
    return '.'.join(f"{n:02d}" for n in nums) if nums else ''


def extract_zodiacs(s):
    return ''.join(c for c in (s or '') if c in ZODIACS)


def is_placeholder(s):
    if not s:
        return True
    for kw in ('宝', '赌', '？', '待', '更新', '公开', '见证', '收', '发', '财', '暴富', '跟上',
               '实力', '关注', '惊喜', '迷路', '赚钱', '早晚', '只要', '常来', '敢', '来料',
               '必中', '把握', 'APP', '下载', '资料', '不迷路', '开路', '真', '准'):
        if kw in s:
            return True
    return False


def target_period(text):
    """识别下一期期号：'澳门第X期' 最大值（页面预告的下一期）。"""
    nums = [int(n) for n in re.findall(r'澳门第(\d+)期', text)]
    return max(nums) if nums else 0


def milao_target_period(text):
    """米老站目标期：'第X期' 最大值（开奖播报区标题，避开栏目期号/占位符）。"""
    nums = [int(n) for n in re.findall(r'第(\d+)期', text)]
    return max(nums) if nums else 0


def fengyun_target_period(text):
    """风云站目标期：'X期;①码' 最大值（一肖一码系列只有真实值期才有①码，占位期无）。"""
    nums = [int(n) for n in re.findall(r'(\d+)期;①码', text)]
    return max(nums) if nums else 0


# ── 各站解析器（t = 目标期号）──────────────────────────────
def parse_zhongte(text, t):
    f = {}
    # 波色：259期牛逼双波【蓝波红波】（259期有真实值）
    m = re.search(rf'{t}期牛逼双波【(红波|蓝波|绿波)\s*(红波|蓝波|绿波)】', text)
    if m:
        f['zhongte_wave1'] = WAVES.get(m.group(1), '')
        f['zhongte_wave2'] = WAVES.get(m.group(2), '')
    # 六肖/四肖/二肖/6码/4码/2码：免费大公开块（期号行"X期:记住赚钱的网站不难..."，
    #     值在后续 3 行：六肖:值\t6码:值 / 四肖:值\t4码:值 / 二肖:值\t2码:值）
    blk = re.search(rf'{t}期:记住[^\n]*\n([^\n]*?六肖[:：][^\n]*)\n([^\n]*?四肖[:：][^\n]*)\n([^\n]*?二肖[:：][^\n]*)', text)
    if blk:
        seg6, seg4, seg2 = blk.group(1), blk.group(2), blk.group(3)
        m = re.search(r'六肖[:：]([鼠牛虎兔龙蛇马羊猴鸡狗猪]+)', seg6)
        if m and not is_placeholder(m.group(1)):
            f['zhongte_zodiac6'] = m.group(1)
        m = re.search(r'6码[:：]([0-9\s.]+)', seg6)
        if m:
            c = extract_codes(m.group(1))
            if c:
                f['zhongte_codes6'] = c
        m = re.search(r'四肖[:：]([鼠牛虎兔龙蛇马羊猴鸡狗猪]+)', seg4)
        if m and not is_placeholder(m.group(1)):
            f['zhongte_zodiac4'] = m.group(1)
        m = re.search(r'4码[:：]([0-9\s.]+)', seg4)
        if m:
            c = extract_codes(m.group(1))
            if c:
                f['zhongte_codes4'] = c
        m = re.search(r'二肖[:：]([鼠牛虎兔龙蛇马羊猴鸡狗猪]+)', seg2)
        if m and not is_placeholder(m.group(1)):
            f['zhongte_zodiac2'] = m.group(1)
        m = re.search(r'2码[:：]([0-9\s.]+)', seg2)
        if m:
            c = extract_codes(m.group(1))
            if c:
                f['zhongte_codes2'] = c
    # 八码：260期:⑧码 28 21 35 16
    m = re.search(rf'{t}期[:：]⑧码\s*([0-9\s.]+)', text)
    if m:
        c = extract_codes(m.group(1))
        if c:
            f['zhongte_codes8'] = c
    # 12码：260期  04 09 10 16 17 19 20 26 28 40 45 46（期号后 tab，12 个两位号码）
    m = re.search(rf'{t}期\s+((?:\d{{2}}\s+){{11}}\d{{2}})', text)
    if m:
        c = extract_codes(m.group(1))
        if len(c.split('.')) == 12:
            f['zhongte_codes12'] = c
    # 五尾：260期【1尾4尾5尾6尾8尾】
    m = re.search(rf'{t}期【((?:\d尾)+)】', text)
    if m:
        tails = re.findall(r'\d', m.group(1))
        if tails:
            f['zhongte_tail5'] = '.'.join(tails)
    # 单双/大小：第259期: 单数单数单数
    m = re.search(rf'第{t}期[:：]\s*(单数|双数)', text)
    if m:
        f['zhongte_oddeven'] = '单' if m.group(1) == '单数' else '双'
    m = re.search(rf'第{t}期[:：]\s*(大数|小数)', text)
    if m:
        f['zhongte_size'] = '大' if m.group(1) == '大数' else '小'
    # 六码改源「本周必开六码」：257-263期(17 20 22 29 30 35)（管7期，覆盖免费大公开6码）
    m = re.search(r'本周必开六码[^\n]*\n(\d+)-(\d+)期\(([0-9\s.]+)\)', text)
    if m:
        x, y = int(m.group(1)), int(m.group(2))
        if x <= t <= y:
            c = extract_codes(m.group(3))
            if c:
                f['zhongte_codes6'] = c
    # 十三码「七期必出特码数字」：255-261期 12 15 16 ...（管7期）
    _p = text.find('七期必出特码数字')
    if _p >= 0:
        for m in re.finditer(r'(\d+)-(\d+)期\s*([0-9 \t.]+)', text[_p:_p + 3000]):
            x, y = int(m.group(1)), int(m.group(2))
            if x <= t <= y:
                c = extract_codes(m.group(3))
                if len(c.split('.')) == 13:
                    f['zhongte_codes13'] = c
                    break
    # 三期四肖「三期必出生肖」：260期 261期 262期 三期必中（虎羊猴龙）（管3期）
    m = re.search(rf'三期必出生肖[^\n]*\n{t}期\s*\n\d+期\s*\n\d+期\s*三期必中（([鼠牛虎兔龙蛇马羊猴鸡狗猪]+)）', text)
    if m and not is_placeholder(m.group(1)):
        f['zhongte_zodiac4_3q'] = m.group(1)
    return f


def parse_jinsuan(text, t):
    f = {}
    # 六肖王：259期:六肖王<兔鸡狗羊龙虎>
    m = re.search(rf'{t}期[:：]六肖王<([鼠牛虎兔龙蛇马羊猴鸡狗猪]+)>', text)
    if m and not is_placeholder(m.group(1)):
        f['jinsuan_zodiac6'] = m.group(1)
    # 澳门六肖⑥码：提供【澳门六肖⑥码】助您灭庄\n260期\t马01.兔16.牛42.虎17.龙03.鼠19
    # （生肖+号码配对，拆成 zodiac6 + zodiac6_codes，覆盖六肖王）
    m = re.search(rf'{t}期\s*((?:[鼠牛虎兔龙蛇马羊猴鸡狗猪]\d{{2}}\.){{5}}[鼠牛虎兔龙蛇马羊猴鸡狗猪]\d{{2}})', text)
    if m:
        pairs = re.findall(r'([鼠牛虎兔龙蛇马羊猴鸡狗猪])(\d{2})', m.group(1))
        if len(pairs) == 6:
            f['jinsuan_zodiac6'] = ''.join(z for z, _ in pairs)
            f['jinsuan_zodiac6_codes'] = '.'.join(f'{int(n):02d}' for _, n in pairs)
    # 六码：259期:六码 16 22 33 36 15 17
    m = re.search(rf'{t}期[:：]六码\s*([0-9\s.]+)', text)
    if m:
        c = extract_codes(m.group(1))
        if c:
            f['jinsuan_codes6'] = c
    # 五尾：259期原创⑤尾{3.4.5.6.7}（[})]] 字符类写错多一个]，已修）
    m = re.search(rf'{t}期原创⑤?尾[{{(]([0-9.,，\s]+)[}})]', text)
    if m:
        tails = re.findall(r'\d+', m.group(1))
        f['jinsuan_tail5'] = '.'.join(tails) if tails else ''
    # 三码：260期:三码 25 28 30
    m = re.search(rf'{t}期[:：]三码\s*([0-9\s.]+)', text)
    if m:
        c = extract_codes(m.group(1))
        if c:
            f['jinsuan_codes3'] = c
    # 十码（精选）：精选:25 28 30 29 27 31 24 32 22 37√\n260期:六码 ...（靠紧跟的"X期:六码"定位期号）
    m = re.search(rf'精选[:：]\s*([0-9\s.]+)[^\n]*\n{t}期[:：]六码', text)
    if m:
        c = extract_codes(m.group(1))
        if len(c.split('.')) >= 10:
            f['jinsuan_codes10'] = c
    # ㈤肖/⑥码（259期推荐1肖1码 系列，第一个=最新期）
    m = re.search(r'㈤肖([鼠牛虎兔龙蛇马羊猴鸡狗猪]+)', text)
    if m and not is_placeholder(m.group(1)):
        f['jinsuan_zodiac5'] = m.group(1)
    m = re.search(r'⑥码\s*([0-9\s.]+)', text)
    if m:
        c = extract_codes(m.group(1))
        if c:
            f['jinsuan_codes6'] = f.get('jinsuan_codes6') or c
    m = re.search(r'㈢肖([鼠牛虎兔龙蛇马羊猴鸡狗猪]+)', text)
    if m and not is_placeholder(m.group(1)):
        f['jinsuan_zodiac3'] = m.group(1)
    m = re.search(r'④码\s*([0-9\s.]+)', text)
    if m:
        c = extract_codes(m.group(1))
        if c:
            f['jinsuan_codes4'] = c
    m = re.search(r'㈠肖([鼠牛虎兔龙蛇马羊猴鸡狗猪])', text)
    if m and not is_placeholder(m.group(1)):
        f['jinsuan_zodiac1'] = m.group(1)
    m = re.search(r'②码\s*([0-9\s.]+)', text)
    if m:
        c = extract_codes(m.group(1))
        if c:
            f['jinsuan_codes2'] = c
    # 平特一肖：259期平特一肖〖羊羊羊羊〗
    m = re.search(rf'{t}期平特一肖〖([鼠牛虎兔龙蛇马羊猴鸡狗猪])', text)
    if m:
        f['jinsuan_zodiac1'] = f.get('jinsuan_zodiac1') or m.group(1)
    return f


def parse_jubao(text, t):
    f = {}
    # 七肖/⑦码（第一个=最新期）
    m = re.search(r'七肖[:：]([鼠牛虎兔龙蛇马羊猴鸡狗猪]+)', text)
    if m and not is_placeholder(m.group(1)):
        f['jubao_zodiac7'] = m.group(1)
    m = re.search(r'⑦码[:：]([0-9\s.]+)', text)
    if m:
        c = extract_codes(m.group(1))
        if c:
            f['jubao_codes7'] = c
    m = re.search(r'四肖[:：]([鼠牛虎兔龙蛇马羊猴鸡狗猪]+)', text)
    if m and not is_placeholder(m.group(1)):
        f['jubao_zodiac4'] = m.group(1)
    m = re.search(r'⑤码[:：]([0-9\s.]+)', text)
    if m:
        c = extract_codes(m.group(1))
        if c:
            f['jubao_codes5'] = c
    m = re.search(r'二肖[:：]([鼠牛虎兔龙蛇马羊猴鸡狗猪]+)', text)
    if m and not is_placeholder(m.group(1)):
        f['jubao_zodiac2'] = m.group(1)
    m = re.search(r'③码[:：]([0-9\s.]+)', text)
    if m:
        c = extract_codes(m.group(1))
        if c:
            f['jubao_codes3'] = c
    # 八肖：260期:⑧肖 虎猪羊兔鸡猴鼠龙
    m = re.search(rf'{t}期[:：]⑧肖\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪]+)', text)
    if m and not is_placeholder(m.group(1)):
        f['jubao_zodiac8'] = m.group(1)
    # 六肖六码（澳彩）：260期澳彩⑥肖⑥码 开？00\n【狗21.蛇14.牛42.猪20.兔28.猴35】
    m = re.search(rf'{t}期澳彩⑥肖⑥码[^\n]*\n[^\n]*【(.*?)】', text)
    if m:
        pairs = re.findall(r'([鼠牛虎兔龙蛇马羊猴鸡狗猪])\s*[.。,，、\-\s]*(\d+)', m.group(1))
        zodiacs = ''.join(z for z, _ in pairs)
        codes = [int(n) for _, n in pairs if 1 <= int(n) <= 49]
        if zodiacs and len(codes) == 6:
            f['jubao_zodiac6'] = zodiacs
            f['jubao_zodiac6_codes'] = '.'.join(f'{n:02d}' for n in codes)
    # 双波：260期:双波中特 【红波+蓝波】
    m = re.search(rf'{t}期[:：]双波中特\s*【(红波|蓝波|绿波)\+(红波|蓝波|绿波)】', text)
    if m:
        f['jubao_wave1'] = WAVES.get(m.group(1), '')
        f['jubao_wave2'] = WAVES.get(m.group(2), '')
    # 六尾：260期:六尾中特 【0.2.4.5.6.7】
    m = re.search(rf'{t}期[:：]六尾中特\s*【([0-9.]+)】', text)
    if m:
        tails = re.findall(r'\d', m.group(1))
        if tails:
            f['jubao_tail6'] = '.'.join(tails)
    # 家野：260期家肖 【猪牛狗】野肖 【龙虎蛇】（家3+野3=6肖）
    m = re.search(rf'{t}期家肖\s*【([鼠牛虎兔龙蛇马羊猴鸡狗猪]+)】\s*野肖\s*【([鼠牛虎兔龙蛇马羊猴鸡狗猪]+)】', text)
    if m:
        f['jubao_jaye'] = m.group(1) + m.group(2)
    # 波段：260期-261期〖极限一波〗...\n（蓝波）二期必出
    m = re.search(rf'{t}期-\d+期〖极限一波〗[^\n]*\n[^\n]*（(红波|蓝波|绿波)）', text)
    if m:
        f['jubao_boduan'] = WAVES.get(m.group(1), '')
    # 单双：260期:单双中特【单单单】
    m = re.search(rf'{t}期[:：]单双中特【(单|双)', text)
    if m:
        f['jubao_danshuang'] = m.group(1)
    # 三期十二码：258期 259期 260期 8个号码\n8个号码（16码）
    m = re.search(rf'\d+期\s*\n\d+期\s*\n{t}期\s*([0-9\s.]+)\n([0-9\s.]+)', text)
    if m:
        c = extract_codes(m.group(1) + ' ' + m.group(2))
        if len(c.split('.')) == 16:
            f['jubao_sanqi12'] = c
    # 合数：260期:合数大小【合数大】
    m = re.search(rf'{t}期[:：]合数大小【(合数大|合数小)】', text)
    if m:
        f['jubao_heshu'] = '大' if m.group(1) == '合数大' else '小'
    # 三期四肖：258期 259期 260期 兔蛇鸡鼠
    m = re.search(rf'\d+期\s*\n\d+期\s*\n{t}期\s*([鼠牛虎兔龙蛇马羊猴鸡狗猪]+)', text)
    if m and not is_placeholder(m.group(1)):
        f['jubao_sixiao3q'] = m.group(1)
    # 12码：260期 澳彩12码中特 开？00\n(05 17 29 41 08 20 32 44 12 24 36 48)
    m = re.search(rf'{t}期\s+澳彩12码中特[^\n]*\n[^\n]*\(([0-9\s.]+)\)', text)
    if m:
        c = extract_codes(m.group(1))
        if len(c.split('.')) == 12:
            f['jubao_codes12'] = c
    # 三头：260期:三头中特 <2头.3头.4头>
    m = re.search(rf'{t}期[:：]三头中特\s*<([0-9]头\.[0-9]头\.[0-9]头)>', text)
    if m:
        heads = re.findall(r'\d', m.group(1))
        if heads:
            f['jubao_santou'] = '.'.join(heads)
    # 16码：260期:精选16码---开:？00准\n荣耀⑧码:02...青铜⑧码:22...
    m = re.search(rf'{t}期[:：]精选16码[^\n]*\n荣耀⑧码[:：]([0-9.]+)\n青铜⑧码[:：]([0-9.]+)', text)
    if m:
        c = extract_codes(m.group(1) + ' ' + m.group(2))
        if len(c.split('.')) == 16:
            f['jubao_codes16'] = c
    return f


def parse_milao(text, t):
    """米老鼠站 parser：网红七肖/爆特单双/七尾/平特/波色/暴富12码/七肖/大小肖/24码/一码~九肖等。"""
    f = {}
    Z = ZODIACS
    # 网红七肖
    m = re.search(rf'{t}期:网红七肖【(.*?)】', text)
    if m and not is_placeholder(m.group(1)):
        f['milao_wanghong7'] = extract_zodiacs(m.group(1))
    # 爆特单双
    m = re.search(rf'{t}期:爆特单双【(单数|双数)】', text)
    if m:
        f['milao_oddeven'] = '单' if m.group(1) == '单数' else '双'
    # 七尾
    m = re.search(rf'{t}期:七尾【([\d\-]+)】', text)
    if m:
        tails = re.findall(r'\d', m.group(1))
        f['milao_wei7'] = '.'.join(tails) if tails else ''
    # 深圳平特
    m = re.search(rf'{t}期:深圳平特【(.*?)】', text)
    if m and not is_placeholder(m.group(1)):
        f['milao_pingte'] = extract_zodiacs(m.group(1))
    # 必中波色
    m = re.search(rf'{t}期:必中波色【(红波|蓝波|绿波)\s*(红波|蓝波|绿波)】', text)
    if m:
        f['milao_wave1'] = WAVES.get(m.group(1), '')
        f['milao_wave2'] = WAVES.get(m.group(2), '')
    # 暴富12码（管3期，覆盖 t）
    for m in re.finditer(r'(\d+)-(\d+)期〖暴富12码〗[^\n]*\n\s*([\d.]+)', text):
        x, y = int(m.group(1)), int(m.group(2))
        if x <= t <= y:
            codes = extract_codes(m.group(3))
            if len(codes.split('.')) == 12:
                f['milao_codes12'] = codes
                break
    # 七肖栏目（带【】，非网红）
    m = re.search(rf'{t}期:七肖【(.*?)】', text)
    if m and not is_placeholder(m.group(1)):
        f['milao_zodiac7'] = extract_zodiacs(m.group(1))
    # 大小肖
    m = re.search(rf'{t}期:\s*大肖\(([^)]*)\)小肖\(([^)]*)\)', text)
    if m:
        f['milao_daxiao'] = extract_zodiacs(m.group(1)) + extract_zodiacs(m.group(2))
    # 内部24码（两行【】）
    m = re.search(rf'{t}期:【内部透露24码】.*?【(.*?)】\s*【(.*?)】', text, re.DOTALL)
    if m:
        codes = extract_codes(m.group(1) + ' ' + m.group(2))
        f['milao_codes24'] = codes
    # 两期平特（管2期）
    for m in re.finditer(r'(\d+)-(\d+)期:两期平特〖(.*?)〗', text):
        x, y = int(m.group(1)), int(m.group(2))
        if x <= t <= y:
            f['milao_pingte2'] = extract_zodiacs(m.group(3))
            break
    # 四肖爆特
    m = re.search(rf'{t}期:四肖爆特【(.*?)】', text)
    if m and not is_placeholder(m.group(1)):
        f['milao_sibao4'] = extract_zodiacs(m.group(1))
    # 一码/四码/八码
    m = re.search(rf'{t}期:一码\s+(\d+)', text)
    if m:
        f['milao_codes1'] = f"{int(m.group(1)):02d}"
    m = re.search(rf'{t}期:四码\s+([\d.]+)', text)
    if m:
        f['milao_codes4'] = extract_codes(m.group(1))
    m = re.search(rf'{t}期:八码\s+([\d.]+)', text)
    if m:
        f['milao_codes8'] = extract_codes(m.group(1))
    # 一肖~九肖（米老鼠系列，tab分隔）
    for field, name in [('milao_zodiac1', '一肖'), ('milao_zodiac2', '二肖'), ('milao_zodiac3', '三肖'),
                        ('milao_zodiac4', '四肖'), ('milao_zodiac6', '六肖'), ('milao_zodiac9', '九肖')]:
        m = re.search(rf'{t}期:{name}\s+([{Z}]+)', text)
        if m and not is_placeholder(m.group(1)):
            f[field] = m.group(1)
    # 大小中特
    m = re.search(rf'{t}期:大小中特【(大数|小数)】', text)
    if m:
        f['milao_size'] = '大' if m.group(1) == '大数' else '小'
    # 绝杀三肖
    m = re.search(rf'{t}期:绝杀三肖〖(.*?)〗', text)
    if m and not is_placeholder(m.group(1)):
        f['milao_juesha3'] = extract_zodiacs(m.group(1))
    return f


def parse_nezha(text, t):
    """哪吒站 parser：①肖①码中特系列（七肖~一肖 + ①③⑤⑩码）/ 八肖 / 五尾 / 三头 / 绝杀三肖 / 前后主六码 / 七肖中特 / 内幕平特 / 5期13码。"""
    f = {}
    Z = ZODIACS
    # 八肖：60100【三太子】八肖挑战全网！\n261期:【蛇狗龙马鸡猴鼠牛】
    m = re.search(rf'{t}期[:：]【([{Z}]{{8}})】', text)
    if m and not is_placeholder(m.group(1)):
        f['nezha_zodiac8'] = m.group(1)
    # 五尾：哪吒【五尾中特】60100.com\n261期:五尾【2.9.7.3.4尾】
    m = re.search(rf'{t}期[:：]五尾【([0-9.]+尾)】', text)
    if m:
        tails = re.findall(r'\d', m.group(1))
        if len(tails) == 5:
            f['nezha_tail5'] = '.'.join(tails) + '尾'
    # ── ①肖①码中特系列（tab 分隔：七肖~一肖 + ①③⑤⑩码）──
    for field, name, expect in [
        ('nezha_zodiac7', '七肖', 7), ('nezha_zodiac6', '六肖', 6),
        ('nezha_zodiac4', '四肖', 4), ('nezha_zodiac3', '三肖', 3),
        ('nezha_zodiac2', '二肖', 2), ('nezha_zodiac1', '一肖', 1),
    ]:
        m = re.search(rf'{t}期{name}[\t ]+([{Z}]+)', text)
        if m and not is_placeholder(m.group(1)):
            f[field] = m.group(1)
    m = re.search(rf'{t}期①码[\t ]+(\d+)', text)
    if m:
        f['nezha_codes1'] = f"{int(m.group(1)):02d}"
    for field, mark in [('nezha_codes3', '③码'), ('nezha_codes5', '⑤码')]:
        m = re.search(rf'{t}期{mark}[\t ]+([\d.]+)', text)
        if m:
            c = extract_codes(m.group(1))
            if c:
                f[field] = c
    # ⑩码跨两行：261期⑩码\t48.12.27.15.20\n44.11.35.25.49\t开:？00
    m = re.search(rf'{t}期⑩码[\t ]+([\d.]+)\s*\n([\d.]+)', text)
    if m:
        c = extract_codes(m.group(1) + ' ' + m.group(2))
        if len(c.split('.')) == 10:
            f['nezha_codes10'] = c
    # 三头中特：261期:三头中特【1.4.2头】
    m = re.search(rf'{t}期[:：]三头中特【([\d.]+)头】', text)
    if m:
        heads = re.findall(r'\d', m.group(1))
        if heads:
            f['nezha_santou'] = '.'.join(heads)
    # 绝杀三肖：261期:绝杀三肖【牛马猴】
    m = re.search(rf'{t}期[:：]绝杀三肖【([{Z}]+)】', text)
    if m and not is_placeholder(m.group(1)):
        f['nezha_juesha3'] = m.group(1)
    # 前后主六码：261期:【前后中特】…主三肖【马狗羊】…精选六码【13.49.09.33.48.24】
    m = re.search(rf'{t}期[:：]【前后中特】.*?主三肖【([{Z}]+)】', text, re.DOTALL)
    if m and not is_placeholder(m.group(1)):
        f['nezha_qianhou3'] = m.group(1)
    m = re.search(rf'{t}期[:：]【前后中特】.*?精选六码【([\d.]+)】', text, re.DOTALL)
    if m:
        c = extract_codes(m.group(1))
        if c:
            f['nezha_qianhou6'] = c
    # 七肖中特（独立栏目）：261期:七肖【龙鸡猪狗牛虎鼠】
    m = re.search(rf'{t}期[:：]七肖【([{Z}]+)】', text)
    if m and not is_placeholder(m.group(1)):
        f['nezha_qizhong7'] = m.group(1)
    # 内幕平特：261期内幕平特【狗】下900万
    m = re.search(rf'{t}期内幕平特【([{Z}])】', text)
    if m:
        f['nezha_neimu1'] = m.group(1)
    # 5期13码：本轮257期至261期:开: 1期\n01.03.05.07.12.13\n15.28.32.33.34.41.43
    for m in re.finditer(r'本轮(\d+)期至(\d+)期[^\n]*\n([\d.]+)\n([\d.]+)', text):
        x, y = int(m.group(1)), int(m.group(2))
        if x <= t <= y:
            c = extract_codes(m.group(3) + ' ' + m.group(4))
            if len(c.split('.')) == 13:
                f['nezha_codes13'] = c
                break
    return f


def parse_fengyun(text, t):
    """风云站（澳门风云 49315.com，hash 路由 JS 渲染）：22 字段。
    一肖一码系列（①⑤⑩码 + 一~九肖）+ 神算③肖/平特一肖/精选波色/金牌⑥肖/
    三期必开/投资六码/④尾⑧码/大小中特/单双主③肖。"""
    f = {}
    Z = ZODIACS
    # ── 一肖一码系列 ──
    m = re.search(rf'{t}期;①码\s+([\d.]+)', text)
    if m:
        c = extract_codes(m.group(1))
        if c:
            f['fengyun_codes1'] = c
    m = re.search(rf'{t}期;⑤码\s+([\d.]+)', text)
    if m:
        c = extract_codes(m.group(1))
        if c:
            f['fengyun_codes5'] = c
    m = re.search(rf'{t}期;⑩码\s+([\d.]+)', text)
    if m:
        c = extract_codes(m.group(1))
        if c:
            f['fengyun_codes10'] = c
    for cn, field in [('一', 'fengyun_zodiac1'), ('二', 'fengyun_zodiac2'), ('三', 'fengyun_zodiac3'),
                      ('四', 'fengyun_zodiac4'), ('五', 'fengyun_zodiac5'), ('六', 'fengyun_zodiac6'),
                      ('七', 'fengyun_zodiac7'), ('九', 'fengyun_zodiac9')]:
        m = re.search(rf'{t}期;{cn}肖\s+([{Z}]+)', text)
        if m:
            f[field] = m.group(1)
    # ── 神算③肖 ──
    m = re.search(rf'{t}期-神算③肖【([{Z}]+)】', text)
    if m:
        f['fengyun_shengsuan3'] = m.group(1)
    # ── 平特一肖 ──
    m = re.search(rf'{t}期;平特①肖【([{Z}]+)】', text)
    if m:
        f['fengyun_pingte1'] = m.group(1)[0]
    # ── 精选波色 ──
    m = re.search(rf'{t}期;双波必中【(红波|蓝波|绿波)\+(红波|蓝波|绿波)】', text)
    if m:
        f['fengyun_wave1'] = WAVES.get(m.group(1), '')
        f['fengyun_wave2'] = WAVES.get(m.group(2), '')
    # ── 金牌⑥肖 ──
    m = re.search(rf'{t}期-六肖【([{Z}]+)】', text)
    if m:
        f['fengyun_jinpai6'] = m.group(1)
    # ── 三期必开 ──
    m = re.search(rf'{t-2}期-{t}期〖([{Z}]+)〗', text)
    if m:
        f['fengyun_sanqi3'] = m.group(1)
    # ── 投资六码 ──
    m = re.search(rf'{t-4}期-{t}期〖六码〗.*?〖([\d.]+)〗', text, re.DOTALL)
    if m:
        c = extract_codes(m.group(1))
        if c:
            f['fengyun_touzi6'] = c
    # ── ④尾⑧码 ──
    m = re.search(rf'{t}期：④尾⑧码[^\n]*\n(\d)尾\(主([\d.]+)\)(\d)尾\(主([\d.]+)\)\n(\d)尾\(主([\d.]+)\)(\d)尾\(主([\d.]+)\)', text)
    if m:
        f['fengyun_wei4'] = '.'.join([m.group(1), m.group(3), m.group(5), m.group(7)])
        allc = []
        for g in [m.group(2), m.group(4), m.group(6), m.group(8)]:
            allc += extract_codes(g).split('.')
        f['fengyun_wei4_codes'] = '.'.join(allc)
    # ── 大小中特 ──
    m = re.search(rf'{t}期-大小中特【(大数|小数)】', text)
    if m:
        f['fengyun_size'] = '大' if m.group(1) == '大数' else '小'
    # ── 单双主③肖 ──
    m = re.search(rf'{t}期-〖(单数|双数)〗主〖([{Z}]+)〗', text)
    if m:
        f['fengyun_danshuang'] = '单' if m.group(1) == '单数' else '双'
        f['fengyun_danshuang3'] = m.group(2)
    return f


def parse_daying(text, t):
    """大赢站『头条内幕』栏目（#toubu18）：七肖/7码/四肖/5码/二肖/3码/内部赠送。"""
    f = {}
    Z = ZODIACS
    # 目标期块：从 "{t}期:关注" 到 "{t}期:内部赠送"
    blk_m = re.search(rf'{t}期:关注[^\n]*\n(.*?){t}期:内部赠送', text, re.DOTALL)
    blk = blk_m.group(1) if blk_m else text
    # 七肖 + 7码：七肖:狗虎鸡龙兔蛇猴\t7码:45 05 34 21 29 33 46
    m = re.search(rf'七肖[:：]([{Z}]+)[\t ]+7码[:：]([\d\s.]+)', blk)
    if m:
        f['daying_zodiac7'] = m.group(1)
        c = extract_codes(m.group(2))
        if len(c.split('.')) == 7:
            f['daying_codes7'] = c
    # 四肖 + 5码：四肖:狗虎鸡龙\t5码:45 05 34 21 29
    m = re.search(rf'四肖[:：]([{Z}]+)[\t ]+5码[:：]([\d\s.]+)', blk)
    if m:
        f['daying_zodiac4'] = m.group(1)
        c = extract_codes(m.group(2))
        if len(c.split('.')) == 5:
            f['daying_codes5'] = c
    # 二肖 + 3码：二肖:狗虎\t3码:45 05 34
    m = re.search(rf'二肖[:：]([{Z}]+)[\t ]+3码[:：]([\d\s.]+)', blk)
    if m:
        f['daying_zodiac2'] = m.group(1)
        c = extract_codes(m.group(2))
        if len(c.split('.')) == 3:
            f['daying_codes3'] = c
    # 内部赠送：263期:内部赠送<狗-45>（1肖1码）
    m = re.search(rf'{t}期:内部赠送<([{Z}])-(\d+)>', text)
    if m:
        f['daying_neimu'] = f"{m.group(1)}{int(m.group(2)):02d}"
    # 大赢家单双：263期:专家单双王【单数+鸡兔】开:？00准
    m = re.search(rf'{t}期:专家单双王【(单数|双数)\+([{Z}]+)】', text)
    if m:
        f['daying_danshuang'] = '单' if m.group(1) == '单数' else '双'
        f['daying_danshuang_zodiac2'] = m.group(2)
    # 金牌家野：263期:大赢家•家野【野兽+狗鸡】开？00准
    m = re.search(rf'{t}期:大赢家[•·・.]家野【(家禽|野兽)\+([{Z}]+)】', text)
    if m:
        f['daying_jiaye'] = '家畜' if m.group(1) == '家禽' else '野兽'
        f['daying_jiaye_zodiac2'] = m.group(2)
    return f


PARSERS = {
    "中特": parse_zhongte,
    "金算": parse_jinsuan,
    "聚宝": parse_jubao,
    "米老": parse_milao,
    "哪吒": parse_nezha,
    "大赢": parse_daying,
    "风云": parse_fengyun,
}


def period_to_date(period):
    return (date(2026, 5, 4) + timedelta(days=period - 124)).strftime("%Y-%m-%d")


def period_ceiling():
    """采集期号上限 = 今天对应期号；每晚 21:30 开奖后站点翻到下一期（明天期号）+1。"""
    from datetime import datetime as _dt
    today = date.today()
    base = (today - date(2026, 5, 4)).days + 124
    now = _dt.now()
    if now.hour > 21 or (now.hour == 21 and now.minute >= 30):
        base += 1
    return base


def save_fields(site, period, fields):
    if not fields:
        return None
    draw_date = period_to_date(period)
    db = sqlite3.connect(DB_PATH)
    cols = list(fields.keys())
    sets = ", ".join([f"{c}=excluded.{c}" for c in cols])
    # 风云站已迁到 multi_group_summary（多组汇总 V1），其余 V2 站仍写 summary2
    table = "multi_group_summary" if site == "风云" else "multi_group_summary2"
    db.execute(
        f"INSERT INTO {table} (draw_date, period, {', '.join(cols)}) "
        f"VALUES (?, ?, {', '.join('?' * len(cols))}) "
        f"ON CONFLICT(draw_date) DO UPDATE SET {sets}, period=excluded.period",
        [draw_date, f"{period}期"] + [fields[c] for c in cols],
    )
    db.commit()
    db.close()
    return draw_date


def fetch_and_save(site, url, wait=10, force_period=None):
    if not ensure_cdp():
        return {"site": site, "status": "fail", "error": "CDP Edge 实例启动失败（9224 不通）"}
    text = fetch_text(url, wait)
    if force_period:
        t = int(force_period)
    else:
        if site == "风云":
            t = fengyun_target_period(text)
        elif site in ("米老", "哪吒"):
            t = milao_target_period(text)
        else:
            t = target_period(text)
        # CDP 冷启动首访常加载慢/空，重试一次（第二次站点已预热）
        if not text or not t:
            text = fetch_text(url, wait + 5)
            if not text:
                return {"site": site, "status": "fail", "error": "采集文本为空"}
            if site == "风云":
                t = fengyun_target_period(text)
            elif site in ("米老", "哪吒"):
                t = milao_target_period(text)
            else:
                t = target_period(text)
    if not t:
        return {"site": site, "status": "fail", "error": "未识别到目标期号"}
    # 未指定期号时约束上限，防止采到未来期
    if force_period is None and t > period_ceiling():
        t = period_ceiling()
    fields = PARSERS[site](text, t)
    if not fields:
        return {"site": site, "status": "fail", "period": t, "error": "未解析到有效字段（可能下一期尚未公开）"}
    draw_date = save_fields(site, t, fields)
    return {"site": site, "status": "ok", "period": t, "draw_date": draw_date, "fields": fields}


if __name__ == "__main__":
    import sys
    SITES = {
        "中特": "https://piao2233mi.0149q8.app:2026/01491111.app",
        "金算": "https://01491111qaz916.0149z62.app:2026/77770149.app",
        "聚宝": "https://jb2fhsa817jb.0149a55.app:2026/01493456.app",
        "米老": "https://zzxxtt12151.12151c.app:8450/ok.html#ai5",
        "哪吒": "https://qgpy8713071.13071fj.app:8447/ok.html",
        "大赢": "https://77770149qaz524.0149a18.app:2026/01493333.app#toubu18",
        "风云": "https://f4d9-x1b6n3.r8n2q5k0l.dev:2028/#26210gg",
    }
    sel = {k: SITES[k] for k in sys.argv[1:] if k in SITES} if len(sys.argv) > 1 else SITES
    for site, url in sel.items():
        print(f"\n===== 采集 {site} =====")
        r = fetch_and_save(site, url)
        print(json.dumps(r, ensure_ascii=False, indent=2))
    close_cdp()
    print("\n（CDP 实例已关闭）")
