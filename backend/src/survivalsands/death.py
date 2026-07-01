"""LLM 生成玩家死亡时的遗骸叙事。

风格："第 N 天，某个漂流者的遗骸静静地躺在……"
传入死亡时的世界快照，返回一段 100-200 字的中文散文。
"""

from __future__ import annotations

from .items import item_by_id
from .llm import ToolDef, call_tool
from .prompts_shared import CHINESE_NARRATION_RULE
from .terrain import TERRAIN_NAMES
from .world import World

DEATH_TOOL: ToolDef = {
    "name": "describe_death",
    "description": "玩家死亡时，生成一段以旁观者视角描述遗骸的叙事。",
    "input_schema": {
        "type": "object",
        "properties": {
            "narration": {
                "type": "string",
                "description": "旁观者视角的遗骸叙事。详见系统提示。",
            },
        },
        "required": ["narration"],
    },
}

SYSTEM = f"""你是一座荒岛生存游戏的叙事者。某个漂流者在岛上独自求生，最终没能撑下去。

用**旁观者视角**写一段遗骸描述，好像多年后有人路过看到了这里留下的痕迹。

- 第三人称（「某个漂流者」「他/她」），100-200 字，一段连续散文，不分段不加标题
- 不用「你」——保持叙事距离
- 自然融入：死亡天数、地点、遗留物品、死因线索
- 用细节传达沉重感（散落的石头、磨损的指甲、半成品的工具），不要廉价煽情
- 结尾留余韵：遗留物仍在原处，等待下一个漂流者
- 禁止出现「游戏结束」「重新开始」等元叙事语言

{CHINESE_NARRATION_RULE}"""


async def generate_death_narration(
    world: World,
    cause: str,
    relics: list[dict],  # [{id, qty}] 留在地面的遗物
) -> str:
    """生成死亡叙事。cause 是死因描述（如"饥渴交加"、"重伤不治"）。"""
    from .landmarks import landmark_at
    from .terrain import tile_at

    p = world.player
    terrain = tile_at(world.island, p.x, p.y)
    lm = landmark_at(world.landmarks, p.x, p.y)

    relic_lines = ""
    if relics:
        parts = []
        for r in relics:
            it = item_by_id(r["id"])
            zh = it.zh if it else r["id"].replace("_", " ")
            parts.append(f"{zh}×{r['qty']}")
        relic_lines = f"- 遗留在地面的物品：{'、'.join(parts)}"

    location = lm.name if lm else TERRAIN_NAMES[terrain]

    user_msg = f"""死亡情境：
- 漂流第 {world.day} 天
- 时间：{world.time}，天气：{world.weather}
- 死亡地点：{location}（{TERRAIN_NAMES[terrain]}）
- 死因：{cause}
- 玩家身上携带的物品（此刻已遗落在此）：{", ".join(f"{item_by_id(s.id).zh if item_by_id(s.id) else s.id}×{s.qty}" for s in p.inventory) or "身无长物"}
{relic_lines}"""

    result = await call_tool(
        system=SYSTEM,
        user=user_msg,
        tool=DEATH_TOOL,
        max_tokens=600,
    )
    text = result.input.get("narration", "")
    return text.replace("**", "").strip()
