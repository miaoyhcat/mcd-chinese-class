# MCP 集成说明

本文说明麦门语文课实际使用的麦当劳 MCP Server、Tool、调用流程，以及实现过程中
发现的接口约束与尚未验证的部分。

---

## 一、接入方式

| 项 | 值 |
|---|---|
| Server | `https://mcp.mcd.cn` |
| 传输协议 | Streamable HTTP（JSON-RPC 2.0 over HTTP POST） |
| 鉴权 | 请求头 `Authorization: Bearer <MCD_MCP_TOKEN>` |
| 协议版本 | `2025-03-26` |
| 限流 | 600 次/分钟，超限返回 `429` |
| 第三方依赖 | **无**。客户端 `mcd_mcp.py` 只用 Python 标准库 |
| Token 来源 | 环境变量 `MCD_MCP_TOKEN`（或 `MCD_TOKEN`），不写入任何文件 |

本项目的 MCP 客户端不依赖任何 SDK、也不依赖 LLM 客户端，直接用标准库完成
`initialize → notifications/initialized → tools/call` 的完整握手。
因此整个 Skill 可以脱离 AI 客户端独立运行。

---

## 二、使用的 Tool

本项目只调用 **1 个只读 Tool**：

| Tool | 用途 | 关键入参 | 调用时机 |
|---|---|---|---|
| `order-list` | 读取个人历史订单（近 90 天），取出**最近一笔**的餐品名 | 无 | `--mcp` 时调用一次；`--watch` 时每 N 秒轮询 |

**本项目的核心功能不依赖 MCP。** 网页演示与命令行默认路径（`--demo` / `--items`）
完全不联网、不需要 Token。MCP 只用来把「手动输入餐品」换成「直接读我的真实订单」，
是一个便利性增强，不是必需品。

---

## 三、为什么只读

代码层面强制：`mcd_mcp.py` 的 `MCDClient` 里有一份**只读白名单**，
不在白名单内的工具会被直接拒绝，调用不会发出。

```python
READ_ONLY_TOOLS = {
    "now-time-info", "query-nearby-stores", "query-meals", "query-meal-detail",
    "list-nutrition-foods", "order-list", "query-my-coupons",
    "available-coupons", "query-store-coupons", "campaign-calendar",
    "calculate-price",
}
```

明确**不调用**的能力：下单、支付、取消订单、领取优惠券、兑换积分、读取收货地址。
本项目不需要这些能力，也不会去碰。

用户的订单数据在本地内存中处理完即丢弃，不落盘、不上传、不写入任何日志。

---

## 四、调用流程

```
读取环境变量 MCD_MCP_TOKEN
   │
   ├─ 初始化：POST initialize  { protocolVersion, capabilities, clientInfo }
   ├─ 通知：  POST notifications/initialized
   └─ 调用：  POST tools/call  { name: "order-list", arguments: {} }
   │
   └─ 找出最近一笔订单 → 取出其中的餐品名
```

`order-list` 的返回结构官方未提供正式 schema。本项目按社区联调记录里出现的字段写的解析：

| 层级 | 字段（含别名） |
|---|---|
| 外层包装 | `data` / `result` / `records` / `list` / `orderList` / `orders` |
| 订单 | `orderId`、`createTime` / `orderTime` / `createDate`、`storeName`、`orderStatus` / `status`、`realTotalAmount` / `totalAmount` / `amount` |
| 餐品行 | `orderProductList` / `products` → `productName` / `name`、`quantity` |

解析策略是**保守**的，三层都做了兼容：

1. **外层包装用递归查找**，不假设固定层数 —— 找到"看起来像订单数组"的那一层就停。
2. **字段名走别名候选**，任何一项取不到都不报错，只是少一个字段。
3. **取最近一笔，跳过已取消的**：`orderStatus` 里含「取消 / 关闭 / 退款 / cancel /
   closed / refund」的订单会被排除；时间字段解析不出来时按"最早"处理，
   不会因为一个奇怪的格式就把旧订单当成新的。
4. 完全解析不出来时**打印原始返回并停止**，不猜一个结果继续往下跑。

`--watch` 模式在此基础上做轮询：记住上一次的 `orderId`，出现新的就自动生成课文。
第一次运行只记录基线、不输出，避免一启动就把你的历史订单当"新订单"念出来。

---

## 五、实现时的防御性处理

以下三点是本项目客户端刻意做的兼容处理。它们属于**防御性设计**，
不是对服务端行为的断言 —— 也就是说：即使服务端哪天改了行为，客户端也不会崩。

1. **不依赖会话状态。** 客户端不保存也不要求 `Mcp-Session-Id`，
   每个请求都是独立 POST。服务端有状态或无状态都能跑。
2. **同时接受两种响应体。** `Content-Type` 是 `application/json` 时直接 `json.loads`；
   是 `text/event-stream` 时逐行解析 `data:` 并取最后一条消息。
3. **`Accept` 头同时声明两种类型**（`application/json, text/event-stream`），
   避免服务端因内容协商失败而拒绝。

另外：所有失败路径统一抛 `MCDError`，并对 `429`（限流）和 `401`（Token 失效）
给出人话提示，而不是把 traceback 甩给用户。

---

## 六、验证边界

**诚实说明**：以下区分「已验证」与「未验证」，不把没测过的说成测过的。

### 已验证

- `--demo` / `--items` / `--list` / `--md` / `--json` 全部路径跑通，
  包括空输入、纯饮品、中英文逗号混用等边界情况
- 餐品分类逻辑（主食/小食/饮品）经过用例回归，三者互不重叠；
  并修掉了一个真实 bug：「板烧鸡腿堡」曾因词表里的「鸡腿」被误判为小食
- 6 个占位符在 16 篇课文中全部替换干净：16 篇 × 4 种订单 = 64 次生成，无残留 `{xxx}`
- 网页演示在真实浏览器中通过端到端测试：默认渲染、切换课文、点选餐品、
  手动输入、复制按钮、无 JS 报错
- 只读白名单：传非白名单工具名会被拒绝，请求不会发出

### 未验证（需要真实 Token）

- **`order-list` 的真实返回结构**：本项目没有可供联调的 Token。
  字段名来自社区项目的联调记录，解析逻辑已用两份**符合该结构的模拟数据**跑通
  （含外层包装差异、字段别名、已取消订单过滤、时间排序），但**未接过真实接口**。
  如果实际结构不匹配，程序会打印原始返回并停下，不会静默产出错误结果。
- **`--watch` 的轮询**：变更检测逻辑（记住 orderId、跳过首次基线）已在代码层实现，
  同样未经真实订单触发验证。
- 服务端对 `initialize` / `tools/call` 的具体响应细节
  （如上文第五节所述，客户端对两种响应形态都做了兼容）。

未验证的部分不会影响项目的主要功能：核心的课文生成完全不经过 MCP。

---

## 七、复现方式

```bash
# 1. 不需要 Token 的路径（主要功能）
python mcd_chinese.py --demo
python mcd_chinese.py --items "巨无霸,中薯条,可乐" --lesson beiying

# 2. 需要 Token 的路径
export MCD_MCP_TOKEN="你的token"
python mcd_chinese.py --mcp
```

Token 申请：<https://open.mcd.cn/mcp>

---

## 八、合规

- 不含任何真实 Token、密钥、密码或账号凭证；配置一律走环境变量占位符
- 不含他人个人信息；订单数据仅在本机内存中用于生成本次课文
- 不含恶意代码、后门、钓鱼链接或指向违规站点的外部链接
- 遵守麦当劳 MCP 服务规则：只调用只读接口，请求频率远低于 600 次/分钟的限制
