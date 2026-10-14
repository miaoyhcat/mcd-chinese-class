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

调用 `tools/list` 实测到服务端共提供 **35 个工具**。本项目只用到其中 1 个。

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

### 返回值不是裸 JSON（实测踩到的坑）

工具的 `content[0].text` **不是** JSON，而是一段混合文本：

```
# API Response Information
...（## Response Structure，字段说明）...

## Original Response

{"success":true,"code":200,"message":"请求成功","datetime":"...","traceId":"...","data":{...}}
```

所以不能直接 `json.loads(text)`。`mcd_mcp._extract_json()` 会先定位到
`## Original Response`，再截取其中第一个 `{` 到最后一个 `}`。

另外三种工具返回形态各不相同，客户端都要能应付：

| 形态 | 例子 | 处理 |
|---|---|---|
| 结构说明 + 嵌入 JSON | `order-list`、`now-time-info` | 按上面的方式提取 |
| 纯 Markdown 文本 | `available-coupons` | 解析不出 JSON 就原样返回字符串 |
| JSON 里 data 又是字符串 | `list-nutrition-foods` | 原样返回，交给上层 |

### order-list 的字段（实测确认）

| 层级 | 字段 |
|---|---|
| 外层 | `success` / `code` / `message` / `datetime` / `traceId` / `data` |
| `data.list[]` | `orderId`、`orderType`、`createTime`、`beType`、`beCode`、`storeCode`、`storeName`、`orderStatus`、`realTotalAmount` |
| `orderProductList[]` | `productCode`、`productName`、`quantity`、`comboItemList` |

解析仍然保留了别名兼容与递归查找（见 `_pick_latest_order`），这样万一服务端
调整了包装层也不会立刻失效。**套餐会把 `comboItemList` 里的子项展开** ——
否则点一份「巨无霸套餐」，课文里只看得到套餐名，看不到里面的薯条和可乐。
子项名字已包含在套餐名里的（「巨无霸」⊂「巨无霸套餐」）会跳过，避免重复。

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

### 已用真实 Token 实测（2026-10-15）

- `--demo` / `--items` / `--list` / `--md` / `--json` 全部路径跑通，
  包括空输入、纯饮品、中英文逗号混用等边界情况
- 餐品分类逻辑（主食/小食/饮品）经过用例回归，三者互不重叠；
  并修掉了一个真实 bug：「板烧鸡腿堡」曾因词表里的「鸡腿」被误判为小食
- 6 个占位符在 16 篇课文中全部替换干净：16 篇 × 4 种订单 = 64 次生成，无残留 `{xxx}`
- 网页演示在真实浏览器中通过端到端测试：默认渲染、切换课文、点选餐品、
  手动输入、复制按钮、无 JS 报错
- 只读白名单：传非白名单工具名会被拒绝，请求不会发出

### 已验证（真实 Token 联调）

- **握手**：`initialize → notifications/initialized → tools/call` 全部成功，
  鉴权头 `Authorization: Bearer <token>` 有效
- **`tools/list`**：服务端返回 **35 个工具**，与客户端文档一致
- **只读白名单真的拦得住**：调用 `query-my-account`（不在白名单）时被客户端拒绝，
  请求根本没有发出去
- **返回值形态**：确认是「结构说明 + `## Original Response` + JSON」的混合文本，
  `_extract_json()` 能正确提取
- **字段名**：`order-list` 的字段与上表一致（来自接口自带的 Response Structure 说明）
- **空数据形态**：该账号近 90 天无订单，`data` 返回 `{}`；
  程序识别这种情况并给出人话提示，而不是报解析错误
- **其他工具**：`now-time-info` 解析为含 `timestamp/datetime/formatted/date/year` 的
  dict；`available-coupons` 返回 Markdown 文本；`list-nutrition-foods` 的 `data`
  是表格字符串

### 仍未验证

- **带真实订单的完整解析链路**：联调时该账号没有历史订单，
  所以「取最近一笔 → 展开套餐子项 → 分类」这条路径是用**严格按接口 schema
  构造的测试数据**验证的（含已取消订单过滤、字段别名、套餐子项展开），
  但没有跑过真实订单行。
- **`--watch` 的新订单触发**：变更检测逻辑已实现，同样未经真实下单触发。

这两项都不影响项目的主要功能：核心的课文生成完全不经过 MCP。

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
