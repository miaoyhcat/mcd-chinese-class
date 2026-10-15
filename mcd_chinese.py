#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""麦门语文课 · 把你的麦当劳订单改写成语文课本。

用法：
    python mcd_chinese.py --demo                    # 内置样例，不需要 Token
    python mcd_chinese.py --items "巨无霸,薯条,可乐"   # 自己给餐品
    python mcd_chinese.py --mcp                     # 读真实订单历史（需要 Token）
    python mcd_chinese.py --list                    # 看有哪些课文可选
    python mcd_chinese.py --demo --lesson kongyiji  # 指定课文
    python mcd_chinese.py --demo --json             # 输出 JSON

设计取向：生成过程是**确定性**的，同一份订单永远得到同一篇课文，
不调用任何大模型。所以它既能当 Skill 用，也能脱离 AI 客户端独立跑。
"""

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
LESSONS_PATH = HERE / "lessons.json"

# 排查模式：只有显式打开才会打印原始接口返回。
# 订单返回里有订单号、门店、金额，默认不能进日志。
DEBUG = bool(os.environ.get("MCD_DEBUG")) or "--debug" in sys.argv


def enable_utf8_stdout():
    """把标准输出/错误切成 UTF-8。

    Windows 上控制台编码跟着系统区域走：中文环境是 GBK（凑巧能编中文），
    英文环境是 cp1252 —— 后者一 print 中文就 UnicodeEncodeError 直接崩。
    终端里跑 CLI 的人不该因为系统语言是英文就用不了。
    errors="replace" 兜底：万一真有编不出的字符，显示成 ? 也比崩掉强。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass        # 被重定向成非 TextIOWrapper（管道/测试捕获）时跳过

# ── 餐品归类 ──
# 判定按三级优先级走，越具体的规则排越前：
#   ① 整名精确命中  ② 子串关键词  ③ 后缀命中  ④ 未知兜底（归小食）
#
# 为什么不能只用子串：以前 DRINK_WORDS 里有「水」，于是「水果派」被当成饮品。
# 太短的词（水、茶、派）必须限定匹配方式，否则会误伤别的餐品名。
DRINK_EXACT = ("水", "矿泉水", "纯净水", "饮用水", "苏打水", "气泡水", "冰水")
DRINK_WORDS = ("可乐", "雪碧", "芬达", "咖啡", "拿铁", "美式", "奶茶",
               "果汁", "橙汁", "豆浆", "牛奶")
DRINK_SUFFIX = ("茶", "水")          # 「柠檬茶」「矿泉水」算，「抹茶派」「水果派」不算

# 注意别放「鸡腿」——「板烧鸡腿堡」「麦辣鸡腿堡」是汉堡，会被误判成小食
SIDE_WORDS = ("薯条", "鸡块", "鸡翅", "沙拉", "玉米", "洋葱圈",
              "冰淇淋", "麦旋风", "新地", "圣代", "蛋挞", "水果")
SIDE_SUFFIX = ("派",)                # 「苹果派」算小食，「派对盒子」不算

# 汉堡类一律算主食，优先级高于上面的小食词
# 「巨无霸」「麦香鱼」是汉堡但名字里没有「堡」，得显式列出来
MAIN_MARKERS = ("堡", "卷", "饭", "粥", "巨无霸", "麦香鱼")


def is_drink(name):
    """是不是饮品。三级判定，避免「水果派」被「水」误伤。"""
    if name in DRINK_EXACT:
        return True
    if any(w in name for w in DRINK_WORDS):
        return True
    return any(name.endswith(s) for s in DRINK_SUFFIX)


def is_side(name):
    """是不是小食。"""
    if any(w in name for w in SIDE_WORDS):
        return True
    return any(name.endswith(s) for s in SIDE_SUFFIX)

# 尺寸前缀：用在「金黄的___」这种形容词位置时要去掉，否则读起来别扭
SIZE_PREFIX = ("超大", "大", "中", "小")


def strip_size(name):
    """「中薯条」→「薯条」。只剥前缀，不动后面的字。"""
    for pre in SIZE_PREFIX:
        if name.startswith(pre) and len(name) > len(pre) + 1:
            return name[len(pre):]
    return name


# 内置样例：一个很典型的「一个人加班到晚上」的订单
DEMO_ORDER = ["巨无霸", "中薯条", "可乐"]


# ─────────────────────── 课文生成 ───────────────────────
def load_lessons():
    data = json.loads(LESSONS_PATH.read_text(encoding="utf-8"))
    return data["lessons"], data.get("fallbacks", {})


def classify(items):
    """把餐品分成 主食 / 小食 / 饮品，三者互不重叠。

    判定顺序：能喝的算饮品；含「堡/卷/饭/粥」的算主食；其余一律归小食。
    实在找不到主食（比如只点了饮料和甜点）就把第一件非饮品顶上去，
    保证模板里 {main} 一定有值——宁可得出一篇滑稽的课文，也不能渲染出空位。
    """
    drinks = [i for i in items if is_drink(i)]
    mains, sides = [], []
    for i in items:
        if i in drinks:
            continue
        if any(w in i for w in MAIN_MARKERS):
            mains.append(i)
        else:
            sides.append(i)          # 认不出来的先归小食，不抢主食的位置
    if not mains:
        # 只点了饮料/甜点这类没有主食的订单：把第一件顶上去当主食。
        # 同时把它从原来那一组里摘掉，保证三组始终互不重叠 ——
        # 否则「只点一杯可乐」会让它同时属于主食和饮品。
        first = next((i for i in items if i not in drinks), items[0])
        mains = [first]
        sides = [s for s in sides if s != first]
        drinks = [d for d in drinks if d != first]
    return mains, sides, drinks


def pick_lesson(lessons, lesson_id=None, seed=None):
    if lesson_id:
        for l in lessons:
            if l["id"] == lesson_id:
                return l
        ids = ", ".join(l["id"] for l in lessons)
        raise SystemExit(f"没有这篇课文：{lesson_id}\n可选：{ids}")
    rng = random.Random(seed)
    return rng.choice(lessons)


def build_fields(items, fallbacks):
    """把订单整理成模板需要的字段。"""
    items = [i.strip() for i in items if i and i.strip()]
    if not items:
        items = list(DEMO_ORDER)
    mains, sides, drinks = classify(items)

    main = mains[0]
    side = strip_size(sides[0]) if sides else fallbacks.get("side", "薯条")
    drink = strip_size(drinks[0]) if drinks else fallbacks.get("drink", "可乐")

    # 去掉重复项，保留出现顺序
    uniq = []
    for i in items:
        if i not in uniq:
            uniq.append(i)
    # 模板里 {items} 会嵌进句子里（「他 A、B、C 的样子」），用顿号连接更通顺
    items_phrase = "、".join(uniq) if len(uniq) > 1 else uniq[0]

    return {
        "main": main,
        "side": side,
        "drink": drink,
        "items": items_phrase,
        "count": len(items),
        "store": fallbacks.get("store", "麦当劳"),
    }


def render(text, fields):
    """填占位符。缺字段就保留原样，方便一眼看出哪里没接上。"""
    try:
        return text.format(**fields)
    except (KeyError, IndexError):
        return text


def lesson_number(items):
    """给订单编一个稳定的「课号」，同一单永远同一号。

    ⚠ 算法必须和网页版 build_web 里内联的 lessonNumber() 一致，
    否则同一个订单在命令行和网页上会得到不同的课号。
    """
    h = 0
    for ch in "|".join(items):
        h = (h * 31 + ord(ch)) % 999983
    return h % 999 + 1


def compose(order, lesson, fallbacks):
    fields = build_fields(order, fallbacks)
    return {
        "lesson_id": lesson["id"],
        "number": lesson_number(order),
        "title": lesson["title"],
        "author": lesson["author"],
        "tag": lesson.get("tag", ""),
        "opening": render(lesson["opening"], fields),
        "body": [render(p, fields) for p in lesson["body"]],
        "ending": render(lesson.get("ending", ""), fields),
        "order": order,
    }


# ─────────────────────── 输出 ───────────────────────
BAR = "─" * 46


def as_text(doc):
    out = [
        "",
        BAR,
        f"  麦门语文课 · 第 {doc['number']:03d} 课",
        BAR,
        "",
        f"{doc['title']:^{44}}",
        f"{doc['author']:^{42}}",
        f"{doc.get('tag', ''):^{40}}",
        f"{'（根据你的订单改编）':^{40}}",
        "",
        f"    {doc['opening']}",
        "",
    ]
    for p in doc["body"]:
        out.append(f"    {p}")
        out.append("")
    if doc["ending"]:
        out.append(f"    {doc['ending']}")
        out.append("")
    out += [
        f"{'课文完':^{42}}",
        "",
        BAR,
        f"  本课订单：{'、'.join(doc['order'])}",
        BAR,
        "",
    ]
    return "\n".join(out)


def as_markdown(doc):
    lines = [
        f"# {doc['title']}",
        "",
        f"> {doc['author']} · 麦门语文课第 {doc['number']:03d} 课",
        "",
        doc["opening"],
        "",
    ]
    for p in doc["body"]:
        lines += [p, ""]
    if doc["ending"]:
        lines += [doc["ending"], ""]
    lines += ["*课文完*", "", "---", "",
              f"*本课订单：{'、'.join(doc['order'])}*"]
    return "\n".join(lines)


# ─────────────────────── 取订单 ───────────────────────
def _pick_latest_order(data):
    """从 order-list 的返回里挑出**最近一笔**订单。

    返回结构（根据社区联调记录整理，字段名可能有多个别名）：
        外层可能是 data / result / records / list / orderList / orders 之一
        订单：orderId, createTime / orderTime / createDate, storeName,
              orderStatus / status, realTotalAmount / totalAmount / amount,
              orderProductList / products: [{ productName / name, quantity }]
    """
    WRAPPERS = ("data", "result", "records", "list", "orderList", "orders")

    def find_orders(node, depth=0):
        """递归找到「看起来像订单数组」的那一层。"""
        if depth > 6:
            return None
        if isinstance(node, list):
            if node and all(isinstance(x, dict) for x in node):
                # 数组元素里有订单特征字段，就认定它是订单列表
                keys = set().union(*(set(x.keys()) for x in node[:5]))
                if keys & {"orderId", "id", "orderProductList", "products",
                           "realTotalAmount", "orderTime", "createTime"}:
                    return node
            for x in node:
                r = find_orders(x, depth + 1)
                if r:
                    return r
        elif isinstance(node, dict):
            for k in WRAPPERS:
                if k in node:
                    r = find_orders(node[k], depth + 1)
                    if r:
                        return r
            for v in node.values():
                r = find_orders(v, depth + 1)
                if r:
                    return r
        return None

    orders = find_orders(data)
    if not orders:
        return None

    def when(o):
        """取订单时间，用于排序。解析不出来就当最早。"""
        for k in ("createTime", "orderTime", "createDate", "orderDate", "time"):
            v = o.get(k)
            if v is None:
                continue
            if isinstance(v, (int, float)):
                return float(v)
            t = str(v).replace("/", "-").replace("T", " ")
            digits = "".join(c for c in t if c.isdigit())
            if len(digits) >= 8:
                return float(digits[:14])
        return 0.0

    # 已取消的订单跳过，然后按时间倒序取第一笔
    CANCELLED = ("取消", "已关闭", "退款", "cancel", "closed", "refund")
    alive = [o for o in orders
             if not any(m in str(o.get("orderStatus") or o.get("status") or "").lower()
                        for m in CANCELLED)]
    # 全部订单都已取消时返回 None，**绝不能退回取消列表** ——
    # 否则会拿一笔作废的订单生成课文，用户看到的是没吃成的东西。
    if not alive:
        return None
    alive.sort(key=when, reverse=True)
    return alive[0]


def _lines_with_qty(order):
    """从一笔订单里取出 [(餐品名, 份数), ...]，同名合并，按出现顺序。

    套餐要把 comboItemList 里的子项也捞出来 —— 否则点一份「巨无霸套餐」，
    课文里只会出现套餐名，看不到里面的薯条和可乐，分类会全落到主食上。
    子项的名字已经包含在套餐名里的（「巨无霸」⊂「巨无霸套餐」）跳过，避免重复。

    套餐内容**只按接口返回的 comboItemList 取**，不凭名字猜 ——
    「巨无霸套餐」里到底有没有薯条，以接口数据为准。
    """
    raw_lines = order.get("orderProductList") or order.get("products") or []
    if not isinstance(raw_lines, list):
        raw_lines = []

    pairs = []          # [(name, qty)]，保持顺序，同名在后面合并

    def add(n, qty):
        n = str(n or "").strip()
        try:
            q = int(qty or 1)
        except (TypeError, ValueError):
            q = 1
        if n:
            pairs.append((n, max(1, q)))

    for it in raw_lines:
        if not isinstance(it, dict):
            continue
        parent = str(it.get("productName") or it.get("name") or "").strip()
        qty = it.get("quantity")
        add(parent, qty)
        for sub in (it.get("comboItemList") or []):
            if isinstance(sub, dict):
                sn = str(sub.get("productName") or sub.get("name") or "").strip()
                if sn and sn not in parent:
                    # 套餐子项的份数一般跟套餐走，接口没给就按 1 算
                    # 子项没给数量时按父项份数算：点了 2 份套餐，
                    # 里面的薯条也是 2 份。这个推断写在这里，不靠运算符优先级凑。
                    add(sn, sub.get("quantity") or qty)

    merged = {}
    order_out = []
    for n, q in pairs:
        if n not in merged:
            merged[n] = q
            order_out.append(n)
        else:
            merged[n] += q
    return [(n, merged[n]) for n in order_out]


def _lines_of(order):
    """餐品名列表（去重保序）—— 给课文模板用，不含份数。"""
    return [n for n, _ in _lines_with_qty(order)]


def _items_note(order):
    """把份数拼成一行，份数大于 1 才标出来。"""
    got = _lines_with_qty(order)
    return "、".join(f"{n} ×{q}" if q > 1 else n for n, q in got)


def _order_meta(order):
    """把「读了哪一笔」拼成一行，用户能一眼确认是不是刚点的那单。"""
    meta = []
    for k in ("createTime", "orderTime", "createDate", "orderDate"):
        if order.get(k):
            meta.append(str(order[k]))
            break
    if order.get("storeName"):
        meta.append(str(order["storeName"]))
    for k in ("realTotalAmount", "totalAmount", "amount"):
        if order.get(k) is not None:
            meta.append(f"{order[k]} 元")
            break
    note = _items_note(order)
    if note:
        meta.append(note)          # 份数在这里体现，正文里不带「×2」这种标记
    return " · ".join(meta)


def order_from_mcp():
    """从麦当劳 MCP 读**最近一笔**订单的餐品名。

    真实返回结构（2026-10-15 用真实 Token 联调确认）：
        data.list[] = { orderId, orderType, createTime, beType, beCode,
                        storeCode, storeName, orderStatus, realTotalAmount,
                        orderProductList: [{ productCode, productName,
                                             quantity, comboItemList }] }
    并且工具返回的是「结构说明 + 原始 JSON」的混合文本，
    真正的 JSON 在 `## Original Response` 之后（见 mcd_mcp._extract_json）。

    token 的有效性、字段名、空数据形态都已实测；解析不出来时会打印原始返回并停下，
    不会静默给一个错误结果。
    """
    from mcd_mcp import MCDClient, MCDError

    try:
        data = MCDClient().call("order-list")
    except MCDError as e:
        raise SystemExit(f"读取订单失败：{e}")

    # 账号没有订单时 data 是空对象。这不是解析失败，要说人话。
    payload = data.get("data") if isinstance(data, dict) else None
    if not payload:
        raise SystemExit(chr(10).join([
            "这个账号近 90 天没有订单记录。",
            "  先用同一个手机号在麦当劳点一单，再回来跑 --mcp。",
            "  （想先看效果的话，用 --demo 或 --items，不需要 Token）",
        ]))

    order = _pick_latest_order(data)
    if order is None:
        _bail(data, "在返回里找不到订单列表")
    names = _lines_of(order)
    if not names:
        _bail(order, "这笔订单里没解析出餐品")

    meta = _order_meta(order)
    if meta:
        print(f"[订单] {meta}", file=sys.stderr)
    return names


def _bail(what, why):
    """解析失败时停下。

    默认**只报错误类别**，不打印原始返回 —— 订单数据里有订单号、门店、金额，
    这些不该默认落到日志里。要排查字段名，加 --debug 或设 MCD_DEBUG=1。
    """
    print(f"{why}。", file=sys.stderr)
    if DEBUG:
        print("原始结构（--debug 模式）：", file=sys.stderr)
        print(json.dumps(what, ensure_ascii=False, indent=2)[:1500], file=sys.stderr)
    else:
        print("  加 --debug 重跑可以看到原始返回结构，方便定位字段名。", file=sys.stderr)
    raise SystemExit(1)


def watch_mcp(interval=20):
    """盯单模式：挂着它，你去下单，出现新订单就自动把菜品改编成课文。

    这正是「点完餐就出课文」—— 不用手动再跑一次。
    """
    from mcd_mcp import MCDClient, MCDError

    try:
        client = MCDClient()
    except MCDError as e:
        raise SystemExit(f"{e}")

    lessons, fallbacks = load_lessons()
    last_id = None
    print(f"正在盯着订单…… 每 {interval} 秒查一次，去点你的餐吧（Ctrl+C 退出）", file=sys.stderr)

    while True:
        try:
            data = client.call("order-list")
            order = _pick_latest_order(data)
            if order is not None:
                oid = str(order.get("orderId") or order.get("id") or "")
                fresh = oid and oid != last_id
                if fresh and last_id is not None:
                    names = _lines_of(order)
                    if names:
                        meta = _order_meta(order)
                        print("")
                        print("=" * 46, flush=True)
                        print(f"  新订单来了：{'、'.join(names)}")
                        if meta:
                            print(f"  {meta}")
                        print('=' * 46)
                        lesson = pick_lesson(lessons, seed="|".join(names))
                        print(as_text(compose(names, lesson, fallbacks)), flush=True)
                if oid:
                    last_id = oid
        except MCDError as e:
            print(f"[跳过] {e}", file=sys.stderr)
        time.sleep(interval)


# ─────────────────────── 入口 ───────────────────────
def main(argv=None):
    enable_utf8_stdout()
    ap = argparse.ArgumentParser(
        description="麦门语文课 · 把你的麦当劳订单改写成语文课本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--demo", action="store_true", help="用内置样例订单（不需要 Token）")
    src.add_argument("--mcp", action="store_true", help="读最近一笔订单（需要 MCD_MCP_TOKEN）")
    src.add_argument("--watch", action="store_true", help="盯单模式：下单后自动出课文")
    src.add_argument("--items", help="直接给餐品，用逗号分隔，例如 \"巨无霸,薯条,可乐\"")
    ap.add_argument("--lesson", help="指定课文 id（见 --list）")
    ap.add_argument("--list", action="store_true", help="列出所有课文")
    ap.add_argument("--interval", type=int, default=20, help="盯单模式的查询间隔秒数（默认 20）")
    ap.add_argument("--debug", action="store_true",
                    help="排查模式：解析失败时打印原始接口返回（含订单号等信息，勿外传）")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--md", action="store_true", help="输出 Markdown")
    args = ap.parse_args(argv)

    lessons, fallbacks = load_lessons()

    if args.list:
        print("\n可选课文：\n")
        for l in lessons:
            print(f"  {l['id']:14s} 《{l['title']}》  {l['author']}  · {l.get('tag','')}")
        print()
        return 0

    if args.watch:
        try:
            watch_mcp(args.interval)
        except KeyboardInterrupt:
            print("")
            print("停了。", file=sys.stderr)
        return 0

    if args.mcp:
        order = order_from_mcp()
    elif args.items:
        order = [x.strip() for x in args.items.replace("，", ",").split(",") if x.strip()]
    else:
        # 默认走 demo：没给参数也不该报错，先让人看到东西
        order = list(DEMO_ORDER)

    seed = "|".join(order) if order else None
    lesson = pick_lesson(lessons, args.lesson, seed=seed)
    doc = compose(order, lesson, fallbacks)

    if args.json:
        print(json.dumps(doc, ensure_ascii=False, indent=2))
    elif args.md:
        print(as_markdown(doc))
    else:
        print(as_text(doc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
