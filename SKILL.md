---
name: mcd-chinese-class
description: 把餐品清单或用户授权读取的麦当劳订单，生成原创语文课文戏仿。支持离线试玩、麦当劳 MCP order-list 只读工具、分享图片。用户提到“麦门语文课”“把订单写成课文”“用麦当劳订单生成故事”时使用。
---

# 麦门语文课

## 核心能力

把用户指定的餐品或通过麦当劳 MCP `order-list` 读到的最近有效订单改写成原创文学小品。严禁把 Token、订单编号、收件信息等隐私信息写到输出。

## 命令

```bash
python mcd_chinese.py --demo
python mcd_chinese.py --items "巨无霸,中薯条,可乐" --lesson beiying
python mcd_chinese.py --items "巨无霸,中薯条,可乐" --json
python mcd_chinese.py --list

# 使用用户自行配置的 MCD_MCP_TOKEN
python mcd_chinese.py --mcp
python mcd_chinese.py --mcp --export-web order-local.json
```

## 接入规则

- 使用真实订单前，必须有用户许可及其本机提供的 `MCD_MCP_TOKEN`。
- MCP 客户端只允许 `order-list`，不得执行写操作。
- 不能访问真实订单时，明确说明限制，并可提供 `--demo` 演示；**不能称模拟订单为真实调用结果**。
- 网页是单文件离线体验；真实订单通过本地 CLI 导出的脱敏 JSON 文件导入。
- 原创故事为文学戏仿，不是原作摘抄，也不是麦当劳官方内容。

## 输出

默认纯文本；`--md` 输出 Markdown，`--json` 输出结构化内容。无课后习题。
