"""单一存档：内存中的 World + SQLite 持久化。

World 中 island 和 landmarks 由 seed 决定，可重新生成。
我们只持久化「会变化」的部分：玩家、时间、库存、建造、探索图、地标描述、storyFlags。
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import math
import sqlite3
from dataclasses import asdict, dataclass

from .animals import (
    ANIMAL_CONTACT_RADIUS,
    AnimalRegistry,
    resolve_animal_interaction,
)
from .arrival import generate_landmark_description
from .items import item_by_id
from .judge import resolve_action
from .landmarks import landmark_at
from .search import SearchStore, check_tools_strict, take_from_pool
from .terrain import generate_island
from .world import (
    BuiltThing,
    GroundItem,
    ItemStack,
    Player,
    World,
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
    base.built_things = [BuiltThing(**b) for b in saved["built_things"]]
    # 向后兼容旧存档（没有 ground_items 字段）
    base.ground_items = [
        GroundItem(**g) for g in saved.get("ground_items", [])
    ]
    explored_bytes = base64.b64decode(saved["explored_b64"])
    base.explored = bytearray(explored_bytes)
    base.landmark_descriptions = saved["landmark_descriptions"]
    base.story_flags = saved["story_flags"]
    return base


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
        self.animals = AnimalRegistry(self.db)
        self.animals.seed(self.world)
        self.search_store = SearchStore(self.db)
        mark_explored(self.world, self.world.player.x, self.world.player.y, 2)
        reveal_around(self.world, self.world.player.x, self.world.player.y)

        # 后台正在为哪些地标生成 LLM 描述
        self._pending_arrival: set[str] = set()
        self._maybe_generate_arrival()

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

    def save(self) -> None:
        snap = json.dumps(_world_to_save(self.world), ensure_ascii=False)
        import time as _time
        self.db.execute(
            """INSERT INTO world_save (id, snapshot, saved_at) VALUES (1, ?, ?)
               ON CONFLICT(id) DO UPDATE SET snapshot = excluded.snapshot, saved_at = excluded.saved_at""",
            (snap, int(_time.time() * 1000)),
        )
        self.db.commit()

    def reset(self) -> None:
        self.world = initial_world()
        self.db.execute("DELETE FROM world_save WHERE id = 1")
        self.db.execute("DELETE FROM animals")
        self.db.execute("DELETE FROM landmark_search")
        self.db.commit()
        self.animals = AnimalRegistry(self.db)
        self.animals.seed(self.world)
        self.search_store = SearchStore(self.db)
        mark_explored(self.world, self.world.player.x, self.world.player.y, 2)
        reveal_around(self.world, self.world.player.x, self.world.player.y)
        self._pending_arrival.clear()
        self._maybe_generate_arrival()
        self.save()

    # === 玩家移动 ===
    def step(self, dx: int, dy: int) -> tuple[bool, str | None]:
        ok, reason = try_move(self.world, dx, dy)
        if ok:
            self.animals.wander(self.world)
            self._maybe_generate_arrival()
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

    def _search_status_text(self) -> str:
        """给 judge 看的「当前地标搜索状态」——只暴露 LLM 必须知道的最少信息。"""
        lm = landmark_at(self.world.landmarks, self.world.player.x, self.world.player.y)
        if lm is None or not lm.search_stages:
            return ""
        state = self.search_store.get(lm.id)
        next_idx = state.next_stage_index_in(lm.search_stages)
        done_count = len(state.completed_stages)
        total = len(lm.search_stages)
        if next_idx is None:
            return f"此地所有可搜索内容都已被玩家搜过（{total}/{total}）。再次搜索只会一无所获。"
        if done_count == 0 and next_idx not in state.remaining_pools:
            return (
                f"此地有可搜索阶段。玩家还没做任何搜索。"
                f"下一阶段索引 = {next_idx}（用于 search_intent.stage_index）。"
                f"\n注意：阶段的具体内容、工具需求、剩余数量都属于玩家应该自己发现的信息——"
                f"不要在 narration 里透露它们。"
            )
        return (
            f"此地有可搜索阶段。玩家已完成 {done_count}/{total} 个阶段。"
            f"下一阶段索引 = {next_idx}（用于 search_intent.stage_index）。"
            f"\n注意：阶段的具体内容、工具需求、剩余数量都属于玩家应该自己发现的信息——"
            f"不要在 narration 里透露它们。"
        )

    # === 动作判定 ===
    async def do_action(self, action: str) -> dict:
        search_status = self._search_status_text()
        # 构建附近地面物品列表传给 judge
        p = self.world.player
        nearby_ground = [
            {"x": g.x, "y": g.y, "id": g.id, "qty": g.qty}
            for g in self.world.ground_items
            if abs(g.x - p.x) <= 3 and abs(g.y - p.y) <= 3
        ]
        result = await resolve_action(
            self.world, action,
            search_status_text=search_status,
            nearby_ground_items=nearby_ground,
        )

        # 如果 LLM 标记了搜索意图，走结构化搜索
        if result.feasible and result.search_stage_index is not None:
            return self._apply_search(result, result.search_stage_index)

        if result.feasible:
            ok, reason = apply_delta(self.world, result.delta)
            if not ok:
                return {
                    "ok": False,
                    "narration": f"{result.narration}\n\n（但是：{reason}）",
                    "reasoning": result.reasoning,
                    "cost_ms": result.cost_ms,
                }
            self.animals.wander(self.world)
            self.save()
            return {
                "ok": True,
                "narration": result.narration,
                "reasoning": result.reasoning,
                "cost_ms": result.cost_ms,
            }
        return {
            "ok": False,
            "narration": result.narration,
            "reasoning": result.reasoning,
            "cost_ms": result.cost_ms,
        }

    def _apply_search(self, result, stage_idx: int) -> dict:
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
            # 宽松模式但需要工具——玩家必须说出方法
            tool_method = (result.search_tool_method or "").strip()
            if not tool_method or tool_method.lower() == "unspecified":
                return {
                    "ok": False,
                    "narration": result.narration,
                    "reasoning": "stage requires a specified method (lenient, silent)",
                    "cost_ms": result.cost_ms,
                }
        # else: required_tools 为空 + 非严格 → 徒手就行，无需 method

        # 从剩余池取物品（每次取少量，多次才清空）
        loot, pool_empty = take_from_pool(state, stage_idx, stage)

        from .world import WorldDelta as _WD
        delta: _WD = {
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
        self.animals.wander(self.world)
        self.save()

        # 这里仍然 append 收获——背包变化是玩家应该看到的反馈
        # 但去掉"（这里彻底搜空了。）"——让玩家自己注意到背包有东西，下次搜索时世界自己说话
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

        return {
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
        }

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
