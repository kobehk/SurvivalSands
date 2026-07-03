"""世界状态：所有"硬"事实由这里管，LLM 永远不直接修改字段，只通过 apply_delta。

玩家用像素坐标 (x, y)；岛屿是 200×120 程序化生成。
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Literal, TypedDict

from items import item_by_id
from landmarks import PlacedLandmark, landmark_at, place_landmarks
from terrain import (
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

# 天气对体力消耗的乘数（饥渴疲劳都按此放大）
WEATHER_DRAIN_MULT: dict[str, float] = {
    "clear": 1.0,
    "cloudy": 1.1,
    "rain": 1.35,
    "storm": 1.7,
}

# 天气对移动的额外时间惩罚（分钟/步）——风暴时行走更耗时
WEATHER_MOVE_PENALTY: dict[str, int] = {
    "clear": 0,
    "cloudy": 0,
    "rain": 5,
    "storm": 15,
}

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
    tags: list[str] = field(default_factory=list)


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
class CropPlot:
    x: int
    y: int
    crop_type: str     # "seeds" | "banana_seedling"
    planted_day: int
    last_watered_day: int  # 0=从未
    watered_count: int
    fertilized: bool
    stage: int         # 0=萌芽 1=生长中 2=可收获


CROP_CONFIG: dict[str, dict] = {
    "seeds": {
        "days_to_mature": 3,
        "watered_day_bonus": 1,
        "fertilize_bonus": 1,
        "yield_id": "wild_fruit",
        "yield_qty": (2, 4),
        "ok_terrains": [Terrain.GRASS, Terrain.JUNGLE, Terrain.DEEP_JUNGLE],
    },
    "banana_seedling": {
        "days_to_mature": 5,
        "watered_day_bonus": 1,
        "fertilize_bonus": 1,
        "yield_id": "banana",
        "yield_qty": (3, 6),
        "ok_terrains": [Terrain.JUNGLE, Terrain.DEEP_JUNGLE],
    },
}

# 储物架类型名白名单（建造物 type 字段匹配）
STORAGE_TYPES = frozenset(["storage", "仓库", "储物架", "rack", "shelf", "储藏室", "储物箱"])


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
    # key = 规范化输入串（如 "sharp_stone:1|stick:1|vine:2"），value = 配方描述
    discovered_recipes: dict[str, dict]
    crop_plots: list[CropPlot] = field(default_factory=list)
    tile_overrides: dict[int, int] = field(default_factory=dict)
    # key = y * width + x (packed 坐标), value = 新 Terrain int 值


def initial_world() -> World:
    island = generate_island()
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
            skills={"crafting": 0, "foraging": 0, "fishing": 0, "cooking": 0},
            inventory=[],
        ),
        island=island,
        landmarks=landmarks,
        built_things=[],
        ground_items=[],
        explored=bytearray(island.width * island.height),
        landmark_descriptions={},
        story_flags={"days_alone": 0, "friday_unlocked": False},
        discovered_recipes={},
        crop_plots=[],
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
    farm: dict                     # {action: "plant"|"water"|"fertilize"|"harvest", crop_type?: str}


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
    drain = WEATHER_DRAIN_MULT.get(world.weather, 1.0)
    # 庇护所在雨天/风暴时降低消耗
    if has_shelter_nearby(world) and world.weather in ("rain", "storm"):
        drain *= 0.7
    world.player.hunger = _clamp(world.player.hunger + hours * 2 * drain, 0, 100)
    world.player.thirst = _clamp(world.player.thirst + hours * 3 * drain, 0, 100)
    world.player.fatigue = _clamp(world.player.fatigue + hours * 1.5 * drain, 0, 100)

    # 储物架坐标集合：这些坐标上的 perishable 物品不腐败
    storage_coords = {
        (b.x, b.y) for b in world.built_things
        if "storage" in b.tags or b.type in STORAGE_TYPES
    }
    # 地面食物腐败：放置超过 1 天的 perishable 物品消失（储物架上的除外）
    world.ground_items = [
        g for g in world.ground_items
        if not _is_perishable(g.id)
        or (world.day - g.placed_day) < 1
        or (g.x, g.y) in storage_coords
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

    # 校验农业操作
    farm_op = delta.get("farm")
    if farm_op:
        ok, reason = _validate_farm(world, farm_op)
        if not ok:
            return (False, reason)

    # 全部校验通过 → 应用
    for c in consume:
        stack = next(s for s in p.inventory if s.id == c["id"])
        stack.qty -= c["qty"]
    p.inventory = [s for s in p.inventory if s.qty > 0]

    for c in delta.get("produce_items") or []:
        qty = c.get("qty", 1)  # LLM 可能不填 qty，兜底为 1
        stack = next((s for s in p.inventory if s.id == c["id"]), None)
        if stack is not None:
            stack.qty += qty
        else:
            p.inventory.append(ItemStack(id=c["id"], qty=qty))

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

    # 火堆加强疲劳恢复
    raw_fatigue = delta.get("fatigue_change", 0)
    if raw_fatigue < 0 and has_fire_nearby(world):
        raw_fatigue = int(raw_fatigue * 1.35)
    if raw_fatigue:
        p.fatigue = _clamp(p.fatigue + raw_fatigue, 0, 100)

    if delta.get("skill_gain"):
        for k, v in delta["skill_gain"].items():
            p.skills[k] = p.skills.get(k, 0) + v

    if delta.get("time_advance_minutes"):
        _advance_time(world, delta["time_advance_minutes"])

    if delta.get("build"):
        b = delta["build"]
        world.built_things.append(
            BuiltThing(
                x=p.x, y=p.y,
                type=b["type"],
                description=b["description"],
                tags=b.get("tags") or [],
            )
        )

    if farm_op:
        _apply_farm_op(world, farm_op)

    return (True, None)


# === 玩家移动（绕开 LLM）===


def try_move(world: World, dx: int, dy: int) -> tuple[bool, str | None]:
    p = world.player
    nx, ny = p.x + dx, p.y + dy
    if not (0 <= nx < world.island.width and 0 <= ny < world.island.height):
        return (False, "到了地图边缘")
    t = tile_at_effective(world, nx, ny)
    if not is_passable(t):
        return (False, "前面过不去")
    p.x, p.y = nx, ny
    cost = TERRAIN_COST[t] + WEATHER_MOVE_PENALTY.get(world.weather, 0)
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
    t = tile_at_effective(world, cx, cy)
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


def tile_at_effective(world: World, x: int, y: int) -> Terrain:
    """带 tile_overrides 的地形查询。O(1)。"""
    if x < 0 or y < 0 or x >= world.island.width or y >= world.island.height:
        return Terrain.OCEAN
    idx = y * world.island.width + x
    if idx in world.tile_overrides:
        return Terrain(world.tile_overrides[idx])
    return tile_at(world.island, x, y)


def current_terrain(world: World) -> Terrain:
    return tile_at_effective(world, world.player.x, world.player.y)


def _has_tag_nearby(
    tag: str,
    type_whitelist: tuple[str, ...],
    world: World,
    radius: int = 2,
) -> bool:
    """检查玩家是否处于有该 tag 的地标内，或附近 radius 格有带该 tag / 旧类型名的建造物。"""
    p = world.player
    if any(
        tag in lm.tags
        for lm in world.landmarks
        if (lm.x - p.x) ** 2 + (lm.y - p.y) ** 2 <= lm.radius ** 2
    ):
        return True
    return any(
        (tag in b.tags or b.type in type_whitelist)
        and abs(b.x - p.x) <= radius and abs(b.y - p.y) <= radius
        for b in world.built_things
    )


def has_fire_nearby(world: World, radius: int = 2) -> bool:
    return _has_tag_nearby(
        "fire",
        ("fire", "campfire", "bonfire", "火堆", "营火", "篝火"),
        world, radius,
    )


def has_shelter_nearby(world: World, radius: int = 2) -> bool:
    return _has_tag_nearby(
        "shelter",
        ("shelter", "hut", "lean_to", "tarp", "庇护所", "草棚", "简易棚", "帐篷", "遮蔽所"),
        world, radius,
    )


def _validate_farm(world: World, farm_op: dict) -> tuple[bool, str | None]:
    """校验农业操作，返回 (ok, reason)。"""
    action = farm_op.get("action")
    p = world.player

    if action == "plant":
        crop_type = farm_op.get("crop_type")
        if not crop_type:
            return (False, "种植需要指定作物类型")
        cfg = CROP_CONFIG.get(crop_type)
        if cfg is None:
            return (False, f"未知作物类型：{crop_type}")
        terrain = tile_at_effective(world, p.x, p.y)
        if terrain not in cfg["ok_terrains"]:
            from terrain import TERRAIN_NAMES
            return (False, f"{TERRAIN_NAMES.get(terrain, terrain)} 不适合种植 {crop_type}")
        stack = next((s for s in p.inventory if s.id == crop_type), None)
        if stack is None or stack.qty < 1:
            return (False, f"背包里没有 {crop_type}")
        # 同格已有作物不能重复种
        if any(c.x == p.x and c.y == p.y for c in world.crop_plots):
            return (False, "这一格已经有作物了")

    elif action == "water":
        water_ids = {"fresh_water", "coconut_water", "water_in_shell"}
        has_water = any(s.id in water_ids and s.qty >= 1 for s in p.inventory)
        if not has_water:
            return (False, "浇水需要背包中有淡水/椰汁/装水的椰壳")
        nearby = [c for c in world.crop_plots if abs(c.x - p.x) <= 3 and abs(c.y - p.y) <= 3]
        if not nearby:
            return (False, "附近 3 格内没有作物地块")

    elif action == "fertilize":
        fertilizer_ids = {"bone", "mud"}
        has_fert = any(s.id in fertilizer_ids and s.qty >= 1 for s in p.inventory)
        if not has_fert:
            return (False, "施肥需要背包中有骨头或泥土")
        nearby = [c for c in world.crop_plots if abs(c.x - p.x) <= 1 and abs(c.y - p.y) <= 1]
        if not nearby:
            return (False, "脚边 1 格内没有作物地块")
        if all(c.fertilized for c in nearby):
            return (False, "附近的作物已经施过肥了")

    elif action == "harvest":
        harvestable = [
            c for c in world.crop_plots
            if c.stage == 2 and abs(c.x - p.x) <= 3 and abs(c.y - p.y) <= 3
        ]
        if not harvestable:
            return (False, "附近 3 格内没有可收获的成熟作物")

    return (True, None)


def _apply_farm_op(world: World, farm_op: dict) -> list[dict]:
    """执行已校验通过的农业操作，返回收获物品列表（仅 harvest 时非空）。"""
    action = farm_op.get("action")
    p = world.player
    harvested: list[dict] = []

    if action == "plant":
        crop_type = farm_op["crop_type"]
        # 消耗背包里的种子/幼苗
        stack = next(s for s in p.inventory if s.id == crop_type)
        stack.qty -= 1
        p.inventory = [s for s in p.inventory if s.qty > 0]
        world.crop_plots.append(CropPlot(
            x=p.x, y=p.y,
            crop_type=crop_type,
            planted_day=world.day,
            last_watered_day=0,
            watered_count=0,
            fertilized=False,
            stage=0,
        ))

    elif action == "water":
        water_ids = {"fresh_water", "coconut_water", "water_in_shell"}
        # 消耗一单位水
        for s in p.inventory:
            if s.id in water_ids and s.qty >= 1:
                s.qty -= 1
                break
        p.inventory = [s for s in p.inventory if s.qty > 0]
        for c in world.crop_plots:
            if abs(c.x - p.x) <= 3 and abs(c.y - p.y) <= 3:
                c.last_watered_day = world.day
                c.watered_count += 1

    elif action == "fertilize":
        fertilizer_ids = {"bone", "mud"}
        for s in p.inventory:
            if s.id in fertilizer_ids and s.qty >= 1:
                s.qty -= 1
                break
        p.inventory = [s for s in p.inventory if s.qty > 0]
        nearby = [c for c in world.crop_plots if abs(c.x - p.x) <= 1 and abs(c.y - p.y) <= 1 and not c.fertilized]
        if nearby:
            nearby[0].fertilized = True

    elif action == "harvest":
        harvestable = [
            c for c in world.crop_plots
            if c.stage == 2 and abs(c.x - p.x) <= 3 and abs(c.y - p.y) <= 3
        ]
        for plot in harvestable:
            cfg = CROP_CONFIG.get(plot.crop_type, {})
            lo, hi = cfg.get("yield_qty", (1, 2))
            qty = random.randint(lo, hi)
            yield_id = cfg.get("yield_id", "wild_fruit")
            # 加入背包
            existing = next((s for s in p.inventory if s.id == yield_id), None)
            if existing:
                existing.qty += qty
            else:
                p.inventory.append(ItemStack(id=yield_id, qty=qty))
            harvested.append({"id": yield_id, "qty": qty})
        # 移除已收获的地块
        harvest_set = {(c.x, c.y) for c in harvestable}
        world.crop_plots = [c for c in world.crop_plots if (c.x, c.y) not in harvest_set]

    return harvested


def _validate_chop(world: World, chop_op: dict) -> tuple[bool, str | None]:
    """校验砍树操作。"""
    action = chop_op.get("action")
    if action != "chop":
        return (False, f"未知的砍树操作：{action}")
    p = world.player
    terrain = tile_at_effective(world, p.x, p.y)
    if terrain not in (Terrain.JUNGLE, Terrain.DEEP_JUNGLE):
        from terrain import TERRAIN_NAMES
        return (False, f"这里（{TERRAIN_NAMES.get(terrain, terrain)}）没有大树可以砍")
    return (True, None)
