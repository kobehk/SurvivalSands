"""LLM 生成"地标的独家描述"——玩家第一次踏入某个地标时调用一次。"""

from __future__ import annotations

from landmarks import PlacedLandmark
from llm import ToolDef, call_tool
from prompts_shared import CHINESE_NARRATION_RULE
from terrain import TERRAIN_NAMES, tile_at
from world import World

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


SYSTEM = f"""你是一座荒岛生存游戏的环境叙事者。玩家是独自漂流到岛上的人，没有同伴，岛上空无一人（除了野生动物）。

当玩家第一次踏入某个特殊地点时，写一段沉浸式的环境描述。

- 第二人称（你），80-180 字，一段连续散文，不分段不加标题
- 聚焦感官（视觉/听觉/嗅觉/触觉），不写心理活动，不替玩家下结论
- 融入当前天气与时间（晴朗正午 vs 雨后黄昏 感觉差很多）
- 不写「你可以做 X」，不给任务提示
- 不重复地标基础描述里已有的句子，要写它没说的细节
- 孤独感是底色——除非 arrival_context 明示「暗示有过别人」，否则不暗示有活人
- 如果有 arrival_context，自然融入其语境，不要机械套用

{CHINESE_NARRATION_RULE}"""


async def generate_landmark_description(
    world: World, landmark: PlacedLandmark
) -> str:
    terrain = tile_at(world.island, landmark.x, landmark.y)
    context_line = (
        f"语境（自然融入，勿直白说出）：{landmark.arrival_context}"
        if landmark.arrival_context
        else ""
    )
    user_msg = f"""第 {world.day} 天 {world.time}，天气 {world.weather}
地标：{landmark.name}
基础描述（勿重复）：{landmark.description}
特性（可暗示一两点）：{"；".join(landmark.features)}
地形：{TERRAIN_NAMES[terrain]}
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
