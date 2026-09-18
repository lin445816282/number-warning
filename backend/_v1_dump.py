import sys
sys.path.insert(0, '/home/xiaolin/projects/number-warning/backend')
import main

sites = {
    '好运': 'https://kk.www18795.com:8443/',
    '大家': 'https://x7q-n1p4k8v.r2j8c5t4w.dev:2028/',
    '鬼谷': 'https://b6w0-j7c3y5.n7s3x0p5m.dev:2028/',
}

kws = {
    '好运': ['必中六肖', '精选24码', '必中16码', '三头中特', '181805'],
    '大家': ['内部24码', '家野中特', '三期四肖', '单双中特', '无错八肖', '聚彩堂'],
    '鬼谷': ['极限12码', '三期内必开', '鬼谷子'],
}

for name, url in sites.items():
    print(f'===== 抓取 {name} =====')
    try:
        html = main._fetch_site_html(url)
        with open(f'/tmp/{name}_html.txt', 'w', encoding='utf-8') as f:
            f.write(html)
        print(f'  长度={len(html)}')
        for kw in kws[name]:
            cnt = html.count(kw)
            if cnt:
                print(f'  [{kw}]: {cnt}处')
    except Exception as e:
        print(f'  失败: {e}')
    print()
