"""Slot-preserving inventory operations and catalog discovery from a loaded save."""
from __future__ import annotations

import copy
import json
import math
from dataclasses import dataclass

from save_codec import SaveFormatError


@dataclass
class ItemTemplate:
    item: dict
    source: str

    @property
    def label(self):
        genes = self.item.get('geneGroup', {}).get('geneIds', [])
        kind = self.item.get('$type', '普通物品').split(',')[0].removeprefix('DolocTown.')
        suffix = ' · ' + ', '.join(genes) if genes else ''
        return f"{self.item['itemName']} · {kind}{suffix}"


def discover_catalog(data):
    """Only reuse real item instances, never reward descriptors or guessed types."""
    templates, genes, seen = [], set(), set()

    def walk(value, path=()):
        if isinstance(value, dict):
            kind = value.get('$type', '')
            in_slots = len(path) > 1 and path[-2] == 'items'
            if (isinstance(value.get('itemName'), str)
                    and type(value.get('itemCount')) is int
                    and ((isinstance(kind, str) and kind.startswith('DolocTown.Item'))
                         or (in_slots and not kind))):
                normalized = copy.deepcopy(value)
                normalized['itemCount'] = 1
                signature = json.dumps(normalized, sort_keys=True, ensure_ascii=False)
                try:
                    validate_item(normalized)
                    valid = True
                except SaveFormatError:
                    valid = False
                if valid and signature not in seen:
                    seen.add(signature)
                    templates.append(ItemTemplate(normalized, '/'.join(map(str, path))))
            for key, child in value.items():
                if key in ('geneIds', 'geneNames', 'unlockedGeneNames') and isinstance(child, list):
                    genes.update(x for x in child if isinstance(x, str) and x)
                if key == 'geneId' and isinstance(child, str) and child:
                    genes.add(child)
                walk(child, path + (key,))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, path + (index,))
    walk(data)
    return sorted(templates, key=lambda t: t.label), sorted(genes)


def backpack(data):
    try:
        result = data['farmData']['inventory']['backpack']
    except (KeyError, TypeError) as exc:
        raise SaveFormatError('存档缺少 farmData/inventory/backpack。') from exc
    validate_container(result)
    return result


def validate_container(container):
    if not isinstance(container, dict) or not isinstance(container.get('items'), list):
        raise SaveFormatError('物品容器必须包含 items 数组。')
    locks = container.get('slotLockStates')
    if locks is not None and (not isinstance(locks, list)
            or len(locks) != len(container['items'])
            or any(type(v) is not bool for v in locks)):
        raise SaveFormatError('slotLockStates 必须与 items 槽位数相同且为布尔值。')


def validate_backpack_layout(data, original):
    """Keep the loaded save's capacity and capacity-related fields unchanged."""
    current, baseline = backpack(data), backpack(original)
    count = len(baseline['items'])
    if len(current['items']) != count:
        raise SaveFormatError(f'背包必须保持原存档的 {count} 格；只能修改格内物品，不能增减格子。')

    def unchanged(current_object, original_object, key):
        if ((key in current_object) != (key in original_object)
                or type(current_object.get(key)) is not type(original_object.get(key))
                or current_object.get(key) != original_object.get(key)):
            raise SaveFormatError(f'不能修改背包容量相关字段 {key}；请保留原存档的值。')

    unchanged(current, baseline, 'slotLockStates')
    unchanged(data['farmData']['inventory'], original['farmData']['inventory'], 'backpackColum')
    unchanged(data['farmData'].get('agentData', {}),
              original['farmData'].get('agentData', {}), 'backpackLevel')


def container_at(data, container_path=()):
    container = backpack(data)
    for index in container_path:
        item = container['items'][index]
        if not isinstance(item, dict) or 'inventory' not in item:
            raise SaveFormatError('选中的物品不是容器。')
        container = item['inventory']
        validate_container(container)
    return container


def item_at(data, path):
    return container_at(data, path[:-1])['items'][path[-1]]


def validate_item(item):
    if not isinstance(item, dict):
        raise SaveFormatError('物品必须是 JSON 对象。')
    if not isinstance(item.get('itemName'), str) or not item['itemName'].strip():
        raise SaveFormatError('itemName 必须是非空文本。')
    count = item.get('itemCount')
    if type(count) is not int or not 1 <= count <= 2_147_483_647:
        raise SaveFormatError('数量必须为 1 至 2,147,483,647 的整数；删除请使用删除按钮。')
    if '$type' in item and not isinstance(item['$type'], str):
        raise SaveFormatError('$type 必须为文本。')
    for key in ('currentDurability', 'incubationProgress'):
        if key in item and (type(item[key]) not in (int, float)
                            or not math.isfinite(item[key]) or item[key] < 0):
            raise SaveFormatError(f'{key} 必须为非负有限数值。')
    if 'geneGroup' in item:
        group = item['geneGroup']
        if not isinstance(group, dict) or not isinstance(group.get('geneIds'), list):
            raise SaveFormatError('geneGroup.geneIds 必须是数组。')
        if any(not isinstance(g, str) or not g.strip() for g in group['geneIds']):
            raise SaveFormatError('基因 ID 必须是非空文本。')
    if 'inventory' in item:
        validate_container(item['inventory'])
        for child in item['inventory']['items']:
            if child is not None:
                validate_item(child)


def replace_item(data, path, item):
    validate_item(item)
    container_at(data, path[:-1])['items'][path[-1]] = copy.deepcopy(item)


def delete_item(data, path):
    # Slots and their lock states are positional; never pop or shift the list.
    container_at(data, path[:-1])['items'][path[-1]] = None


def add_item(data, container_path, item, slot=None):
    validate_item(item)
    container = container_at(data, container_path)
    items = container['items']
    locks = container.get('slotLockStates', [False] * len(items))
    if slot is None:
        slot = next((i for i, value in enumerate(items) if value is None and not locks[i]), None)
    if slot is None:
        raise SaveFormatError('这个容器没有可用空槽，请先删除物品或选择其他容器。')
    if not 0 <= slot < len(items) or items[slot] is not None or locks[slot]:
        raise SaveFormatError('请选择未锁定的空槽。')
    items[slot] = copy.deepcopy(item)
    return container_path + (slot,)
