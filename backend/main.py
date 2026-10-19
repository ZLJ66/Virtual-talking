# FastAPI 主应用：AI 世界引擎后端
# 代理 AI 调用，保护 API 密钥不暴露给客户端

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ai_engine import generate_turn, generate_opening
from world_loader import (
    WorldLoadError,
    build_initial_player_state,
    can_move_to,
    load_world,
    move_to,
    MoveError,
)
from world_models import PlayerState, WorldContent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main")

# 全局世界对象。启动时加载，加载失败则应用启动失败。
WORLD_CONTENT: WorldContent | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    启动时加载并校验世界内容。

    设计依据：《世界层设计.md》10.2
    内容错误是"AI 表现奇怪"的头号原因——地点卡少一个字段，
    AI 会静默降级，很难发现。**启动时炸掉，好过运行时悄悄变傻。**
    """
    global WORLD_CONTENT
    logger.info("🚀 AI 世界引擎后端启动")
    try:
        WORLD_CONTENT = load_world()
        logger.info(
            "✅ 世界已加载: %s（%d 地点 / %d NPC / %d 主线节点）",
            WORLD_CONTENT.world.title,
            len(WORLD_CONTENT.world.locations),
            len(WORLD_CONTENT.world.npcs),
            len(WORLD_CONTENT.world.mainline.nodes),
        )
    except WorldLoadError as e:
        # 不降级、不吞异常——直接让启动失败
        logger.error("❌ 世界加载失败，后端无法启动:\n%s", e)
        raise

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

class LocationInfo(BaseModel):
    """地点卡（来自世界内容）"""

    id: str
    name: str
    name_en: str = ""
    sensory: dict[str, str] = {}
    variant: str = ""
    open_hours: list[int] = [0, 24]
    resident_npcs: list[str] = []


class NPCInfo(BaseModel):
    """NPC 卡（含运行时印象标签与记忆）"""

    id: str
    name: str
    role: str = ""
    age: int | None = None
    background: str = ""
    personality: str = ""
    speech: dict[str, str] = {}
    impression_tags: list[str] = []
    memories: list[str] = []
    # 是否为跟随玩家同行的 NPC（与当地常驻 NPC 区分）
    is_companion: bool = False


class ProfileInfo(BaseModel):
    englishLevel: str = "beginner"
    name: str | None = None
    narrationLanguage: str | None = None


class WorldStateInfo(BaseModel):
    """玩家运行时状态（世界层）"""

    location: str = ""
    time: dict = {}
    inventory: list[str] = []
    facts: dict[str, bool] = {}
    knowledge: list[str] = []
    world_title: str = ""
    mainline_title: str = ""
    deadline: dict | None = None
    companions: list[str] = []


class WorldRulesInfo(BaseModel):
    rules: list[str] = []
    taboos: list[str] = []


class TurnRequest(BaseModel):
    """玩家输入一个回合的请求"""

    location: LocationInfo
    # 当前在场的所有人：当地常驻 + 同行者。可以只有一个，也可以有多个。
    npcs: list[NPCInfo] = []
    profile: ProfileInfo
    world_state: WorldStateInfo
    world_rules: WorldRulesInfo | None = None
    history: list[dict[str, str]] = []
    player_input: dict[str, str]  # {"speech": "...", "action": "..."}


class OpeningRequest(BaseModel):
    """地点开场请求"""

    location: LocationInfo
    # 当前在场的所有人：当地常驻 + 同行者
    npcs: list[NPCInfo] = []
    profile: ProfileInfo
    world_state: WorldStateInfo
    world_rules: WorldRulesInfo | None = None
    recent_summary: str | None = None


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
            location=req.location.model_dump(),
            npcs=[n.model_dump() for n in req.npcs],
            world_state=req.world_state.model_dump(),
            world_rules=req.world_rules.model_dump() if req.world_rules else None,
            history=req.history,
            player_input=req.player_input,
        )
        return TurnResponse(**result)
    except Exception as e:
        logger.error("generate_turn 失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/api/opening", response_model=TurnResponse, responses={500: {"model": ErrorResponse}})
async def api_opening(req: OpeningRequest):
    """生成地点开场旁白和 NPC 对话"""
    try:
        result = await generate_opening(
            location=req.location.model_dump(),
            npcs=[n.model_dump() for n in req.npcs],
            world_state=req.world_state.model_dump(),
            world_rules=req.world_rules.model_dump() if req.world_rules else None,
            recent_summary=req.recent_summary,
        )
        return TurnResponse(**result)
    except Exception as e:
        logger.error("generate_opening 失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/api/health")
async def health():
    """健康检查"""
    return {
        "status": "ok",
        "model": "qwen3.8-flash",
        "world_loaded": WORLD_CONTENT is not None,
    }


# ══════════════════════════════════════════════════════════
#  世界层 API
# ══════════════════════════════════════════════════════════


def _require_world() -> WorldContent:
    if WORLD_CONTENT is None:
        raise HTTPException(status_code=503, detail="世界尚未加载")
    return WORLD_CONTENT


@app.get("/api/world")
async def api_world():
    """
    返回世界静态定义 + 初始玩家状态。

    前端用这份数据渲染地点图、初始化状态，无需硬编码任何场景内容。
    """
    content = _require_world()
    world = content.world
    initial = build_initial_player_state(content)

    return {
        "world": {
            "id": world.id,
            "title": world.title,
            "year": world.year,
            "meta": world.meta.model_dump(),
            "rules": world.rules.model_dump(),
        },
        "locations": [
            {
                "id": loc.id,
                "name": loc.name,
                "name_en": loc.name_en,
                "open_hours": list(loc.open_hours),
                "travel_cost": loc.travel_cost,
                "connections": loc.connections,
                "resident_npcs": loc.resident_npcs,
                "sensory": loc.sensory.model_dump(),
                "variants": loc.variants,
                "state_fields": loc.state_fields,
            }
            for loc in world.locations
        ],
        "npcs": [
            {
                "id": npc.id,
                "name": npc.name,
                "role": npc.role,
                "age": npc.age,
                "background": npc.background,
                "personality": npc.personality,
                "speech": npc.speech.model_dump(),
            }
            for npc in world.npcs
        ],
        "mainline": {
            "title": world.mainline.title,
            "deadline": world.mainline.deadline,
            "nodes": [
                {
                    "id": n.id,
                    "title": n.title,
                    "location": n.location,
                    "requires": n.requires,
                    "requires_items": n.requires_items,
                    "grants_facts": n.grants_facts,
                }
                for n in world.mainline.nodes
            ],
        },
        "facts": world.facts,
        "player_start": initial.model_dump(mode="json"),
    }


class MoveRequest(BaseModel):
    """移动请求"""

    player_state: dict[str, Any]
    target: str


class MoveResponse(BaseModel):
    """移动结果"""

    ok: bool
    reason: str = ""
    player_state: dict[str, Any] | None = None
    time_narration: str = ""
    location: dict[str, Any] | None = None


@app.post("/api/move", response_model=MoveResponse)
async def api_move(req: MoveRequest):
    """
    执行移动。

    **时间只在这里被推进**（AI 不得推进时间，见世界层设计 5.6）。
    """
    content = _require_world()
    world = content.world

    try:
        state = PlayerState.model_validate(req.player_state)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"玩家状态无效: {e}") from e

    ok, reason = can_move_to(world, state, req.target)
    if not ok:
        return MoveResponse(ok=False, reason=reason)

    try:
        new_state, narration = move_to(world, state, req.target)
    except MoveError as e:
        return MoveResponse(ok=False, reason=str(e))

    # 记录进入次数（用于开场分级）
    depth = new_state.record_visit(req.target)
    logger.info("移动到 %s（第 %d 次进入）", req.target, depth)

    loc = world.get_location(req.target)
    return MoveResponse(
        ok=True,
        player_state=new_state.model_dump(mode="json"),
        time_narration=narration,
        location={
            "id": loc.id,
            "name": loc.name,
            "name_en": loc.name_en,
            "travel_cost": loc.travel_cost,
            "connections": loc.connections,
            "resident_npcs": loc.resident_npcs,
            "sensory": loc.sensory.model_dump(),
            "variant": loc.variant_for(new_state.time.slot),
            "is_open": loc.is_open_at(new_state.time.slot),
        },
    )


class WaitRequest(BaseModel):
    """原地等待请求"""

    player_state: dict[str, Any]


@app.post("/api/wait", response_model=MoveResponse)
async def api_wait(req: WaitRequest):
    """
    原地等待：消耗 1 个时段，世界推进一拍。

    设计依据：《世界层设计.md》4.6
    "等待不是空转，是给世界一个机会。"
    没有它，玩家在错误时段到达某地只能靠来回移动刷时间。
    """
    content = _require_world()
    world = content.world

    try:
        state = PlayerState.model_validate(req.player_state)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"玩家状态无效: {e}") from e

    old_time = state.time
    new_state = state.model_copy(deep=True)
    new_state.time = old_time.advance(1)

    if old_time.day != new_state.time.day:
        narration = f"你在原地待了很久，再抬头时天已经亮了——第 {new_state.time.day} 天。"
    else:
        slot_phrase = {
            "morning": "天光一点点亮起来",
            "forenoon": "上午过去了",
            "noon": "到了中午",
            "afternoon": "下午慢慢滑过去",
            "evening": "天色暗了下来",
            "night": "夜更深了",
        }
        narration = f"你等了一会儿，{slot_phrase.get(new_state.time.slot.value, '时间过去了')}。"

    loc = world.get_location(new_state.location)
    return MoveResponse(
        ok=True,
        player_state=new_state.model_dump(mode="json"),
        time_narration=narration,
        location={
            "id": loc.id,
            "name": loc.name,
            "name_en": loc.name_en,
            "travel_cost": loc.travel_cost,
            "connections": loc.connections,
            "resident_npcs": loc.resident_npcs,
            "sensory": loc.sensory.model_dump(),
            "variant": loc.variant_for(new_state.time.slot),
            "is_open": loc.is_open_at(new_state.time.slot),
        },
    )
