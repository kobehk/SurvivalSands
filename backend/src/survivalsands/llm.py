"""LLM 抽象层。整个游戏只通过这个文件调 LLM。

当前接 DeepSeek（OpenAI 兼容协议）。换回 Claude / 接别的，只改这个文件。
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, TypedDict

from dotenv import load_dotenv
from openai import AsyncOpenAI

# 优先用 backend/ 同级（仓库根）的 .env；找不到再 fallback 到默认搜索路径
_REPO_ROOT_ENV = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".env"))
if os.path.exists(_REPO_ROOT_ENV):
    load_dotenv(_REPO_ROOT_ENV)
else:
    load_dotenv()

_client = AsyncOpenAI(
    api_key=os.environ.get("DEEPSEEK_API_KEY"),
    base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
)
MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")


class ToolDef(TypedDict):
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class ToolCallResult:
    input: dict[str, Any]
    cost_ms: int


class LLMError(Exception):
    """LLM 没有按预期返回（没调工具 / JSON 损坏 / 等）。"""


async def call_tool(
    *,
    system: str,
    user: str,
    tool: ToolDef,
    max_tokens: int = 1024,
    cancel_token: object | None = None,
) -> ToolCallResult:
    """强制 LLM 调用指定 tool，返回结构化输入。

    DeepSeek v4 默认启用 thinking，导致：
      1. 不支持强制 tool_choice
      2. 输出常被 max_tokens 截断
      3. 延迟与 token 都更高
    我们这里关掉 thinking，换回强制 tool_choice。

    cancel_token 暂未使用——OpenAI Python SDK 走 httpx，可以用 AsyncClient 上下文里的
    asyncio.CancelledError 自动传播取消信号。session 层用 asyncio.Task.cancel() 即可。
    """
    started = time.perf_counter()

    resp = await _client.chat.completions.create(
        model=MODEL,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["input_schema"],
                },
            }
        ],
        tool_choice={"type": "function", "function": {"name": tool["name"]}},
        # OpenAI SDK 不认识 thinking，用 extra_body 透传给 DeepSeek
        extra_body={"thinking": {"type": "disabled"}},
    )

    choice = resp.choices[0]
    tool_calls = choice.message.tool_calls or []
    matched = None
    for tc in tool_calls:
        if tc.type == "function" and tc.function.name == tool["name"]:
            matched = tc
            break
    if matched is None or matched.type != "function":
        finish = choice.finish_reason
        content_preview = (choice.message.content or "")[:300]
        raise LLMError(
            f"LLM 没有按预期调用 {tool['name']}。"
            f"finish_reason={finish}, content={content_preview}"
        )

    try:
        parsed = json.loads(matched.function.arguments or "{}")
    except json.JSONDecodeError as e:
        raise LLMError(
            f"LLM 返回的 tool arguments 不是合法 JSON：{(matched.function.arguments or '')[:300]}"
        ) from e

    cost_ms = int((time.perf_counter() - started) * 1000)
    return ToolCallResult(input=parsed, cost_ms=cost_ms)
