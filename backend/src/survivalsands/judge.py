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
                "description": "产出的物品（仅 feasible=true 时使用）。",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "qty": {"type": "integer", "minimum": 1},
                    },
                    "required": ["id", "qty"],
                },
            },
            "drop_items": {
                "type": "array",
                "description": "把物品从背包放到地面（当前坐标）。适用于「我把 X 放在这里」「我在营地旁边堆放 X」。物品会永久存在地面上（食物类 1 天后腐败）。",
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
                "description": "把地面上的物品捡入背包。适用于「我捡起地面上的 X」。只能捡玩家附近地面上实际存在的物品（见情境里的「附近地面物品」）。",
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
                "description": "产出的是建造物（庇护所、火堆、陷阱等）时使用。会建在玩家当前坐标。",
                "properties": {
                    "type": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["type", "description"],
            },
            "search_intent": {
                "type": "object",
                "description": (
                    "如果玩家明显在「搜索/翻找/拆解」当前地标（例如说我在船里翻找/我撬开船板/我把船拆了），且当前地标有可搜索的阶段，"
                    "用这个字段告诉系统玩家在做哪一阶段。系统会处理实际产出，你不用填 produce_items。"
                    "stage_index 必须是当前地标 search_stages 中下一个未完成的阶段——见情境提示。"
                    "如果玩家不是在搜索（例如只是观察、聊天、移动、其他动作），不要填这个字段。"
                ),
                "properties": {
                    "stage_index": {
                        "type": "integer",
                        "minimum": 0,
                        "description": "搜索阶段索引",
                    },
                    "tool_method": {
                        "type": "string",
                        "description": (
                            "玩家在 action 里描述了用什么物体或方法去做这件事——比如"
                            "「用铁钉当撬棍」、「用一根硬树枝撬」、「用石头砸」、「徒手」。"
                            "如果玩家没明说方法（只说『搜搜看』『还有别的吗』这种笼统话），填 'unspecified'。"
                            "如果玩家说了一个明显荒谬的方法（『用椰子壳撬』），按你判断照实填——后端会拒。"
                        ),
                    },
                },
                "required": ["stage_index"],
            },
        },
        "required": ["feasible", "reasoning", "narration"],
    },
}


def _system_prompt() -> str:
    return f"""你是一个开放世界生存游戏的判定引擎。游戏背景是一个无人小岛，玩家是独自漂流上来的幸存者。

你的工作：根据玩家的自由动作描述，判定它在当前情境下是否合理可行，给出物理上合理的消耗、产出、时间花费和旁白。

=== 移动指令的特殊处理 ===
玩家的「移动」由游戏系统直接处理（WASD 走格子），不走你这里。
如果玩家说「我去 X」、「我走到丛林」、「我前往岩洞」——这类纯移动请求：
  → feasible=false，narration 简短提示「想换地方就用 WASD 自己走过去吧」
  → 不要消耗物品/产出/推时间/建造

如果是「我走到水边喝口水」这类**移动+动作**复合指令，当作"在当前位置做这个动作"处理。
当前位置确实够近就执行；太远就 feasible=false 提示「先走过去再说」。

=== 物理常识（小岛规则）===
- 椰子需要先破壳（用石头砸/锐物撬），才能取椰肉和椰汁
- 海水不能直接饮用，会让人更渴
- 淡水必须从淡水泉、雨水、河流或植物汁液获得
- 生火三要素：火种（摩擦/打火石/聚焦阳光）+ 干燥的火绒 + 木柴。三者缺一不可
- 雨天/夜晚生火困难，需要遮蔽
- 没有工具，徒手能做的事很有限：捡、搬、砸、攀爬、撕扯
- 制作工具需要更基础的工具（用石头打磨石头）
- 生鱼/生肉一天就会腐败，除非烟熏/晒干/用盐腌
- 受伤会感染，需要清洁与休息
- 夜晚视线极差、危险增多；体温下降；需要遮蔽和火堆
- 体力（HP/hunger/thirst/fatigue）耗尽会出问题：饿到 100 开始扣 HP；累到 100 行动失败率上升

=== 判定原则 ===
- 玩家有创意应该被鼓励，但物理上不可能的事要拒绝（"用椰子壳召唤神龙" → feasible=false）
- 不可行时不要简单说「不行」，要让世界自己说话（"指甲抠在木缝里只刮下一点碎屑"）
- 时间消耗要合理：捡个东西 5-15 分钟，做个杯子 30-60 分钟，搭简易棚子 4-6 小时，挖个坑半小时
  （注意：地标搜索的耗时由系统给定，你不用填 time_minutes）
- 拒绝玩家明显作弊的请求（"我捡到 100 把宝剑"、"我从空气里变出火"）

=== 产出来源（重要：地形 vs 地标 vs 搜索）===
玩家在不同情境下产出物品的来源不一样，按下面的优先级判断：

1. **当前在某个有 search_stages 的地标**（情境里"地标搜索状态"非空）：
   产出**完全由系统决定**——你只需要识别玩家是不是在搜索，按下面"地标搜索"块处理。
   **这种情况下绝不要自己填 produce_items**。

2. **当前在某个无 search_stages 的地标**（如"椰子林"、"淡水泉"）：
   该地标有"特性"字段说明能做什么——参考它来决定产出（在椰子林捡椰子，在淡水泉装水）。
   按地标特性自由产出 produce_items。

3. **当前不在任何地标**（"无特殊地标，只是普通的{{地形}}"）：
   按地形给环境物：沙滩有沙/贝壳/浮木/海水，丛林有椰子/野果/树枝/藤蔓，
   山地有石头，沼泽有泥/螃蟹，悬崖能鸟瞰。

=== 地面物品（放下与捡起）===
玩家可以把背包里的东西放到地面作为"储存"——比如在营地旁堆放树枝备用、把多余的食物存在某处。
- 玩家说「我把 X 放在这里/营地旁/地上」→ 用 drop_items（从背包移到当前坐标地面），**不要用 consume_items**
- 玩家说「我捡起地面上的 X」→ 用 pick_up_items，只能捡情境里「附近地面物品」列表中存在的东西
- 食物/水类物品放地面 1 天后会腐败消失（narration 可以提醒玩家这一点，但不要每次都说）
- 工具/原料/燃料永久保存在地面上
- pick_up_items 里的物品必须在「附近地面物品」里真实存在，不能凭空捡不存在的东西

=== 地标搜索（重要规则）===
- 「附近的标志」是远处可见的参考，仅用于丰富叙事或玩家「远眺/瞭望」动作；
  **不能**在那些远处地点执行动作——玩家要到达那里需先用 WASD 走过去
情境里的「地标搜索状态」会告诉你：是否还有未完成的阶段、下一阶段索引。
你**不会**得到下一阶段的名字、所需工具、剩余数量——这些是玩家应该自己摸索的，你也不知道。

**识别玩家是不是在搜索**：玩家说「搜/翻/找/拆/撬/挖/掀开/翻找/搜索/找东西」这类，且在有可搜索阶段的地标上 → 是搜索。

【规则 S1】**判定流程**（按下面顺序逐条考虑）：

  (a) 玩家**不在搜索**（比如说"我躺下睡觉"/"看看天空"）：按普通动作处理，不要填 search_intent。

  (b) 玩家在搜索，但他描述的**方法物理上不可能完成**这个阶段所需的工作（比如徒手撬钉死的船板、用椰子壳撬铁钉、用软布砸硬壳）：
      → feasible=true（动作本身可以"试"），但**不要填 search_intent**
      → narration 描写徒手/不合用方法的失败感受："指甲抠在木缝里只刮下一点碎屑"，**到此为止**
      → 不要消耗物品/产出/推时间

  (c) 玩家在搜索，方法**物理上能做**（包括"unspecified" 笼统话——后端会另行处理）：
      → 填 search_intent.stage_index = 情境给的"下一阶段索引"
      → 填 search_intent.tool_method（见 S2）
      → narration 只写过程感官描写

【方法可行性参考】（用于决定走 (b) 还是 (c)）：
- 表面翻找（只搜松散的东西）：徒手就够，几乎什么方法都行 → 一律走 (c)
- 撬开钉死的木板 / 砸开硬壳：需要**有杠杆或硬度的物体**——铁钉、长树枝、坚硬骨头、锐石、刀都行；
  「徒手」「用手」「用力掰」「用脚踹」「软布」「椰子壳」→ **不行，走 (b)**
- 切割绳索 / 撕开布：需要**有刃的东西**——锐石、刀、贝壳边、铁片；徒手或钝物 → 不行，走 (b)
- 挖土：需要**长条物**或**容器边缘**——长树枝、骨头、贝壳、扁石头；徒手挖泥土勉强行但慢

【规则 S2】填 search_intent.tool_method = 玩家**实际描述的方法**：
- 「我用铁钉当撬棍撬开船板」 → tool_method = "用铁钉当撬棍"
- 「我找根硬树枝挑开钉死的木板」 → tool_method = "用硬树枝撬"
- 「我用石头砸碎舱门」 → tool_method = "用石头砸"
- 「我徒手把破布拽下来」 → tool_method = "徒手"
- 「翻一翻」「搜搜看」「还有别的吗」「再仔细看看」 → tool_method = "unspecified"

【规则 S3】填了 search_intent 后：
- **不要**填 produce_items / time_minutes / fatigue_change（系统会填）
- consume_items / hp_change / hunger_change / thirst_change / skill_gain 也都不要填
- narration 只写**搜索过程的感官描写**——蹲下、拨开、翻动、嗅到、摸到——不要剧透找到了什么

【规则 S4】narration 在搜索情境下的禁忌：
- 失败时**不能**暗示有发现——禁止"指尖碰到硬物"、"似乎有什么"、"角落里有东西"等
  失败的 narration 应该传达"这次什么也没找到/没做成"——明确的负反馈
  例：写"沙子和碎木屑钻进指缝，再没别的东西"，而不是"指尖摸到硬邦邦的东西"
- **绝不引导玩家下一步做什么**：禁止「试试 X」「可以 Y」「或许找根 Z」「看看能不能…」「这步得先 X」「想…吗?」
- **绝不提具体工具或具体动作建议**——你既不知道下一阶段是什么，也不该替玩家想招
- **绝不使用系统语言**：不要写「阶段[0]/[1]」「次序」「N 个阶段」「下一阶段索引」
- 不要列具体工具清单（"用锐石/锈刀/木棒"）

=== 物品命名规范 ===
{item_id_rule_full()}

=== 通用旁白规范 ===
{ITEM_USE_RULE}

{CHINESE_NARRATION_RULE}"""


@dataclass
class ResolveResult:
    feasible: bool
    narration: str
    reasoning: str
    delta: WorldDelta
    cost_ms: int
    search_stage_index: int | None = None
    search_tool_method: str | None = None  # LLM 提取的方法描述（"铁钉撬"/"树枝撬"/"unspecified"）


async def resolve_action(
    world: World,
    action: str,
    search_status_text: str = "",
    nearby_ground_items: list[dict] | None = None,
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
        f"- {l.name}（{round(math.hypot(l.x - p.x, l.y - p.y))} 格之外，要去那里得先走过去）"
        for l in nearby_others
    ) or "（视野内没有特殊标志）"

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
            + ("（食物/水，1天后腐败）" if _item_by_id(g['id']) and _item_by_id(g['id']).perishable else "")
            for g in nearby_ground_items
        )
    else:
        ground_lines = "（附近地面上没有物品）"

    user_msg = f"""当前情境：
- 第 {world.day} 天，{world.time}，天气 {world.weather}
- 玩家位置：({p.x}, {p.y})
- 脚下地形：{TERRAIN_NAMES[terrain]}
- 当前地标：{landmark_part}
- 此地标特性：{features_part}
- 此地标的搜索状态：{search_status_text or "（无可搜索阶段，按普通动作判定）"}
- 附近的标志（仅供远眺，不可在那里直接动作）:
{nearby_lines}
- 此处的建造物：
{builds_str}
- 附近地面上的物品（3格内，可捡起或在旁边放更多）：
{ground_lines}
- 玩家身体状态：{describe_player_state(world)}（HP {p.hp}, 饿 {p.hunger}, 渴 {p.thirst}, 累 {p.fatigue}）
- 玩家背包：{inventory_str}
- 玩家技能：{skills_str}

玩家动作：{action}"""

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
    if inp.get("feasible"):
        # 如果 LLM 标记了 search_intent，优先走搜索路径——不接受其它 produce_items/time/fatigue
        if inp.get("search_intent"):
            search_stage_index = inp["search_intent"].get("stage_index")
            search_tool_method = inp["search_intent"].get("tool_method")
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
    )
