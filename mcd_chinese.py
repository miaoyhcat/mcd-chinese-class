#!/usr/bin/env python3
"""麦门语文课命令行入口；用 `python mcd_chinese.py --help` 查看全部命令。"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from engine import InputError, as_markdown, as_plain, browser_payload, compose, load_lessons, parse_items
from mcd_mcp import MCPClient, MCPError, fetch_latest_items, latest_valid_order, order_items

DEMO_ITEMS = ['巨无霸', '中薯条', '可乐']


def main(argv=None):
    p = argparse.ArgumentParser(description='麦门语文课 · 将餐品写成原创文学戏仿')
    group = p.add_mutually_exclusive_group()
    group.add_argument('--demo', action='store_true', help='演示订单（无网络）')
    group.add_argument('--items', help='手动输入，用逗号分隔')
    group.add_argument('--mcp', action='store_true', help='通过官方麦当劳 MCP 读取最近有效订单')
    group.add_argument('--watch', action='store_true', help='只监控新增订单，不输出历史订单')
    group.add_argument('--list', action='store_true', help='列出可用课文')
    p.add_argument('--lesson', help='固定课文 ID')
    output = p.add_mutually_exclusive_group()
    output.add_argument('--json', action='store_true', help='打印安全生成结果 JSON')
    output.add_argument('--md', action='store_true', help='打印 Markdown')
    p.add_argument('--export-web', type=Path, metavar='FILE', help='仅导出脱敏的餐品 JSON，供网页导入')
    p.add_argument('--interval', type=int, default=30, help='轮询间隔（最少 15 秒）')
    args = p.parse_args(argv)
    if args.export_web and args.watch:
        p.error('--watch 不能和 --export-web 一起使用')
    if args.interval < 15:
        p.error('--interval 必须至少 15 秒')
    try:
        if args.list:
            for l in load_lessons():
                print(f"{l['id']:15}  {l['title']}  ·  {l['genre']}")
            return 0
        if args.watch:
            client = MCPClient()
            last_id = None
            print('监控已启动：先记录现有订单，不自动输出历史记录。按 Ctrl+C 退出。', file=sys.stderr)
            while True:
                try:
                    order = latest_valid_order(client.list_orders())
                    oid = str(order.get('orderId') or order.get('id') or '') if order else ''
                    if last_id is None:
                        last_id = oid
                    elif oid and oid != last_id:
                        print(as_plain(compose(order_items(order), args.lesson)), flush=True)
                        last_id = oid
                except (MCPError, InputError) as e:
                    print(f'监控提示：{e}', file=sys.stderr)
                time.sleep(args.interval)
        if args.mcp:
            items = fetch_latest_items(MCPClient())
        elif args.items is not None:
            items = parse_items(args.items)
        else:
            items = DEMO_ITEMS
        if args.export_web:
            # 文件中只有餐品名和数量，不含 Token、订单号、店铺、价格、时间。
            args.export_web.write_text(json.dumps(browser_payload(items), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            print(f'已导出脱敏订单：{args.export_web}（可导入网页）')
            return 0
        doc = compose(items, args.lesson)
        if args.json:
            print(json.dumps(doc, ensure_ascii=False, indent=2))
        elif args.md:
            print(as_markdown(doc))
        else:
            print(as_plain(doc))
        return 0
    except KeyboardInterrupt:
        print('\n已退出', file=sys.stderr)
        return 130
    except (InputError, MCPError, OSError) as e:
        print(f'错误：{e}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
