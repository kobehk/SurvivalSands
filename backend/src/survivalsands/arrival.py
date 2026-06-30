"""LLM 生成"地标的独家描述"——玩家第一次踏入某个地标时调用一次。"""

from __future__ import annotations

from .landmarks import PlacedLandmark
from .llm import ToolDef, call_tool
from .prompts_shared import CHINESE_NARRATION_RULE
from .terrain import TERRAIN_NAMES, tile_at
from .world import World

ARRIVAL_TOOL: ToolDef = {
    "name": "describe_arrival",
    "description": "玩家第一次踏入某个地标时，生成一段身临其境的描述。",
    "input_schema": {
        "type": "object",
        "properties": {
            "narration": {
                "type": "string",
                "description": "玩家踏入此地的第一印象。详见系统提示。",
            },
        },
        "required": ["narration"],
    },
}


SYSTEM = f"""你是一座荒岛生存游戏的环境叙事者。玩家是一个独自漂流到岛上的人，没有同伴、没有 NPC——岛上空无一人（除了野生动物）。

=== 工作 ===
当玩家第一次踏入岛上某个特殊地点时，你写一段沉浸式的环境描述，让玩家感受到「这地方真的不一样」。

=== 写作约束 ===
- 第二人称（你），80-180 字，**一段连续散文**，绝不分点、不加标题、不用 markdown
- 聚焦感官（视觉/听觉/嗅觉/触觉），不写心理活动也不替玩家下结论
- 自然地融入当前天气与时间（晴朗的正午 vs 雨后的黄昏 vs 寒冷的夜晚 感觉差很多）
- 不要写「你可以做 X」、不要给玩家任务提示——那是别的系统的事
- 不要重复地标硬编码描述里已经写过的句子，要「绕到它背后」，写它没说的细节
- **鲁滨逊式的孤独感是底色**——除非地标的 arrival_context 明示「暗示有过别人」（如废弃营地、骸骨堆、漂流瓶），否则不要让任何描述暗示这里有别的活人
- 如果有 arrival_context，请把它的语境融入描述，而不是机械地套用——读起来要自然
- 不写明显的隐喻和「哲理感慨」，让画面本身说话

{CHINESE_NARRATION_RULE}"""


async def generate_landmark_description(
    world: World, landmark: PlacedLandmark
) -> str:
    terrain = tile_at(world.island, landmark.x, landmark.y)
    context_line = (
        f"- 剧情语境（融入描述但不要直白说出）：{landmark.arrival_context}"
        if landmark.arrival_context
        else ""
    )
    user_msg = f"""当前情境：
- 第 {world.day} 天，{world.time}，天气 {world.weather}
- 玩家踏入的地标：{landmark.name}
- 地标硬编码基础描述（避免重复）：{landmark.description}
- 地标特性（不要复述，但可以暗示其中一两点）：{"；".join(landmark.features)}
- 此处地形：{TERRAIN_NAMES[terrain]}
{context_line}"""

    result = await call_tool(
        system=SYSTEM,
        user=user_msg,
        tool=ARRIVAL_TOOL,
        max_tokens=600,
    )
    text = result.input.get("narration", "")
    # 简单清洗：去掉可能漏出来的 markdown 标记
    return text.replace("\n#", "\n").replace("**", "").strip()
