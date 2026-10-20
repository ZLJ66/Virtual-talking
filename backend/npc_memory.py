"""
NPC 记忆与印象标签

设计依据：《世界层设计.md》4.4 / 4.5

职责：
1. 校验 AI 提议的记忆与印象，过滤掉不该记的东西
2. 主线节点完成时，由代码直接写入在场 NPC 的记忆（不依赖 AI）

为什么需要第 2 条：节点完成是**世界事实**，不该取决于 AI 这一回合有没有
想起来写 update_npc。设计文档 4.5 明确把「涉及世界事实变化（拿到了学生证）」
列为值得记的事——这种记忆必须 100% 落到在场者身上。否则玩家办成了大事，
在场的人却毫无印象，等于世界没有看见玩家做了什么。

核心红线（产品文档 1.3 硬约束 1）：
关系度不得由英语表达质量驱动。任何提到语法、用词、发音、生硬的记忆一律拒收。
若允许写入，等于用英语水平给玩家的人际关系打分，会让最需要鼓励的
初级用户体验最差——这与「NPC 不惩罚表达」是同一条原则的两面。
"""

from __future__ import annotations

from typing import Any

from world_models import MainlineNode, NPCState, PlayerState, World

# ── 长度上限 ────────────────────────────────────────────
# 设计文档里的示例记忆都在 20~25 字。给到 60 是宽松的，
# 但必须有上限：记忆会随回合数累积，单条太长会把 prompt 撑爆，
# 而 prompt 越拥挤，AI 对每条的注意力越弱。
MAX_MEMORY_CHARS = 60
MAX_IMPRESSION_CHARS = 40

# 每回合最多接受几个 NPC 的记忆更新。
# 设计文档 4.5 是「0~1 条」，但多人同场时（室友 + 店员）两人各记一件事
# 是合理的，所以放宽到 3，同时防止 AI 一口气写十条刷屏。
MAX_UPDATES_PER_TURN = 3


# ══════════════════════════════════════════════════════════
#  过滤：什么不许记
# ══════════════════════════════════════════════════════════

# 硬红线：英语表达质量。出现即拒收（不是截断——截断会留下一句残缺的话）。
#
# 用核心词匹配而不是完整短语，理由和套话检测器一样：
# 写「语法错误」「你的语法不错」「语法上有点问题」都是同一件事，
# 列举短语永远列不全，只会漏。
_QUALITY_TERMS: tuple[str, ...] = (
    "语法",
    "英语",
    "英文",
    "用词",
    "发音",
    "口音",
    "口语",
    "生硬",
    "不地道",
    "地道",
    "自然度",
    "得体度",
    "说错",
    "翻译",
    "表达能力",
    "语言能力",
    "词汇",
)

# 设计文档 4.4：玩家无礼时「记录行为，不记评价」。
# 所以「他把杯子推回去就走了」可以记，「他没礼貌」不行。
_JUDGMENT_TERMS: tuple[str, ...] = (
    "没礼貌",
    "不礼貌",
    "粗鲁",
    "无礼",
    "不友好",
    "讨厌",
    "差劲",
    "糟糕",
    "很笨",
    "很蠢",
    "没教养",
)

# 元词汇：NPC 不会说「玩家」这个词。出现它说明 AI 把第三人称的
# 分析写进了记忆，注入 prompt 后会变成「Sam 知道你（这个 NPC）…」这种
# 指代混乱的句子，NPC 会照着念出来。
_META_TERMS: tuple[str, ...] = ("玩家", "用户", "AI", "系统")

# 第三人称指代玩家：写成「记得他刚来时想家」。
#
# 为什么不直接拒收：这类记忆的信息是对的，只是人称错了，
# 拒收等于让一条真实的记忆彻底消失。改写比拒收宽容，也符合
# 「世界层宽容」的原则——NPC 不会因为系统的人称规范没写好而失忆。
#
# 只在记忆**以「记得他」「知道他们」开头**时改写，避免误伤
# 「记得他和我说过」之外的正常用法（比如「记得他妈妈做的茶」里的
# 「他」指的是玩家的家人，不该改）。
_THIRD_PERSON_PREFIXES: tuple[tuple[str, str], ...] = (
    ("记得他", "记得你"),
    ("记得她", "记得你"),
    ("记得他们", "记得你们"),
    ("知道他", "知道你"),
    ("知道她", "知道你"),
    ("觉得他", "觉得你"),
    ("觉得她", "觉得你"),
)


def _normalize_person(text: str) -> str:
    """
    把第三人称指代玩家的记忆改成第二人称。

    「记得他第一次见面时帮我扶住纸箱」→「记得你第一次见面时帮我扶住纸箱」

    只改开头，因为只有开头那个代词确定指玩家。句中出现的「他」
    可能指别人（家人、同事），改了会失真。

    但**句子里已经出现「你」时不改**。实测模型会写出视角自相矛盾的句子：

        「记得他差点把纸箱弄倒，你伸手扶住了。」

    这里的「他」和「你」指的是同一个人（玩家），模型把两种视角混在
    一句话里。如果盲目改写开头，会得到：

        「记得你差点把纸箱弄倒，你伸手扶住了。」  ← 意思反了

    玩家从「帮忙的人」变成了「差点闯祸的人」。

    已经出现「你」说明这句话的玩家视角是完整的，开头那个「他」
    顶多是个多余的第三人称，留着不伤原意；改掉才会毁掉原意。
    宁可保留一句稍显别扭的真话，也不要把它改成一句通顺的假话。
    """
    if "你" in text:
        return text

    for old, new in _THIRD_PERSON_PREFIXES:
        if text.startswith(old):
            return new + text[len(old):]
    return text


def _has_cjk(text: str) -> bool:
    """是否含中日韩汉字"""
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def _reject_reason(text: str, *, kind: str, max_chars: int) -> str | None:
    """
    检查一段记忆/印象是否可接受。可接受返回 None，否则返回拒收原因。

    拒收原因会进日志，不给玩家看——玩家看到的是 NPC 的反应，
    世界没有记住这件事本身就是反馈。
    """
    stripped = text.strip()
    if not stripped:
        return f"{kind}为空"

    if len(stripped) > max_chars:
        return f"{kind}超过 {max_chars} 字（{len(stripped)} 字）"

    # 必须是中文。
    #
    # 实测模型偶尔会写 "He saw me struggling with the enrolment paper..."——
    # 英文 + 第三人称。注入后变成「你（这个 NPC）对玩家的了解：· He saw me …」，
    # 既混了语言又混了视角，NPC 可能照着念出来。
    #
    # 这里只要求「含汉字」而不是「纯中文」：记忆里出现 Right to Study、
    # share code 这类专有名词是正常的，不该因此被拒。
    if not _has_cjk(stripped):
        return f"{kind}必须用中文写（收到纯英文）：{stripped[:20]}…"

    for term in _META_TERMS:
        if term in stripped:
            return f"{kind}出现元词汇「{term}」：要写成 NPC 的第一人称记忆，不要写成分析"

    for term in _QUALITY_TERMS:
        if term in stripped:
            return (
                f"{kind}涉及英语表达质量（「{term}」）："
                "关系度不得由表达好坏驱动（产品文档 1.3 硬约束 1）"
            )

    for term in _JUDGMENT_TERMS:
        if term in stripped:
            return f"{kind}是道德评判（「{term}」）：只记录行为，不记录评价（设计文档 4.4）"

    return None


# ══════════════════════════════════════════════════════════
#  在场者
# ══════════════════════════════════════════════════════════


def present_npc_ids(world: World, player: PlayerState) -> list[str]:
    """
    此刻在场的 NPC id：当地常驻 + 同行者。

    与 PlayerState.present_npcs 的区别：这个函数自己查地点，
    调用方不必先拿到 Location。地点 id 非法时返回空列表而不是抛异常——
    判定器不该因为一个坏地点 id 就整轮崩掉，那会让玩家卡死在错误里。
    """
    try:
        location = world.get_location(player.location)
    except KeyError:
        return []
    return player.present_npcs(location.resident_npcs)


# ══════════════════════════════════════════════════════════
#  应用 AI 的提议
# ══════════════════════════════════════════════════════════


def apply_update_npc(
    world: World, player: PlayerState, changes: dict[str, Any]
) -> tuple[list[str], list[str]]:
    """
    应用 update_npc 提议。返回 (applied, rejected) 的人类可读消息。

    支持单个对象或列表：
        "update_npc": {"npc_id": "sam", "memory": "..."}
        "update_npc": [{"npc_id": "sam", ...}, {"npc_id": "raj", ...}]
    """
    raw = changes.get("update_npc")
    if raw is None:
        return [], []

    if isinstance(raw, dict):
        items: list[Any] = [raw]
    elif isinstance(raw, list):
        items = raw
    else:
        return [], [f"拒绝 update_npc：格式必须是对象或数组，收到 {type(raw).__name__}"]

    if len(items) > MAX_UPDATES_PER_TURN:
        return [], [
            f"拒绝 update_npc：一回合最多 {MAX_UPDATES_PER_TURN} 条，"
            f"收到 {len(items)} 条"
        ]

    applied: list[str] = []
    rejected: list[str] = []
    present = set(present_npc_ids(world, player))
    handled: set[str] = set()

    for item in items:
        if not isinstance(item, dict):
            rejected.append(f"拒绝 update_npc 条目：格式必须是对象，收到 {type(item).__name__}")
            continue

        npc_id = item.get("npc_id")
        if not isinstance(npc_id, str) or not npc_id:
            rejected.append("拒绝 update_npc：缺少 npc_id")
            continue

        if npc_id not in {n.id for n in world.npcs}:
            rejected.append(f"拒绝 update_npc：世界里没有 NPC {npc_id}")
            continue

        if npc_id not in present:
            # 人不在场就不可能记住这件事。这条校验挡的是「AI 顺手给
            # 上一个场景的人写记忆」——那种记忆没有发生地点，注入后
            # NPC 会在别的场合说出他不可能知道的事。
            rejected.append(f"拒绝 update_npc：{npc_id} 此刻不在场")
            continue

        if npc_id in handled:
            rejected.append(f"拒绝 update_npc：同一回合对 {npc_id} 只能写一条")
            continue

        memory = item.get("memory")
        impression = item.get("impression")
        memory = memory.strip() if isinstance(memory, str) else ""
        impression = impression.strip() if isinstance(impression, str) else ""

        if not memory and not impression:
            rejected.append(f"拒绝 update_npc：{npc_id} 的 memory 与 impression 都是空的")
            continue

        # 人称归一化放在校验之前：先把「记得他…」改成「记得你…」，
        # 再判断长度和内容，避免改写后长度变化导致误判。
        memory = _normalize_person(memory)
        impression = _normalize_person(impression)

        bad = None
        if memory:
            bad = _reject_reason(memory, kind="记忆", max_chars=MAX_MEMORY_CHARS)
        if bad is None and impression:
            bad = _reject_reason(impression, kind="印象", max_chars=MAX_IMPRESSION_CHARS)
        if bad:
            rejected.append(f"拒绝 update_npc（{npc_id}）：{bad}")
            continue

        handled.add(npc_id)
        state = player.get_npc_state(npc_id)

        if memory:
            before = len(state.memories)
            state.add_memory(memory)
            if len(state.memories) > before:
                applied.append(f"{npc_id} 记住了：{memory}")

        if impression:
            before = len(state.impression_tags)
            state.add_impression(impression)
            if len(state.impression_tags) > before:
                applied.append(f"{npc_id} 对你的印象：{impression}")

    return applied, rejected


# ══════════════════════════════════════════════════════════
#  代码直写：节点完成
# ══════════════════════════════════════════════════════════


def remember_node_completion(
    world: World, player: PlayerState, node: MainlineNode
) -> list[str]:
    """
    主线节点完成时，把这件事写进所有在场者的记忆。

    由代码直写、不经过 AI 的原因见模块说明：这是世界事实，
    不能取决于 AI 这一回合想不想得起来写 update_npc。

    返回写入了记忆的 NPC id 列表（供日志与测试断言）。
    """
    # 直接接节点标题，因为内容作者写的标题本身就是动词短语：
    # 「完成线上注册」「通过 Right to Study 检查」「领取学生证」。
    # 早期用「知道你办成了「{title}」」，读出来是「知道你办成了「完成线上注册」」，
    # 标题里的动词和外层模板重复了一遍。
    text = f"记得你{node.title}"
    written: list[str] = []
    for npc_id in present_npc_ids(world, player):
        state: NPCState = player.get_npc_state(npc_id)
        before = len(state.memories)
        state.add_memory(text)
        if len(state.memories) > before:
            written.append(npc_id)
    return written
