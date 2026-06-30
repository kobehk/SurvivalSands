"""物品白名单：游戏内已知物品的"id ↔ 中文名 ↔ 分类"权威表。

给 LLM 的 prompt 里会贴出这个清单，告诉它：
  "如果产出/消耗的物品在清单里，必须用清单的 id；不在清单里的可以新造但要符合 snake_case 规范。"

注意：public/game.js 里有一份等价的 ITEM_ZH 表用于前端展示。两份必须保持同步。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ItemCategory = Literal["food", "water", "tool", "material", "fuel", "misc"]


@dataclass(frozen=True)
class ItemDef:
    id: str
    zh: str
    category: ItemCategory
    notes: str | None = None
    # 放在地面上会腐败（food/water 类默认 True，其余 False）
    perishable: bool = False


ITEMS: list[ItemDef] = [
    # === 椰子相关 ===
    ItemDef("coconut", "椰子", "food", "完整未破壳；需用石头砸或锐物撬开", perishable=True),
    ItemDef("coconut_shell", "椰子壳", "material", "破壳后剩下的硬壳，可装水/做容器"),
    ItemDef("coconut_meat", "椰肉", "food", "破壳后取出的果肉", perishable=True),
    ItemDef("coconut_water", "椰汁", "water", "椰子里的清液，可解渴", perishable=True),
    ItemDef("coconut_fiber", "椰壳纤维", "fuel", "椰子壳外层的干燥纤维，火绒首选"),
    # === 水 ===
    ItemDef("fresh_water", "淡水", "water", "可饮用；通常装在容器里", perishable=True),
    ItemDef("water_in_shell", "装水的椰壳", "water", "用椰子壳盛的淡水", perishable=True),
    ItemDef("salt_water", "咸水", "misc", "不可饮用，用于晒盐或烹饪"),
    # === 食物 ===
    ItemDef("small_fish", "小鱼", "food", perishable=True),
    ItemDef("fish_raw", "生鱼", "food", "不烹饪一天就腐败", perishable=True),
    ItemDef("fish_cooked", "熟鱼", "food", perishable=True),
    ItemDef("crab", "螃蟹", "food", perishable=True),
    ItemDef("clam", "蛤蜊", "food", perishable=True),
    ItemDef("shellfish", "贝类", "food", perishable=True),
    ItemDef("seashell", "贝壳", "material", "空贝壳，可做小容器或装饰"),
    ItemDef("banana", "香蕉", "food", perishable=True),
    ItemDef("wild_fruit", "野果", "food", perishable=True),
    ItemDef("berries", "浆果", "food", perishable=True),
    ItemDef("seeds", "种子", "food", perishable=True),
    ItemDef("nuts", "坚果", "food", perishable=True),
    ItemDef("meat_raw", "生肉", "food", perishable=True),
    ItemDef("meat_cooked", "熟肉", "food", perishable=True),
    ItemDef("egg", "蛋", "food", perishable=True),
    ItemDef("salt", "盐", "misc"),
    # === 石/木/植物原料 ===
    ItemDef("stone", "石头", "material"),
    ItemDef("sharp_stone", "锐石", "tool", "打磨过或天然锋利的石头，可切割"),
    ItemDef("large_stone", "大石头", "material"),
    ItemDef("pebble", "小石子", "material"),
    ItemDef("wood", "木头", "material"),
    ItemDef("wood_plank", "木板", "material", "通常从船的残骸或砍下的树取得"),
    ItemDef("driftwood", "浮木", "material", "海水冲上岸的木头，比较潮湿"),
    ItemDef("stick", "树枝", "material"),
    ItemDef("long_branch", "长树枝", "material"),
    ItemDef("vine", "藤蔓", "material"),
    ItemDef("rope", "绳子", "material", "用藤蔓/纤维搓成"),
    ItemDef("leaf", "树叶", "material"),
    ItemDef("dry_leaf", "干树叶", "fuel"),
    ItemDef("tinder", "火绒", "fuel", "生火用的易燃物"),
    ItemDef("firewood", "柴火", "fuel"),
    ItemDef("mud", "泥土", "material"),
    ItemDef("clay", "黏土", "material"),
    # === 工具 ===
    ItemDef("rusty_knife", "锈刀", "tool", "从骸骨堆/船残骸里捡到，状况不佳但能用"),
    ItemDef("bone_knife", "骨刀", "tool"),
    ItemDef("spear", "矛", "tool", "用长树枝绑锐石或骨头制成"),
    ItemDef("club", "木棒", "tool"),
    ItemDef("fishing_line", "鱼线", "tool"),
    ItemDef("fishing_hook", "鱼钩", "tool"),
    ItemDef("torch", "火把", "tool"),
    # === 容器 ===
    ItemDef("cup", "杯子", "tool"),
    ItemDef("bowl", "碗", "tool"),
    ItemDef("basket", "篮子", "tool"),
    ItemDef("glass_bottle", "玻璃瓶", "tool", "罕见；漂流瓶里的容器"),
    # === 杂物 ===
    ItemDef("feather", "羽毛", "misc"),
    ItemDef("bone", "骨头", "misc"),
    ItemDef("cloth", "布条", "material"),
    ItemDef("iron_nail", "铁钉", "material"),
    ItemDef("iron_scrap", "铁片", "material"),
    ItemDef("bottle_message", "瓶中信", "misc", "漂流瓶里的字条"),
]

ITEM_BY_ID: dict[str, ItemDef] = {it.id: it for it in ITEMS}


def item_by_id(item_id: str) -> ItemDef | None:
    return ITEM_BY_ID.get(item_id)


_CATEGORY_LABELS: dict[ItemCategory, str] = {
    "food": "食物",
    "water": "水",
    "fuel": "燃料",
    "material": "原料",
    "tool": "工具",
    "misc": "杂物",
}
_CATEGORY_ORDER: list[ItemCategory] = ["food", "water", "fuel", "material", "tool", "misc"]


def item_catalog_for_prompt() -> str:
    """给 LLM prompt 用的物品清单字符串（按分类分组）。"""
    by_cat: dict[ItemCategory, list[ItemDef]] = {}
    for it in ITEMS:
        by_cat.setdefault(it.category, []).append(it)
    lines: list[str] = []
    for cat in _CATEGORY_ORDER:
        items = by_cat.get(cat, [])
        if not items:
            continue
        body = "，".join(
            f"{it.id}（{it.zh}：{it.notes}）" if it.notes else f"{it.id}（{it.zh}）"
            for it in items
        )
        lines.append(f"【{_CATEGORY_LABELS[cat]}】{body}")
    return "\n".join(lines)
