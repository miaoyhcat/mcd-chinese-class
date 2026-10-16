"""麦门语文课 · 纯标准库文字生成内核。

不进行网络访问。所有返回数据均为餐品、数量和原创课文，绝不包含订单号、地址等元数据。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LESSONS_FILE = ROOT / 'lessons.json'
CATALOG_FILE = ROOT / 'catalog.json'
MAX_ITEM_LENGTH = 72
MAX_ITEMS = 40


class InputError(ValueError):
    """用户可修复的输入错误。"""


@dataclass(frozen=True)
class Item:
    name: str
    quantity: int = 1

    def as_dict(self):
        return {'name': self.name, 'quantity': self.quantity}


def normalize_items(items):
    """规范化餐品；长度限额、合并相同餐品；不凭空补默认餐品。"""
    if not isinstance(items, (list, tuple)):
        raise InputError('餐品必须是数组')
    merged: dict[str, int] = {}
    for raw in items:
        if isinstance(raw, Item):
            name, qty = raw.name, raw.quantity
        elif isinstance(raw, str):
            name, qty = raw, 1
        elif isinstance(raw, dict):
            name, qty = raw.get('name'), raw.get('quantity', 1)
        else:
            raise InputError('存在无法识别的餐品数据')
        if not isinstance(name, str):
            raise InputError('餐品名称必须是文字')
        if any(ord(ch) < 32 for ch in name):
            raise InputError('餐品名称不能包含控制字符')
        name = re.sub(r'\s+', ' ', name).strip()
        if not name or len(name) > MAX_ITEM_LENGTH or any(ord(c) < 32 for c in name):
            raise InputError(f'餐品名称不能为空、包含控制符或超过 {MAX_ITEM_LENGTH} 字')
        if isinstance(qty, bool) or not isinstance(qty, int) or not 1 <= qty <= 99:
            raise InputError('数量必须为 1～99 的整数')
        if name not in merged and len(merged) >= MAX_ITEMS:
            raise InputError(f'最多支持 {MAX_ITEMS} 种餐品')
        merged[name] = min(99, merged.get(name, 0) + qty)
    if not merged:
        raise InputError('先选择至少一样餐品')
    return [Item(k, v) for k, v in merged.items()]


def parse_items(text):
    if not isinstance(text, str) or len(text) > 5000:
        raise InputError('请输入不超过 5000 字的餐品清单')
    parts = re.split(r'[,，、;；\n]+', text)
    normalized = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        match = re.fullmatch(r'(.*?)\s*[×*xX]\s*(\d{1,2})', part)
        if match:
            normalized.append({'name': match.group(1).strip(), 'quantity': int(match.group(2))})
        else:
            normalized.append(part)
    return normalize_items(normalized)


def load_catalog():
    return json.loads(CATALOG_FILE.read_text('utf-8'))


def load_lessons():
    data = json.loads(LESSONS_FILE.read_text('utf-8'))
    return data['lessons']


def category(name, catalog=None):
    c = catalog or load_catalog()
    # 顺序：完整分类表 > 主食 > 小食 > 饮品；避免“水果派”的“水”触发饮品。
    for group in ('main', 'side', 'drink'):
        if name in c['exact'][group]:
            return group
    if any(w in name for w in c['markers']['main']):
        return 'main'
    if any(w in name for w in c['markers']['side']):
        return 'side'
    if any(w in name for w in c['markers']['drink']):
        return 'drink'
    if name.endswith(('水', '茶')) and not name.endswith(('奶茶派', '抹茶派')):
        return 'drink'
    return 'side'


def safe_fields(items, catalog=None):
    norm = normalize_items(items)
    c = catalog or load_catalog()
    groups = {'main': [], 'side': [], 'drink': []}
    for item in norm:
        groups[category(item.name, c)].append(item.name)
    lead = groups['main'][0] if groups['main'] else norm[0].name
    others = [x.name for x in norm if x.name != lead]
    side = (groups['side'] or others or [lead])[0]
    drink = (groups['drink'] or others or [lead])[0]
    return {
        'main': lead, 'side': side, 'drink': drink,
        'items': '、'.join(i.name for i in norm),
        'count': str(sum(i.quantity for i in norm)),
        'kinds': str(len(norm)),
    }


def stable_number(items):
    # 和浏览器保持一致：UTF-8，SHA-256 前四字节取模（WebCrypto 在 file:// 可能不可用，
    # 因此前端另有相同、无需加密 API 的 FNV-1a 实现；这里也用 FNV-1a）。
    b = '|'.join(f'{x.name}*{x.quantity}' for x in normalize_items(items)).encode('utf-8')
    h = 2166136261
    for v in b:
        h ^= v
        h = (h * 16777619) & 0xffffffff
    return h % 999 + 1


def choose_lesson(items, lessons=None):
    ls = lessons or load_lessons()
    normalized = normalize_items(items)
    h = stable_number(normalized)
    return ls[(h - 1) % len(ls)]


def render_text(s, fields):
    if not isinstance(s, str):
        raise ValueError('模板字段必须是文字')
    # 不允许动态属性/下标格式化。
    def replace(match):
        key = match.group(1)
        if key not in fields:
            raise ValueError(f'未知模板占位符: {key}')
        return fields[key]
    # 检查原模板，而不是填入用户餐品后的文本；餐品可能合法地带有花括号。
    out = re.sub(r'\{([a-z]+)\}', replace, s)
    return out


def compose(items, lesson_id=None, lessons=None):
    norm = normalize_items(items)
    ls = lessons or load_lessons()
    if lesson_id:
        target = next((l for l in ls if l['id'] == lesson_id), None)
        if not target:
            raise InputError('找不到指定课文')
    else:
        target = choose_lesson(norm, ls)
    fields = safe_fields(norm)
    return {
        'id': target['id'], 'number': stable_number(norm),
        'title': target['title'], 'genre': target['genre'],
        'inspired_by': target.get('inspired_by', ''),
        'opening': render_text(target['opening'], fields),
        'body': [render_text(p, fields) for p in target['body']],
        'ending': render_text(target['ending'], fields),
        'items': [i.as_dict() for i in norm],
        'notice': '原创文学戏仿 · 非麦当劳官方产品',
    }


def as_markdown(doc):
    ps = [f"# {doc['title']}", f"*麦门语文 · 第 {doc['number']:03d} 课 · {doc['genre']}*", '', doc['opening'], *doc['body'], doc['ending']]
    return '\n\n'.join(ps) + '\n\n---\n课文完 · 本课餐品：' + '、'.join(x['name'] for x in doc['items']) + '\n'


def as_plain(doc):
    return (f"麦门语文 · 第 {doc['number']:03d} 课\n{doc['title']} · {doc['genre']}\n\n"
            + '\n\n'.join([doc['opening'], *doc['body'], doc['ending']])
            + '\n\n—— 课文完 ——\n餐品：' + '、'.join(x['name'] for x in doc['items']))


def browser_payload(items):
    """导出的网页订单格式只允许餐品名称、数量和模式标识，绝不含 MCP 元数据。"""
    return {'format': 'mcd-chinese-class/items-v1', 'items': [i.as_dict() for i in normalize_items(items)]}
