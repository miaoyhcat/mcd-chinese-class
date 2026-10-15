#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""麦门语文课 · 测试套件（只用标准库，不依赖 pytest）。

跑法：
    python tests/test_mcd_chinese.py

覆盖：
    生成    16 篇 × 多种订单，无残留占位符、不含习题
    分类    三级判定：水果派/抹茶派不被误判为饮品
    订单    取最近一笔、跳过已取消、全部取消时返回 None
    份数    quantity 被解析且不丢
    课号    同一订单稳定；非 BMP 字符与 JS 端算法对齐
    合规    必需文件齐全、声明文件与官方一致、无硬编码凭据
"""

import base64
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    mark = "✓" if cond else "✗"
    print(f"  {mark} {name}" + (f"   {detail}" if detail and not cond else ""))


def load():
    spec = importlib.util.spec_from_file_location("mc", ROOT / "mcd_chinese.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def run_cli(*args, **kw):
    return subprocess.run([sys.executable, str(ROOT / "mcd_chinese.py"), *args],
                          capture_output=True, text=True, encoding="utf-8", **kw)


# ─────────────────────── 生 成 ───────────────────────
def test_generate(mc):
    print("\n[生成]")
    lessons = json.loads((ROOT / "lessons.json").read_text(encoding="utf-8"))["lessons"]
    orders = ["巨无霸,中薯条,可乐", "板烧鸡腿堡,大薯条,雪碧",
              "水果派,巨无霸,抹茶派,奶茶", "可乐", "巨无霸套餐,麦乐鸡"]

    bad_placeholder = bad_questions = bad_rc = 0
    for l in lessons:
        for o in orders:
            r = run_cli("--items", o, "--lesson", l["id"], "--json")
            if r.returncode != 0:
                bad_rc += 1
                continue
            d = json.loads(r.stdout)
            txt = d["opening"] + "".join(d["body"]) + d["ending"]
            if re.search(r"\{\w+\}", txt):
                bad_placeholder += 1
            if "questions" in d or "课后习题" in txt or "习题" in txt:
                bad_questions += 1

    n = len(lessons) * len(orders)
    check(f"{len(lessons)} 篇 × {len(orders)} 种订单 = {n} 次生成全部成功", bad_rc == 0, f"{bad_rc} 次失败")
    check("生成结果无残留占位符", bad_placeholder == 0, f"{bad_placeholder} 次有")
    check("生成结果不含任何习题字段/文案", bad_questions == 0, f"{bad_questions} 次有")

    # 三端都不该出现习题
    r = run_cli("--demo")
    check("终端输出不含习题", "习题" not in r.stdout and "课文完" in r.stdout)
    r = run_cli("--demo", "--md")
    check("Markdown 输出不含习题", "习题" not in r.stdout and "课文完" in r.stdout)
    r = run_cli("--demo", "--json")
    check("JSON 里没有 questions 字段", "questions" not in json.loads(r.stdout))

    # 正文完整性：课文核心文本必须保留
    be = next(l for l in lessons if l["id"] == "beiying")
    d = json.loads(run_cli("--items", "巨无霸,可乐", "--lesson", "beiying", "--json").stdout)
    check("课文正文段落完整（未误删）",
          len(d["body"]) == len(be["body"]) and all(p.strip() for p in d["body"]))
    check("课号 / 标题 / 作者 / 文体都在",
          all(d.get(k) for k in ("number", "title", "author", "tag")))


# ─────────────────────── 分 类 ───────────────────────
def test_classify(mc):
    print("\n[分类]")
    cases = [
        (["水果派", "巨无霸", "可乐"], "水果派" not in mc.classify(["水果派", "巨无霸", "可乐"])[2],
         "水果派不该是饮品"),
        (["抹茶派", "奶茶"], "抹茶派" not in mc.classify(["抹茶派", "奶茶"])[2],
         "抹茶派不该是饮品"),
        (["矿泉水", "巨无霸"], "矿泉水" in mc.classify(["矿泉水", "巨无霸"])[2],
         "矿泉水应该是饮品"),
        (["柠檬茶", "苹果派"], "柠檬茶" in mc.classify(["柠檬茶", "苹果派"])[2],
         "柠檬茶应该是饮品"),
    ]
    for items, cond, why in cases:
        ma, si, dr = mc.classify(items)
        check(f"classify({items}) — {why}", cond, f"得到 主食={ma} 小食={si} 饮品={dr}")

    # 三者互不重叠，且主食一定有值
    bad = 0
    for items in [["巨无霸", "中薯条", "可乐"], ["可乐"], ["水果派", "麦旋风"],
                  ["板烧鸡腿堡", "大薯条", "雪碧"], ["麦香鱼"], ["巨无霸套餐", "麦乐鸡"]]:
        ma, si, dr = mc.classify(items)
        if set(ma) & set(si) or set(ma) & set(dr) or set(si) & set(dr) or not ma:
            bad += 1
    check("主食/小食/饮品三者互不重叠且主食非空", bad == 0, f"{bad} 例有问题")

    # 认不出的餐品要能降级，不能抛异常
    try:
        mc.classify(["某个不存在的餐品", "另一个怪东西"])
        check("未知餐品可降级不报错", True)
    except Exception as e:
        check("未知餐品可降级不报错", False, str(e))


# ─────────────────────── 订 单 ───────────────────────
def test_orders(mc):
    print("\n[订单解析]")
    def mk(rows):
        return {"data": {"list": rows}}

    mixed = mk([
        {"orderId": "B2", "createTime": "2026-10-13 12:00", "orderStatus": "已完成",
         "orderProductList": [{"productName": "巨无霸", "quantity": 1}]},
        {"orderId": "B1", "createTime": "2026-10-12 12:00", "orderStatus": "已取消",
         "orderProductList": [{"productName": "薯饼", "quantity": 2}]},
    ])
    check("取最近一笔（跳过已取消）", (mc._pick_latest_order(mixed) or {}).get("orderId") == "B2")

    allcancel = mk([
        {"orderId": "A1", "createTime": "2026-10-12", "orderStatus": "已取消",
         "orderProductList": [{"productName": "薯饼", "quantity": 2}]},
        {"orderId": "A0", "createTime": "2026-10-11", "orderStatus": "退款成功",
         "orderProductList": [{"productName": "麦香鱼", "quantity": 1}]},
    ])
    check("全部已取消时返回 None（不退回取消列表）",
          mc._pick_latest_order(allcancel) is None)

    qty = mk([{"orderId": "C1", "createTime": "2026-10-15", "orderStatus": "已完成",
               "orderProductList": [{"productName": "巨无霸", "quantity": 2},
                                    {"productName": "可乐", "quantity": 3}]}])
    o = mc._pick_latest_order(qty)
    check("份数被解析", mc._lines_with_qty(o) == [("巨无霸", 2), ("可乐", 3)])
    check("正文用名单不含份数标记", mc._lines_of(o) == ["巨无霸", "可乐"])
    check("展示行体现份数", "×2" in mc._items_note(o) and "×3" in mc._items_note(o))

    # 套餐：子项展开、与套餐名重复的跳过
    combo = mk([{"orderId": "D1", "createTime": "2026-10-15", "orderStatus": "已完成",
                 "orderProductList": [{"productName": "巨无霸套餐", "quantity": 1,
                                       "comboItemList": [{"productName": "巨无霸"},
                                                         {"productName": "中薯条"},
                                                         {"productName": "可乐"}]}]}])
    names = mc._lines_of(mc._pick_latest_order(combo))
    check("套餐子项展开", "中薯条" in names and "可乐" in names)
    check("与套餐名重复的子项被跳过", names.count("巨无霸") == 0)
    check("套餐子项不凭空推断（只取接口给的）", names == ["巨无霸套餐", "中薯条", "可乐"])

    # 别名结构也要认得
    alias = {"result": {"records": [
        {"id": "E1", "orderDate": "2026-10-16", "status": "已完成",
         "products": [{"name": "麦辣鸡腿堡", "quantity": 1}]},
        {"id": "E0", "orderDate": "2026-10-10", "status": "已完成",
         "products": [{"name": "麦香鱼", "quantity": 1}]}]}}
    check("兼容别名结构与另一种包装层",
          (mc._pick_latest_order(alias) or {}).get("id") == "E1")


# ─────────────────────── 课 号 ───────────────────────
def test_number(mc):
    print("\n[课号一致性]")
    check("同一订单课号稳定", mc.lesson_number(["巨无霸", "可乐"]) == mc.lesson_number(["巨无霸", "可乐"]))
    check("不同订单课号不同", mc.lesson_number(["巨无霸"]) != mc.lesson_number(["麦香鱼"]))
    check("课号在 1..999", all(1 <= mc.lesson_number([s]) <= 999
                              for s in ["巨无霸", "🍔套餐", "𠮷野家", "abc", ""]))

    # 与 JS 端算法对齐（含非 BMP 字符）
    js = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
    m = re.search(r"function lessonNumber\(items\)\{[\s\S]*?\n\}", js)
    check("网页里能找到 lessonNumber", bool(m))
    check("网页用 codePointAt（非 charCodeAt）", bool(m) and "codePointAt" in m.group(0))
    check("网页用 for...of 遍历（走码点）", bool(m) and "for (const ch of" in m.group(0))


# ─────────────────────── 合 规 ───────────────────────
def test_compliance(mc):
    print("\n[合规与安全]")
    for f in ["README.md", "CONTEST_DECLARATION.md", "MCP_INTEGRATION.md",
              "mcp-config.example.json"]:
        check(f"必需文件存在：{f}", (ROOT / f).exists())

    cfg = json.loads((ROOT / "mcp-config.example.json").read_text(encoding="utf-8"))
    auth = cfg["mcpServers"]["mcd-mcp"]["headers"]["Authorization"]
    check("配置示例只用占位符", "YOUR_MCP_TOKEN" in auth)
    check("配置示例 URL 正确", cfg["mcpServers"]["mcd-mcp"]["url"] == "https://mcp.mcd.cn")

    # 声明文件与官方逐字节一致
    r = subprocess.run(["gh", "api",
                        "repos/M-China/mcd-developer-innovation-challenge/contents/CONTEST_DECLARATION.md",
                        "--jq", ".content"], capture_output=True, text=True, encoding="utf-8")
    if r.returncode == 0 and r.stdout.strip():
        offi = base64.b64decode(r.stdout.strip())
        check("CONTEST_DECLARATION 与官方逐字节一致",
              offi == (ROOT / "CONTEST_DECLARATION.md").read_bytes())
    else:
        check("CONTEST_DECLARATION 与官方逐字节一致", False, "取不到官方文件，跳过")

    # 扫描硬编码凭据
    SEC = re.compile(r"(sk-[A-Za-z0-9]{16,}|ghp_[A-Za-z0-9]{20,}"
                     r"|MCD_MCP_TOKEN\s*=\s*[\"'][^\"']{16,}"
                     r"|Bearer\s+[A-Za-z0-9]{20,})")
    hits = []
    for f in ROOT.rglob("*"):
        if not f.is_file() or ".git" in f.parts or f.suffix in (".png", ".jpg"):
            continue
        t = f.read_text(encoding="utf-8", errors="ignore")
        if SEC.search(t):
            hits.append(str(f.relative_to(ROOT)))
    check("仓库内无硬编码凭据", not hits, str(hits))

    # 错误日志不该泄露订单数据（方案 3.3）
    import os as _os
    code = """
import sys; sys.path.insert(0, ".")
import mcd_chinese as m
try:
    m._bail({"orderId": "SECRET-99999", "storeName": "某某店"}, "解析失败")
except SystemExit:
    pass
"""
    r = subprocess.run([sys.executable, "-c", code], capture_output=True,
                       text=True, encoding="utf-8", cwd=str(ROOT),
                       env={**_os.environ, "MCD_DEBUG": ""})
    check("默认模式不打印原始订单数据",
          "SECRET-99999" not in r.stderr and "某某店" not in r.stderr)
    check("默认模式给出 --debug 提示", "--debug" in r.stderr)
    r2 = subprocess.run([sys.executable, "-c", code], capture_output=True,
                        text=True, encoding="utf-8", cwd=str(ROOT),
                        env={**_os.environ, "MCD_DEBUG": "1"})
    check("--debug 模式才打印原始结构", "SECRET-99999" in r2.stderr)

    # 编译产物里不该有习题残留
    built = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
    check("网页产物不含习题", "习题" not in built and "questions" not in built)
    # 只查真实的赋值语句 —— 注释里出现这个单词不算
    assigns = re.findall(r"\.innerHTML\s*=", built)
    check("网页用 textContent 建节点（防注入）",
          "textContent" in built and not assigns,
          f"仍有 {len(assigns)} 处 innerHTML 赋值")
    check("网页不含 document.write / eval",
          not re.search(r"document\.write|eval\s*\(", built))


def main():
    print("═" * 52)
    print("  麦门语文课 · 测试套件")
    print("═" * 52)
    mc = load()
    test_generate(mc)
    test_classify(mc)
    test_orders(mc)
    test_number(mc)
    test_compliance(mc)

    total = len(PASS) + len(FAIL)
    print("\n" + "═" * 52)
    print(f"  通过 {len(PASS)}/{total}" + (f"，失败 {len(FAIL)}" if FAIL else "，全部通过 ✓"))
    if FAIL:
        print("  失败项：")
        for f in FAIL:
            print("    ·", f)
    print("═" * 52)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
