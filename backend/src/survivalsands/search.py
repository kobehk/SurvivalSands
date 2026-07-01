"""地标的多阶段搜索系统。

设计：池子耗尽模型
- 每个 stage 有一个"物品池"——进入该阶段时**展开并实例化**所有物品
- 每次搜索：从剩余物品里取出 per_search_count 件，剩余的留着下次取
- 池子彻底空了 → stage 完成，再搜"已经没了"
- 这样玩家多搜几次就能拿到全部内容，而不是靠一次随机运气

持久化：SQLite landmark_search 表，存 state_json（含 remaining_pool）。
"""

from __future__ import annotations

import json
import random
import sqlite3
from dataclasses import dataclass, field

from .items import item_by_id


@dataclass
class LootEntry:
    """单条 loot：物品 id + 数量范围 + 该物品在池里出现几次（weight 决定概率）。"""

    item_id: str
    weight: int = 1     # 初始化池子时该物品出现的份数（=相对权重）
    qty_min: int = 1
    qty_max: int = 1


@dataclass
class SearchStage:
    """搜索的一个阶段。"""

    name: str
    description: str
    pool: list[LootEntry]             # 该阶段物品池的定义
    # 每次调用搜索能取出几件（建议 1-2，让玩家搜多次才清空）
    per_search_count: tuple[int, int] = (1, 2)
    required_tools: list[str] = field(default_factory=list)
    time_minutes: int = 15
    fatigue: int = 5
    consumes_landmark: bool = False
    tool_strict: bool = False
    tool_alternatives: list[str] = field(default_factory=list)


def _init_pool(stage: SearchStage, rng: random.Random) -> list[dict]:
    """把 SearchStage.pool 展开成实例化的物品列表（每个 LootEntry 按 weight 复制多份）。

    例：weight=3, qty_min=1, qty_max=2 → 生成 3 个 {id, qty} 条目（qty 随机 1-2）。
    这样池子一开始就有确定的内容，玩家靠多次搜索把它掏空。
    """
    items: list[dict] = []
    for entry in stage.pool:
        if item_by_id(entry.item_id) is None:
            continue  # 不在白名单，跳过
        for _ in range(entry.weight):
            qty = rng.randint(entry.qty_min, entry.qty_max)
            items.append({"id": entry.item_id, "qty": qty})
    rng.shuffle(items)  # 打乱顺序，每次取前 N 件
    return items


@dataclass
class LandmarkSearchState:
    landmark_id: str
    completed_stages: list[int]             # 已完成（池空）的 stage 索引
    # stage_idx → 剩余物品列表（每项 {id, qty}）
    # 进入某阶段时初始化；每次搜索从头取出 1-2 件并移除；空了才算完成
    remaining_pools: dict[int, list[dict]] = field(default_factory=dict)

    def is_stage_done(self, idx: int) -> bool:
        return idx in self.completed_stages

    def is_stage_pool_empty(self, idx: int) -> bool:
        return not self.remaining_pools.get(idx)

    def next_stage_index_in(self, stages: list) -> int | None:
        for i in range(len(stages)):
            if not self.is_stage_done(i):
                return i
        return None


class SearchStore:
    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db
        db.execute(
            """CREATE TABLE IF NOT EXISTS landmark_search (
                landmark_id TEXT PRIMARY KEY,
                state_json TEXT NOT NULL
            )"""
        )
        db.commit()

    def get(self, landmark_id: str) -> LandmarkSearchState:
        cur = self.db.execute(
            "SELECT state_json FROM landmark_search WHERE landmark_id = ?",
            (landmark_id,),
        )
        row = cur.fetchone()
        if row is None:
            return LandmarkSearchState(landmark_id=landmark_id, completed_stages=[])
        d = json.loads(row[0])
        return LandmarkSearchState(
            landmark_id=landmark_id,
            completed_stages=list(d.get("completed_stages", [])),
            remaining_pools={int(k): v for k, v in d.get("remaining_pools", {}).items()},
        )

    def save(self, state: LandmarkSearchState) -> None:
        payload = json.dumps({
            "completed_stages": state.completed_stages,
            "remaining_pools": {str(k): v for k, v in state.remaining_pools.items()},
        })
        self.db.execute(
            """INSERT INTO landmark_search (landmark_id, state_json) VALUES (?, ?)
               ON CONFLICT(landmark_id) DO UPDATE SET state_json = excluded.state_json""",
            (state.landmark_id, payload),
        )
        self.db.commit()

    def reset_all(self) -> None:
        self.db.execute("DELETE FROM landmark_search")
        self.db.commit()


def take_from_pool(
    state: LandmarkSearchState,
    stage_idx: int,
    stage: SearchStage,
    rng: random.Random | None = None,
) -> tuple[list[dict], bool]:
    """从阶段的剩余池里取出 per_search_count 件。

    如果池子还没初始化（第一次进这个阶段），先展开初始化。
    返回 (取出的物品列表, 取完后池子是否已空)。
    """
    rng = rng or random.Random()

    # 初始化池子（如果还没有）
    if stage_idx not in state.remaining_pools:
        state.remaining_pools[stage_idx] = _init_pool(stage, rng)

    pool = state.remaining_pools[stage_idx]
    if not pool:
        return [], True  # 已空

    lo, hi = stage.per_search_count
    n = min(rng.randint(lo, hi), len(pool))
    taken = pool[:n]
    state.remaining_pools[stage_idx] = pool[n:]

    pool_empty = len(state.remaining_pools[stage_idx]) == 0

    # 合并同类物品
    aggregated: dict[str, int] = {}
    for item in taken:
        aggregated[item["id"]] = aggregated.get(item["id"], 0) + item["qty"]
    result = [{"id": iid, "qty": q} for iid, q in aggregated.items()]

    return result, pool_empty


def check_tools_strict(
    player_inventory: list,
    required_tools: list[str],
    alternatives: list[str] | None = None,
) -> tuple[bool, str | None]:
    pool = list(required_tools) + list(alternatives or [])
    if not pool:
        return (True, None)
    inv_ids = {s.id for s in player_inventory}
    if any(t in inv_ids for t in pool):
        return (True, None)
    from .items import item_by_id as _ib
    names = [_ib(t).zh if _ib(t) else t for t in required_tools]
    return (False, f"需要先拥有：{'、'.join(names)}（任意一个）")


# 兼容旧名
check_tools = check_tools_strict
