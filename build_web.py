#!/usr/bin/env python3
"""将网页源文件和原创课文嵌入单个 HTML，供 GitHub Pages / file:// 离线运行。"""
import json
from pathlib import Path

from console_utf8 import enable_utf8_stdout

ROOT = Path(__file__).resolve().parent

def safe_js(value):
    # JSON 装载入 script：防止 </script> 等结束标签和特殊分隔符打断脚本。
    return (json.dumps(value, ensure_ascii=False, separators=(',', ':'))
            .replace('<', '\\u003c').replace('>', '\\u003e')
            .replace('&', '\\u0026').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029'))

def main():
    raw = (ROOT / 'web/template.html').read_text('utf-8')
    js = (ROOT / 'web/app.js').read_text('utf-8')
    js = js.replace('/*__LESSONS__*/', safe_js(json.loads((ROOT/'lessons.json').read_text('utf-8'))['lessons']))
    js = js.replace('/*__CATALOG__*/', safe_js(json.loads((ROOT/'catalog.json').read_text('utf-8'))))
    html = raw.replace('/*__CSS__*/', (ROOT / 'web/style.css').read_text('utf-8'))
    html = html.replace('/*__DATA__*/', '')
    html = html.replace('/*__JS__*/', js)
    if '/*__' in html or '__LESSONS__' in html:
        raise RuntimeError('存在未替换的网页构建占位符')
    target = ROOT / 'docs/index.html'
    target.parent.mkdir(exist_ok=True)
    # 显式写死 LF。默认写文件会按 os.linesep 转换，于是同一份模板在 Windows
    # 上生成 CRLF、在 Linux 上生成 LF。仓库和 CI 都按 LF 走，所以在 Windows 上
    # 跑一次 unittest，test_build 的「构建产物与仓库提交一致」就会挂。
    with open(target, 'w', encoding='utf-8', newline='\n') as f:
        f.write(html)
    print(f'构建完成：{target.relative_to(ROOT)} · {len(html.encode("utf-8")):,} bytes · 全部资源内联')

if __name__ == '__main__':
    enable_utf8_stdout()
    main()
