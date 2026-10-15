#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""麦当劳 MCP 最小客户端（只用 Python 标准库，不依赖任何 MCP SDK）。

为什么自己写：本项目的核心逻辑是确定性的文本生成，不需要把 LLM 拖进来。
直接用标准库完成 Streamable HTTP 握手，整个 Skill 就能脱离 AI 客户端独立跑。

握手顺序：
    initialize → notifications/initialized → tools/call

三个容易踩的坑（联调记录见 MCP_INTEGRATION.md）：
  1. 服务端是**无状态**的，initialize 响应里没有 Mcp-Session-Id，每个请求独立 POST。
  2. 响应体可能是 application/json，也可能是 text/event-stream（SSE），两种都要能解析。
  3. Accept 头必须同时声明 application/json 和 text/event-stream，只写一个可能被拒。
"""

import json
import os
import urllib.error
import urllib.request

SERVER = "https://mcp.mcd.cn"
PROTOCOL_VERSION = "2025-03-26"
CLIENT_INFO = {"name": "mcd-chinese-class", "version": "1.0.0"}


class MCDError(RuntimeError):
    """MCP 调用失败。所有失败都抛这个，调用方只需处理一种异常。"""


def _parse_body(body: str, ctype: str):
    """把响应体解析成 dict。兼容 JSON 和 SSE 两种返回。"""
    if "text/event-stream" in (ctype or ""):
        # SSE：逐行取 data:，最后一条才是结果
        last = None
        for line in body.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                chunk = line[5:].strip()
                if chunk and chunk != "[DONE]":
                    last = chunk
        if last is None:
            raise MCDError("SSE 响应里没有 data 行")
        body = last
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        raise MCDError(f"响应不是合法 JSON：{body[:200]}") from None


class MCDClient:
    """麦当劳 MCP 客户端。只调用只读工具，不涉及下单、支付、领券。"""

    #: 本项目允许调用的工具白名单 —— 全部只读，代码层面挡掉写操作
    READ_ONLY_TOOLS = {
        "now-time-info",
        "query-nearby-stores",
        "query-meals",
        "query-meal-detail",
        "list-nutrition-foods",
        "order-list",
        "query-my-coupons",
        "available-coupons",
        "query-store-coupons",
        "campaign-calendar",
        "calculate-price",
    }

    def __init__(self, token=None, server=SERVER, timeout=30):
        self.token = (
            token
            or os.environ.get("MCD_MCP_TOKEN")
            or os.environ.get("MCD_TOKEN")
            or ""
        ).strip()
        if not self.token:
            raise MCDError(
                "未提供 MCP Token。\n"
                "  申请：https://open.mcd.cn/mcp\n"
                "  设置：export MCD_MCP_TOKEN=\"你的token\""
            )
        self.server = server.rstrip("/")
        self.timeout = timeout
        self._seq = 0
        self._ready = False

    # ── 传输层 ──────────────────────────────────────────────
    def _next_id(self):
        self._seq += 1
        return self._seq

    def _post(self, payload, expect_reply=True):
        raw = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self.server, data=raw, method="POST")
        req.add_header("Content-Type", "application/json")
        # 两种都要声明，否则服务端可能直接拒绝
        req.add_header("Accept", "application/json, text/event-stream")
        req.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8", "replace")
                ctype = resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            if e.code == 429:
                raise MCDError("触发限流（600 次/分钟），稍后再试") from None
            if e.code == 401:
                raise MCDError("Token 无效或已过期，请重新申请") from None
            raise MCDError(f"HTTP {e.code}：{detail}") from None
        except urllib.error.URLError as e:
            raise MCDError(f"连不上 {self.server}：{e.reason}") from None
        if not expect_reply:
            return None
        msg = _parse_body(body, ctype)
        if isinstance(msg, dict) and msg.get("error"):
            raise MCDError(f"服务端错误：{msg['error']}")
        return msg

    # ── 协议层 ──────────────────────────────────────────────
    def initialize(self):
        """握手。服务端无状态，握手一次即可，之后每个请求独立。"""
        self._post(
            {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": CLIENT_INFO,
                },
            }
        )
        # 通知没有 id，也不期待回复
        self._post(
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            expect_reply=False,
        )
        self._ready = True
        return self

    def list_tools(self):
        self._ensure_ready()
        msg = self._post(
            {"jsonrpc": "2.0", "id": self._next_id(), "method": "tools/list", "params": {}}
        )
        return (msg.get("result") or {}).get("tools") or []

    def call(self, name, arguments=None):
        """调用一个工具。写操作会被白名单挡下。"""
        if name not in self.READ_ONLY_TOOLS:
            raise MCDError(
                f"工具 {name!r} 不在只读白名单内。\n"
                "本项目只读取数据，绝不下单、支付或领取任何权益。"
            )
        self._ensure_ready()
        msg = self._post(
            {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments or {}},
            }
        )
        result = msg.get("result") or {}
        if result.get("isError"):
            raise MCDError(f"{name} 返回错误：{result}")
        return _unwrap(result)

    def _ensure_ready(self):
        if not self._ready:
            self.initialize()


def _extract_json(text: str):
    """从工具的 text 块里把真正的 JSON 抠出来。

    ⚠ 真实联调发现（2026-10-15）：MCP 工具返回的**不是**裸 JSON，而是一段
    «接口结构说明 + 原始响应» 的混合文本，长这样：

        # API Response Information
        ...## Response Structure（字段说明）...
        ## Original Response

        {"success":true,"code":200,"data":{...}}

    所以不能直接 json.loads 整个 text。要定位到 `## Original Response`
    之后再截取第一个 { 到最后一个 }。
    """
    marker = "## Original Response"
    if marker in text:
        text = text.split(marker, 1)[1]
    i, j = text.find("{"), text.rfind("}")
    if i >= 0 and j > i:
        text = text[i:j + 1]
    return json.loads(text)


def _unwrap(result: dict):
    """把 MCP 的 content 数组拆成 Python 数据。

    优先解析 text 块里嵌的 JSON；解析不出来就原样返回文本，
    交给上层决定怎么办（本项目里会打印原文并停下，不猜）。
    """
    contents = result.get("content") or []
    texts = [c.get("text", "") for c in contents if c.get("type") == "text"]
    joined = chr(10).join(t for t in texts if t).strip()
    if not joined:
        # 有些工具把结构化数据放在 structuredContent 里
        return result.get("structuredContent") or result
    try:
        return _extract_json(joined)
    except (json.JSONDecodeError, ValueError):
        return joined
