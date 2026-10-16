#!/usr/bin/env python3
"""静态规则检查（不联网、不依赖三方包，任何平台都能跑）。

和 unittest 套件的分工：
    tests/test_*.py    → 跑行为（生成、解析、构建、浏览器）
    check_static.py    → 查规则（安全约束、合规文件、文档一致、构建产物）

这些规则都是「不需要跑起来也该成立」的，而且大多是比赛的硬要求，
所以单独成文件、单独进 CI —— 混在功能测试里容易在重构时被顺手删掉。

跑法：python tests/check_static.py
退出码：0 = 全部通过；1 = 有失败
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from console_utf8 import enable_utf8_stdout
enable_utf8_stdout()  # 英文 Windows 控制台是 cp1252，print 中文会崩

PASS, FAIL, SKIP = [], [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'✓' if cond else '✗'} {name}" + (f"   {detail}" if detail and not cond else ""))


def skip(name, why):
    """环境不具备时跳过。**不计入通过** —— 报告里单独列出，不伪装成绿。"""
    SKIP.append(f"{name}（{why}）")
    print(f"  · {name}   {why}")


def read(p):
    return (ROOT / p).read_text(encoding="utf-8")


def main():
    print("═" * 52)
    print("  麦门语文课 · 静态规则检查")
    print("═" * 52)

    # ── 1. 只读 MCP 约束 ──
    print("\n[MCP 只读约束]")
    mcp = read("mcd_mcp.py")
    # 只抓 tools/call 这个调用点的 name 参数。
    # 一开始我抓的是全文所有 'name': 'xxx'，结果把 MCP 握手里的
    # clientInfo.name（"mcd-chinese-class"）也算了进来，误报成"调了别的工具"。
    calls = re.findall(r"tools/call['\"]\s*,\s*\{\s*['\"]name['\"]\s*:\s*['\"]([\w-]+)['\"]", mcp)
    check("MCP 客户端只调用 order-list", calls and set(calls) == {"order-list"},
          str(sorted(set(calls))) or "一个调用点都没抓到")

    # 写操作的**工具名**一旦出现就得拦下来。
    # 这里只列麦当劳 MCP 里语义明确的写操作工具名 —— 不用 "coupon"「refund」
    # 这类通用词：文件里有一份 CANCEL_MARKERS 状态词表（含 'refund'），
    # 那是用来跳过已退款订单的，用通用词匹配会误报，逼得检查被改成假的。
    WRITE_TOOLS = ["create-order", "cancel-order", "auto-bind-coupons",
                   "draw-lottery", "mall-create-order"]
    found = [t for t in WRITE_TOOLS
             if re.search(rf"['\"]{re.escape(t)}['\"]", mcp, re.I)]
    check("客户端里没有出现任何写操作工具名", not found, str(found))

    # ── 2. 凭据与隐私 ──
    print("\n[凭据与隐私]")
    SEC = re.compile(r"(sk-[A-Za-z0-9]{16,}|ghp_[A-Za-z0-9]{20,}"
                     r"|MCD_MCP_TOKEN\s*=\s*[\"'][^\"']{16,}"
                     r"|Bearer\s+[A-Za-z0-9]{20,})")
    hits = []
    for f in ROOT.rglob("*"):
        if not f.is_file() or ".git" in f.parts or "__pycache__" in f.parts:
            continue
        if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".ico"):
            continue
        if SEC.search(f.read_text(encoding="utf-8", errors="ignore")):
            hits.append(str(f.relative_to(ROOT)))
    check("仓库内无硬编码凭据", not hits, str(hits))

    cfg = json.loads(read("mcp-config.example.json"))
    node = cfg["mcpServers"]["mcd-mcp"]
    check("脱敏配置用 ${MCD_MCP_TOKEN} 占位符",
          node["headers"]["Authorization"] == "Bearer ${MCD_MCP_TOKEN}")
    check("脱敏配置指向官方 MCP 地址", node["url"] == "https://mcp.mcd.cn")

    # 导出的浏览器 JSON 只能有餐品名和数量（engine.browser_payload 的承诺）
    import engine
    payload = engine.browser_payload(["巨无霸", "中薯条", "可乐"])
    leaked = [k for k in json.dumps(payload, ensure_ascii=False).split('"')
              if k.lower() in ("orderid", "storename", "storecode", "realtotalamount",
                               "createtime", "token", "phone", "address")]
    check("导出给网页的 JSON 不含订单号/门店/金额/时间字段", not leaked, str(leaked))

    # ── 3. 合规文件 ──
    print("\n[合规文件]")
    for name in ["README.md", "LICENSE", "SECURITY.md", "COPYRIGHT.md", "SKILL.md",
                 "CONTEST_DECLARATION.md", "MCP_INTEGRATION.md",
                 "mcp-config.example.json", "lessons.json", "catalog.json"]:
        check(f"必需文件存在：{name}", (ROOT / name).exists())

    check("LICENSE 保留作者署名",
          "缪艺涵" in read("LICENSE") or "miaoyhcat" in read("LICENSE"))

    # ── 4. 文档一致性 ──
    print("\n[文档一致性]")
    rd = read("README.md")
    # 「没有课后习题」这种否认句里也含"习题"三个字，直接查子串会把
    # 正确表述误判成宣传。所以逐处看上下文：只要每处"习题"都在否定词后面
    # 才算过；真写了"本课配有课后习题"就会失败。
    advertised = [rd[max(0, m.start() - 12):m.end()]
                  for m in re.finditer("习题", rd)
                  if not re.search(r"没有|不含|不新增|无", rd[max(0, m.start() - 12):m.end()])]
    check('README 不宣传课后习题（「习题」只出现在否定句里）', not advertised, str(advertised))
    check("README 含在线体验链接", "miaoyhcat.github.io/mcd-chinese-class" in rd)
    check("README 链接到版权说明文件", "COPYRIGHT.md" in rd)
    check("README 如实声明真实订单未验证", "尚未" in rd or "未验证" in rd)
    for name in ["README.md", "MCP_INTEGRATION.md", "SECURITY.md"]:
        check(f"{name} 说明只读约束", "只读" in read(name) or "order-list" in read(name))

    lessons = json.loads(read("lessons.json"))
    check("课文数量为 16", len(lessons["lessons"]) == 16)
    check("课文 ID 不重复",
          len({l["id"] for l in lessons["lessons"]}) == len(lessons["lessons"]))
    check("课文里没有课后习题字段",
          not any("question" in k.lower() or "习题" in str(l)
                  for l in lessons["lessons"] for k in l))

    # ── 5. 构建产物 ──
    print("\n[构建产物]")
    page = (ROOT / "docs/index.html").read_bytes()
    check("docs/index.html 不含 CR（是 LF）", b"\r" not in page)
    text = page.decode("utf-8")
    check("产物里没有未替换的占位符", "/*__" not in text)
    check("产物不含课后习题", "课后习题" not in text)
    check("产物不引用任何外部脚本",
          not re.search(r"<script\s[^>]*src=", text))
    check("产物不引用任何外部样式表",
          not re.search(r"<link\s[^>]*rel=[\"']stylesheet[\"']", text))
    check("产物没有 innerHTML / document.write / eval",
          not re.search(r"innerHTML|document\.write|eval\(", text))

    built = subprocess.run([sys.executable, "build_web.py"], cwd=str(ROOT),
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
    check("build_web.py 可正常构建", built.returncode == 0,
          (built.stdout or built.stderr or "").strip()[:140])
    again = (ROOT / "docs/index.html").read_bytes()
    check("构建产物与仓库提交逐字节一致", page == again,
          "重跑构建后产物变了 —— 提交的产物不是最新，或构建不确定")

    # ── 6. 无付费 API ──
    print("\n[零外部依赖]")
    blob = "".join(read(p) for p in
                   ["engine.py", "mcd_chinese.py", "mcd_mcp.py", "build_web.py",
                    "console_utf8.py", "web/app.js", "web/template.html"])
    check("代码里没有任何付费/第三方模型 API",
          not re.search(r"api\.openai\.com|api\.anthropic\.com|api\.deepseek\.com"
                        r"|generativelanguage\.googleapis\.com", blob))

    # ── 7. 参赛声明 ──
    print("\n[参赛声明]")
    dec = (ROOT / "CONTEST_DECLARATION.md").read_bytes()
    check("声明文件是 LF（与官方原件一致的前提）", b"\r" not in dec)
    try:
        r = subprocess.run(["gh", "api",
                            "repos/M-China/mcd-developer-innovation-challenge/contents/CONTEST_DECLARATION.md",
                            "--jq", ".content"],
                           capture_output=True, text=True, encoding="utf-8")
    except FileNotFoundError:
        r = None
    if r is None or r.returncode != 0 or not r.stdout.strip():
        skip("声明文件与官方逐字节一致", "取不到官方文件（无 gh 或无网络）")
    else:
        import base64
        check("声明文件与官方逐字节一致",
              base64.b64decode(r.stdout.strip()) == dec)

    # ── 汇总 ──
    print("\n" + "═" * 52)
    print(f"  PASS {len(PASS)} / FAIL {len(FAIL)} / SKIP {len(SKIP)}")
    for s in SKIP:
        print(f"  · {s}")
    if FAIL:
        print("  未通过：")
        for f in FAIL:
            print(f"    ✗ {f}")
        print("═" * 52)
        return 1
    print("  全部通过 ✓")
    print("═" * 52)
    return 0


if __name__ == "__main__":
    sys.exit(main())
