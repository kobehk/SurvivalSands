"""瓶中信：LLM 生成一封由另一个落难者写下的求救信或遗书。"""

from __future__ import annotations

from llm import ToolDef, call_tool
from prompts_shared import CHINESE_NARRATION_RULE
from world import World

BOTTLE_TOOL: ToolDef = {
    "name": "generate_bottle_message",
    "description": "生成瓶中信的内容——一封由另一个落难者写下的信件。",
    "input_schema": {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "信件正文，80-200 字，以第一人称写就，充满情感但克制。",
            },
        },
        "required": ["content"],
    },
}

_SYSTEM = f"""你是一座荒岛生存游戏的叙事者。玩家在岛上找到了一封漂流瓶里的信件，由某个曾经困在这片海域的人写下。

=== 工作 ===
写这封信的内容。要求：
- 第一人称，作者是另一个落难者（可以是水手、渔夫、旅行者）
- 80-200 字，一段连续文字，不要分段、不加标题
- 内容有具体细节：作者在哪里（模糊的地理描述即可）、发生了什么事（简单几句）、想对读到这封信的人说什么
- 笔迹描述可以反映作者当时的状态（颤抖/有力/潦草）
- **不要**出现当前玩家的名字或直接呼应玩家的状态——这是写信人的独白
- 语气要有真实感：绝望、坚韧、平静、或几种情绪混合都可以——不要刻意煽情
- **不要**写「如果你找到这封信」这类老套开头

{CHINESE_NARRATION_RULE}"""


async def generate_bottle_message(world: World) -> str:
    user_msg = f"""当前游戏情境（供你决定信件的气氛）：
- 玩家已在岛上待了 {world.day} 天
- 当前天气 {world.weather}，时间 {world.time}
- 玩家在 {world.player.x}, {world.player.y} 处发现了这封信"""

    result = await call_tool(
        system=_SYSTEM,
        user=user_msg,
        tool=BOTTLE_TOOL,
        max_tokens=600,
    )
    return result.input.get("content", "").strip()
