import sys, json, time
sys.path.insert(0, '/home/xiaolin/projects/number-warning/backend')
import fetch_predict as fp

# 改进抓取：抓 body.innerText（含 div/span，不只 table）
JS = """
(() => {
  function collect(doc) {
    let out = [doc.body ? doc.body.innerText : ''];
    doc.querySelectorAll('iframe').forEach(f => {
      try { if (f.contentDocument) out = out.concat(collect(f.contentDocument)); } catch(e) {}
    });
    return out.join('\\n');
  }
  return JSON.stringify(collect(document));
})()
"""

def fetch_body(url, wait=12):
    ws_url = fp.new_tab(url)
    ws = fp.websocket.create_connection(ws_url, timeout=60, suppress_origin=True)
    time.sleep(wait)
    raw = fp.eval_js(ws, JS)
    ws.close()
    if not raw:
        return ""
    try:
        return json.loads(raw)
    except Exception:
        return raw

url = "https://jb2fhsa817jb.0149a55.app:2026/01493456.app"
print("抓取聚宝 body.innerText ...")
text = fetch_body(url)
with open('/tmp/聚宝_body.txt', 'w', encoding='utf-8') as f:
    f.write(text)
print(f"长度={len(text)}")
# 搜索卡片关键词
for kw in ['家野', '波段', '单双中特', '合数', '四肖三期', '12码', '三头', '16码', '甄选', '一波', '发财', '经典', '独创', '传奇', '头数', '专家']:
    cnt = text.count(kw)
    if cnt:
        print(f'  [{kw}]: {cnt}处')
