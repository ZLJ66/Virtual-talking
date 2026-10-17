"""
世界加载器

职责：
1. 从 YAML 读取世界定义
2. 用 Pydantic 模型校验
3. 校验失败即抛错（启动时炸掉，而非运行时静默降级）

设计依据：《世界层设计.md》10.2
内容错误是"AI 表现奇怪"的头号原因——地点卡少一个字段，
AI 会静默降级，你根本不知道哪里错了。
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from pydantic import ValidationError

from world_models import PlayerState, World, WorldContent, WorldTime

logger = logging.getLogger("world_loader")

# 内容目录：backend/content/
CONTENT_DIR = Path(__file__).parent / "content"
DEFAULT_WORLD_FILE = CONTENT_DIR / "world_uk_first_week.yaml"


class WorldLoadError(RuntimeError):
    """世界加载失败。启动时应直接终止，不要降级。"""


def load_world(path: Path | str = DEFAULT_WORLD_FILE) -> WorldContent:
    """
    加载并校验世界定义。

    Args:
        path: YAML 文件路径

    Raises:
        WorldLoadError: 文件不存在、YAML 语法错误、或模型校验失败
    """
    path = Path(path)

    if not path.exists():
        raise WorldLoadError(f"世界文件不存在: {path}")

    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise WorldLoadError(f"无法读取世界文件 {path}: {e}") from e

    try:
        data = yaml.safe_load(raw_text)
    except yaml.YAMLError as e:
        raise WorldLoadError(f"YAML 语法错误 {path.name}:\n{e}") from e

    if not isinstance(data, dict):
        raise WorldLoadError(f"世界文件顶层必须是映射，收到 {type(data).__name__}")

    try:
        content = WorldContent.model_validate(data)
    except ValidationError as e:
        raise WorldLoadError(_format_validation_error(path.name, e)) from e

    logger.info(
        "世界已加载: %s (%d 地点, %d NPC, %d 主线节点)",
        content.world.title,
        len(content.world.locations),
        len(content.world.npcs),
        len(content.world.mainline.nodes),
    )
    return content


def _format_validation_error(filename: str, e: ValidationError) -> str:
    """把 Pydantic 的校验错误整理成可读的多行文本"""
    lines = [f"世界文件校验失败 {filename}:"]
    for err in e.errors():
        loc = " -> ".join(str(p) for p in err["loc"])
        msg = err["msg"]
        lines.append(f"  • {loc}: {msg}")
    return "\n".join(lines)


def build_initial_player_state(content: WorldContent) -> PlayerState:
    """根据 player_start 构造初始玩家状态"""
    start = content.player_start or {}
    world = content.world

    location = start.get("location") or world.locations[0].id
    if location not in {loc.id for loc in world.locations}:
        raise WorldLoadError(f"player_start.location 指向不存在的地点: {location}")

    time_data = start.get("time") or {}
    time = WorldTime(
        day=int(time_data.get("day", 1)),
        slot=time_data.get("slot", "morning"),
    )

    return PlayerState(
        location=location,
        time=time,
        inventory=list(start.get("inventory") or []),
        facts=dict(world.facts),
        knowledge=list(start.get("knowledge") or []),
    )


# ══════════════════════════════════════════════════════════
#  移动逻辑
# ══════════════════════════════════════════════════════════


class MoveError(ValueError):
    """非法移动"""


def can_move_to(world: World, state: PlayerState, target: str) -> tuple[bool, str]:
    """
    判断能否移动到目标地点。

    返回 (是否可移动, 原因)。原因在不可移动时用于向玩家解释。
    """
    try:
        current = world.get_location(state.location)
    except KeyError:
        return False, f"当前位置无效: {state.location}"

    if target not in current.connections:
        try:
            world.get_location(target)
        except KeyError:
            return False, f"不存在的地点: {target}"
        return False, f"从「{current.name}」无法直接到达该地点"

    return True, ""


def move_to(
    world: World, state: PlayerState, target: str
) -> tuple[PlayerState, str]:
    """
    执行移动：更新地点、推进时间。

    **这是唯一允许推进时间的地方**（另有「原地等待」）。
    AI 不得推进时间（见世界层设计 5.6）。

    Returns:
        (新的玩家状态, 时间流逝的叙述文本)
    """
    ok, reason = can_move_to(world, state, target)
    if not ok:
        raise MoveError(reason)

    current = world.get_location(state.location)
    target_loc = world.get_location(target)

    old_time = state.time
    new_time = old_time.advance(target_loc.travel_cost)

    new_state = state.model_copy(deep=True)
    new_state.location = target
    new_state.time = new_time

    narration = _describe_time_passage(old_time, new_time, target_loc)
    return new_state, narration


def _describe_time_passage(
    old: WorldTime, new: WorldTime, target: "Location | object"
) -> str:
    """
    生成时间流逝的叙述文本。

    设计要求：时间流逝必须被叙述，而不是 UI 数字跳变。
    """
    if old.day != new.day:
        return f"等你看清周围时，天已经亮了——这是第 {new.day} 天。"

    if old.slot == new.slot:
        return ""

    slot_phrase = {
        "morning": "天刚亮起来",
        "forenoon": "上午的日头升高了",
        "noon": "太阳到了头顶",
        "afternoon": "午后的光变软了",
        "evening": "天开始暗下来",
        "night": "路灯已经亮了",
    }
    return f"等你走到时，{slot_phrase.get(new.slot.value, '时间过去了一会儿')}。"
