# -*- coding: utf-8 -*-
"""CDP 采集测试：导航到预测站，提取渲染后文本。"""
import json, time, urllib.request
import websocket

CDP_HTTP = "http://172.23.128.1:9224"

def http_get(path):
    return json.loads(urllib.request.urlopen(CDP_HTTP + path, timeout=10).read())

def new_tab(url):
    """创建新标签页并返回 webSocketDebuggerUrl（PUT 方法）。"""
    import urllib.parse
    req = urllib.request.Request(CDP_HTTP + f"/json/new?{urllib.parse.quote(url)}", method="PUT")
    target = json.loads(urllib.request.urlopen(req, timeout=10).read())
    return target["webSocketDebuggerUrl"]

def cdp_call(ws, method, params=None, msg_id=1):
    ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
    while True:
        msg = json.loads(ws.recv())
        if msg.get("id") == msg_id:
            return msg

def eval_js(ws, expression, msg_id=100):
    r = cdp_call(ws, "Runtime.evaluate", {"expression": expression, "returnByValue": True}, msg_id)
    return r.get("result", {}).get("result", {}).get("value")

if __name__ == "__main__":
    import urllib.parse
    url = "https://piao2233mi.0149q8.app:2026/01491111.app"
    ws_url = new_tab(url)
    print("新建标签页:", ws_url[:60])
    ws = websocket.create_connection(ws_url, timeout=60, suppress_origin=True)
    # 等待多层 iframe 渲染
    time.sleep(10)
    # 递归提取 iframe 文本
    js = """
    (() => {
      function collect(doc, depth) {
        let result = [];
        doc.querySelectorAll('table').forEach(t => {
          const txt = t.innerText.replace(/\\s+/g, ' ').trim();
          if (txt && /期|肖|码|尾|波|单|双|大|小/.test(txt)) result.push({ depth, txt });
        });
        doc.querySelectorAll('iframe').forEach(f => {
          try { if (f.contentDocument) result = result.concat(collect(f.contentDocument, depth+1)); } catch(e) {}
        });
        return result;
      }
      const r = collect(document, 0);
      return JSON.stringify({ url: location.href, title: document.title, tables: r.length, data: r.slice(0, 30) });
    })()
    """
    result = eval_js(ws, js)
    ws.close()
    d = json.loads(result)
    print(f"\nURL: {d['url']}")
    print(f"title: {d['title']}")
    print(f"table 数: {d['tables']}")
    for t in d['data'][:15]:
        print(f"\n[depth {t['depth']}] {t['txt'][:180]}")
