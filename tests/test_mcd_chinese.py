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
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PASS, FAIL, SKIP = [], [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    mark = "✓" if cond else "✗"
    print(f"  {mark} {name}" + (f"   {detail}" if detail and not cond else ""))


def skip(name, why):
    """环境不具备时跳过。**不计入通过** —— 报告里单独列出。"""
    SKIP.append(f"{name}（{why}）")
    print(f"  SKIP {name}   {why}")


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
    try:
        check("取最近一笔（跳过已取消）",
              (mc._pick_latest_order(mixed) or {}).get("orderId") == "B2")
    except Exception as e:
        check("取最近一笔（跳过已取消）", False, f"抛异常 {type(e).__name__}: {e}")

    allcancel = mk([
        {"orderId": "A1", "createTime": "2026-10-12", "orderStatus": "已取消",
         "orderProductList": [{"productName": "薯饼", "quantity": 2}]},
        {"orderId": "A0", "createTime": "2026-10-11", "orderStatus": "退款成功",
         "orderProductList": [{"productName": "麦香鱼", "quantity": 1}]},
    ])
    try:
        check("全部已取消时返回 None（不退回取消列表）",
              mc._pick_latest_order(allcancel) is None)
    except Exception as e:
        check("全部已取消时返回 None（不退回取消列表）", False,
              f"抛异常 {type(e).__name__}: {e}（应该返回 None，不是崩溃）")

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
    # 官方规则要求示例只用「环境变量占位符」，不能出现任何真实凭据
    check("配置示例用环境变量占位符 ${MCD_MCP_TOKEN}", "${MCD_MCP_TOKEN}" in auth)
    check("配置示例里没有真实密钥形状的串",
          not re.search(r"Bearer\s+(?!\$\{)[A-Za-z0-9_\-]{16,}", auth))
    check("配置示例 URL 正确", cfg["mcpServers"]["mcd-mcp"]["url"] == "https://mcp.mcd.cn")

    # 声明文件与官方逐字节一致 —— 需要联网 + gh，取不到就报 SKIP（不算通过）
    r = subprocess.run(["gh", "api",
                        "repos/M-China/mcd-developer-innovation-challenge/contents/CONTEST_DECLARATION.md",
                        "--jq", ".content"], capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0 or not r.stdout.strip():
        skip("CONTEST_DECLARATION 与官方逐字节一致", "取不到官方文件（无 gh / 无网络）")
    else:
        offi = base64.b64decode(r.stdout.strip())
        check("CONTEST_DECLARATION 与官方逐字节一致",
              offi == (ROOT / "CONTEST_DECLARATION.md").read_bytes())

    # 演示页不能和构建产物漂移。
    # 用 --check 模式：只比对、不写入 —— 否则检查本身会把漂移就地修好，
    # 同一个漂移第二次跑就查不出来了。
    rb = subprocess.run([sys.executable, str(ROOT / "build_web.py"), "--check"],
                        capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT))
    check("docs/index.html 与构建产物一致（--check，不写入）", rb.returncode == 0,
          (rb.stdout or rb.stderr or "").strip()[:140])

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



# ─────────────────────── 订单解析回归（P1-6）───────────────────────
def test_order_edge_cases(mc):
    """任务书点名的边界：套餐子项、父子数量、同名合并、0/负数量、坏字段、未知商品、时间排序。"""
    print(chr(10) + "[订单解析 · 边界]")

    def mk(rows):
        return {"data": {"list": rows}}

    # 套餐：父子项数量独立解析
    combo = mk([{"orderId": "C1", "createTime": "2026-10-15", "orderStatus": "已完成",
                 "orderProductList": [
                     {"productName": "巨无霸套餐", "quantity": 2,
                      "comboItemList": [{"productName": "中薯条"},
                                        {"productName": "可乐", "quantity": 2}]}]}])
    got = mc._lines_with_qty(mc._pick_latest_order(combo))
    check("套餐：父项数量被解析", dict(got).get("巨无霸套餐") == 2, str(got))
    check("套餐：子项单独计数", dict(got).get("可乐") == 2, str(got))
    # 子项没给数量时按父项份数算：2 份套餐 = 2 份套餐里的薯条
    check("套餐：子项无数量时按父项份数算", dict(got).get("中薯条") == 2, str(got))

    # 同名合并
    dup = mk([{"orderId": "D1", "createTime": "2026-10-15", "orderStatus": "已完成",
               "orderProductList": [{"productName": "巨无霸", "quantity": 1},
                                    {"productName": "巨无霸", "quantity": 2}]}])
    check("同名条目数量合并", dict(mc._lines_with_qty(mc._pick_latest_order(dup)))["巨无霸"] == 3)
    check("同名合并不产生重复名字", mc._lines_of(mc._pick_latest_order(dup)) == ["巨无霸"])

    # 0 / 负 / 非法数量
    weird = mk([{"orderId": "E1", "createTime": "2026-10-15", "orderStatus": "已完成",
                 "orderProductList": [{"productName": "巨无霸", "quantity": 0},
                                      {"productName": "薯条", "quantity": -3},
                                      {"productName": "可乐", "quantity": "abc"},
                                      {"productName": "麦香鱼", "quantity": None}]}])
    g2 = mc._lines_with_qty(mc._pick_latest_order(weird))
    check("0/负/非法数量一律按 1 处理", all(q == 1 for _, q in g2), str(g2))

    # 坏字段
    bad = mk([{"orderId": "F1", "createTime": "2026-10-15", "orderStatus": "已完成",
               "orderProductList": [None, "字符串", 42,
                                    {"productName": ""}, {"name": "板烧鸡腿堡", "quantity": 1}]}])
    try:
        got_bad = mc._lines_of(mc._pick_latest_order(bad))
        check("坏字段不会抛异常", True)
        check("坏字段里能取出有效餐品", got_bad == ["板烧鸡腿堡"], str(got_bad))
    except Exception as e:
        check("坏字段不会抛异常", False, f"{type(e).__name__}: {e}")
        check("坏字段里能取出有效餐品", False, "上一步就抛了")

    # 未知商品可降级
    unknown = mk([{"orderId": "G1", "createTime": "2026-10-15", "orderStatus": "已完成",
                   "orderProductList": [{"productName": "某个不存在的餐品", "quantity": 1}]}])
    ma, si, dr = mc.classify(mc._lines_of(mc._pick_latest_order(unknown)))
    check("未知商品仍能生成正文（降级到主食）", bool(ma))

    # 时间排序：乱序输入也要取最新
    shuffled = mk([
        {"orderId": "H1", "createTime": "2026-10-10", "orderStatus": "已完成",
         "orderProductList": [{"productName": "A", "quantity": 1}]},
        {"orderId": "H3", "createTime": "2026-10-18", "orderStatus": "已完成",
         "orderProductList": [{"productName": "C", "quantity": 1}]},
        {"orderId": "H2", "createTime": "2026-10-14", "orderStatus": "已完成",
         "orderProductList": [{"productName": "B", "quantity": 1}]},
    ])
    check("乱序输入按时间取最新", mc._pick_latest_order(shuffled)["orderId"] == "H3")

    # 空列表 / 缺字段
    for label, payload in [("订单列表为空", mk([])), ("完全没有订单字段", {}),
                           ("data 为空对象", {"data": {}})]:
        try:
            check(f"{label}时返回 None", mc._pick_latest_order(payload) is None)
        except Exception as e:
            check(f"{label}时返回 None", False, f"抛异常 {type(e).__name__}")


# ─────────────────────── MCP 客户端异常（P1-6）───────────────────────
def test_mcp_client():
    print(chr(10) + "[MCP 客户端 · 异常处理]")
    import importlib.util as _iu
    spec = _iu.spec_from_file_location("mm", ROOT / "mcd_mcp.py")
    mm = _iu.module_from_spec(spec)
    spec.loader.exec_module(mm)

    # 无效 JSON
    try:
        mm._parse_body("这不是 JSON", "application/json")
        check("无效 JSON 抛 MCDError", False, "没抛异常")
    except mm.MCDError:
        check("无效 JSON 抛 MCDError", True)
    except Exception as e:
        check("无效 JSON 抛 MCDError", False, f"抛了 {type(e).__name__}")

    NL = chr(10)

    # SSE 多事件：取最后一条
    sse = (f'event: message{NL}data: {{"jsonrpc":"2.0","id":1,'
           f'"result":{{"n":"first"}}}}{NL}{NL}'
           f'data: {{"jsonrpc":"2.0","id":1,"result":{{"n":"last"}}}}{NL}{NL}')
    got = mm._parse_body(sse, "text/event-stream")
    check("SSE 多事件取最后一条", got["result"]["n"] == "last", str(got))

    # SSE 收尾的 [DONE] 不应被当成数据
    sse2 = f'data: {{"result":{{"n":"x"}}}}{NL}{NL}data: [DONE]{NL}{NL}'
    check("SSE 忽略 [DONE]", mm._parse_body(sse2, "text/event-stream")["result"]["n"] == "x")

    # 「结构说明 + 原始 JSON」混合文本
    mixed = ('# API Response Information' + NL + '...' + NL +
             '## Original Response' + NL + NL +
             '{"success":true,"data":{"list":[]}}')
    check("能从混合文本里提取 JSON",
          mm._extract_json(mixed)["data"]["list"] == [])

    # 只读白名单：写操作必须被拒
    c = mm.MCDClient.__new__(mm.MCDClient)   # 不走 __init__，只测白名单
    for tool in ["create-order", "cancel-order", "auto-bind-coupons",
                 "mall-create-order", "draw-lottery", "party-order-create"]:
        try:
            mm.MCDClient.call(c, tool, {})
            check(f"写操作 {tool} 被拒绝", False, "居然放行了")
        except mm.MCDError:
            check(f"写操作 {tool} 被拒绝", True)
        except Exception as e:
            # 白名单检查在 _ensure_ready 之前，不该跑到网络
            check(f"写操作 {tool} 被拒绝", False, f"抛了 {type(e).__name__}: {e}")

    # 无 Token 时的报错
    old = os.environ.pop("MCD_MCP_TOKEN", None)
    old2 = os.environ.pop("MCD_TOKEN", None)
    try:
        mm.MCDClient()
        check("无 Token 时抛 MCDError", False, "没抛")
    except mm.MCDError as e:
        check("无 Token 时抛 MCDError", "Token" in str(e))
    except Exception as e:
        check("无 Token 时抛 MCDError", False, type(e).__name__)
    finally:
        if old: os.environ["MCD_MCP_TOKEN"] = old
        if old2: os.environ["MCD_TOKEN"] = old2



# ─────────────────────── 分类的确定性断言（防盲区）───────────────────────
def test_classify_exact(mc):
    """变异测试暴露的盲区：只断言「主食非空」抓不到「全部归到小食」这类错误，
    因为兜底逻辑会把第一件顶上去当主食。所以这里断言**明确的具体结果**。"""
    print(chr(10) + "[分类 · 明确结果]")
    cases = [
        (["巨无霸", "中薯条", "可乐"], ["巨无霸"], ["中薯条"], ["可乐"]),
        (["板烧鸡腿堡", "大薯条", "雪碧"], ["板烧鸡腿堡"], ["大薯条"], ["雪碧"]),
        (["麦香鱼", "苹果派"], ["麦香鱼"], ["苹果派"], []),
        (["双层吉士堡", "玉米杯", "拿铁"], ["双层吉士堡"], ["玉米杯"], ["拿铁"]),
        (["水果派", "矿泉水"], None, None, ["矿泉水"]),
        # 小食排在前面：兜底逻辑会把「第一个非饮品」顶成主食，
        # 所以必须用这种顺序才能测出「主食判定是否真的生效」
        (["中薯条", "巨无霸", "可乐"], ["巨无霸"], ["中薯条"], ["可乐"]),
        (["苹果派", "板烧鸡腿堡"], ["板烧鸡腿堡"], ["苹果派"], []),
    ]
    for items, want_main, want_side, want_drink in cases:
        ma, si, dr = mc.classify(items)
        if want_main is not None:
            check(f"classify({items}) 主食={want_main}", ma == want_main, f"实际 {ma}")
        if want_side is not None:
            check(f"classify({items}) 小食={want_side}", si == want_side, f"实际 {si}")
        check(f"classify({items}) 饮品={want_drink}", dr == want_drink, f"实际 {dr}")

    # 汉堡类必须进主食，不能被降级成小食
    for burger in ["巨无霸", "板烧鸡腿堡", "麦辣鸡腿堡", "双层吉士堡", "麦香鱼"]:
        ma, _, _ = mc.classify([burger])
        check(f"{burger} 被识别为主食", ma == [burger], f"实际 {ma}")


# ─────────────────────── 课号真正跨端比对 ───────────────────────
def test_number_cross_platform(mc):
    """真正的跨端一致性检查：把网页里的 lessonNumber 抽出来在 Node 里跑，
    和 Python 的结果逐个比对。

    （原来只检查了「网页源码里写了 codePointAt」，那是**查源码文本**，
      不是查两个实现是否真的算出同一个数 —— 变异测试证明它能被绕过。）"""
    print(chr(10) + "[课号 · 跨端真比对]")
    import shutil, tempfile

    node = shutil.which("node")
    if not node:
        skip("课号 Python/JS 一致", "本机没有 node")
        return

    built = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
    m = re.search(r"function lessonNumber\(items\)\{[\s\S]*?\n\}", built)
    if not m:
        check("能从产物里抽出 lessonNumber", False, "没找到函数")
        return
    check("能从产物里抽出 lessonNumber", True)

    orders = [["巨无霸", "中薯条", "可乐"], ["板烧鸡腿堡", "大薯条", "雪碧"],
              ["可乐"], ["麦香鱼"], ["🍔套餐"], ["𠮷野家"], ["A", "B"],
              ["某个不存在的餐品", "另一个怪东西"]]

    NL = chr(10)
    script = (m.group(0) + NL
              + "const orders = " + json.dumps(orders, ensure_ascii=False) + ";" + NL
              + "for (const o of orders) console.log(lessonNumber(o));")
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as f:
        f.write(script)
        tmp = f.name
    try:
        r = subprocess.run([node, tmp], capture_output=True, text=True,
                           encoding="utf-8")
        if r.returncode != 0:
            check("Node 能运行 lessonNumber", False, (r.stderr or "")[:100])
            return
        js_nums = [int(x) for x in r.stdout.split()]
    finally:
        os.unlink(tmp)

    py_nums = [mc.lesson_number(o) for o in orders]
    mismatches = [(o, p, j) for o, p, j in zip(orders, py_nums, js_nums) if p != j]
    check(f"{len(orders)} 组订单 Python 与 JS 课号逐个相同",
          not mismatches, f"不一致: {mismatches}")

    # 非 BMP 字符单独点名（历史上就是这里出的问题）
    for o in [["🍔套餐"], ["𠮷野家"]]:
        p_, j_ = mc.lesson_number(o), js_nums[orders.index(o)]
        check(f"非 BMP 序列 {o} 跨端一致（Python {p_} / JS {j_}）", p_ == j_)


def main():
    print("═" * 52)
    print("  麦门语文课 · 测试套件")
    print("═" * 52)
    mc = load()
    test_generate(mc)
    test_classify(mc)
    test_classify_exact(mc)
    test_orders(mc)
    test_order_edge_cases(mc)
    test_mcp_client()
    test_number(mc)
    test_number_cross_platform(mc)
    test_compliance(mc)

    print("\n" + "═" * 52)
    print(f"  PASS {len(PASS)} / FAIL {len(FAIL)} / SKIP {len(SKIP)}")
    if FAIL:
        print("  失败项：")
        for f in FAIL:
            print("    ·", f)
    if SKIP:
        print("  跳过项（环境不具备，**未验证，不算通过**）：")
        for f in SKIP:
            print("    ·", f)
    if not FAIL and not SKIP:
        print("  全部通过 ✓")
    elif not FAIL:
        print(f"  无失败，但有 {len(SKIP)} 项跳过 —— 不能视为全部通过")
    print("═" * 52)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
