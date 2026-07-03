"""砍树系统：池子耗尽模型。

每个可砍伐的格子（JUNGLE / DEEP_JUNGLE）有一个物品池。
每次砍树从池子取 1-2 件物品，池子空了则该格变为 GRASS。
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from items import item_by_id
from search import LootEntry
from terrain import Terrain

# 可砍树的地形
TREEABLE_TERRAINS = {Terrain.JUNGLE, Terrain.DEEP_JUNGLE}

# 每次砍伐产出 1-2 件物品
PER_CHOP_COUNT = (1, 2)

# 每斧耗时与疲劳
CHOP_TIME_MINUTES = 20
CHOP_FATIGUE = 8

# ── 丛林 loot 表 ──
JUNGLE_POOL: list[LootEntry] = [
    LootEntry(item_id="wood", weight=5, qty_min=1, qty_max=2),
    LootEntry(item_id="stick", weight=4, qty_min=1, qty_max=3),
    LootEntry(item_id="long_branch", weight=2, qty_min=1, qty_max=1),
    LootEntry(item_id="vine", weight=3, qty_min=1, qty_max=2),
    LootEntry(item_id="leaf", weight=3, qty_min=1, qty_max=2),
    LootEntry(item_id="dry_leaf", weight=2, qty_min=1, qty_max=2),
    LootEntry(item_id="tinder", weight=1, qty_min=1, qty_max=1),
    LootEntry(item_id="firewood", weight=2, qty_min=1, qty_max=1),
    LootEntry(item_id="seeds", weight=1, qty_min=0, qty_max=1),
    LootEntry(item_id="nuts", weight=1, qty_min=0, qty_max=2),
    LootEntry(item_id="wild_fruit", weight=1, qty_min=0, qty_max=1),
]

# ── 密林深处 loot 表（更丰盛）──
DEEP_JUNGLE_POOL: list[LootEntry] = [
    LootEntry(item_id="wood", weight=6, qty_min=2, qty_max=3),
    LootEntry(item_id="wood_plank", weight=2, qty_min=1, qty_max=1),
    LootEntry(item_id="long_branch", weight=3, qty_min=1, qty_max=2),
    LootEntry(item_id="stick", weight=4, qty_min=1, qty_max=3),
    LootEntry(item_id="vine", weight=3, qty_min=1, qty_max=3),
    LootEntry(item_id="leaf", weight=4, qty_min=1, qty_max=3),
    LootEntry(item_id="dry_leaf", weight=2, qty_min=1, qty_max=3),
    LootEntry(item_id="tinder", weight=2, qty_min=1, qty_max=2),
    LootEntry(item_id="firewood", weight=3, qty_min=1, qty_max=2),
    LootEntry(item_id="nuts", weight=2, qty_min=1, qty_max=3),
    LootEntry(item_id="wild_fruit", weight=2, qty_min=0, qty_max=2),
    LootEntry(item_id="feather", weight=1, qty_min=0, qty_max=1),
    LootEntry(item_id="egg", weight=1, qty_min=0, qty_max=1),
]


def init_tree_pool(terrain: int, rng: random.Random) -> list[dict]:
    """将 loot 表展开为具体物品池（每格首次砍时调用）。"""
    pool_def = DEEP_JUNGLE_POOL if terrain == Terrain.DEEP_JUNGLE else JUNGLE_POOL
    items: list[dict] = []
    for entry in pool_def:
        if item_by_id(entry.item_id) is None:
            continue
        for _ in range(entry.weight):
            qty = rng.randint(entry.qty_min, entry.qty_max)
            if qty > 0:
                items.append({"id": entry.item_id, "qty": qty})
    rng.shuffle(items)
    return items


def terrain_after_clear(terrain: int) -> int:
    """树木砍光后的地形。"""
    if terrain in (Terrain.JUNGLE, Terrain.DEEP_JUNGLE):
        return Terrain.GRASS
    return terrain


@dataclass
class TreeChopState:
    """每个格子的砍树进度。

    - remaining_pools: packed_coord → 池子剩余物品列表
    - cleared_cells: 已砍光的格子（packed_coord set）
    """

    remaining_pools: dict[int, list[dict]] = field(default_factory=dict)
    cleared_cells: set[int] = field(default_factory=set)
