"""程序化地形生成。一次性算出整个岛的 24000 格底图，存为 bytearray。

基于固定 seed 决定形态，确保同一存档每次生成的地图完全一致。
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import IntEnum
from typing import TypedDict

from opensimplex import OpenSimplex

MAP_W = 200
MAP_H = 120


class Terrain(IntEnum):
    OCEAN = 0
    SHALLOW_WATER = 1
    BEACH = 2
    GRASS = 3
    JUNGLE = 4
    DEEP_JUNGLE = 5
    HILLS = 6
    MOUNTAIN = 7
    SWAMP = 8
    RIVER = 9
    CLIFF = 10


TERRAIN_NAMES: dict[Terrain, str] = {
    Terrain.OCEAN: "深海",
    Terrain.SHALLOW_WATER: "浅滩",
    Terrain.BEACH: "沙滩",
    Terrain.GRASS: "草地",
    Terrain.JUNGLE: "丛林",
    Terrain.DEEP_JUNGLE: "密林深处",
    Terrain.HILLS: "丘陵",
    Terrain.MOUNTAIN: "山地",
    Terrain.SWAMP: "沼泽",
    Terrain.RIVER: "河流",
    Terrain.CLIFF: "悬崖",
}

TERRAIN_EMOJI: dict[Terrain, str] = {
    Terrain.OCEAN: "🌊",
    Terrain.SHALLOW_WATER: "🟦",
    Terrain.BEACH: "🟨",
    Terrain.GRASS: "🟩",
    Terrain.JUNGLE: "🌴",
    Terrain.DEEP_JUNGLE: "🌳",
    Terrain.HILLS: "🟫",
    Terrain.MOUNTAIN: "🗻",
    Terrain.SWAMP: "🟪",
    Terrain.RIVER: "💧",
    Terrain.CLIFF: "⬛",
}

# float('inf') 表示不可通行
TERRAIN_COST: dict[Terrain, float] = {
    Terrain.OCEAN: float("inf"),
    Terrain.SHALLOW_WATER: 4,
    Terrain.BEACH: 1,
    Terrain.GRASS: 1,
    Terrain.JUNGLE: 2,
    Terrain.DEEP_JUNGLE: 3,
    Terrain.HILLS: 2,
    Terrain.MOUNTAIN: 5,
    Terrain.SWAMP: 4,
    Terrain.RIVER: 3,
    Terrain.CLIFF: float("inf"),
}


def is_passable(t: Terrain) -> bool:
    return TERRAIN_COST[t] != float("inf")


# 站立点的视野半径（格）。地形越复杂越受限。
TERRAIN_SIGHT: dict[Terrain, int] = {
    Terrain.OCEAN: 12,
    Terrain.SHALLOW_WATER: 10,
    Terrain.BEACH: 10,
    Terrain.GRASS: 8,
    Terrain.JUNGLE: 4,
    Terrain.DEEP_JUNGLE: 3,
    Terrain.HILLS: 12,
    Terrain.MOUNTAIN: 16,
    Terrain.SWAMP: 4,
    Terrain.RIVER: 6,
    Terrain.CLIFF: 12,
}


@dataclass
class Island:
    width: int
    height: int
    tiles: bytearray  # length = width * height


def tile_at(island: Island, x: int, y: int) -> Terrain:
    if x < 0 or y < 0 or x >= island.width or y >= island.height:
        return Terrain.OCEAN
    return Terrain(island.tiles[y * island.width + x])


def _terrain_elevation_rank(t: Terrain) -> int:
    return {
        Terrain.OCEAN: 0,
        Terrain.SHALLOW_WATER: 1,
        Terrain.RIVER: 2,
        Terrain.BEACH: 3,
        Terrain.SWAMP: 4,
        Terrain.GRASS: 5,
        Terrain.JUNGLE: 6,
        Terrain.DEEP_JUNGLE: 7,
        Terrain.HILLS: 8,
        Terrain.MOUNTAIN: 9,
        Terrain.CLIFF: 10,
    }[t]


def _carve_rivers(
    tiles: bytearray, w: int, h: int, rng: random.Random, count: int
) -> None:
    """从高地起点贪心向低处雕刻河流。"""
    candidates: list[tuple[int, int]] = []
    for y in range(5, h - 5):
        for x in range(5, w - 5):
            t = Terrain(tiles[y * w + x])
            if t in (Terrain.MOUNTAIN, Terrain.HILLS, Terrain.DEEP_JUNGLE):
                candidates.append((x, y))
    if not candidates:
        return

    for _ in range(count):
        sx, sy = rng.choice(candidates)
        x, y = sx, sy
        visited: set[int] = set()
        for _step in range(200):
            idx = y * w + x
            if idx in visited:
                break
            visited.add(idx)
            t = Terrain(tiles[idx])
            if t in (Terrain.OCEAN, Terrain.SHALLOW_WATER):
                break
            if t != Terrain.CLIFF:
                tiles[idx] = Terrain.RIVER
            # 找邻居中"海拔最低"的——加点扰动
            neighbors = [(-1, 0), (1, 0), (0, -1), (0, 1)]
            rng.shuffle(neighbors)
            best: tuple[int, int, int] | None = None
            for dx, dy in neighbors:
                nx, ny = x + dx, y + dy
                if not (0 <= nx < w and 0 <= ny < h):
                    continue
                nt = Terrain(tiles[ny * w + nx])
                rank = _terrain_elevation_rank(nt)
                if best is None or rank < best[2]:
                    best = (dx, dy, rank)
            if best is None:
                break
            x += best[0]
            y += best[1]


def generate_island() -> Island:
    """生成 200×120 的固定岛屿。"""
    rng = random.Random(42)
    elev_noise = OpenSimplex(seed=42)
    moist_noise = OpenSimplex(seed=43)
    detail_noise = OpenSimplex(seed=44)

    w, h = MAP_W, MAP_H
    tiles = bytearray(w * h)

    cx, cy = w / 2, h / 2
    max_r = min(w, h) / 2

    for y in range(h):
        for x in range(w):
            dx = (x - cx) / max_r
            dy = (y - cy) / max_r
            r = (dx * dx + dy * dy) ** 0.5

            # 多倍频噪声
            e1 = elev_noise.noise2(x / 60, y / 60)
            e2 = elev_noise.noise2(x / 25, y / 25) * 0.5
            e3 = detail_noise.noise2(x / 10, y / 10) * 0.25
            elevation = (e1 + e2 + e3) / 1.75
            elevation += 0.35
            # 软衰减：r<0.55 几乎不衰减；r>0.55 快速衰减
            fade = max(0.0, (r - 0.55) / 0.45)
            elevation -= fade * fade * 1.8
            # 中心凸起：在岛心自然形成主峰 / 丘陵地带
            bump = max(0.0, 0.55 - r * 0.50)
            elevation += bump * 0.75

            moisture = (
                moist_noise.noise2(x / 50, y / 50)
                + moist_noise.noise2(x / 20, y / 20) * 0.5
            ) / 1.5

            if elevation < -0.05:
                t = Terrain.OCEAN if elevation < -0.2 else Terrain.SHALLOW_WATER
            elif elevation < 0.05:
                t = Terrain.BEACH
            elif elevation < 0.5:
                if moisture < 0.2:
                    t = Terrain.GRASS
                elif moisture < 0.5:
                    t = Terrain.JUNGLE
                else:
                    t = Terrain.SWAMP
            elif elevation < 0.75:
                t = Terrain.DEEP_JUNGLE if moisture > 0.3 else Terrain.HILLS
            else:
                t = Terrain.CLIFF if elevation > 0.9 else Terrain.MOUNTAIN

            tiles[y * w + x] = int(t)

    _carve_rivers(tiles, w, h, rng, 3)

    return Island(width=w, height=h, tiles=tiles)


def find_spawn_point(island: Island) -> tuple[int, int]:
    """找南侧海岸沙滩作为出生点（从底部往上扫，让玩家面朝岛屿内陆）。"""
    for y in range(island.height - 1, -1, -1):
        for x in range(island.width):
            if tile_at(island, x, y) != Terrain.BEACH:
                continue
            for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                nt = tile_at(island, x + dx, y + dy)
                if nt in (Terrain.OCEAN, Terrain.SHALLOW_WATER):
                    return (x, y)
    return (island.width // 2, island.height - 1)


# === 导出给前端的 enum 值映射（供 server 序列化时用） ===
class TerrainExport(TypedDict):
    name: str
    emoji: str


def terrain_export() -> dict[int, TerrainExport]:
    return {int(t): {"name": TERRAIN_NAMES[t], "emoji": TERRAIN_EMOJI[t]} for t in Terrain}
