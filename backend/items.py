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
    perishable: bool = False
    # 体积单位：拆分/合成时的守恒基准（无量纲正整数）
    # 工具/容器/离散单品 = 0，表示"不参与体积推算"，产出固定 ×1
    volume: int = 0


ITEMS: list[ItemDef] = [
    # === 椰子相关 ===
    ItemDef("coconut",       "椰子",     "food",     "需用石头砸或锐物撬开才能取肉和汁", perishable=True, volume=1),
    ItemDef("coconut_shell", "椰子壳",   "material",                                                  volume=1),
    ItemDef("coconut_meat",  "椰肉",     "food",     perishable=True, volume=1),
    ItemDef("coconut_water", "椰汁",     "water",    perishable=True, volume=1),
    ItemDef("coconut_fiber", "椰壳纤维", "fuel",                      volume=2),
    # === 水 ===
    ItemDef("fresh_water",   "淡水",     "water",    perishable=True, volume=1),
    ItemDef("water_in_shell","装水的椰壳","water",   perishable=True, volume=1),
    ItemDef("salt_water",    "咸水",     "misc",     "不可饮用，用于晒盐或烹饪",          volume=1),
    # === 食物 ===
    ItemDef("small_fish",  "小鱼",  "food", perishable=True, volume=1),
    ItemDef("fish_raw",    "生鱼",  "food", "不烹饪一天就腐败", perishable=True, volume=2),
    ItemDef("fish_cooked", "熟鱼",  "food", perishable=True, volume=2),
    ItemDef("crab",        "螃蟹",  "food", perishable=True, volume=2),
    ItemDef("clam",        "蛤蜊",  "food", perishable=True, volume=1),
    ItemDef("shellfish",   "贝类",  "food", perishable=True, volume=1),
    ItemDef("seashell",    "贝壳",  "material", volume=1),
    ItemDef("banana",      "香蕉",  "food", perishable=True, volume=1),
    ItemDef("wild_fruit",  "野果",  "food", perishable=True, volume=1),
    ItemDef("berries",     "浆果",  "food", perishable=True, volume=1),
    ItemDef("seeds",       "种子",  "food", perishable=True, volume=1),
    ItemDef("nuts",        "坚果",  "food", perishable=True, volume=1),
    ItemDef("meat_raw",    "生肉",  "food", perishable=True, volume=3),
    ItemDef("meat_cooked", "熟肉",  "food", perishable=True, volume=3),
    ItemDef("egg",         "蛋",    "food", perishable=True, volume=1),
    ItemDef("salt",        "盐",    "misc",                  volume=1),
    # === 石/木/植物原料 ===
    ItemDef("stone",       "石头",   "material", volume=2),
    ItemDef("sharp_stone", "锐石",   "tool",     "天然锋利或打磨过，可切割", volume=0),
    ItemDef("large_stone", "大石头", "material", volume=6),
    ItemDef("pebble",      "小石子", "material", volume=1),
    ItemDef("wood",        "木头",   "material", volume=4),
    ItemDef("wood_plank",  "木板",   "material", volume=3),
    ItemDef("driftwood",   "浮木",   "material", volume=4),
    ItemDef("stick",       "树枝",   "material", volume=1),
    ItemDef("long_branch", "长树枝", "material", volume=2),
    ItemDef("vine",        "藤蔓",   "material", volume=1),
    ItemDef("rope",        "绳子",   "material", volume=3),
    ItemDef("leaf",        "树叶",   "material", volume=1),
    ItemDef("dry_leaf",    "干树叶", "fuel",      volume=1),
    ItemDef("tinder",      "火绒",   "fuel",     "生火用的易燃物", volume=1),
    ItemDef("firewood",    "柴火",   "fuel",      volume=2),
    ItemDef("mud",         "泥土",   "material",  volume=2),
    ItemDef("clay",        "黏土",   "material",  volume=2),
    # === 工具 ===
    ItemDef("rusty_knife",   "锈刀",   "tool", volume=0),
    ItemDef("bone_knife",    "骨刀",   "tool", volume=0),
    ItemDef("spear",         "矛",     "tool", volume=0),
    ItemDef("club",          "木棒",   "tool", volume=0),
    ItemDef("fishing_line",  "鱼线",   "tool", volume=0),
    ItemDef("fishing_hook",  "鱼钩",   "tool", volume=0),
    ItemDef("torch",         "火把",   "tool", volume=0),
    # === 容器 ===
    ItemDef("cup",          "杯子",   "tool", volume=0),
    ItemDef("bowl",         "碗",     "tool", volume=0),
    ItemDef("basket",       "篮子",   "tool", volume=0),
    ItemDef("glass_bottle", "玻璃瓶", "tool", volume=0),
    # === 杂物 ===
    ItemDef("feather",       "羽毛",  "misc", volume=1),
    ItemDef("bone",          "骨头",  "misc", volume=2),
    ItemDef("cloth",         "布条",  "material", volume=2),
    ItemDef("iron_nail",     "铁钉",  "material", volume=1),
    ItemDef("iron_scrap",    "铁片",  "material", volume=2),
    ItemDef("bottle_message","瓶中信","misc", volume=0),
    ItemDef("banana_seedling","香蕉幼苗","material", "可种植在丛林，数天后结香蕉", volume=0),
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


def calc_produce_qty(
    inputs: list[dict],    # [{id, qty}]  LLM 给的消耗
    output_id: str,        # LLM 给的产出 id
    llm_qty: int,          # LLM 给的产出数量（仅当无法推算时兜底）
    skill_level: int = 0,  # 玩家 crafting 技能等级
    clever: bool = False,  # LLM 判定玩家用了有创意的技法
) -> int:
    """根据体积守恒 + 技能系数 + 创意加成推算产出数量。

    三层叠加：
      base   = floor(输入总体积 / 输出体积)
      ×skill = 技能系数（新手有损耗，高手更充分利用原料）
      ×clever = 有具体技法描述时额外 ×1.2

    特殊情况：
      - 输出 volume=0（工具/离散单品）→ 固定返回 1，不受系数影响
      - 任意输入 volume=0（组装类）→ 固定返回 1
    """
    out_def = item_by_id(output_id)
    if out_def is None or out_def.volume == 0:
        return 1

    total_input_vol = 0
    for c in inputs:
        in_def = item_by_id(c["id"])
        if in_def is None or in_def.volume == 0:
            return 1
        total_input_vol += in_def.volume * c["qty"]

    if total_input_vol == 0:
        return llm_qty or 1

    base = total_input_vol / out_def.volume

    # 技能系数：0级有10%废料损耗，每2级涨10%，上限1.6
    skill_mult = max(0.8, min(1.6, 0.9 + skill_level * 0.1))

    # 创意加成
    clever_mult = 1.2 if clever else 1.0

    return max(1, int(base * skill_mult * clever_mult))
