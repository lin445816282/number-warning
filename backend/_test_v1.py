import sys
sys.path.insert(0, '/home/xiaolin/projects/number-warning/backend')
import main

# 测试大家、鬼谷解析（HTML 已抓）
for name, key, fpath in [
    ('大家', 'dajia', '/tmp/大家_html.txt'),
    ('鬼谷', 'gui', '/tmp/鬼谷_html.txt'),
]:
    html = open(fpath, encoding='utf-8').read()
    r = main._parse_site_predict(key, html)
    print(f'=== {name} ===')
    if r:
        for k, v in sorted(r.items()):
            print(f'  {k} = {v}')
    else:
        print('  解析返回 None')
    print()

# 重新抓好运（新 js 拼接）
print('重新抓好运...')
html = main._fetch_site_html('https://kk.www18795.com:8443/')
with open('/tmp/好运_html2.txt', 'w', encoding='utf-8') as f:
    f.write(html)
print(f'好运 HTML 长度 = {len(html)}')
r = main._parse_site_predict('haoyun', html)
print('=== 好运 ===')
if r:
    for k, v in sorted(r.items()):
        print(f'  {k} = {v}')
else:
    print('  解析返回 None')
