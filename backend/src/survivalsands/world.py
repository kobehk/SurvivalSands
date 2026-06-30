"""世界状态：所有"硬"事实由这里管，LLM 永远不直接修改字段，只通过 apply_delta。

玩家用像素坐标 (x, y)；岛屿是 200×120 程序化生成。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal, TypedDict

from .items import item_by_id
from .landmarks import PlacedLandmark, landmark_at, place_landmarks
from .terrain import (
    TERRAIN_COST,
    TERRAIN_SIGHT,
    Island,
    Terrain,
    find_spawn_point,
    generate_island,
    is_passable,
    tile_at,
)

Weather = Literal["clear", "cloudy", "rain", "storm"]
TimeOfDay = Literal["dawn", "morning", "noon", "afternoon", "dusk", "night"]

TIME_ORDER: list[TimeOfDay] = ["dawn", "morning", "noon", "afternoon", "dusk", "night"]


@dataclass
class ItemStack:
    id: str
    qty: int


@dataclass
class Player:
    hp: int
    hunger: int
    thirst: int
    fatigue: int
    x: int
    y: int
    skills: dict[str, int]
    inventory: list[ItemStack]


@dataclass
class BuiltThing:
    x: int
    y: int
    type: str
    description: str


# 地面物品堆：放在世界某坐标的物品
# perishable=True 的物品（食物/水）放一天会腐败；工具/原料永久保存
@dataclass
class GroundItem:
    x: int
    y: int
    id: str
    qty: int
    placed_day: int  # 放下时的游戏天数（用于腐败计算）


@dataclass
class World:
    day: int
    time: TimeOfDay
    weather: Weather
    player: Player
    island: Island
    landmarks: list[PlacedLandmark]
    built_things: list[BuiltThing]
    ground_items: list[GroundItem]   # 世界中的地面物品
    explored: bytearray  # 0=未探索 1=见过 2=走过
    landmark_descriptions: dict[str, str]
    story_flags: dict[str, bool | int | str]


SEED = 42


def initial_world() -> World:
    island = generate_island(SEED)
    landmarks = place_landmarks(island)
    spawn_x, spawn_y = find_spawn_point(island)
    # 把 wreck 挪到出生点
    for lm in landmarks:
        if lm.id == "wreck":
            lm.x = spawn_x
            lm.y = spawn_y
            break
    return World(
        day=1,
        time="morning",
        weather="clear",
        player=Player(
            hp=100,
            hunger=30,
            thirst=20,
            fatigue=10,
            x=spawn_x,
            y=spawn_y,
            skills={"crafting": 0, "foraging": 0, "fishing": 0},
            inventory=[],
        ),
        island=island,
        landmarks=landmarks,
        built_things=[],
        ground_items=[],
        explored=bytearray(island.width * island.height),
        landmark_descriptions={},
        story_flags={"days_alone": 0, "friday_unlocked": False},
    )


# === WorldDelta：LLM 通过 tool call 产出，runtime 校验后才应用 ===


class WorldDelta(TypedDict, total=False):
    consume_items: list[dict]      # [{id, qty}]  从背包消耗
    produce_items: list[dict]      # [{id, qty}]  加入背包
    drop_items: list[dict]         # [{id, qty}]  从背包移到地面（当前坐标）
    pick_up_items: list[dict]      # [{id, qty, x?, y?}]  从地面捡入背包（默认玩家当前坐标）
    hp_change: int
    hunger_change: int
    thirst_change: int
    fatigue_change: int
    skill_gain: dict[str, int]
    time_advance_minutes: int
    build: dict                    # {type, description}


def _clamp(n: float, lo: float, hi: float) -> int:
    return int(max(lo, min(hi, n)))


def _advance_time(world: World, minutes: int) -> None:
    buckets = minutes // 240
    idx = TIME_ORDER.index(world.time)
    for _ in range(buckets):
        idx += 1
        if idx >= len(TIME_ORDER):
            idx = 0
            world.day += 1
    world.time = TIME_ORDER[idx]

    hours = minutes / 60
    world.player.hunger = _clamp(world.player.hunger + hours * 2, 0, 100)
    world.player.thirst = _clamp(world.player.thirst + hours * 3, 0, 100)
    world.player.fatigue = _clamp(world.player.fatigue + hours * 1.5, 0, 100)

    # 地面食物腐败：放置超过 1 天的 perishable 物品消失
    world.ground_items = [
        g for g in world.ground_items
        if not _is_perishable(g.id) or (world.day - g.placed_day) < 1
    ]


def _is_perishable(item_id: str) -> bool:
    it = item_by_id(item_id)
    return it.perishable if it else False


def apply_delta(world: World, delta: WorldDelta) -> tuple[bool, str | None]:
    """先校验全部条件，全 OK 才 mutate。返回 (ok, reason)。"""
    p = world.player

    consume = delta.get("consume_items") or []
    for c in consume:
        stack = next((s for s in p.inventory if s.id == c["id"]), None)
        if stack is None or stack.qty < c["qty"]:
            return (False, f"背包里没有足够的 {c['id']}（需要 {c['qty']}）")

    # 校验 drop_items（从背包放到地面）
    for d in delta.get("drop_items") or []:
        stack = next((s for s in p.inventory if s.id == d["id"]), None)
        if stack is None or stack.qty < d["qty"]:
            return (False, f"背包里没有足够的 {d['id']}（需要 {d['qty']}）")

    # 校验 pick_up_items（从地面捡入背包）
    for pu in delta.get("pick_up_items") or []:
        gx = pu.get("x", p.x)
        gy = pu.get("y", p.y)
        total = sum(g.qty for g in world.ground_items if g.id == pu["id"] and g.x == gx and g.y == gy)
        if total < pu["qty"]:
            return (False, f"地面上没有足够的 {pu['id']}（需要 {pu['qty']}，现有 {total}）")

    # 全部校验通过 → 应用
    for c in consume:
        stack = next(s for s in p.inventory if s.id == c["id"])
        stack.qty -= c["qty"]
    p.inventory = [s for s in p.inventory if s.qty > 0]

    for c in delta.get("produce_items") or []:
        stack = next((s for s in p.inventory if s.id == c["id"]), None)
        if stack is not None:
            stack.qty += c["qty"]
        else:
            p.inventory.append(ItemStack(id=c["id"], qty=c["qty"]))

    # 放下物品：从背包移到地面当前坐标
    for d in delta.get("drop_items") or []:
        stack = next(s for s in p.inventory if s.id == d["id"])
        stack.qty -= d["qty"]
        # 合并到已有的地面堆，或新建
        existing = next((g for g in world.ground_items if g.id == d["id"] and g.x == p.x and g.y == p.y), None)
        if existing:
            existing.qty += d["qty"]
        else:
            world.ground_items.append(GroundItem(x=p.x, y=p.y, id=d["id"], qty=d["qty"], placed_day=world.day))
    p.inventory = [s for s in p.inventory if s.qty > 0]

    # 从地面捡起物品
    for pu in delta.get("pick_up_items") or []:
        gx = pu.get("x", p.x)
        gy = pu.get("y", p.y)
        need = pu["qty"]
        for g in world.ground_items:
            if g.id != pu["id"] or g.x != gx or g.y != gy or need <= 0:
                continue
            take = min(g.qty, need)
            g.qty -= take
            need -= take
        world.ground_items = [g for g in world.ground_items if g.qty > 0]
        stack = next((s for s in p.inventory if s.id == pu["id"]), None)
        if stack:
            stack.qty += pu["qty"]
        else:
            p.inventory.append(ItemStack(id=pu["id"], qty=pu["qty"]))

    if delta.get("hp_change"):
        p.hp = _clamp(p.hp + delta["hp_change"], 0, 100)
    if delta.get("hunger_change"):
        p.hunger = _clamp(p.hunger + delta["hunger_change"], 0, 100)
    if delta.get("thirst_change"):
        p.thirst = _clamp(p.thirst + delta["thirst_change"], 0, 100)
    if delta.get("fatigue_change"):
        p.fatigue = _clamp(p.fatigue + delta["fatigue_change"], 0, 100)

    if delta.get("skill_gain"):
        for k, v in delta["skill_gain"].items():
            p.skills[k] = p.skills.get(k, 0) + v

    if delta.get("time_advance_minutes"):
        _advance_time(world, delta["time_advance_minutes"])

    if delta.get("build"):
        b = delta["build"]
        world.built_things.append(
            BuiltThing(x=p.x, y=p.y, type=b["type"], description=b["description"])
        )

    return (True, None)


# === 玩家移动（绕开 LLM）===


def try_move(world: World, dx: int, dy: int) -> tuple[bool, str | None]:
    p = world.player
    nx, ny = p.x + dx, p.y + dy
    if not (0 <= nx < world.island.width and 0 <= ny < world.island.height):
        return (False, "到了地图边缘")
    t = tile_at(world.island, nx, ny)
    if not is_passable(t):
        return (False, "前面过不去")
    p.x, p.y = nx, ny
    cost = TERRAIN_COST[t]
    _advance_time(world, int(cost))
    mark_explored(world, nx, ny, 2)
    reveal_around(world, nx, ny)
    return (True, None)


def mark_explored(world: World, x: int, y: int, level: int) -> None:
    if not (0 <= x < world.island.width and 0 <= y < world.island.height):
        return
    idx = y * world.island.width + x
    if world.explored[idx] < level:
        world.explored[idx] = level


def reveal_around(world: World, cx: int, cy: int) -> None:
    t = tile_at(world.island, cx, cy)
    sight = TERRAIN_SIGHT.get(t, 6)
    for dy in range(-sight, sight + 1):
        for dx in range(-sight, sight + 1):
            if dx * dx + dy * dy > sight * sight:
                continue
            mark_explored(world, cx + dx, cy + dy, 1)


def describe_player_state(world: World) -> str:
    p = world.player
    parts: list[str] = []
    if p.hunger > 70:
        parts.append("非常饥饿")
    elif p.hunger > 40:
        parts.append("有点饿")
    if p.thirst > 70:
        parts.append("非常口渴")
    elif p.thirst > 40:
        parts.append("有点渴")
    if p.fatigue > 70:
        parts.append("精疲力尽")
    elif p.fatigue > 40:
        parts.append("疲倦")
    if p.hp < 50:
        parts.append("受伤")
    return "，".join(parts) if parts else "状态良好"


def current_landmark(world: World) -> PlacedLandmark | None:
    return landmark_at(world.landmarks, world.player.x, world.player.y)


def current_terrain(world: World) -> Terrain:
    return tile_at(world.island, world.player.x, world.player.y)
