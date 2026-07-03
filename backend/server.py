"""FastAPI 服务：/api/* + 静态托管 public/。"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from session import GameSession

logger = logging.getLogger(__name__)

# 项目结构：repo_root/backend/server.py
# repo_root/public/ 是前端目录
_REPO_ROOT = Path(__file__).resolve().parents[1]
_PUBLIC_DIR = _REPO_ROOT / "public"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    db_path = os.environ.get("DB_PATH", "./game.db")
    game = GameSession(db_path=db_path)
    app.state.game = game
    logger.info("GameSession 加载完毕（db=%s）", db_path)
    yield
    # 退出时把数据库关掉
    game.db.close()


app = FastAPI(lifespan=lifespan)


# === 模型 ===
class MoveBody(BaseModel):
    dx: int = Field(default=0, ge=-1, le=1)
    dy: int = Field(default=0, ge=-1, le=1)


class MoveBatchBody(BaseModel):
    moves: list[MoveBody]


class ActionBody(BaseModel):
    action: str


class AnimalBody(BaseModel):
    animal: str
    action: str


# === 路由 ===
@app.get("/api/map")
async def api_map(request: Request):
    game: GameSession = request.app.state.game
    return game.map_info()


@app.get("/api/state")
async def api_state(request: Request):
    game: GameSession = request.app.state.game
    return game.snapshot()


@app.get("/api/items")
async def api_items():
    """物品名单"""
    from items import ITEMS

    return {
        "items": [
            {
                "id": it.id,
                "zh": it.zh,
                "category": it.category,
                "notes": it.notes,
            }
            for it in ITEMS
        ]
    }


@app.post("/api/move")
async def api_move(body: MoveBody, request: Request):
    if body.dx == 0 and body.dy == 0:
        raise HTTPException(status_code=400, detail="no movement")
    game: GameSession = request.app.state.game
    ok, reason = game.step(body.dx, body.dy)
    return {
        "ok": ok,
        "reason": reason,
        "state": game.snapshot(),
        "exploredB64": game.map_info()["exploredB64"],
    }


@app.post("/api/move/batch")
async def api_move_batch(body: MoveBatchBody, request: Request):
    """批量移动：一次性处理多步，减少 HTTP 往返和 IO 开销。"""
    if not body.moves:
        raise HTTPException(status_code=400, detail="empty moves")
    game: GameSession = request.app.state.game
    game.step_batch([(m.dx, m.dy) for m in body.moves])
    return {
        "ok": True,
        "state": game.snapshot(),
        "exploredB64": game.map_info()["exploredB64"],
    }


@app.post("/api/action")
async def api_action(body: ActionBody, request: Request):
    if not body.action.strip():
        raise HTTPException(status_code=400, detail="action required")
    game: GameSession = request.app.state.game
    try:
        # asyncio.shield + cancel_on_disconnect: 客户端断开时让任务取消
        # 简单做法：直接 await。客户端 abort 会让 starlette 抛 ClientDisconnect，
        # 任务被取消时会传播到 LLM 调用，OpenAI SDK 会把 httpx 请求一并取消
        result = await game.do_action(body.action)
        return {**result, "state": game.snapshot()}
    except asyncio.CancelledError:
        # 客户端中止
        return JSONResponse(
            status_code=408,
            content={"error": "aborted", "aborted": True},
        )
    except Exception as e:
        logger.exception("/api/action 失败")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/animal")
async def api_animal(body: AnimalBody, request: Request):
    if not body.animal or not body.action.strip():
        raise HTTPException(status_code=400, detail="animal and action required")
    game: GameSession = request.app.state.game
    try:
        result = await game.interact_animal(body.animal, body.action)
        return {**result, "state": game.snapshot()}
    except asyncio.CancelledError:
        return JSONResponse(
            status_code=408,
            content={"error": "aborted", "aborted": True},
        )
    except Exception as e:
        logger.exception("/api/animal 失败")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/reset")
async def api_reset(request: Request):
    game: GameSession = request.app.state.game
    game.reset()
    return {"ok": True, "state": game.snapshot()}


# === 静态文件托管（public/）===
# 必须放在所有 /api/* 路由后面
if _PUBLIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(_PUBLIC_DIR), html=True), name="public")
else:
    logger.warning("public 目录不存在: %s", _PUBLIC_DIR)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    port = int(os.environ.get("PORT", 3000))
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=port,
        reload=False,
    )


if __name__ == "__main__":
    main()
