#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 lessons.json 内联进 web/template.html，生成自包含的 docs/index.html。

为什么要构建这一步：演示页要能**双击直接打开**（file://）也能挂在 GitHub Pages 上。
如果让页面去 fetch('lessons.json')，file:// 下会被 CORS 拦掉，
所以干脆在构建时把模板烤进 HTML，产物是一个单文件、零依赖的页面。

用法：
    python build_web.py            # 生成/覆盖 docs/index.html
    python build_web.py --check    # 只比对，不写入（给测试和 CI 用）
"""

import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LESSONS = HERE / "lessons.json"
TPL = HERE / "web" / "template.html"
# 输出到 docs/ —— GitHub Pages 直接从这里托管，演示地址干净
OUT = HERE / "docs" / "index.html"

REPO_URL = "https://github.com/miaoyhcat/mcd-chinese-class"

# 需要注入网页的词表。唯一数据源是 mcd_chinese.py ——
# 网页这边不单独维护，免得两边慢慢漂移（之前就漂过一次）。
INJECT_LISTS = ("DRINK_EXACT", "DRINK_WORDS", "DRINK_SUFFIX",
                "SIDE_WORDS", "SIDE_SUFFIX", "MAIN_MARKERS", "SIZE_PREFIX")


def js(obj):
    """输出合法 JS 字面量；</ 转义避免提前闭合 script 标签。"""
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")


def build(tpl: str, data: dict) -> str:
    """纯函数：模板 + 数据 → 最终 HTML。不碰磁盘，方便比对。"""
    spec = importlib.util.spec_from_file_location("mc", HERE / "mcd_chinese.py")
    mc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mc)
    sys.modules.pop("mc", None)

    out = tpl
    for key in INJECT_LISTS:
        out = out.replace(f"/*__{key}__*/", js(list(getattr(mc, key))))
    out = out.replace("/*__LESSONS__*/", js(data["lessons"]))
    out = out.replace("/*__FALLBACKS__*/", js(data.get("fallbacks", {})))
    out = out.replace("https://github.com/OWNER/REPO", REPO_URL)

    # 占位符一个都不能剩 —— 漏掉的话页面会拿空数组静默跑，分类全错却看不出来
    holes = [f"__{k}__" for k in INJECT_LISTS] + ["__LESSONS__", "__FALLBACKS__",
                                                  "OWNER/REPO"]
    for leftover in holes:
        assert leftover not in out, f"占位符 {leftover} 没替换干净"
    return out


def check() -> int:
    """只比对，不写入。

    为什么要有这个模式：如果检查的方式是「先覆盖产物、再和覆盖前的内容比」，
    那么产物一旦漂移就被就地改回来了 —— 同一个漂移只会被报一次，
    第二次跑就看不出来。这种检查等于没有。
    """
    data = json.loads(LESSONS.read_text(encoding="utf-8"))
    built = build(TPL.read_text(encoding="utf-8"), data)
    current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
    if built == current:
        print("docs/index.html 与构建产物一致 ✓")
        return 0
    print("docs/index.html 与构建产物不一致 —— 请重跑 python build_web.py 并提交")
    print(f"  当前 {len(current)} 字符 / 应为 {len(built)} 字符")
    return 1


def main() -> int:
    data = json.loads(LESSONS.read_text(encoding="utf-8"))
    built = build(TPL.read_text(encoding="utf-8"), data)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(built, encoding="utf-8")
    print(f"已生成 {OUT.relative_to(HERE)}  ({len(built.encode('utf-8')) / 1024:.0f} KB, "
          f"自包含，无外部依赖)")
    print(f"  内联课文 {len(data['lessons'])} 篇："
          f"{'、'.join(l['title'] for l in data['lessons'])}")
    return 0


if __name__ == "__main__":
    sys.exit(check() if "--check" in sys.argv else main())
