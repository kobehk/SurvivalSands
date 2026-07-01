"""单一存档：内存中的 World + SQLite 持久化。

World 中 island 和 landmarks 由 seed 决定，可重新生成。
我们只持久化「会变化」的部分：玩家、时间、库存、建造、探索图、地标描述。
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import math
import sqlite3
import time
from dataclasses import asdict, dataclass

from .animals import (
    ANIMAL_CONTACT_RADIUS,
    AnimalRegistry,
    resolve_animal_interaction,
)
from .arrival import generate_landmark_description
from .death import generate_death_narration
from .items import item_by_id
from .items import calc_produce_qty as _calc_produce_qty
from .judge import ResolveResult, resolve_action
from .weather import fetch_real_weather
from .landmarks import landmark_at
from .search import SearchStore, check_tools_strict, take_from_pool
from .terrain import generate_island
from .world import (
    CROP_CONFIG,
    BuiltThing,
    CropPlot,
    GroundItem,
    ItemStack,
    Player,
    World,
    WorldDelta,
    _apply_farm_op,
    _validate_farm,
    apply_delta,
    initial_world,
    mark_explored,
    reveal_around,
    try_move,
)

logger = logging.getLogger(__name__)

ISLAND_SEED = 42


def _world_to_save(world: World) -> dict:
    return {
        "day": world.day,
        "time": world.time,
        "weather": world.weather,
        "player": {
            "hp": world.player.hp,
            "hunger": world.player.hunger,
            "thirst": world.player.thirst,
            "fatigue": world.player.fatigue,
            "x": world.player.x,
            "y": world.player.y,
            "skills": world.player.skills,
            "inventory": [{"id": s.id, "qty": s.qty} for s in world.player.inventory],
        },
        "built_things": [asdict(b) for b in world.built_things],
        "ground_items": [
            {"x": g.x, "y": g.y, "id": g.id, "qty": g.qty, "placed_day": g.placed_day}
            for g in world.ground_items
        ],
        "explored_b64": base64.b64encode(bytes(world.explored)).decode("ascii"),
        "landmark_descriptions": world.landmark_descriptions,
        "story_flags": world.story_flags,
        "discovered_recipes": world.discovered_recipes,
        "crop_plots": [asdict(c) for c in world.crop_plots],
    }


def _save_to_world(saved: dict) -> World:
    """从存档重建 World：island/landmarks 由 seed 重新生成。"""
    base = initial_world()  # 给 island、landmarks、wreck 落点
    p = saved["player"]
    base.day = saved["day"]
    base.time = saved["time"]
    base.weather = saved["weather"]
    base.player = Player(
        hp=p["hp"],
        hunger=p["hunger"],
        thirst=p["thirst"],
        fatigue=p["fatigue"],
        x=p["x"],
        y=p["y"],
        skills=p["skills"],
        inventory=[ItemStack(id=i["id"], qty=i["qty"]) for i in p["inventory"]],
    )
    base.built_things = [
        BuiltThing(
            x=b["x"], y=b["y"],
            type=b["type"],
            description=b["description"],
            tags=b.get("tags") or [],
        )
        for b in saved["built_things"]
    ]
    # 向后兼容旧存档（没有 ground_items 字段）
    base.ground_items = [
        GroundItem(**g) for g in saved.get("ground_items", [])
    ]
    explored_bytes = base64.b64decode(saved["explored_b64"])
    base.explored = bytearray(explored_bytes)
    base.landmark_descriptions = saved["landmark_descriptions"]
    base.story_flags = saved["story_flags"]
    base.discovered_recipes = saved.get("discovered_recipes", {})
    base.crop_plots = [CropPlot(**c) for c in saved.get("crop_plots", [])]
    return base


def _apply_volume_qty(delta: dict, skill_level: int = 0, clever: bool = False) -> None:
    """用体积守恒规则覆盖 LLM 给的产出数量，叠加技能系数和创意加成。"""
    produced = delta.get("produce_items") or []
    consumed = delta.get("consume_items") or []
    if not produced or not consumed:
        return
    for item in produced:
        item["qty"] = _calc_produce_qty(
            consumed, item["id"], item.get("qty", 1),
            skill_level=skill_level,
            clever=clever,
        )


class GameSession:
    def __init__(self, db_path: str = "./game.db") -> None:
        self.db_path = db_path
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode = WAL")
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS world_save (
                id INTEGER PRIMARY KEY,
                snapshot TEXT NOT NULL,
                saved_at INTEGER NOT NULL
            )"""
        )
        self.db.commit()

        self.world = self._load_or_init()
        self._reinit_world_state()

        # 后台正在为哪些地标生成 LLM 描述
        self._pending_arrival: set[str] = set()
        self._maybe_generate_arrival()
        # 天气刷新：换天时触发一次；_weather_day 记录上次拉取的游戏天数
        self._weather_day: int = self.world.day
        self._weather_task: asyncio.Task | None = None
        # 死亡叙事：hp<=0 时异步生成，前端拉到后清空
        self._death_narration: str | None = None
        self._game_over: bool = False

    def _load_or_init(self) -> World:
        cur = self.db.execute("SELECT snapshot FROM world_save WHERE id = 1")
        row = cur.fetchone()
        if row is None:
            return initial_world()
        try:
            saved = json.loads(row[0])
            return _save_to_world(saved)
        except Exception as e:
            logger.exception("存档读取失败，重新初始化: %s", e)
            return initial_world()

    def _reinit_world_state(self) -> None:
        """重建与 world 绑定的注册表并标记出生点视野。__init__/reset/_handle_death 共用。"""
        self.animals = AnimalRegistry(self.db)
        self.animals.seed(self.world)
        self.search_store = SearchStore(self.db)
        mark_explored(self.world, self.world.player.x, self.world.player.y, 2)
        reveal_around(self.world, self.world.player.x, self.world.player.y)

    def save(self) -> None:
        snap = json.dumps(_world_to_save(self.world), ensure_ascii=False)
        self.db.execute(
            """INSERT INTO world_save (id, snapshot, saved_at) VALUES (1, ?, ?)
               ON CONFLICT(id) DO UPDATE SET snapshot = excluded.snapshot, saved_at = excluded.saved_at""",
            (snap, int(time.time() * 1000)),
        )
        self.db.commit()

    def reset(self) -> None:
        self.world = initial_world()
        self.db.execute("DELETE FROM world_save WHERE id = 1")
        self.db.execute("DELETE FROM animals")
        self.db.execute("DELETE FROM landmark_search")
        self.db.commit()
        self._reinit_world_state()
        self._pending_arrival.clear()
        self._maybe_generate_arrival()
        self._death_narration = None
        self._game_over = False
        self.save()

    # === 玩家移动 ===
    def step(self, dx: int, dy: int) -> tuple[bool, str | None]:
        prev_day = self.world.day
        ok, reason = try_move(self.world, dx, dy)
        if ok:
            self.animals.wander(self.world)
            self._maybe_generate_arrival()
            if self.world.day != prev_day:
                self._tick_crops()
                self._maybe_update_weather()
            self.save()
        return ok, reason

    def _maybe_generate_arrival(self) -> None:
        """玩家踏入未生成描述的地标 → 后台触发 LLM 调用。"""
        lm = landmark_at(self.world.landmarks, self.world.player.x, self.world.player.y)
        if lm is None:
            return
        if lm.id in self.world.landmark_descriptions:
            return
        if lm.id in self._pending_arrival:
            return
        self._pending_arrival.add(lm.id)
        # fire and forget——返回的 task 不 await
        asyncio.create_task(self._do_generate_arrival(lm.id))

    def _maybe_update_weather(self) -> None:
        """换天时触发一次真实天气拉取（fire-and-forget）。同一天只拉一次。"""
        if self.world.day == self._weather_day:
            return
        if self._weather_task and not self._weather_task.done():
            return
        self._weather_day = self.world.day
        self._weather_task = asyncio.create_task(self._do_update_weather())

    async def _do_update_weather(self) -> None:
        try:
            result = await fetch_real_weather()
            if result is not None:
                self.world.weather = result
                self.save()
                logger.info("[weather] 第 %d 天天气更新为: %s", self.world.day, result)
        except Exception as e:
            logger.debug("[weather] 拉取失败，保持当前天气: %s", e)

    def _tick_crops(self) -> None:
        """换天时更新所有作物的生长阶段。"""
        for plot in self.world.crop_plots:
            cfg = CROP_CONFIG.get(plot.crop_type)
            if cfg is None:
                continue
            actual_age = self.world.day - plot.planted_day
            # 浇水加速：每次浇水最多减少天数上限为 days_to_mature//2
            water_bonus = min(plot.watered_count, cfg["days_to_mature"] // 2) * cfg["watered_day_bonus"]
            fert_bonus = cfg["fertilize_bonus"] if plot.fertilized else 0
            threshold = max(1, cfg["days_to_mature"] - water_bonus - fert_bonus)
            half = max(0, threshold // 2)
            if actual_age >= threshold:
                plot.stage = 2
            elif actual_age >= half:
                plot.stage = 1
            else:
                plot.stage = 0

    # === 死亡处理 ===
    def _infer_cause(self) -> str:
        p = self.world.player
        if p.hunger >= 100 and p.thirst >= 100:
            return "饥渴交加，油尽灯枯"
        if p.hunger >= 100:
            return "长期饥饿，体力耗尽"
        if p.thirst >= 100:
            return "严重脱水，口渴而死"
        if p.fatigue >= 100:
            return "极度疲惫，倒地不起"
        return "重伤不治"

    async def _handle_death(self) -> None:
        """软死亡：保留探索图、把背包部分物品埋到地面、LLM 生成遗骸叙事、重置玩家状态。"""
        import random as _random

        p = self.world.player
        cause = self._infer_cause()

        # 随机选最多 3 种物品留在死亡坐标
        relics: list[dict] = []
        candidates = list(p.inventory)
        _random.shuffle(candidates)
        for stack in candidates[:3]:
            relics.append({"id": stack.id, "qty": stack.qty})
            # 放到地面
            from .world import GroundItem
            existing = next(
                (g for g in self.world.ground_items if g.id == stack.id and g.x == p.x and g.y == p.y),
                None,
            )
            if existing:
                existing.qty += stack.qty
            else:
                self.world.ground_items.append(
                    GroundItem(x=p.x, y=p.y, id=stack.id, qty=stack.qty, placed_day=self.world.day)
                )

        # 死亡惩罚：地面物品清理
        # - 5 格内：全部清空（死在仓库旁边救不了你）
        # - 5 格外：仅清当天放下的（死前刷仓无效，长期经营的营地保留）
        DEATH_RADIUS = 5
        self.world.ground_items = [
            g for g in self.world.ground_items
            if math.hypot(g.x - p.x, g.y - p.y) > DEATH_RADIUS
            and g.placed_day != self.world.day
        ]

        # 保留探索图（bytearray 原地复用）
        saved_explored = bytearray(self.world.explored)
        saved_ground = list(self.world.ground_items)
        saved_descriptions = dict(self.world.landmark_descriptions)
        saved_story_flags = dict(self.world.story_flags)
        saved_recipes = dict(self.world.discovered_recipes)

        # 生成遗骸叙事（用死亡时的 world 状态）
        try:
            narration = await generate_death_narration(self.world, cause, relics)
        except Exception as e:
            logger.exception("[death] LLM 叙事生成失败: %s", e)
            narration = f"第 {self.world.day} 天，一个漂流者在这里倒下了，再也没有起来。"

        # 软重置：重建玩家，保留世界记忆
        new_world = initial_world()
        # 死亡惩罚：重生时虚弱，防止通过故意死亡刷状态
        new_world.player.hp = 70
        new_world.player.hunger = 60
        new_world.player.thirst = 50
        new_world.player.fatigue = 50
        new_world.explored = saved_explored
        new_world.ground_items = saved_ground
        new_world.landmark_descriptions = saved_descriptions
        new_world.story_flags = saved_story_flags
        new_world.discovered_recipes = saved_recipes
        self.world = new_world
        self._reinit_world_state()
        self._pending_arrival.clear()
        self._weather_day = self.world.day

        self._game_over = True
        self._death_narration = narration
        self.save()
        logger.info("[death] 玩家死亡（%s），遗物 %s", cause, relics)

    def _maybe_record_recipe(self, delta: dict) -> None:
        """LLM 成功将材料转化为新物品时，记录配方到 discovered_recipes。"""
        consumed = delta.get("consume_items") or []
        produced = delta.get("produce_items") or []
        if not consumed or not produced:
            return
        # 按 id 排序保证相同材料组合的 key 唯一
        key = "|".join(f"{c['id']}:{c['qty']}" for c in sorted(consumed, key=lambda x: x["id"]))
        if key in self.world.discovered_recipes:
            return
        self.world.discovered_recipes[key] = {
            "inputs": {c["id"]: c["qty"] for c in sorted(consumed, key=lambda x: x["id"])},
            "outputs": {p["id"]: p["qty"] for p in produced},
        }
        logger.info("[recipe] 发现配方: %s → %s", key, produced)

    def _format_recipes(self) -> str:
        """把 discovered_recipes 格式化成玩家可读的中文字符串。"""
        recipes = self.world.discovered_recipes
        if not recipes:
            return "你还没有摸索出任何制作方法。试试用材料做点什么吧。"
        lines = ["你目前摸索出的制作方法：\n"]
        for entry in recipes.values():
            inputs_str = "、".join(
                f"{(item_by_id(k).zh if item_by_id(k) else k)}×{v}"
                for k, v in entry["inputs"].items()
            )
            outputs_str = "、".join(
                f"{(item_by_id(k).zh if item_by_id(k) else k)}×{v}"
                for k, v in entry["outputs"].items()
            )
            lines.append(f"· {inputs_str}  →  {outputs_str}")
        return "\n".join(lines)

    async def _do_generate_arrival(self, lm_id: str) -> None:
        try:
            lm = next(l for l in self.world.landmarks if l.id == lm_id)
            text = await generate_landmark_description(self.world, lm)
            self.world.landmark_descriptions[lm_id] = text
            self.save()
            logger.info("[arrival] %s (%d 字)", lm_id, len(text))
        except Exception as e:
            logger.exception("[arrival] %s 生成失败: %s", lm_id, e)
        finally:
            self._pending_arrival.discard(lm_id)

    async def _read_bottle_message(self) -> dict:
        """读取背包里的瓶中信——LLM 生成内容，消耗一封，保留玻璃瓶。"""
        # 已读过同一封信就直接返回缓存内容，不重复生成
        cached = self.world.story_flags.get("bottle_message_content")
        if cached:
            narration = f"你再次打开那张皱巴巴的纸条，上面的字迹依然清晰：\n\n{cached}"
            return {"ok": True, "narration": narration, "cost_ms": 0}

        from .bottle import generate_bottle_message
        t0 = time.perf_counter()
        try:
            content = await generate_bottle_message(self.world)
        except Exception as e:
            logger.exception("[bottle] LLM 生成失败: %s", e)
            content = "纸条上的字迹已经被海水浸透，只剩下几个依稀可辨的词：「……还活着……求救……」"
        cost_ms = int((time.perf_counter() - t0) * 1000)

        # 消耗一封信，留下玻璃瓶
        p = self.world.player
        stack = next((s for s in p.inventory if s.id == "bottle_message"), None)
        if stack:
            stack.qty -= 1
            if stack.qty <= 0:
                p.inventory = [s for s in p.inventory if s.id != "bottle_message"]
            # 加回玻璃瓶
            bottle = next((s for s in p.inventory if s.id == "glass_bottle"), None)
            if bottle:
                bottle.qty += 1
            else:
                from .world import ItemStack
                p.inventory.append(ItemStack(id="glass_bottle", qty=1))

        # 缓存内容到 story_flags，死亡后也保留
        self.world.story_flags["bottle_message_content"] = content
        self.world.story_flags["bottle_message_read"] = True
        self.save()

        narration = f"你小心地展开那张泛黄的纸条，上面写着：\n\n{content}\n\n（玻璃瓶留在了你手里）"
        return {"ok": True, "narration": narration, "cost_ms": cost_ms}

    def _search_status_text(self) -> str:
        lm = landmark_at(self.world.landmarks, self.world.player.x, self.world.player.y)
        if lm is None or not lm.search_stages:
            return ""
        state = self.search_store.get(lm.id)
        next_idx = state.next_stage_index_in(lm.search_stages)
        done_count = len(state.completed_stages)
        total = len(lm.search_stages)
        if next_idx is None:
            return f"已全部搜完（{total}/{total}）"
        if done_count == 0 and next_idx not in state.remaining_pools:
            return f"可搜索，下一阶段={next_idx}"
        return f"可搜索，已完成{done_count}/{total}，下一阶段={next_idx}"

    # === 动作判定 ===
    def _try_quick_response(self, action: str) -> dict | None:
        """不走 LLM 的快速响应。匹配到关键词就返回结果，否则返回 None。"""
        if any(kw in action for kw in ("学会了什么", "我会做什么", "制作清单", "配方", "我学会")):
            return {"ok": True, "narration": self._format_recipes(), "cost_ms": 0}
        if any(kw in action for kw in ("读", "看", "打开", "阅读")) and any(
            kw in action for kw in ("瓶中信", "信", "纸条", "漂流瓶")
        ):
            if any(s.id == "bottle_message" for s in self.world.player.inventory):
                return None  # 留给调用方 await _read_bottle_message
        return None

    def _build_judge_context(self) -> dict:
        """构建传给 resolve_action 的附加上下文。"""
        p = self.world.player
        return {
            "search_status_text": self._search_status_text(),
            "nearby_ground_items": [
                {"x": g.x, "y": g.y, "id": g.id, "qty": g.qty}
                for g in self.world.ground_items
                if abs(g.x - p.x) <= 3 and abs(g.y - p.y) <= 3
            ],
            "crop_plots_text": self._crop_plots_text(),
        }

    def _result_dict(self, ok: bool, result, extra: str = "") -> dict:
        """从 ResolveResult 生成统一的返回字典。"""
        narration = result.narration + (f"\n\n{extra}" if extra else "")
        return {
            "ok": ok,
            "narration": narration,
            "reasoning": result.reasoning,
            "cost_ms": result.cost_ms,
        }

    async def _apply_normal_action(self, result: ResolveResult, prev_day: int) -> dict:
        """普通可行动作：应用 delta、触发副作用、存档。"""
        _apply_volume_qty(
            result.delta,
            skill_level=self.world.player.skills.get("crafting", 0),
            clever=(result.craft_quality == "clever"),
        )
        ok, reason = apply_delta(self.world, result.delta)
        if not ok:
            return self._result_dict(False, result, f"（但是：{reason}）")
        self._post_action_effects(prev_day)
        if self.world.player.hp <= 0:
            await self._handle_death()
        self._maybe_record_recipe(result.delta)
        self.save()
        return self._result_dict(True, result)

    def _post_action_effects(self, prev_day: int) -> None:
        """每次成功动作后的共同副作用：动物游走、换天处理。"""
        self.animals.wander(self.world)
        if self.world.day != prev_day:
            self._tick_crops()
            self._maybe_update_weather()

    async def do_action(self, action: str) -> dict:
        # 瓶中信单独处理（有专属叙事 LLM）
        if any(kw in action for kw in ("读", "看", "打开", "阅读")) and any(
            kw in action for kw in ("瓶中信", "信", "纸条", "漂流瓶")
        ):
            if any(s.id == "bottle_message" for s in self.world.player.inventory):
                return await self._read_bottle_message()

        # 配方查询不走 LLM
        if any(kw in action for kw in ("学会了什么", "我会做什么", "制作清单", "配方", "我学会")):
            return {"ok": True, "narration": self._format_recipes(), "cost_ms": 0}

        prev_day = self.world.day
        ctx = self._build_judge_context()
        result = await resolve_action(self.world, action, **ctx)

        if result.feasible and result.search_stage_index is not None:
            return await self._apply_search(result, result.search_stage_index, prev_day)
        if result.feasible and result.farm_action:
            return await self._apply_farm_action(result, prev_day)
        if result.feasible:
            return await self._apply_normal_action(result, prev_day)
        return self._result_dict(False, result)

    def _crop_plots_text(self) -> str:
        """生成附近 5 格内的作物状态文本，供 LLM 上下文使用。"""
        p = self.world.player
        nearby = [
            c for c in self.world.crop_plots
            if abs(c.x - p.x) <= 5 and abs(c.y - p.y) <= 5
        ]
        if not nearby:
            return "（附近无作物）"
        stage_names = {0: "萌芽中", 1: "生长中", 2: "可收获"}
        crop_zh = {"seeds": "种子", "banana_seedling": "香蕉幼苗"}
        lines = []
        for c in nearby:
            stage = stage_names.get(c.stage, "未知")
            name = crop_zh.get(c.crop_type, c.crop_type)
            water_hint = f"浇水{c.watered_count}次" if c.watered_count else "未浇水"
            fert_hint = "，已施肥" if c.fertilized else ""
            lines.append(f"- ({c.x},{c.y}) {name} [{stage}] 第{c.planted_day}天种，{water_hint}{fert_hint}")
        return "\n".join(lines)

    async def _apply_farm_action(self, result: ResolveResult, prev_day: int) -> dict:
        """LLM 标记了农业操作 → 校验 + 执行 + 推时间。"""
        farm_op = result.farm_action

        ok, reason = _validate_farm(self.world, farm_op)
        if not ok:
            return {
                "ok": False,
                "narration": result.narration,
                "reasoning": f"farm validation failed: {reason}",
                "cost_ms": result.cost_ms,
            }

        # 推进时间（农业操作有时间消耗）
        time_map = {"plant": 15, "water": 10, "fertilize": 10, "harvest": 20}
        time_delta: WorldDelta = {"time_advance_minutes": time_map.get(farm_op.get("action", ""), 10)}
        apply_delta(self.world, time_delta)

        harvested = _apply_farm_op(self.world, farm_op)
        self._post_action_effects(prev_day)
        self.save()

        action = farm_op.get("action")
        narration = result.narration
        if action == "harvest" and harvested:
            loot_str = "、".join(
                f"{(item_by_id(h['id']).zh if item_by_id(h['id']) else h['id'])}×{h['qty']}"
                for h in harvested
            )
            narration = f"{narration}\n\n收获：{loot_str}"

        return {
            "ok": True,
            "narration": narration,
            "reasoning": f"farm:{action}",
            "cost_ms": result.cost_ms,
        }

    async def _apply_search(self, result: ResolveResult, stage_idx: int, prev_day: int = -1) -> dict:
        """LLM 说玩家在搜索 → 校验 + 抽 loot + 推时间 + 写存档。

        注意：不在 narration 后追加任何"系统提示"括号——LLM 已被要求只描写感官，
        不引导玩家。我们若再追加"（需要 X）"或"（这步做过了）"就破坏了沉浸感。
        """
        lm = landmark_at(self.world.landmarks, self.world.player.x, self.world.player.y)
        if lm is None or not lm.search_stages:
            # LLM 误判——没东西可搜。当作普通失败动作返回 LLM 的原 narration
            return {
                "ok": False,
                "narration": result.narration,
                "reasoning": "LLM marked search_intent but landmark has no stages",
                "cost_ms": result.cost_ms,
            }
        if stage_idx < 0 or stage_idx >= len(lm.search_stages):
            return {
                "ok": False,
                "narration": result.narration,
                "reasoning": f"stage_index {stage_idx} out of range",
                "cost_ms": result.cost_ms,
            }

        state = self.search_store.get(lm.id)
        # 已完成的阶段：不再产出 loot；narration 用 LLM 的"翻了半天只摸到湿沙"那段
        if state.is_stage_done(stage_idx):
            return {
                "ok": True,
                "narration": result.narration,
                "reasoning": f"stage {stage_idx} already done (silent)",
                "cost_ms": result.cost_ms,
            }
        # 跳级：feasible=false 由 LLM 描述"船板钉得很死"
        next_idx = state.next_stage_index_in(lm.search_stages)
        if next_idx is not None and stage_idx > next_idx:
            return {
                "ok": False,
                "narration": result.narration,
                "reasoning": f"skipped to stage {stage_idx}, next is {next_idx}",
                "cost_ms": result.cost_ms,
            }

        stage = lm.search_stages[stage_idx]

        # 工具/方法校验：双轨制
        # 1) tool_strict=True：必须背包里真有 required_tools 或 alternatives 之一（拆船龙骨这种）
        # 2) tool_strict=False + required_tools 非空：玩家必须说出**具体方法**（unspecified 不通过）
        # 3) tool_strict=False + required_tools 为空：徒手即可（unspecified 也通过）——表面翻找
        if stage.tool_strict:
            ok_tools, _reason = check_tools_strict(
                self.world.player.inventory,
                stage.required_tools,
                stage.tool_alternatives,
            )
            if not ok_tools:
                return {
                    "ok": False,
                    "narration": result.narration,
                    "reasoning": "required tools missing (strict, silent)",
                    "cost_ms": result.cost_ms,
                }
        elif stage.required_tools:
            # 宽松模式但需要工具——玩家必须说出方法，且背包里要有至少一件匹配的工具
            tool_method = (result.search_tool_method or "").strip()
            if not tool_method or tool_method.lower() == "unspecified":
                return {
                    "ok": False,
                    "narration": result.narration,
                    "reasoning": "stage requires a specified method (lenient, silent)",
                    "cost_ms": result.cost_ms,
                }
            all_tools = list(stage.required_tools) + list(stage.tool_alternatives)
            inv_ids = {s.id for s in self.world.player.inventory}
            if not any(t in inv_ids for t in all_tools):
                return {
                    "ok": False,
                    "narration": result.narration,
                    "reasoning": "lenient mode: player lacks any required tool in inventory",
                    "cost_ms": result.cost_ms,
                }
        # else: required_tools 为空 + 非严格 → 徒手就行，无需 method

        # 从剩余池取物品（每次取少量，多次才清空）
        loot, pool_empty = take_from_pool(state, stage_idx, stage)

        delta: WorldDelta = {
            "produce_items": loot,
            "time_advance_minutes": stage.time_minutes,
            "fatigue_change": stage.fatigue,
        }
        ok, _ = apply_delta(self.world, delta)
        if not ok:
            return {
                "ok": False,
                "narration": result.narration,
                "reasoning": "apply_delta failed",
                "cost_ms": result.cost_ms,
            }

        # 只有池子彻底空了，才标记 stage 完成
        if pool_empty:
            state.completed_stages.append(stage_idx)
        self.search_store.save(state)
        self._post_action_effects(prev_day)
        if self.world.player.hp <= 0:
            await self._handle_death()
        self.save()

        loot_summary = self._format_loot(loot)
        return {
            "ok": True,
            "narration": f"{result.narration}\n\n收获：{loot_summary}",
            "reasoning": f"search stage {stage_idx} ({stage.name})",
            "cost_ms": result.cost_ms,
        }

    @staticmethod
    def _format_loot(loot: list[dict]) -> str:
        if not loot:
            return "什么都没找到。"
        parts: list[str] = []
        for entry in loot:
            it = item_by_id(entry["id"])
            zh = it.zh if it else entry["id"]
            parts.append(f"{zh}×{entry['qty']}")
        return "、".join(parts)

    async def interact_animal(self, animal_id: str, action: str) -> dict:
        animal = self.animals.get(animal_id)
        if animal is None:
            return {"ok": False, "narration": f"没有这只动物：{animal_id}", "cost_ms": 0}
        dist = math.hypot(
            animal.state.x - self.world.player.x,
            animal.state.y - self.world.player.y,
        )
        if dist > ANIMAL_CONTACT_RADIUS:
            return {
                "ok": False,
                "narration": f"{animal.persona.name}已经离开你的视野了。",
                "cost_ms": 0,
            }
        r = await resolve_animal_interaction(self.world, self.animals, animal_id, action)
        self.save()
        return {
            "ok": True,
            "narration": r.narration,
            "cost_ms": r.cost_ms,
            "animal_name": animal.persona.name,
        }

    # === 给前端的快照 ===
    def snapshot(self) -> dict:
        w = self.world
        animals_near = [
            {
                "id": a.persona.id,
                "name": a.persona.name,
                "species": a.persona.species,
                "description": a.persona.description,
                "x": a.state.x,
                "y": a.state.y,
                "trust": a.state.trust,
                "fear": a.state.fear,
            }
            for a in self.animals.near(w.player.x, w.player.y)
        ]
        lm = landmark_at(w.landmarks, w.player.x, w.player.y)

        # 注：搜索进度只在后端 + LLM 之间流转，不暴露给前端 UI——让玩家自己摸索
        # （仍然通过 LLM 的旁白做软引导："这一步搜过了"/"试试撬开"）

        # 玩家 3 格内的地面物品（合并同坐标同物品）
        nearby_ground: dict[tuple[int, int, str], int] = {}
        for g in w.ground_items:
            if abs(g.x - w.player.x) <= 3 and abs(g.y - w.player.y) <= 3:
                key = (g.x, g.y, g.id)
                nearby_ground[key] = nearby_ground.get(key, 0) + g.qty
        nearby_ground_list = [
            {"x": x, "y": y, "id": item_id, "qty": qty}
            for (x, y, item_id), qty in nearby_ground.items()
        ]

        result = {
            "day": w.day,
            "time": w.time,
            "weather": w.weather,
            "player": {
                "hp": w.player.hp,
                "hunger": w.player.hunger,
                "thirst": w.player.thirst,
                "fatigue": w.player.fatigue,
                "x": w.player.x,
                "y": w.player.y,
                "skills": w.player.skills,
                "inventory": [{"id": s.id, "qty": s.qty} for s in w.player.inventory],
            },
            "builtThings": [asdict(b) for b in w.built_things],
            "animalsNear": animals_near,
            "storyFlags": w.story_flags,
            "currentLandmarkId": lm.id if lm else None,
            "currentLandmarkArrival": w.landmark_descriptions.get(lm.id) if lm else None,
            "arrivalPending": (lm.id in self._pending_arrival) if lm else False,
            "nearbyGroundItems": nearby_ground_list,
            "gameOver": self._game_over,
            "deathNarration": self._death_narration,
            "cropPlots": [
                {
                    "x": c.x, "y": c.y,
                    "crop_type": c.crop_type,
                    "stage": c.stage,
                    "planted_day": c.planted_day,
                    "watered_count": c.watered_count,
                    "fertilized": c.fertilized,
                }
                for c in w.crop_plots
            ],
        }
        # 前端拿到 game_over 后清空，避免每次 poll 都触发
        if self._game_over:
            self._game_over = False
            self._death_narration = None
        return result

    def map_info(self) -> dict:
        w = self.world
        return {
            "width": w.island.width,
            "height": w.island.height,
            "tilesB64": base64.b64encode(bytes(w.island.tiles)).decode("ascii"),
            "landmarks": [
                {"id": l.id, "name": l.name, "x": l.x, "y": l.y, "radius": l.radius}
                for l in w.landmarks
            ],
            "exploredB64": base64.b64encode(bytes(w.explored)).decode("ascii"),
        }
