# FastAPI 主应用：AI 世界引擎后端
# 代理 AI 调用，保护 API 密钥不暴露给客户端

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ai_engine import generate_turn, generate_opening

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 AI 世界引擎后端启动")
    yield
    logger.info("👋 后端关闭")


app = FastAPI(title="AI 沉浸式英语 - 世界引擎", lifespan=lifespan)

# CORS：允许前端 dev server 访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174", "http://127.0.0.1:5173", "http://127.0.0.1:5174"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── 请求/响应模型 ──────────────────────────────────

class SceneInfo(BaseModel):
    title: str
    description: str
    goal: str
    location: str
    npcs: list[dict] | None = None


class ProfileInfo(BaseModel):
    englishLevel: str = "beginner"
    name: str | None = None


class WorldStateInfo(BaseModel):
    inventory: list[str] = []
    quests: list[dict] = []
    npcStates: dict | None = None


class TurnRequest(BaseModel):
    """玩家输入一个回合的请求"""
    scene: SceneInfo
    profile: ProfileInfo
    world_state: WorldStateInfo
    history: list[dict[str, str]] = []
    player_input: dict[str, str]  # {"speech": "...", "action": "..."}


class OpeningRequest(BaseModel):
    """场景开场请求"""
    scene: SceneInfo
    profile: ProfileInfo
    prev_scene_summary: str | None = None


class TurnResponse(BaseModel):
    """AI 生成的回合响应"""
    narration: dict[str, str]  # {"en": ..., "zh": ...}
    npc: dict[str, str]        # {"speaker_id": ..., "speaker_name": ..., "content": ...}
    feedback: dict | None = None
    completes_scene: bool = False
    world_changes: dict = {}


class ErrorResponse(BaseModel):
    error: str
    detail: str = ""


# ── API 端点 ───────────────────────────────────────

@app.post("/api/turn", response_model=TurnResponse, responses={500: {"model": ErrorResponse}})
async def api_turn(req: TurnRequest):
    """生成一个回合的 AI 响应（旁白 + NPC 对话 + 英语反馈）"""
    try:
        result = await generate_turn(
            scene=req.scene.model_dump(),
            profile=req.profile.model_dump(),
            world_state=req.world_state.model_dump(),
            history=req.history,
            player_input=req.player_input,
        )
        return TurnResponse(**result)
    except Exception as e:
        logger.error("generate_turn 失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/api/opening", response_model=TurnResponse, responses={500: {"model": ErrorResponse}})
async def api_opening(req: OpeningRequest):
    """生成场景开场旁白和 NPC 对话"""
    try:
        result = await generate_opening(
            scene=req.scene.model_dump(),
            profile=req.profile.model_dump(),
            prev_scene_summary=req.prev_scene_summary,
        )
        return TurnResponse(**result)
    except Exception as e:
        logger.error("generate_opening 失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/api/health")
async def health():
    """健康检查"""
    return {"status": "ok", "model": "qwen3.8-flash"}
