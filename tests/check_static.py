#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""静态合规检查（不联网、不依赖三方包，任何平台都能跑）。

CI 里用来兜住那些「不需要跑起来也该成立」的规则。
和 test_mcd_chinese.py 的分工：
    test_mcd_chinese.py  → 跑功能（生成、解析、异常处理）
    check_static.py      → 查文件与规则（参赛要求、安全约束、构建一致性）

跑法：python tests/check_static.py
退出码：0 = 全部通过；1 = 有失败
"""

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'✓' if cond else '✗'} {name}" + (f"   {detail}" if detail and not cond else ""))


def read(p):
    return (ROOT / p).read_text(encoding="utf-8")


def main():
    print("═" * 52)
    print("  静态合规检查")
    print("═" * 52)

    # ── 1. 官方要求的参赛文件 ──
    print("\n[参赛必需文件]")
    for f in ["README.md", "CONTEST_DECLARATION.md", "MCP_INTEGRATION.md",
              "mcp-config.example.json"]:
        check(f"存在 {f}", (ROOT / f).exists())

    decl = read("CONTEST_DECLARATION.md")
    check("参赛声明含「原创性声明」", "原创性声明" in decl)
    check("参赛声明含「合规声明」", "合规声明" in decl)
    check("参赛声明含「信息安全声明」", "信息安全声明" in decl)

    # ── 2. MCP 配置只用占位符 ──
    print("\n[MCP 配置]")
    cfg = json.loads(read("mcp-config.example.json"))
    srv = cfg["mcpServers"]["mcd-mcp"]
    auth = srv["headers"]["Authorization"]
    check("用环境变量占位符 ${MCD_MCP_TOKEN}", "${MCD_MCP_TOKEN}" in auth)
    check("URL 正确", srv["url"] == "https://mcp.mcd.cn")
    check("传输类型为 streamablehttp", srv.get("type") == "streamablehttp")
    check("配置里没有真实密钥形状的串",
          not re.search(r"Bearer\s+(?!\$\{)[A-Za-z0-9_\-]{16,}", auth))

    # ── 3. 仓库内不得有硬编码凭据 ──
    print("\n[凭据与隐私]")
    SEC = re.compile(r"(sk-[A-Za-z0-9]{16,}"
                     r"|ghp_[A-Za-z0-9]{20,}"
                     r"|MCD_MCP_TOKEN\s*=\s*[\"'][^\"']{16,}"
                     r"|Bearer\s+[A-Za-z0-9]{20,})")
    hits = []
    for f in sorted(ROOT.rglob("*")):
        if not f.is_file() or ".git" in f.parts or "node_modules" in f.parts:
            continue
        if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".ico"):
            continue
        try:
            t = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if SEC.search(t):
            hits.append(str(f.relative_to(ROOT)))
    check("全仓无硬编码凭据", not hits, str(hits))

    # ── 4. 产品定位：16 篇、无习题 ──
    print("\n[产品定位]")
    lessons = json.loads(read("lessons.json"))["lessons"]
    check("课文数量为 16", len(lessons) == 16, f"实际 {len(lessons)}")
    check("每篇都有 id/title/author/tag/opening/body",
          all(all(k in l and l[k] for k in ("id", "title", "author", "tag",
                                            "opening", "body")) for l in lessons))
    check("课文数据里没有 questions 字段",
          not any("questions" in l for l in lessons))
    check("课文 id 不重复", len({l["id"] for l in lessons}) == len(lessons))

    # ── 5. 前端安全约束 ──
    print("\n[前端安全]")
    tpl = read("web/template.html")
    built = read("docs/index.html")
    check("模板里没有 innerHTML 赋值",
          not re.search(r"\.innerHTML\s*=", tpl))
    check("产物里没有 innerHTML 赋值",
          not re.search(r"\.innerHTML\s*=", built))
    check("模板用 textContent 建节点", "textContent" in tpl)
    check("没有 document.write / eval",
          not re.search(r"document\.write|eval\s*\(", tpl + built))
    check("模板里没有 MCP 请求（网页不读订单）",
          not re.search(r"mcp\.mcd\.cn|MCD_MCP_TOKEN", tpl))
    check("产物无习题字样", "习题" not in built)

    # 前端不得引入付费 API
    check("前端不调用 OpenAI / Anthropic / DeepSeek 接口",
          not re.search(r"api\.openai\.com|api\.anthropic\.com|api\.deepseek\.com",
                        tpl + built))

    # ── 6. 只读 MCP 白名单 ──
    print("\n[MCP 只读约束]")
    mcp = read("mcd_mcp.py")
    for w in ["create-order", "cancel-order", "auto-bind-coupons",
              "draw-lottery", "mall-create-order"]:
        check(f"白名单未包含写操作 {w}",
              not re.search(rf'"{re.escape(w)}"', mcp.split("READ_ONLY_TOOLS")[1]
                            .split("}")[0] if "READ_ONLY_TOOLS" in mcp else ""))
    check("客户端声明了只读白名单", "READ_ONLY_TOOLS" in mcp)
    check("不调用支付相关接口", "pay" not in mcp.lower() or "不" in mcp)

    # ── 7. 构建一致性 ──
    print("\n[构建一致性]")
    before = (ROOT / "docs" / "index.html").read_bytes()
    r = subprocess.run([sys.executable, str(ROOT / "build_web.py")],
                       capture_output=True, text=True, cwd=str(ROOT))
    after = (ROOT / "docs" / "index.html").read_bytes()
    check("build_web.py 可执行", r.returncode == 0, (r.stderr or "")[:120])
    check("docs/index.html 与构建产物一致", before == after,
          "演示页漂移了，请重跑 build_web.py")

    # ── 8. 文档一致性 ──
    print("\n[文档一致性]")
    rd, sk, mi = read("README.md"), read("SKILL.md"), read("MCP_INTEGRATION.md")
    check("README 无习题宣传", "习题" not in rd or "没有课后习题" in rd)
    check("README 列出了在线体验链接",
          "miaoyhcat.github.io/mcd-chinese-class" in rd)
    check("README 提到 COPYRIGHT.md", "COPYRIGHT.md" in rd)
    check("三份文档都提到 order-list",
          all("order-list" in d for d in (rd, sk, mi)))
    check("SKILL.md 说明不新增习题", "习题" in sk)

    print("\n" + "═" * 52)
    print(f"  PASS {len(PASS)} / FAIL {len(FAIL)}")
    if FAIL:
        print("  失败项：")
        for f in FAIL:
            print("    ·", f)
    else:
        print("  全部通过 ✓")
    print("═" * 52)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
