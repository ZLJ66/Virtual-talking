# FastAPI 主应用：AI 世界引擎后端
# 代理 AI 调用，保护 API 密钥不暴露给客户端

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, model_validator

from ai_engine import generate_turn, generate_opening
from mainline import judge as judge_changes
from mainline import prompt_lines as mainline_prompt_lines
from mainline import mainline_progress
from world_loader import (
    WorldLoadError,
    build_initial_player_state,
    can_move_to,
    load_world,
    move_to,
    MoveError,
)
from world_models import PlayerState, World, WorldContent

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
    # 由 mainline.prompt_lines() 生成的人话判定结果。
    # 不传时 AI 只能看到事实 id，无法判断哪件事现在能做。
    mainline_lines: list[str] = []


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
    # lines: 本回合的所有台词，按说话顺序。1~3 项。
    # 大多数回合只有 1 项；玩家同时对多人说话、或有人插话时才会多项。
    lines: list[dict[str, str]] = []
    # npc: 兼容字段，恒等于 lines[0]。旧前端/测试仍可用。
    # 有默认值，因为新代码可以只传 lines，由校验器回填。
    npc: dict[str, str] = {}
    feedback: dict | None = None
    completes_scene: bool = False
    world_changes: dict = {}

    @model_validator(mode="after")
    def _sync_lines_and_npc(self) -> "TurnResponse":
        """保证 lines 与 npc 双向一致。

        ai_engine.apply_lines 已经做过一次归一化，这里是最后一道闸：
        任何直接构造 TurnResponse 的调用方（测试、旧代码）都不会漏掉其中一边。
        契约是「npc 恒等于 lines[0]」，所以有 lines 时一律以 lines[0] 为准。
        """
        if self.lines:
            self.npc = dict(self.lines[0])
        elif self.npc:
            self.lines = [dict(self.npc)]
        return self


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
                    "grants_items": n.grants_items,
                    "window": n.window,
                    "soft_paths": n.soft_paths,
                }
                for n in world.mainline.nodes
            ],
        },
        "facts": world.facts,
        "player_start": initial.model_dump(mode="json"),
        # 起始时刻的主线判定结果。前端直接拿去渲染，不必自己算一遍，
        # 免得前后端对「什么算能办」理解不一致。
        "mainline_lines": mainline_prompt_lines(world, initial),
        "progress": mainline_progress(world, initial),
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
    # 这次移动是否刚好越过了主线截止时间
    mainline_just_missed: bool = False
    mainline_lines: list[str] = []
    progress: dict[str, Any] | None = None


def _location_payload(world: World, state: PlayerState) -> dict[str, Any]:
    """
    地点的运行时快照。

    移动与等待都要返回它，两处各写一遍必然会漂移
    （改了一处忘了另一处，前端就会拿到缺字段的对象）。
    """
    loc = world.get_location(state.location)
    return {
        "id": loc.id,
        "name": loc.name,
        "name_en": loc.name_en,
        "travel_cost": loc.travel_cost,
        "connections": loc.connections,
        "resident_npcs": loc.resident_npcs,
        "sensory": loc.sensory.model_dump(),
        "variant": loc.variant_for(state.time.slot),
        "is_open": loc.is_open_at(state.time.slot),
    }


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

    # 移动会推进时间，因此必须重新判定截止（判定器内部单向，重复调用安全）。
    judged = judge_changes(world, new_state, {})
    new_state = judged.player

    return MoveResponse(
        ok=True,
        player_state=new_state.model_dump(mode="json"),
        time_narration=narration,
        location=_location_payload(world, new_state),
        mainline_just_missed=judged.just_missed,
        mainline_lines=mainline_prompt_lines(world, new_state),
        progress=mainline_progress(world, new_state),
    )


class WaitRequest(BaseModel):
    """原地等待请求"""

    player_state: dict[str, Any]
    # 一次等待推进几个时段。默认 1（「等一会儿」）。
    # 设为足够大就是「睡一觉」：夜里一次推进到次日早晨。
    slots: int = Field(default=1, ge=1, le=6)


@app.post("/api/wait", response_model=MoveResponse)
async def api_wait(req: WaitRequest):
    """
    原地等待：消耗时段，世界推进。

    设计依据：《世界层设计.md》4.6
    "等待不是空转，是给世界一个机会。"
    没有它，玩家在错误时段到达某地只能靠来回移动刷时间。

    slots=1 是「等一会儿」；slots 大到跨日就是「睡一觉」。
    早期版本只支持 1 个时段，玩家要从第 1 天早晨走到第 2 天早晨
    得连按 6 次，且每次只说「上午过去了」——没有人能想到这是通往
    第二天的路。夜里给一个「睡觉」按钮比加提示更直接。
    """
    content = _require_world()
    world = content.world

    try:
        state = PlayerState.model_validate(req.player_state)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"玩家状态无效: {e}") from e

    old_time = state.time
    new_state = state.model_copy(deep=True)
    new_state.time = old_time.advance(req.slots)

    day_passed = new_state.time.day - old_time.day

    if day_passed > 0:
        if day_passed == 1:
            narration = (
                f"你睡了一觉，醒来时窗外已经亮了——第 {new_state.time.day} 天，"
                f"{new_state.time.slot.label_zh}。"
            )
        else:
            narration = (
                f"时间过去了 {day_passed} 天，再抬头时是第 "
                f"{new_state.time.day} 天的{new_state.time.slot.label_zh}。"
            )
    elif req.slots > 1:
        narration = (
            f"你待了 {req.slots} 个时段，"
            f"现在是{new_state.time.slot.label_zh}。"
        )
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

    # 时间推进后必须重新判定截止。
    # 判定器内部对 mainline_missed 是单向的，重复调用安全。
    judged = judge_changes(world, new_state, {})
    new_state = judged.player

    return MoveResponse(
        ok=True,
        player_state=new_state.model_dump(mode="json"),
        time_narration=narration,
        location=_location_payload(world, new_state),
        mainline_just_missed=judged.just_missed,
        mainline_lines=mainline_prompt_lines(world, new_state),
        progress=mainline_progress(world, new_state),
    )


# ── 主线判定 ───────────────────────────────────────


class JudgeRequest(BaseModel):
    """应用 AI 提议的世界变更"""

    player_state: dict[str, Any]
    # AI 返回的 world_changes，形如 {"set_fact": {...}, "add_item": "..."}
    world_changes: dict[str, Any] = {}


class JudgeResponse(BaseModel):
    """判定结果"""

    player_state: dict[str, Any]
    applied: list[str] = []
    rejected: list[str] = []
    completed: list[str] = []
    # 因节点完成而记住了这件事的 NPC id。代码直写，不依赖 AI 是否提议。
    remembered: list[str] = []
    just_missed: bool = False
    mainline_lines: list[str] = []
    progress: dict[str, Any] | None = None
    # 给前端的提示语。空字符串表示没什么要说的。
    notice: str = ""


@app.post("/api/judge", response_model=JudgeResponse)
async def api_judge(req: JudgeRequest):
    """
    校验并应用 AI 提议的世界变更。

    这是事实进入玩家状态的**唯一入口**。
    前端不再自己写 set_fact —— 旧实现只做白名单检查就写入，
    AI 一句「她说你已经办好了」就能把世界事实改掉，
    而玩家可能根本不在场、材料也没带。

    判定器拒绝的变更不会静默消失：rejected 里带着人话原因，
    既用于排查，也可以给玩家一句「还差什么」的提示。
    """
    content = _require_world()
    world = content.world

    try:
        state = PlayerState.model_validate(req.player_state)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"玩家状态无效: {e}") from e

    result = judge_changes(world, state, req.world_changes)

    for line in result.rejected:
        logger.info("判定器拒绝: %s", line)
    for line in result.applied:
        logger.info("判定器接受: %s", line)
    if result.remembered:
        logger.info("NPC 记住了: %s", ", ".join(result.remembered))

    return JudgeResponse(
        player_state=result.player.model_dump(mode="json"),
        applied=result.applied,
        rejected=result.rejected,
        completed=result.completed,
        remembered=result.remembered,
        just_missed=result.just_missed,
        mainline_lines=mainline_prompt_lines(world, result.player),
        progress=mainline_progress(world, result.player),
        notice=_build_notice(world, result),
    )


def _build_notice(world: World, result) -> str:
    """
    把判定结果翻成给玩家看的一句话。

    设计文档 1.3 硬约束：世界层宽容，学习层严格。
    所以这里只说「世界发生了什么」，不说「你做错了什么」——
    拒绝也写成客观事实（"还差 X"），不写成评判。
    """
    if result.just_missed:
        deadline = world.mainline.deadline or {}
        day = deadline.get("day")
        when = f"第 {day} 天" if day else "截止时间"
        return (
            f"{when}的期限已经过去了。注册处现在会要求你说明原因，"
            "走特殊情况申请——这不是结束，只是换了一条路。"
        )

    if result.completed:
        titles = []
        for node_id in result.completed:
            for node in world.mainline.nodes:
                if node.id == node_id:
                    titles.append(f"「{node.title}」")
                    break
        gained = "、".join(titles)
        if result.player.facts and all(result.player.facts.values()):
            return f"{gained}办好了。主线全部完成。"
        return f"{gained}办好了。"

    return ""
