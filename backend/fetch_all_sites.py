# -*- coding: utf-8 -*-
"""采集全部预测站（11 家）：登录 number-warning 后端 → 调 fetchAll 接口。

fetchAll 会采集 predict_site_config 表里所有 enabled=1 的站点
（11 家：鬼谷/大家/诸葛/好运/中特/金算/聚宝/米老/哪吒/大赢/风云）。
V2 站走 CDP、V1 站走 HTTP，统一落库（风云→multi_group_summary，其余→multi_group_summary2）。
"""
import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8025"
USERNAME = "admin"
PASSWORD = "8283103"


def _post(path, body=None, token=None, timeout=900):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, headers=headers)
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def main():
    try:
        login = _post("/api/system/login", {"username": USERNAME, "password": PASSWORD})
    except Exception as e:
        print(f"登录失败（8025 服务不通或密码错误）: {type(e).__name__}: {e}")
        sys.exit(1)
    token = login.get("token", "")
    if not token:
        print("登录失败：未返回 token")
        sys.exit(1)

    try:
        r = _post("/api/predictSite/fetchAll", token=token)
    except Exception as e:
        print(f"fetchAll 调用失败: {type(e).__name__}: {e}")
        sys.exit(1)

    ok = r.get("ok", 0)
    total = r.get("total", 0)
    results = r.get("results", [])
    fails = [x for x in results if x.get("status") != "ok"]

    print(f"采集完成：成功 {ok}/{total} 站")
    for x in results:
        s = x.get("status")
        key = x.get("site_key", "")
        detail = x.get("detail") or x.get("error") or ""
        print(f"  [{s}] {key}  {detail}")

    if fails:
        print(f"\n失败 {len(fails)} 站：")
        for x in fails:
            print(f"  - {x.get('site_key')}: {x.get('error') or x.get('detail')}")


if __name__ == "__main__":
    main()
