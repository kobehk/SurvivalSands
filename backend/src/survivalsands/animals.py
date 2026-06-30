"""动物：玩家不直接对话，而是通过动作交互；动物的反应由 LLM 判定。

用 sqlite3 标准库持久化（每个动物 persona + state JSON）。
"""

from __future__ import annotations

import json
import math
import random
import sqlite3
from dataclasses import dataclass, field
from typing import Literal, TypedDict

from .llm import ToolDef, call_tool
from .prompts_shared import CHINESE_NARRATION_RULE, GIFT_ITEM_HINT, ITEM_USE_RULE
from .terrain import Terrain, is_passable, tile_at
from .world import World

Species = Literal["parrot", "monkey", "dog"]
ANIMAL_CONTACT_RADIUS = 4


@dataclass
class TrustThresholds:
    approach: int
    follow: int
    gift: int


@dataclass
class SpeciesTraits:
    fears_humans: int
    eats: list[str]
    can_carry: bool
    can_vocalize: bool
    behavior: str
    trust_thresholds: TrustThresholds


SPECIES_TRAITS: dict[Species, SpeciesTraits] = {
    "parrot": SpeciesTraits(
        fears_humans=50,
        eats=["coconut_meat", "wild_fruit", "seeds", "nuts"],
        can_carry=True,
        can_vocalize=True,
        behavior="好奇但敏捷，遇威胁立刻起飞。喜欢从枝头观察人类。可能模仿听到的两三个短词（hola、嘎），但不会对话。社会性中等——通常单飞，偶尔小群。聪明但注意力短。",
        trust_thresholds=TrustThresholds(approach=40, follow=75, gift=88),
    ),
    "monkey": SpeciesTraits(
        fears_humans=60,
        eats=["wild_fruit", "banana", "coconut_meat", "nuts", "seeds"],
        can_carry=True,
        can_vocalize=False,
        behavior="聪明、贪食、灵活，群居。会观察人类的动作并模仿（包括开椰子的方式）。低 trust 时会从树上扔东西、做威胁姿态；高 trust 时会偷东西然后躲到树上观察玩家反应。情绪起伏大。",
        trust_thresholds=TrustThresholds(approach=50, follow=80, gift=90),
    ),
    "dog": SpeciesTraits(
        fears_humans=30,
        eats=["fish_raw", "fish_cooked", "meat_raw", "meat_cooked", "bone"],
        can_carry=True,
        can_vocalize=False,
        behavior="记性好、忠诚，一旦建立信任就稳定。会通过摇尾、低吠、靠近坐下表达情绪。能记住对它好/不好的人类。擅长追踪气味，可能成为高 trust 时的好伙伴——但岛上有狗本身就奇怪（暗示之前来过其他人）。",
        trust_thresholds=TrustThresholds(approach=30, follow=60, gift=80),
    ),
}


@dataclass
class AnimalPersona:
    id: str
    species: Species
    name: str
    description: str
    shyness: int
    curiosity: int
    habitat: list[Terrain]


@dataclass
class AnimalState:
    trust: int
    fear: int
    hunger: int
    x: int
    y: int
    alive: bool
    last_seen_action: str | None
    last_seen_day: int


@dataclass
class Animal:
    persona: AnimalPersona
    state: AnimalState


@dataclass
class AnimalSeed:
    persona: AnimalPersona
    initial_trust: int
    initial_fear: int
    initial_hunger: int


INITIAL_ANIMAL_SEEDS: list[AnimalSeed] = [
    AnimalSeed(
        persona=AnimalPersona(
            id="parrot_red",
            species="parrot",
            name="红冠",
            description="一只红色冠羽的鹦鹉，绿色身体上有几道蓝色斑纹，左翼有一道旧伤疤。",
            shyness=40,
            curiosity=70,
            habitat=[Terrain.JUNGLE, Terrain.DEEP_JUNGLE],
        ),
        initial_trust=5,
        initial_fear=30,
        initial_hunger=50,
    ),
]


def _persona_to_json(p: AnimalPersona) -> str:
    return json.dumps(
        {
            "id": p.id,
            "species": p.species,
            "name": p.name,
            "description": p.description,
            "shyness": p.shyness,
            "curiosity": p.curiosity,
            "habitat": [int(t) for t in p.habitat],
        },
        ensure_ascii=False,
    )


def _persona_from_json(s: str) -> AnimalPersona:
    d = json.loads(s)
    return AnimalPersona(
        id=d["id"],
        species=d["species"],
        name=d["name"],
        description=d["description"],
        shyness=d["shyness"],
        curiosity=d["curiosity"],
        habitat=[Terrain(t) for t in d["habitat"]],
    )


def _state_to_json(s: AnimalState) -> str:
    return json.dumps(
        {
            "trust": s.trust,
            "fear": s.fear,
            "hunger": s.hunger,
            "x": s.x,
            "y": s.y,
            "alive": s.alive,
            "last_seen_action": s.last_seen_action,
            "last_seen_day": s.last_seen_day,
        },
        ensure_ascii=False,
    )


def _state_from_json(s: str) -> AnimalState:
    d = json.loads(s)
    return AnimalState(**d)


def _find_habitat_spawn(world: World, habitat: list[Terrain]) -> tuple[int, int]:
    candidates: list[tuple[int, int]] = []
    for y in range(world.island.height):
        for x in range(world.island.width):
            if tile_at(world.island, x, y) in habitat:
                candidates.append((x, y))
    if not candidates:
        return (world.player.x, world.player.y)
    return random.choice(candidates)


class AnimalRegistry:
    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db
        db.execute(
            """CREATE TABLE IF NOT EXISTS animals (
                id TEXT PRIMARY KEY,
                persona TEXT NOT NULL,
                state TEXT NOT NULL
            )"""
        )
        db.commit()

    def seed(self, world: World) -> None:
        cur = self.db.execute("SELECT COUNT(*) FROM animals")
        if cur.fetchone()[0] > 0:
            return
        for s in INITIAL_ANIMAL_SEEDS:
            x, y = _find_habitat_spawn(world, s.persona.habitat)
            state = AnimalState(
                trust=s.initial_trust,
                fear=s.initial_fear,
                hunger=s.initial_hunger,
                x=x,
                y=y,
                alive=True,
                last_seen_action=None,
                last_seen_day=1,
            )
            self.db.execute(
                "INSERT INTO animals (id, persona, state) VALUES (?, ?, ?)",
                (s.persona.id, _persona_to_json(s.persona), _state_to_json(state)),
            )
        self.db.commit()

    def all(self) -> list[Animal]:
        cur = self.db.execute("SELECT persona, state FROM animals")
        return [
            Animal(persona=_persona_from_json(p), state=_state_from_json(s))
            for p, s in cur.fetchall()
        ]

    def near(
        self, x: int, y: int, radius: int = ANIMAL_CONTACT_RADIUS
    ) -> list[Animal]:
        return [
            a
            for a in self.all()
            if a.state.alive and math.hypot(a.state.x - x, a.state.y - y) <= radius
        ]

    def get(self, animal_id: str) -> Animal | None:
        cur = self.db.execute(
            "SELECT persona, state FROM animals WHERE id = ?", (animal_id,)
        )
        row = cur.fetchone()
        if row is None:
            return None
        return Animal(persona=_persona_from_json(row[0]), state=_state_from_json(row[1]))

    def save_state(self, animal_id: str, state: AnimalState) -> None:
        self.db.execute(
            "UPDATE animals SET state = ? WHERE id = ?",
            (_state_to_json(state), animal_id),
        )
        self.db.commit()

    def wander(self, world: World) -> None:
        for a in self.all():
            if not a.state.alive:
                continue
            move_prob = 0.3 + a.state.fear / 200
            if random.random() < move_prob:
                steps = 2 if a.state.fear > 50 else 1
                for _ in range(steps):
                    dirs: list[tuple[int, int]] = [(-1, 0), (1, 0), (0, -1), (0, 1)]
                    if a.state.fear > 40:
                        # 远离玩家
                        dirs.sort(
                            key=lambda d: -math.hypot(
                                world.player.x - (a.state.x + d[0]),
                                world.player.y - (a.state.y + d[1]),
                            )
                        )
                    else:
                        random.shuffle(dirs)
                    moved = False
                    for dx, dy in dirs:
                        nx, ny = a.state.x + dx, a.state.y + dy
                        if not (0 <= nx < world.island.width and 0 <= ny < world.island.height):
                            continue
                        t = tile_at(world.island, nx, ny)
                        if not is_passable(t):
                            continue
                        if (
                            a.state.fear < 30
                            and t not in a.persona.habitat
                            and random.random() < 0.7
                        ):
                            continue
                        a.state.x = nx
                        a.state.y = ny
                        moved = True
                        break
                    if not moved:
                        break
            a.state.fear = max(0, a.state.fear - 5)
            a.state.hunger = min(100, a.state.hunger + 3)
            self.save_state(a.persona.id, a.state)


# === LLM 判定动物反应 ===

ANIMAL_INTERACTION_TOOL: ToolDef = {
    "name": "resolve_animal_reaction",
    "description": "根据玩家针对动物的动作，判定动物的反应：trust/fear 变化、是否离开、是否给予回报。",
    "input_schema": {
        "type": "object",
        "properties": {
            "narration": {
                "type": "string",
                "description": "描述动物的反应，第三人称，30-100 字。聚焦于动作、姿态、神态——动物不会说话（除了鹦鹉可能模仿短词）。",
            },
            "trust_change": {"type": "integer", "description": "trust 变化 -30 到 +20"},
            "fear_change": {"type": "integer", "description": "fear 变化 -30 到 +50"},
            "hunger_change": {"type": "integer", "description": "hunger 变化（动物吃了东西就降）-50 到 0"},
            "animal_flees": {"type": "boolean", "description": "动物是否被吓跑"},
            "animal_gives": {
                "type": "object",
                "description": "高信任时动物可能叼来/留下物品给玩家。低信任时禁用。",
                "properties": {
                    "item_id": {"type": "string"},
                    "qty": {"type": "integer", "minimum": 1},
                },
                "required": ["item_id", "qty"],
            },
        },
        "required": ["narration", "trust_change", "fear_change"],
    },
}


def _animal_system_prompt() -> str:
    return f"""你是一个生存游戏的「动物反应判定器」。玩家在一座荒岛上，会试图与野生动物互动。

=== 总原则 ===
- 动物**不会说话**（鹦鹉可能模仿一两个短词；其他物种只会发声不会语言）
- 反应基于：物种本性 + 个体特质（胆小度/好奇心）+ 当前状态（trust/fear/hunger）+ 玩家动作的威胁性
- 反应要**渐进**——只有真的把动物喂饱、长期接近才会建立深层信任。

=== 数值变化的方向（不是公式）===
你给出的 trust_change / fear_change / hunger_change 是**方向 + 幅度的判断**，不是死板的公式。
按下面的"方向感"自由出数，只要在 schema 限定范围内即可：

- 玩家温柔/缓慢/喂食/保持距离 → trust 小幅↑（个位数），fear 小幅↓
- 玩家移动太快/突然伸手/盯着看 → fear 小幅↑
- 玩家扔东西/吼叫/举棍/突然冲过去 → fear 急升（两位数），trust 跌
- 动物饿了对食物特别敏感（hunger 高时同样的喂食 trust 涨幅更明显）
- 已经被吓得很厉害的动物（fear 高），就算玩家做安抚的事，也不会立刻冷静——需要多次温和接触

不要追求每次给"刚好 +3"这种工整数字——根据情境的强弱给一个合适的数。
注意：trust 一次不要涨太多（除非玩家做了特别罕见的事），fear 可以猛涨也可以猛跌。

=== trust 阈值与互动解锁（按物种动态阈值）===
解锁阈值因物种而异，由 user message 中的「互动门槛」字段给出。
- 低于「接近门槛」：动物保持安全距离，看玩家的眼神就跑/飞 → animal_flees 通常 true
- 跨过「接近门槛」：可能停下来观察、靠近一两步、试探食物
- 跨过「跟随门槛」：可能跟着玩家走一段路；玩家挪位置时它会跟过来
- 跨过「赠礼门槛」：可能（不是必须）叼/留小东西给玩家

=== 关于赠礼（animal_gives）===
**赠礼是稀有事件**——同一只动物在玩家的整个游戏过程里只会发生几次，不要每次互动都给。
判断要不要赠礼：
- trust 必须**实打实跨过赠礼门槛**（不是刚好擦边），且
- 这次互动里玩家做了让动物特别愉快的事（喂食 / 长时间陪伴 / 玩家受伤后动物来探望），且
- 你掷个心理骰子：3 次中也就 1 次该给——大多数高 trust 互动都**不**给礼物
绝大多数互动 → **不要**填 animal_gives。

如果决定给：
{GIFT_ITEM_HINT}

=== 旁白风格 ===
- 第三人称，30-100 字。聚焦动作/姿态/神态/距离的变化
- 不要把动物拟人化成「它对你笑」、「它似乎理解了」——它们是动物
- 描写要**具体**：写「鹦鹉歪头侧眼瞄着椰肉」，不写「它显得很警惕」
- 让玩家从动物的**行为**推断它的状态变化，而不是直接告诉玩家「trust 涨了」

=== 通用旁白规范 ===
{ITEM_USE_RULE}

{CHINESE_NARRATION_RULE}"""


@dataclass
class AnimalInteractionResult:
    animal_id: str
    narration: str
    cost_ms: int


async def resolve_animal_interaction(
    world: World,
    registry: AnimalRegistry,
    animal_id: str,
    action: str,
) -> AnimalInteractionResult:
    animal = registry.get(animal_id)
    if animal is None:
        raise ValueError(f"未知动物: {animal_id}")
    traits = SPECIES_TRAITS[animal.persona.species]
    th = traits.trust_thresholds

    distance = round(math.hypot(animal.state.x - world.player.x, animal.state.y - world.player.y))
    inv_str = ", ".join(f"{i.id}x{i.qty}" for i in world.player.inventory) or "（空）"

    user_msg = f"""情境：第 {world.day} 天 {world.time}，天气 {world.weather}。
玩家位置：({world.player.x}, {world.player.y})
动物位置：({animal.state.x}, {animal.state.y})，距离 {distance} 格。

动物：{animal.persona.name}（{animal.persona.species}）
- 外观：{animal.persona.description}
- 个体特质：胆小度 {animal.persona.shyness}/100，好奇心 {animal.persona.curiosity}/100
- 物种通性：怕人 {traits.fears_humans}/100；喜欢吃 {"/".join(traits.eats)}（用中文）；{"能叼小物" if traits.can_carry else "不能叼东西"}；{"能模仿短词" if traits.can_vocalize else "不会发语言"}
- 物种行为：{traits.behavior}
- 互动门槛：接近 trust>{th.approach}，跟随 trust>{th.follow}，赠礼 trust>{th.gift}
- 当前状态：trust {animal.state.trust}/100, fear {animal.state.fear}/100, hunger {animal.state.hunger}/100
- 上次玩家对它做了什么：{animal.state.last_seen_action or "（第一次见到玩家）"}

玩家背包：{inv_str}

玩家动作：{action}"""

    result = await call_tool(
        system=_animal_system_prompt(),
        user=user_msg,
        tool=ANIMAL_INTERACTION_TOOL,
        max_tokens=600,
    )
    inp = result.input

    animal.state.trust = max(0, min(100, animal.state.trust + inp.get("trust_change", 0)))
    animal.state.fear = max(0, min(100, animal.state.fear + inp.get("fear_change", 0)))
    if inp.get("hunger_change"):
        animal.state.hunger = max(0, min(100, animal.state.hunger + inp["hunger_change"]))
    animal.state.last_seen_action = action
    animal.state.last_seen_day = world.day

    if inp.get("animal_flees"):
        # 朝远离玩家的方向挪 2 格
        for _ in range(2):
            dirs = [(-1, 0), (1, 0), (0, -1), (0, 1)]
            dirs.sort(
                key=lambda d: -math.hypot(
                    world.player.x - (animal.state.x + d[0]),
                    world.player.y - (animal.state.y + d[1]),
                )
            )
            for dx, dy in dirs:
                nx, ny = animal.state.x + dx, animal.state.y + dy
                if not (0 <= nx < world.island.width and 0 <= ny < world.island.height):
                    continue
                if not is_passable(tile_at(world.island, nx, ny)):
                    continue
                animal.state.x = nx
                animal.state.y = ny
                break

    registry.save_state(animal.persona.id, animal.state)

    return AnimalInteractionResult(
        animal_id=animal.persona.id,
        narration=inp.get("narration", ""),
        cost_ms=result.cost_ms,
    )
