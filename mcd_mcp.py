"""麦当劳只读 MCP 客户端（Python 标准库）。不会记录、回显 Token 与订单原文。"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

from engine import Item, InputError, normalize_items

SERVER = 'https://mcp.mcd.cn'
PROTOCOL_VERSION = '2025-03-26'
MAX_RESPONSE_BYTES = 2_500_000
CANCEL_MARKERS = ('已取消', '取消', '退款', '关闭', 'cancel', 'refund', 'closed')


class MCPError(RuntimeError):
    pass


def extract_json(text):
    """兼容 JSON 和 '## Original Response' 嵌套正文，避免从说明区误读 schema。"""
    if not isinstance(text, str):
        raise MCPError('MCP 响应类型错误')
    marker = '## Original Response'
    if marker in text:
        text = text.split(marker, 1)[1]
    decoder = json.JSONDecoder()
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for i, ch in enumerate(text):
        if ch in '{[':
            try:
                obj, _ = decoder.raw_decode(text[i:])
                return obj
            except json.JSONDecodeError:
                continue
    raise MCPError('无法识别 MCP JSON 响应格式')


def parse_envelope(raw, content_type):
    """支持 JSON 和 SSE，忽略 keepalive，解析完整 data 多行事件。"""
    if not raw.strip():
        return {}
    if 'text/event-stream' not in content_type:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            raise MCPError('MCP 响应不是合法 JSON') from None
    events, parts = [], []
    for line in raw.splitlines() + ['']:
        if not line:
            if parts:
                events.append('\n'.join(parts)); parts = []
        elif line.startswith('data:'):
            parts.append(line[5:].lstrip(' '))
    for item in reversed(events):
        if item != '[DONE]':
            try:
                return json.loads(item)
            except json.JSONDecodeError:
                continue
    raise MCPError('MCP 事件流没有有效数据')


def unwrap_tool_result(result):
    if not isinstance(result, dict):
        raise MCPError('工具返回格式错误')
    if result.get('isError'):
        raise MCPError('麦当劳订单工具返回业务错误')
    structured = result.get('structuredContent')
    if isinstance(structured, dict):
        return structured
    for content in result.get('content', []):
        if not isinstance(content, dict) or content.get('type') != 'text':
            continue
        try:
            return extract_json(content.get('text', ''))
        except MCPError:
            continue
    raise MCPError('麦当劳订单工具没有返回可解析的数据')


class MCPClient:
    """单用途客户端：只允许 `order-list`，不会向 MCP 发起任何写操作。"""
    def __init__(self, token=None, opener=None, timeout=25):
        self.token = (token if token is not None else os.getenv('MCD_MCP_TOKEN', '')).strip()
        if not self.token:
            raise MCPError('缺少 MCD_MCP_TOKEN，请先配置环境变量')
        self._opener = opener or urllib.request.urlopen
        self._counter = 0
        self.timeout = timeout
        self._initialized = False

    def _request(self, method, params=None, notification=False):
        data = {'jsonrpc': '2.0', 'method': method}
        if not notification:
            self._counter += 1
            data['id'] = self._counter
        if params is not None:
            data['params'] = params
        req = urllib.request.Request(SERVER, data=json.dumps(data).encode('utf-8'), method='POST')
        req.add_header('Authorization', f'Bearer {self.token}')
        req.add_header('Content-Type', 'application/json')
        req.add_header('Accept', 'application/json, text/event-stream')
        try:
            with self._opener(req, timeout=self.timeout) as response:
                body = response.read(MAX_RESPONSE_BYTES + 1)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise MCPError('MCP 响应过大，已安全中止')
                content_type = response.headers.get('Content-Type', '')
        except urllib.error.HTTPError as exc:
            reason = 'Token 无效或过期' if exc.code in (401, 403) else ('请求太频繁' if exc.code == 429 else '上游服务错误')
            raise MCPError(f'MCP HTTP {exc.code}：{reason}') from None
        except urllib.error.URLError:
            raise MCPError('无法连接麦当劳 MCP 服务，请检查网络') from None
        except TimeoutError:
            raise MCPError('连接麦当劳 MCP 超时') from None
        if notification:
            return {}
        result = parse_envelope(body.decode('utf-8', 'replace'), content_type)
        if not isinstance(result, dict):
            raise MCPError('MCP 响应封装格式错误')
        if result.get('error'):
            # 不回显服务端原始 error 字符串，避免泄露隐私数据。
            raise MCPError('MCP 服务器返回 JSON-RPC 错误')
        return result.get('result') or {}

    def initialize(self):
        self._request('initialize', {'protocolVersion': PROTOCOL_VERSION,
                    'capabilities': {}, 'clientInfo': {'name': 'mcd-chinese-class', 'version': '2.0.0'}})
        self._request('notifications/initialized', notification=True)
        self._initialized = True

    def list_orders(self):
        if not self._initialized:
            self.initialize()
        return unwrap_tool_result(self._request('tools/call', {'name': 'order-list', 'arguments': {}}))


def find_orders(data, depth=0):
    if depth > 8:
        return None
    if isinstance(data, list):
        if data and all(isinstance(x, dict) for x in data):
            keys = set().union(*(set(x.keys()) for x in data[:8]))
            if keys & {'orderId', 'orderProductList', 'products', 'realTotalAmount'}:
                return data
        for v in data:
            nested = find_orders(v, depth+1)
            if nested is not None:
                return nested
    elif isinstance(data, dict):
        for key in ('data', 'list', 'orders', 'orderList', 'records', 'result'):
            if key in data:
                nested = find_orders(data[key], depth+1)
                if nested is not None:
                    return nested
    return None


def time_value(order):
    for key in ('createTime', 'orderTime', 'createDate', 'orderDate', 'time'):
        raw = order.get(key)
        if raw is None or raw == '':
            continue
        if isinstance(raw, (int, float)):
            return float(raw) / (1000 if raw > 1e11 else 1)
        try:
            parsed = datetime.fromisoformat(str(raw).replace('/', '-').replace('Z', '+00:00'))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone(timedelta(hours=8)))
            return parsed.timestamp()
        except (ValueError, OverflowError):
            continue
    return float('-inf')


def latest_valid_order(data):
    orders = find_orders(data)
    if not orders:
        return None
    active = []
    for o in orders:
        status = str(o.get('orderStatus') or o.get('status') or '').lower()
        if not any(x in status for x in CANCEL_MARKERS):
            active.append(o)
    return max(active, key=time_value) if active else None


# 订单里的字段名在不同接口/不同版本间并不统一。已经用真实返回确认过的是
# productName + quantity；但官方其它接口的返回示例里出现过 itemName /
# itemQuantity 的写法。如果只认第一种，套餐子项会整段解析不出来，
# 于是静默退化成父套餐名（「巨无霸套餐 ×2」而不是「中薯条 + 可乐」）——
# 不报错，但结果是错的，所以按优先级把别名都认上。
NAME_KEYS = ('productName', 'name', 'itemName', 'product_name', 'item_name')
QTY_KEYS = ('quantity', 'itemQuantity', 'item_quantity', 'qty', 'count')


def pick_field(mapping, keys):
    """按优先级取第一个有值的字段；全都没有则返回 None。"""
    for key in keys:
        value = mapping.get(key)
        if value is not None and value != '':
            return value
    return None


def order_items(order):
    """套餐优先展开真实子项；不凭套餐名猜组件，合并相同商品及数量。"""
    if not isinstance(order, dict):
        raise MCPError('订单结构不是对象')
    lines = order.get('orderProductList') or order.get('products') or []
    if not isinstance(lines, list):
        raise MCPError('订单商品清单不是数组')
    items = []
    def quantity(raw):
        try:
            n = int(raw if raw is not None else 1)
            return n if 1 <= n <= 99 else 1
        except (TypeError, ValueError):
            return 1
    for p in lines:
        if not isinstance(p, dict):
            continue
        name = pick_field(p, NAME_KEYS) or ''
        parent_qty = quantity(pick_field(p, QTY_KEYS))
        children = p.get('comboItemList') or []
        found = []
        if isinstance(children, list):
            for child in children:
                if isinstance(child, dict):
                    child_name = pick_field(child, NAME_KEYS) or ''
                    if isinstance(child_name, str) and child_name.strip():
                        # 接口未保证子项数量的语义，按每套餐子项数量解释；在文档中声明。
                        child_qty = quantity(pick_field(child, QTY_KEYS))
                        found.append(Item(child_name.strip(), min(99, child_qty * parent_qty)))
        if found:
            items.extend(found)
        elif isinstance(name, str) and name.strip():
            items.append(Item(name.strip(), parent_qty))
    try:
        return normalize_items(items)
    except InputError as e:
        raise MCPError(f'订单餐品不符合输入要求：{e}') from None


def fetch_latest_items(client):
    data = client.list_orders()
    order = latest_valid_order(data)
    if not order:
        raise MCPError('没有找到可用的有效订单（可能无订单或均已取消）')
    items = order_items(order)
    if not items:
        raise MCPError('订单中没有可识别的商品')
    return items
