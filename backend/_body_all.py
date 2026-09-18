import sys, json, time
sys.path.insert(0, '/home/xiaolin/projects/number-warning/backend')
import fetch_predict as fp

sites = {
    "金算": "https://01491111qaz916.0149z62.app:2026/77770149.app",
    "中特": "https://piao2233mi.0149q8.app:2026/01491111.app",
}
for name, url in sites.items():
    print(f"抓取 {name} body ...")
    text = fp.fetch_text(url, wait=12)
    with open(f'/tmp/{name}_body.txt', 'w', encoding='utf-8') as f:
        f.write(text)
    print(f"  长度={len(text)}")
    # 用现有解析器测试
    t = fp.target_period(text)
    f = fp.PARSERS[name](text, t)
    print(f"  目标期={t}, 解析字段数={len(f)}")
    for k, v in sorted(f.items()):
        print(f'    {k} = {v}')
    print()
