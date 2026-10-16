# 麦当劳 MCP 接入与验证边界

## 真实调用路径

项目包含独立的 `mcd_mcp.py` 客户端，通过 `https://mcp.mcd.cn`（Streamable HTTP / JSON-RPC 2.0）发送下列调用：

1. `initialize`，声明协议版本 `2025-03-26`。
2. `notifications/initialized`。
3. `tools/call`，仅允许工具 `order-list`，参数 `{}`。

使用 `MCD_MCP_TOKEN` 环境变量拼接 `Authorization: Bearer <token>` 请求头。网页本身不会读取 Token，也不会直接访问 MCP 服务，避免向静态托管站点暴露凭据或触发浏览器跨域问题。

**真实业务价值：** 实际麦当劳订单中的商品名与数量进入作品生成流程，产生个性化文学小品。离线演示使用模拟订单，但真实订单接入是另外一条已编写的代码路径。

## 从真实订单到浏览器

```bash
export MCD_MCP_TOKEN="在官方平台取得的 Token"
python mcd_chinese.py --mcp --lesson beiying
python mcd_chinese.py --mcp --export-web order-local.json
```

上述 JSON 是**脱敏订单文件**，格式如下。将它通过网页「导入真实订单」按钮打开：

```json
{
  "format": "mcd-chinese-class/items-v1",
  "items": [
    {"name": "巨无霸", "quantity": 1},
    {"name": "中薯条", "quantity": 1}
  ]
}
```

MCP 调用及 JSON 文件格式彼此分离。导出程序不会将订单号、门店、时间、金额、收货地址、手机号或令牌写入 JSON；网页只读取这个文件，不向服务器发送它。

## 解析策略

- 同时处理正常 JSON 和 `text/event-stream` SSE 包裹的 JSON-RPC。
- 接受 MCP 文本中 `## Original Response` 后的嵌入 JSON、`structuredContent` 数据。
- 识别 `data.list`、`orders`、`records` 等订单包装层（深度限制）。
- 跳过带「取消／退款／关闭」及其英文关键词的订单，再根据订单时间选最近的一笔。
- 对 `comboItemList` 套餐组件优先使用真实子项，不根据套餐名臆造配餐。子项数量视为每套餐份数，再乘父套餐数量；不同后端的数量语义可能不一致，需要以实际非空订单联调确认。
- 只在本地处理原始订单数据；异常不回显 HTTP 原文、原始令牌或订单内容；请求设置大小和超时限制。

## 验证结果分级

| 项目 | 本次重构验证边界 |
|---|---|
| MCP 握手、工具调用路径 | 使用 Mock 传输单元测试，验证请求结构与只读工具名 |
| SSE / 嵌入 JSON / `structuredContent` | 离线夹具测试 |
| 已取消订单、日期排序、套餐和数量 | 离线夹具测试 |
| 用户真实 Token 联调 | **此次没有 Token，未重新进行线上联调** |
| 真实非空个人订单 | **尚未实测**（上线前建议测试一单并注意隐私） |
| 页面导入 JSON | 浏览器端到端测试，不上传文件 |

旧仓库文档记录了此前在 2026-10-15 的令牌联调，但那不等于重构版已通过同一次线上测试。官方规则要求**真实使用**麦当劳 MCP，因此上线前必须通过 `--mcp` 对真实服务实际验证；仅有 Mock 测试不能替代。

## 配置样例说明

`mcp-config.example.json` 使用 `${MCD_MCP_TOKEN}` 环境变量占位符，以符合赛事要求。不保证所有 MCP 客户端都支持该插值语法；使用者需按客户端文档设置映射或凭据输入。不要把填有真实令牌的配置文件提交到 GitHub。

## 安全和服务边界

- 仅访问 `order-list`，明确禁止任何 MCP 写操作、消费及优惠领取。
- 命令行不会自动上传订单；导出文件在本机创建。
- 不把浏览器导入的订单写入 `localStorage`，不接入埋点或分析服务。
- `--watch` 最短间隔为 15 秒；默认 30 秒；首次记录基线，避免重复通知历史订单。
- 代码遵守麦当劳 MCP 服务条款仍须由使用者按实时条款复核。
