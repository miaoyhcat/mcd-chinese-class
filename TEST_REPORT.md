# 测试与验证记录

本文件记录**实际执行过**的验证及结果，并明确区分「已验证」与「未验证」。
没有跑过的项目一律标为未验证，不写成通过。

## 可复现命令

```bash
python build_web.py                  # 重建网页（产物应无变化）
python -m unittest discover -s tests -p "test_*.py"   # 单元测试
python tests/browser_smoke.py        # 浏览器端到端，需 Playwright
```

浏览器测试需要额外安装**仅供测试**的依赖，不影响项目本身零依赖运行：

```bash
python -m pip install playwright
python -m playwright install chromium
```

## 已验证

| 项目 | 数量 | 结果 |
|---|---|---|
| Python 单元测试 | 23 | 全部通过 |
| 浏览器端到端检查 | 40 | 全部通过（真实 Chromium，非跳过） |
| 命令行冒烟（--demo/--md/--items/--list） | 4 | 全部通过 |
| 网页产物可重建且与提交逐字节一致 | 1 | 通过 |

单元测试覆盖：课文库结构与占位符、餐品分类与边界、订单选取（跳过取消）、
套餐子项展开与数量、字段别名兼容、JSON/SSE/`## Original Response` 三种响应
格式、只读工具调用路径、错误信息不泄露凭据、构建产物一致性。

浏览器测试覆盖：16 篇课文列表、正文无漏填、恶意输入不执行脚本、
导入订单文件、拒绝含订单号的文件、PNG 导出、超长课文分页、
320/375/390px 无横向溢出、全程无 JS 报错。

另有自动化检查确认：网页产物不含 `innerHTML` / `document.write` / `eval`，
不引用任何外部脚本或样式表。

## 尚未验证（不要当成已通过）

1. **真实非空订单的端到端联调**：本项目在真实 Token 下确认过 MCP 的握手、
   工具列表与返回结构，但**没有**用真实订单跑通 `--mcp` 与 `--export-web`。
   字段命名与数量语义应以你自己的真实订单为准。
   （2026-10-16 说明：此前用于联调的 Token 已失效，服务端返回 401，
   需要重新申请后验证。）
2. **真实下单触发的 `--watch`**：目前只有 Mock 测试，没接过真实新订单事件。
3. **其它 MCP 客户端的配置导入**：`mcp-config.example.json` 的写法未在具体
   客户端里实测过。
4. **版权与品牌合规**：见 [COPYRIGHT.md](COPYRIGHT.md)，其中列出了风险与
   尚未完成的核查，不构成法律意见。
5. **官方最终审核**：参赛资格与获奖由主办方认定，本地测试不能替代。

## 环境

- 本地：Windows，Python 3.14
- CI：GitHub Actions，ubuntu-latest / Python 3.12
  （流程见 `.github/workflows/ci.yml`；CI 只在 Linux 上跑，
  所以 Windows 特有问题需要本地跑测试才能发现）
