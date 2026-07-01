"""LLM 判定层：玩家自然语言动作 → WorldDelta + 旁白。"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .landmarks import nearest_landmarks
from .llm import ToolDef, call_tool
from .prompts_shared import CHINESE_NARRATION_RULE, ITEM_USE_RULE, item_id_rule_full
from .terrain import TERRAIN_NAMES
from .world import (
    World,
    WorldDelta,
    current_landmark,
    current_terrain,
    describe_player_state,
    has_fire_nearby,
    has_shelter_nearby,
)

ACTION_TOOL: ToolDef = {
    "name": "resolve_action",
    "description": "判定玩家在当前位置做某件事是否可行，并给出消耗、产出、时间消耗与旁白。如果不可行，feasible=false 并通过 narration 告诉玩家差什么。",
    "input_schema": {
        "type": "object",
        "properties": {
            "feasible": {
                "type": "boolean",
                "description": "动作是否可行。缺前置物品/位置不对/物理上不可能 → false。",
            },
            "reasoning": {
                "type": "string",
                "description": "一句话内部判定理由（≤30 字，不会显示给玩家）。务必简短。",
            },
            "narration": {
                "type": "string",
                "description": "直接显示给玩家的中文旁白，50-150 字，第二人称（你）。",
            },
            "consume_items": {
                "type": "array",
                "description": "消耗的物品（仅 feasible=true 时使用）。物品 id 见系统提示中的物品清单。",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "qty": {"type": "integer", "minimum": 1},
                    },
                    "required": ["id", "qty"],
                },
            },
            "produce_items": {
                "type": "array",
                "description": "产出的物品（仅 feasible=true 时使用）。qty 不用填，系统按体积规则自动计算。",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "qty": {"type": "integer", "minimum": 1},
                    },
                    "required": ["id"],
                },
            },
            "drop_items": {
                "type": "array",
                "description": "从背包放到地面（当前坐标）。「我把 X 放在这里/地上」时用，不要用 consume_items。",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "qty": {"type": "integer", "minimum": 1},
                    },
                    "required": ["id", "qty"],
                },
            },
            "pick_up_items": {
                "type": "array",
                "description": "从地面捡入背包。只能捡情境「附近地面物品」里实际存在的东西。",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "qty": {"type": "integer", "minimum": 1},
                    },
                    "required": ["id", "qty"],
                },
            },
            "hp_change": {"type": "integer", "description": "生命值变化（-100 到 100）"},
            "hunger_change": {"type": "integer", "description": "饥饿值变化（-100 到 100），吃东西用负数"},
            "thirst_change": {"type": "integer", "description": "口渴值变化（-100 到 100），喝水用负数"},
            "fatigue_change": {"type": "integer", "description": "疲劳值变化（-100 到 100），休息用负数"},
            "skill_gain": {
                "type": "object",
                "description": "技能涨点。键是技能名（crafting/foraging/fishing/...），值是 1-3。",
                "additionalProperties": {"type": "integer"},
            },
            "time_minutes": {
                "type": "integer",
                "minimum": 0,
                "description": "动作消耗的时间（分钟）。短动作 5-15，中等 30-60，长 120+。",
            },
            "build": {
                "type": "object",
                "description": "产出的是建造物时使用。会建在玩家当前坐标。",
                "properties": {
                    "type": {"type": "string"},
                    "description": {"type": "string"},
                    "tags": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["shelter", "fire", "storage"],
                        },
                        "description": "功能标签（可多选，无功能则留空）：shelter=能遮风挡雨；fire=持续火源；storage=用于存放物品。",
                    },
                },
                "required": ["type", "description"],
            },
            "search_intent": {
                "type": "object",
                "description": "玩家在搜索/翻找/拆解有可搜索阶段的地标时填写。系统处理实际产出，不要填 produce_items。",
                "properties": {
                    "stage_index": {
                        "type": "integer",
                        "minimum": 0,
                        "description": "情境给出的下一阶段索引",
                    },
                    "tool_method": {
                        "type": "string",
                        "description": "玩家描述的方法（「用铁钉撬」「用石头砸」「徒手」）；未说明填 'unspecified'。",
                    },
                },
                "required": ["stage_index"],
            },
            "farm": {
                "type": "object",
                "description": "农业操作：种植/浇水/施肥/收获。填此字段后不要填 consume_items/produce_items，资源由系统处理。",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["plant", "water", "fertilize", "harvest"],
                        "description": "plant=种植当前格, water=浇水3格内所有作物, fertilize=施肥1格内作物, harvest=收获3格内成熟作物",
                    },
                    "crop_type": {
                        "type": "string",
                        "enum": ["seeds", "banana_seedling"],
                        "description": "种植时需指定作物类型",
                    },
                },
                "required": ["action"],
            },
            "craft_quality": {
                "type": "string",
                "enum": ["normal", "clever"],
                "description": "制作/加工类动作时填。clever = 玩家描述了具体技法（「交叉编织」「刮薄骨头」）；normal = 普通操作。",
            },
        },
        "required": ["feasible", "reasoning", "narration"],
    },
}


def _build_system_prompt() -> str:
    return f"""你是一个开放世界生存游戏的判定引擎。游戏背景是一个无人小岛，玩家是独自漂流上来的幸存者。根据玩家的自由动作描述，判定它在当前情境下是否合理可行，给出物理上合理的消耗、产出、时间花费和旁白。

=== 移动指令 ===
「移动」由系统直接处理，不走你这里。纯移动请求（「我去 X」「我走到丛林」）→ feasible=false，narration 简短提示「想换地方就自己走过去」。
「移动+动作」复合指令（「走到水边喝水」）→ 当作在当前位置做该动作；距离太远就 feasible=false。

=== 物理常识 ===
- 椰子需破壳（石头砸/锐物撬）才能取椰肉和椰汁
- 海水不能饮用；淡水来自泉水/雨水/河流/植物汁液
- 生火三要素：火种 + 干燥火绒 + 木柴，三者缺一不可
- 徒手可做：捡、搬、砸、攀爬、撕扯；制作工具需要更基础的工具
- 生鱼/生肉一天腐败，除非烟熏/晒干/盐腌
- 夜晚视线差、体温低，需要遮蔽和火堆

=== 天气与建造物效果 ===
情境会给出天气（clear/cloudy/rain/storm）、「附近有无火堆」、「附近有无庇护所」。

**生火**：rain → 需要庇护所，无则 feasible=false；storm → 即使有庇护所也极难（山洞/崖底除外）。
**雨天集水**：有容器（椰壳/碗/瓶）可收集雨水；无容器效率极差。
**storm 行动**：移动/攀爬/砍伐有 hp 惩罚，feasible 谨慎判断。
**行动消耗**：天气越差 fatigue_change 越高，尤其是长时间户外作业。

**有火堆时**：可烹饪（fish_raw/meat_raw → cooked）、可制火把（stick + cloth/dry_leaf）；夜晚/rain 下休息 fatigue 恢复更好（系统自动加成 ×1.35，旁白可提及温暖驱散疲惫）。
**有庇护所时**：rain/storm 下休息恢复更多（系统自动降低天气消耗 ×0.7）；rain/storm 生火的前提。可建造「储物架/仓库」（type=storage）——放在储物架附近的食物不腐败，旁白提及这一点。

**build.tags 分类标准**（影响系统红利，认真填）：
- `shelter`：有顶盖或天然遮蔽，能挡雨——椰叶斜棚、草棚、帆布遮蔽、崖底凹陷改造 → shelter；四根木桩没有顶 → 不填
- `fire`：本身是持续燃烧的火源——篝火、火堆、小炉灶 → fire；火把（手持）、烧过的痕迹 → 不填
- `storage`：专门用于存放物品——木架、储物坑、编织篮架 → storage；随手堆放的石头 → 不填
- 多标签：崖边生火坑 + 石板挡风 → ["fire", "shelter"]；带顶的储物棚 → ["shelter", "storage"]

=== 农业 ===
情境里的「作物地块」给出附近农田状态（萌芽中/生长中/可收获）。

**识别农业操作**：
- 「种/播种/栽/埋下种子/插下幼苗」→ farm.action=plant，指定 crop_type
- 「浇水/给作物浇水/灌溉」→ farm.action=water
- 「施肥/给作物施肥/撒骨粉/埋泥」→ farm.action=fertilize
- 「收割/采摘/收获/拔掉」且有「可收获」作物 → farm.action=harvest

**约束**：
- 种植：仅草地/丛林（GRASS/JUNGLE/DEEP_JUNGLE），沙滩/山地/沼泽 → feasible=false
- 种植前必须背包有 seeds 或 banana_seedling；浇水需要 fresh_water/coconut_water/water_in_shell
- 施肥：消耗 bone 或 mud（任意一种）
- 收获：只在情境有「可收获」作物时才 feasible=true，否则 feasible=false，narration 描写「还没熟」
- 填了 farm 字段后不填 consume_items/produce_items/time_minutes，系统处理这些

=== 捕鱼与烹饪 ===
捕鱼必须在有水位置（浅滩/河流/潮汐池/岸边），内陆 feasible=false。
- 徒手/石头：退潮/浅水可得 small_fish，效率低
- 鱼线+鱼钩：垂钓 30-60 min，得 fish_raw
- 矛：叉鱼，效率中等，fish_raw
- fishing 技能越高，time_minutes 越短，narration 描写更老练手法

烹饪必须有火堆，否则 feasible=false。
- 转化：fish_raw/small_fish → fish_cooked；meat_raw/crab → meat_cooked
- 时间 30-45 min；新手 skill_gain cooking +1
- coconut_meat/banana/野果可直接食用，不需要烹饪

=== 判定原则 ===
- 鼓励创意，但物理不可能的事拒绝；不可行时让世界自己说话（"指甲抠在木缝里只刮下碎屑"）
- 时间：捡东西 5-15 min，做工具 30-60 min，搭棚子 4-6 h，挖坑 30 min（地标搜索耗时由系统给，不填 time_minutes）
- 拒绝明显作弊（"我从空气里变出火"）

=== 产出来源 ===
1. **在有 search_stages 的地标**（情境「地标搜索状态」非空）→ 产出由系统决定，绝不自己填 produce_items，按搜索规则处理
2. **在无 search_stages 的地标**（椰子林/淡水泉等）→ 按地标「特性」字段自由产出
3. **不在任何地标** → 按地形：沙滩有贝壳/浮木，丛林有树枝/藤蔓/野果，山地有石头，沼泽有泥/螃蟹

=== 地面物品 ===
- 「把 X 放在这里/地上」→ drop_items（不要用 consume_items）；食物 1 天腐败，工具永久
- 「捡起地面上的 X」→ pick_up_items；只能捡情境「附近地面物品」里存在的东西

=== 地标搜索 ===
情境里的「地标搜索状态」给出下一阶段索引；你不会得到阶段名称、工具需求、剩余数量——这些玩家自己摸索。
「附近的标志」只用于远眺，不能在那里直接动作。

识别搜索：玩家说「搜/翻/找/拆/撬/挖/掀/搜索」且在有可搜索阶段的地标上。

**判定流程**：
(a) 不在搜索 → 普通动作，不填 search_intent
(b) 在搜索，但方法物理上做不到（徒手撬钉死的板、用软布砸硬壳）→ feasible=true，不填 search_intent，narration 描写失败感受，不推时间
(c) 在搜索，方法可行（含 unspecified）→ 填 search_intent.stage_index + tool_method，narration 只写感官过程

**方法可行性速查**：
- 表面翻找：徒手即可 → 一律走 (c)
- 撬钉死的板/砸硬壳：需有杠杆或硬度（铁钉/树枝/骨头/锐石/刀）；徒手/软布/椰子壳 → (b)
- 切割/撕开：需有刃（锐石/刀/贝壳边）；徒手或钝物 → (b)
- 挖土：需长条物或容器边缘；徒手挖泥勉强行

tool_method 填玩家描述的方法（「用铁钉撬」「用石头砸」「徒手」）；笼统话填 'unspecified'。

填了 search_intent 后：不填 produce_items/time_minutes/fatigue_change/consume_items/hp_change；narration 只写感官描写，不剧透收获。

**搜索 narration 禁忌**：
- 失败时禁止暗示有发现（「指尖碰到硬物」「角落里有东西」）——明确传达「什么都没找到」
- 禁止引导下一步（「试试 X」「或许找根 Z」「想…吗」）
- 禁止出现系统语言（「阶段[0]」「下一阶段索引」）

=== 物品命名规范 ===
{item_id_rule_full()}

{ITEM_USE_RULE}
{CHINESE_NARRATION_RULE}"""


# 模块级缓存：系统提示只构建一次（物品清单是静态的）
_SYSTEM_PROMPT: str | None = None


def _system_prompt() -> str:
    global _SYSTEM_PROMPT
    if _SYSTEM_PROMPT is None:
        _SYSTEM_PROMPT = _build_system_prompt()
    return _SYSTEM_PROMPT


@dataclass
class ResolveResult:
    feasible: bool
    narration: str
    reasoning: str
    delta: WorldDelta
    cost_ms: int
    search_stage_index: int | None = None
    search_tool_method: str | None = None
    craft_quality: str = "normal"  # "normal" | "clever"
    farm_action: dict | None = None


async def resolve_action(
    world: World,
    action: str,
    search_status_text: str = "",
    nearby_ground_items: list[dict] | None = None,
    crop_plots_text: str = "",
) -> ResolveResult:
    p = world.player
    inventory_str = (
        "（空）"
        if not p.inventory
        else ", ".join(f"{s.id} x{s.qty}" for s in p.inventory)
    )

    builds_here = [
        f"- {b.type}: {b.description}"
        for b in world.built_things
        if abs(b.x - p.x) <= 1 and abs(b.y - p.y) <= 1
    ]
    builds_str = "\n".join(builds_here) if builds_here else "（无）"

    terrain = current_terrain(world)
    lm = current_landmark(world)
    nearby_others = [
        l for l in nearest_landmarks(world.landmarks, p.x, p.y, 3)
        if lm is None or l.id != lm.id
    ]
    nearby_lines = "\n".join(
        f"- {l.name}（{round(math.hypot(l.x - p.x, l.y - p.y))} 格外）"
        for l in nearby_others
    ) or "（无）"

    if lm is not None:
        landmark_part = f"{lm.name} —— {lm.description}"
        features_part = "；".join(lm.features)
    else:
        landmark_part = f"（无特殊地标，只是普通的{TERRAIN_NAMES[terrain]}）"
        features_part = "（按地形通常情况判断）"

    skills_str = ", ".join(f"{k} {v}" for k, v in p.skills.items())

    # 地面物品描述
    from .items import item_by_id as _item_by_id
    if nearby_ground_items:
        ground_lines = "\n".join(
            f"- ({g['x']},{g['y']}) {_item_by_id(g['id']).zh if _item_by_id(g['id']) else g['id']} ×{g['qty']}"
            for g in nearby_ground_items
        )
    else:
        ground_lines = "（无）"

    # 建造物环境状态（单行）
    env_parts = []
    env_parts.append("火堆✓" if has_fire_nearby(world) else "火堆✗")
    env_parts.append("庇护所✓" if has_shelter_nearby(world) else "庇护所✗")
    env_str = "、".join(env_parts)

    user_msg = f"""情境：第 {world.day} 天 {world.time}，天气 {world.weather}
地形：{TERRAIN_NAMES[terrain]}
地标：{landmark_part}
特性：{features_part}
搜索：{search_status_text or "无"}
附近标志（只能远眺）：
{nearby_lines}
建造物：
{builds_str}
环境：{env_str}
地面物品（3格内）：
{ground_lines}
作物地块（5格内）：
{crop_plots_text or "（附近无作物）"}
状态：{describe_player_state(world)}（HP {p.hp} 饿 {p.hunger} 渴 {p.thirst} 累 {p.fatigue}）
背包：{inventory_str}
技能：{skills_str}

动作：{action}"""

    result = await call_tool(
        system=_system_prompt(),
        user=user_msg,
        tool=ACTION_TOOL,
        max_tokens=1500,
    )
    inp = result.input

    delta: WorldDelta = {}
    search_stage_index: int | None = None
    search_tool_method: str | None = None
    farm_action: dict | None = None
    if inp.get("feasible"):
        # 如果 LLM 标记了 search_intent，优先走搜索路径——不接受其它 produce_items/time/fatigue
        if inp.get("search_intent"):
            search_stage_index = inp["search_intent"].get("stage_index")
            search_tool_method = inp["search_intent"].get("tool_method")
        elif inp.get("farm"):
            # 农业操作：不接受 produce_items/consume_items（系统处理）
            farm_action = inp["farm"]
        else:
            if inp.get("consume_items"):
                delta["consume_items"] = inp["consume_items"]
            if inp.get("produce_items"):
                delta["produce_items"] = inp["produce_items"]
            if inp.get("drop_items"):
                delta["drop_items"] = inp["drop_items"]
            if inp.get("pick_up_items"):
                delta["pick_up_items"] = inp["pick_up_items"]
            if inp.get("hp_change"):
                delta["hp_change"] = inp["hp_change"]
            if inp.get("hunger_change"):
                delta["hunger_change"] = inp["hunger_change"]
            if inp.get("thirst_change"):
                delta["thirst_change"] = inp["thirst_change"]
            if inp.get("fatigue_change"):
                delta["fatigue_change"] = inp["fatigue_change"]
            if inp.get("skill_gain"):
                delta["skill_gain"] = inp["skill_gain"]
            if inp.get("time_minutes"):
                delta["time_advance_minutes"] = inp["time_minutes"]
            if inp.get("build"):
                delta["build"] = inp["build"]

    return ResolveResult(
        feasible=bool(inp.get("feasible")),
        narration=inp.get("narration", ""),
        reasoning=inp.get("reasoning", ""),
        delta=delta,
        cost_ms=result.cost_ms,
        search_stage_index=search_stage_index,
        search_tool_method=search_tool_method,
        craft_quality=inp.get("craft_quality", "normal") or "normal",
        farm_action=farm_action,
    )
