"""
主线判定器

设计依据：《世界层设计.md》5.3 / 5.4 / 5.6

职责：
1. 判定主线节点能否完成，并给出人话的原因
2. 校验 AI 提议的世界变更 —— AI 是传感器，判定器才是权威
3. 截止时间检查与「错过」标记（软后果，不中断游戏）

核心原则：判定基于世界事实，不基于对话质量。
玩家说得好说得差，只要信息传达到、文件带齐，事实就成立。

但「不基于对话质量」不等于「不需要交互」：
节点不会因为玩家走进房间就自动完成——那会让整条主线变成走地图。
AI 观察到事情确实发生了（材料递过去了、对方确认了），提议对应事实；
判定器再检查地点、前置事实、随身物品、办理窗口是否都成立，成立才写入。

这样即使玩家说「我上周已经办过了」，AI 附和她写入事实，
判定器也会因为玩家不在注册处、或材料没带而拒绝。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from world_models import MainlineNode, PlayerState, World


class NodeState(str, Enum):
    """节点在某一时刻的状态。顺序即「检查优先级」。"""

    DONE = "done"
    AVAILABLE = "available"            # 条件全满足，只差交互
    WRONG_LOCATION = "wrong_location"  # 人不在这儿
    OUTSIDE_WINDOW = "outside_window"  # 时间不在窗口内
    MISSING_FACTS = "missing_facts"    # 前置事实未完成
    MISSING_ITEMS = "missing_items"    # 材料没带


# 给 prompt 用的一句话说明。AI 需要知道「为什么现在不能办」，
# 否则它会对着玩家硬推一个当前根本办不了的事。
_STATE_HINT_ZH: dict[NodeState, str] = {
    NodeState.DONE: "已完成",
    NodeState.AVAILABLE: "现在就可以办",
    NodeState.WRONG_LOCATION: "人不在这里",
    NodeState.OUTSIDE_WINDOW: "现在不在办理时间内",
    NodeState.MISSING_FACTS: "前置步骤没完成",
    NodeState.MISSING_ITEMS: "材料没带齐",
}


@dataclass
class NodeStatus:
    """单个节点的判定结果"""

    node: MainlineNode
    state: NodeState
    # 人话原因。为空表示无需解释（DONE / AVAILABLE）。
    reason: str = ""
    # 地点的中文名。给 AI 的 prompt 里不能出现 registry 这类内部 id，
    # 否则模型会把这个英文单词当成地名直接念给玩家听。
    location_name: str = ""

    @property
    def done(self) -> bool:
        return self.state is NodeState.DONE

    @property
    def available(self) -> bool:
        return self.state is NodeState.AVAILABLE

    def to_prompt_line(self) -> str:
        """
        给 AI 看的一行描述。

        刻意**不包含**事实 id（rts_check_passed 这类）。
        这些行是给模型理解「现在能做什么」的叙事上下文，
        里面混英文 id 会让模型把它当台词念给玩家听。
        机器指令单独放在 prompt_lines 末尾的「可写入的事实」区块。
        """
        where = self.location_name or self.node.location
        head = f"- 「{self.node.title}」（{where}）：{_STATE_HINT_ZH[self.state]}"
        if self.reason:
            return f"{head} —— {self.reason}"
        return head


@dataclass
class JudgeResult:
    """一次判定（含变更应用）的完整结果"""

    player: PlayerState
    # 被接受的变更，中文描述，用于日志与事件流
    applied: list[str] = field(default_factory=list)
    # 被拒绝的变更，含原因。这是排查「AI 说办好了但世界没变」的关键
    rejected: list[str] = field(default_factory=list)
    # 本回合新完成的主线节点 id
    completed: list[str] = field(default_factory=list)
    # 本回合是否刚刚越过截止时间
    just_missed: bool = False

    @property
    def changed(self) -> bool:
        return bool(self.applied or self.completed or self.just_missed)


# ══════════════════════════════════════════════════════════
#  节点判定
# ══════════════════════════════════════════════════════════


def _node_is_done(node: MainlineNode, player: PlayerState) -> bool:
    """节点的授予事实是否已全部成立"""
    if not node.grants_facts:
        return False
    return all(player.facts.get(f) for f in node.grants_facts)


def _is_missed(world: World, player: PlayerState) -> bool:
    """
    当前是否处于「已逾期」状态。

    不能只读 player.mainline_missed：那个标志位只在 judge() 里写入，
    而 evaluate_node 会被 /api/move、/api/world 等路径直接调用。
    只读标志位的话，一份时间已越界但还没触发过判定的存档，
    在逾期前依然会卡在 OUTSIDE_WINDOW —— 也就是玩家走到注册处，
    明明已经逾期，系统却告诉他「不在办理时间内」，而他再怎么等
    也等不回来（时间只会向前）。这是死胡同。

    所以这里用「标志位 or 时间已过截止」的组合判断。
    """
    if player.mainline_missed:
        return True
    deadline = world.mainline.deadline
    return bool(deadline and player.time.is_after(deadline))


def evaluate_node(
    node: MainlineNode, player: PlayerState, world: World
) -> NodeStatus:
    """
    判定单个节点当前能否完成。

    检查顺序刻意从「玩家最需要知道的那一条」开始：
    先看他是不是站错地方了，再看他是不是来错时间了，
    最后才说他步骤没做或材料没带——前两条玩家能立刻行动，
    后两条需要回忆或返回。
    """
    try:
        loc_name = world.get_location(node.location).name
    except KeyError:
        loc_name = node.location

    if _node_is_done(node, player):
        return NodeStatus(node, NodeState.DONE, location_name=loc_name)

    if player.location != node.location:
        return NodeStatus(
            node,
            NodeState.WRONG_LOCATION,
            f"需要去「{loc_name}」",
            location_name=loc_name,
        )

    # 错过截止后窗口不再拦截。
    #
    # 设计文档 8.2：因果链不能有死胡同。一个「窗口已过就永远做不了」的节点
    # 正是死胡同——玩家会被永久卡在主线中间，而游戏不会告诉他为什么。
    # 现实里的处理方式也不是「办不了」，而是「可以办，但要先说明原因」，
    # 所以这里放行，把难度交给对话（玩家必须解释自己为什么逾期）。
    if not _is_missed(world, player) and not player.time.is_within(node.window):
        return NodeStatus(
            node,
            NodeState.OUTSIDE_WINDOW,
            f"现在是{player.time.label_zh()}，{_describe_window(node)}",
            location_name=loc_name,
        )

    missing_facts = [f for f in node.requires if not player.facts.get(f)]
    if missing_facts:
        names = "、".join(_fact_title(world, f) for f in missing_facts)
        return NodeStatus(
            node, NodeState.MISSING_FACTS, f"还差：{names}", location_name=loc_name
        )

    missing_items = [i for i in node.requires_items if i not in player.inventory]
    if missing_items:
        return NodeStatus(
            node,
            NodeState.MISSING_ITEMS,
            f"没带：{'、'.join(missing_items)}",
            location_name=loc_name,
        )

    return NodeStatus(node, NodeState.AVAILABLE, location_name=loc_name)


def evaluate_all(world: World, player: PlayerState) -> list[NodeStatus]:
    """判定全部节点，按世界定义顺序返回"""
    return [evaluate_node(n, player, world) for n in world.mainline.nodes]


def _describe_window(node: MainlineNode) -> str:
    """把办理窗口说成人话，含时段"""
    window = node.window or {}
    start = window.get("from") or {}
    end = window.get("to") or {}
    s_day, s_slot = start.get("day"), start.get("slot")
    e_day, e_slot = end.get("day"), end.get("slot")

    s_text = _point_zh(s_day, s_slot)
    e_text = _point_zh(e_day, e_slot)

    if s_text and e_text:
        return f"只在 {s_text} 至 {e_text} 之间办理"
    if s_text:
        return f"{s_text} 之后才办理"
    if e_text:
        return f"{e_text} 之前办理"
    return "现在不在办理时间内"


def _point_zh(day: int | None, slot: Any) -> str:
    """把 {day, slot} 说成「第 1 天上午」这样的短语"""
    parts: list[str] = []
    if day:
        parts.append(f"第 {day} 天")
    if slot:
        parts.append(_slot_zh(slot))
    return "".join(parts)


def _fact_title(world: World, fact: str) -> str:
    """把事实 id 翻成节点标题，避免 prompt 里出现 pre_enrolment_submitted 这种生词"""
    for node in world.mainline.nodes:
        if fact in node.grants_facts:
            return node.title
    return fact


# ══════════════════════════════════════════════════════════
#  变更校验与应用
# ══════════════════════════════════════════════════════════


def judge(
    world: World,
    player: PlayerState,
    changes: dict[str, Any] | None,
) -> JudgeResult:
    """
    校验并应用 AI 提议的世界变更。

    这是 facts 进入玩家状态的**唯一入口**。
    前端不再直接写 set_fact（旧实现只做白名单检查就写入，
    AI 一句「她说你已经办好了」就能把事实改掉）。

    支持在一次调用里应用多个事实变更：办事员同时递上学生证和在读证明
    是完全合理的，逐个应用并重新判定即可。
    """
    result = JudgeResult(player=player.model_copy(deep=True))
    changes = changes or {}

    # ── 明确拒绝：AI 不得移动玩家 / 推进时间（设计文档 5.6）──
    for forbidden in ("set_location", "set_time"):
        if forbidden in changes:
            result.rejected.append(f"拒绝 {forbidden}：AI 不得移动玩家或推进时间")

    _apply_facts(world, result, changes)
    _apply_items(result, changes)
    _apply_companions(world, result, changes)

    # 截止检查放在最后：本回合可能刚好把最后一个节点做完，
    # 先判截止会把「踩线完成」错判成「错过」。
    result.just_missed = _check_deadline(world, result.player)

    return result


def _apply_facts(world: World, result: JudgeResult, changes: dict[str, Any]) -> None:
    """应用事实变更：白名单 + 节点条件双重校验"""
    raw = changes.get("set_fact") or changes.get("set_facts")
    if not raw:
        return
    if not isinstance(raw, dict):
        result.rejected.append(f"拒绝 set_fact：格式必须是对象，收到 {type(raw).__name__}")
        return

    for fact, value in raw.items():
        if fact not in world.facts:
            result.rejected.append(f"拒绝未知事实 {fact}：不在世界白名单内")
            continue

        # 只允许「设为 true」。设为 false 等于让 AI 撤销玩家已经办成的事，
        # 现实里办完的手续不会因为一句话就作废，且会破坏事件流的单调性。
        if not value:
            result.rejected.append(f"拒绝把 {fact} 设为 false：已完成的事实不可撤销")
            continue

        if result.player.facts.get(fact):
            # 已经为真，静默忽略（AI 重复提议很常见，不该报错刷屏）
            continue

        node = _node_granting(world, fact)
        if node is None:
            # 白名单内但没有节点授予它 —— 允许（预留给未来的自由事实），
            # 但记录下来，方便发现内容设计漏洞。
            result.player.facts[fact] = True
            result.applied.append(f"事实 {fact} → true（无对应主线节点）")
            continue

        status = evaluate_node(node, result.player, world)
        if not status.available:
            result.rejected.append(
                f"拒绝完成「{node.title}」：{status.reason or _STATE_HINT_ZH[status.state]}"
            )
            continue

        _complete_node(result, node)


def _complete_node(result: JudgeResult, node: MainlineNode) -> None:
    """完成一个节点：写入事实、发放物品"""
    for fact in node.grants_facts:
        result.player.facts[fact] = True
    for item in node.grants_items:
        if item not in result.player.inventory:
            result.player.inventory.append(item)
    result.completed.append(node.id)
    gained = "、".join(node.grants_facts)
    result.applied.append(f"完成「{node.title}」（{gained}）")


def _node_granting(world: World, fact: str) -> MainlineNode | None:
    for node in world.mainline.nodes:
        if fact in node.grants_facts:
            return node
    return None


def _apply_items(result: JudgeResult, changes: dict[str, Any]) -> None:
    """应用物品变更"""
    item = changes.get("add_item")
    if not isinstance(item, str) or not item.strip():
        return
    item = item.strip()
    if item in result.player.inventory:
        return
    result.player.inventory.append(item)
    result.applied.append(f"获得物品「{item}」")


def _apply_companions(world: World, result: JudgeResult, changes: dict[str, Any]) -> None:
    """应用同行者变更"""
    add = changes.get("add_companion")
    if isinstance(add, str) and add:
        if add not in {n.id for n in world.npcs}:
            result.rejected.append(f"拒绝同行者 {add}：世界里没有这个 NPC")
        elif result.player.add_companion(add):
            result.applied.append(f"{add} 开始同行")

    remove = changes.get("remove_companion")
    if isinstance(remove, str) and remove:
        if result.player.remove_companion(remove):
            result.applied.append(f"{remove} 不再同行")


# ══════════════════════════════════════════════════════════
#  截止与软后果
# ══════════════════════════════════════════════════════════


def _check_deadline(world: World, player: PlayerState) -> bool:
    """
    检查是否刚越过截止时间。返回是否「刚刚」错过。

    设计文档 5.4：错过不中断游戏、不显示失败，只是世界记住这件事。
    标记是单向的（一旦错过就保持），所以这里只在状态翻转时返回 True。
    """
    deadline = world.mainline.deadline
    if not deadline or player.mainline_missed:
        return False
    if not player.time.is_after(deadline):
        return False
    player.mainline_missed = True
    return True


def mainline_progress(world: World, player: PlayerState) -> dict[str, Any]:
    """
    主线整体进度，供 prompt 与 UI 使用。

    missed 用 _is_missed 判断而非只读标志位，原因见该函数的说明。
    """
    nodes = world.mainline.nodes
    done = [n for n in nodes if _node_is_done(n, player)]
    return {
        "title": world.mainline.title,
        "deadline": world.mainline.deadline,
        "missed": _is_missed(world, player),
        "total": len(nodes),
        "done": len(done),
        "done_titles": [n.title for n in done],
        "pending_titles": [n.title for n in nodes if n not in done],
    }


def available_here(world: World, player: PlayerState) -> list[NodeStatus]:
    """
    玩家此刻真正能办的事。

    这是给 AI 的关键输入：AI 需要知道「在这儿能做什么」，
    否则它只能看着一串 pre_enrolment_submitted 这样的 id 猜。
    """
    return [s for s in evaluate_all(world, player) if s.available]


def prompt_lines(world: World, player: PlayerState) -> list[str]:
    """主线状态的可读描述，直接拼进 prompt"""
    progress = mainline_progress(world, player)
    lines = [
        f"\n## 主线：{progress['title']}"
        f"（{progress['done']}/{progress['total']}）"
    ]

    deadline = progress["deadline"]
    if deadline:
        day = deadline.get("day")
        slot = deadline.get("slot")
        if progress["missed"]:
            lines.append(
                "**截止时间已经过了。** 世界已经进入「逾期」状态："
                "注册处会要求说明原因、需要转去 Student Centre。"
                "不要评判玩家，也不要提示读档——按现实中的流程走。"
            )
        elif day:
            lines.append(f"截止：第 {day} 天 {_slot_zh(slot)}")

    pending = [s for s in evaluate_all(world, player) if not s.done]
    if pending:
        lines.append("未完成的主线节点：")
        lines.extend(s.to_prompt_line() for s in pending)
    else:
        lines.append("主线节点已全部完成。")

    # 机器指令单独一块，与上面的叙事描述分开。
    #
    # 这些行里必须出现 rts_check_passed 这样的英文 id——模型要拿它
    # 填 set_fact。但混进叙事行会被当台词念出来，所以隔开。
    #
    # 只列「现在就能办」的节点。早期版本把全部未完成节点的 id 都列出来，
    # 模型会照着抄一个当前根本办不了的事实（比如人在注册处却写
    # pre_enrolment_submitted），然后被判定器拒绝——白跑一次判定，
    # 玩家还会看到「系统没反应」。
    ready = [s for s in pending if s.available]
    if ready:
        lines.append("\n## 本回合可能写入的事实（仅当玩家真的办成时才写）")
        for s in ready:
            for fact in s.node.grants_facts:
                lines.append(f'- 办完「{s.node.title}」→ `"set_fact": {{"{fact}": true}}`')

    return lines


def _slot_zh(slot: Any) -> str:
    from world_models import TimeSlot

    try:
        return TimeSlot(str(slot)).label_zh
    except ValueError:
        return str(slot or "")
