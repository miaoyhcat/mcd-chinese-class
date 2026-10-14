#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 lessons.json 内联进 web/template.html，生成自包含的 web/index.html。

为什么要构建这一步：演示页要能**双击直接打开**（file://）也能挂在 GitHub Pages 上。
如果让页面去 fetch('lessons.json')，file:// 下会被 CORS 拦掉，
所以干脆在构建时把模板烤进 HTML，产物是一个单文件、零依赖的页面。

产物：docs/index.html —— 页面设置里把 Pages 指向 main 分支的 /docs 即可。
"""

import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
LESSONS = HERE / "lessons.json"
TPL = HERE / "web" / "template.html"
# 输出到 docs/ —— GitHub Pages 直接从这里托管，演示地址干净
OUT = HERE / "docs" / "index.html"

REPO_URL = "https://github.com/miaoyhcat/mcd-chinese-class"


def main():
    data = json.loads(LESSONS.read_text(encoding="utf-8"))
    lessons = data["lessons"]
    fallbacks = data.get("fallbacks", {})

    OUT.parent.mkdir(parents=True, exist_ok=True)
    # 分类词表从 mcd_chinese.py 导入后注入网页 —— 单一数据源，
    # 免得命令行和网页两边各自维护一份、慢慢漂移。
    spec = importlib.util.spec_from_file_location("mc", HERE / "mcd_chinese.py")
    mc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mc)

    tpl = TPL.read_text(encoding="utf-8")

    # 用 json.dumps 保证注入的是合法 JS 字面量；</ 转义避免提前闭合 script
    def js(obj):
        return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")

    out = tpl
    for key, val in [("__DRINK_WORDS__", mc.DRINK_WORDS),
                     ("__SIDE_WORDS__", mc.SIDE_WORDS),
                     ("__MAIN_MARKERS__", mc.MAIN_MARKERS),
                     ("__SIZE_PREFIX__", mc.SIZE_PREFIX)]:
        out = out.replace(f"/*{key}*/", js(list(val)))

    out = out.replace("/*__LESSONS__*/", js(lessons))
    out = out.replace("/*__FALLBACKS__*/", js(fallbacks))
    out = out.replace("https://github.com/OWNER/REPO", REPO_URL)

    # 占位符一个都不能剩 —— 漏掉的话页面会拿空数组静默跑，分类全错却看不出来
    for leftover in ("__LESSONS__", "__FALLBACKS__", "__DRINK_WORDS__",
                     "__SIDE_WORDS__", "__MAIN_MARKERS__", "__SIZE_PREFIX__",
                     "OWNER/REPO"):
        assert leftover not in out, f"占位符 {leftover} 没替换干净"

    OUT.write_text(out, encoding="utf-8")
    kb = len(out.encode("utf-8")) / 1024
    print(f"已生成 {OUT.relative_to(HERE)}  ({kb:.0f} KB, 自包含，无外部依赖)")
    print(f"  内联课文 {len(lessons)} 篇：{'、'.join(l['title'] for l in lessons)}")


if __name__ == "__main__":
    main()
