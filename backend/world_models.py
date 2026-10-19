"""
世界层数据模型

本文件是《世界层设计.md》第四章的实现，作为内容层与代码层的合同。
改动这里的字段名或结构，等同于修改合同——需同步更新设计文档并迁移数据。

设计要点：
1. 内容用 YAML 编写，由本文件的 Pydantic 模型校验
2. 启动时校验，校验失败即报错（而非运行时静默降级）
3. 运行时状态（PlayerState）与静态世界（World）严格分离
"""

from __future__ import annotations

from enum import Enum
from typing import Any, ClassVar

from pydantic import BaseModel, Field, field_validator, model_validator


# ══════════════════════════════════════════════════════════
#  枚举
# ══════════════════════════════════════════════════════════


class TimeSlot(str, Enum):
    """六个时段。不显示具体分钟——有节奏感，但不逼玩家算时间。"""

    MORNING = "morning"       # 早晨
    FORENOON = "forenoon"     # 上午
    NOON = "noon"             # 中午
    AFTERNOON = "afternoon"   # 下午
    EVENING = "evening"       # 傍晚
    NIGHT = "night"           # 晚上

    @property
    def label_zh(self) -> str:
        return _SLOT_LABELS_ZH[self.value]

    def next_slot(self) -> tuple[TimeSlot, bool]:
        """返回 (下一个时段, 是否跨日)"""
        order = list(TimeSlot)
        idx = order.index(self)
        if idx + 1 >= len(order):
            return TimeSlot.MORNING, True
        return order[idx + 1], False


_SLOT_LABELS_ZH: dict[str, str] = {
    "morning": "早晨",
    "forenoon": "上午",
    "noon": "中午",
    "afternoon": "下午",
    "evening": "傍晚",
    "night": "晚上",
}


# ══════════════════════════════════════════════════════════
#  世界静态定义
# ══════════════════════════════════════════════════════════


class WorldMeta(BaseModel):
    """世界元信息"""

    country: str
    city: str
    season: str = ""
    weather: str = ""
    currency: str = ""
    language_env: str = "en-GB"
    timezone: str = ""


class WorldRules(BaseModel):
    """世界规则与禁忌。每次生成都注入 prompt。"""

    rules: list[str] = Field(default_factory=list)
    taboos: list[str] = Field(default_factory=list)


class Sensory(BaseModel):
    """
    感官细节：生成层具体性的来源。

    这是消除"套路感"的关键——AI 输入抽象，输出必然抽象。
    设计要求至少 5 条，故五项全部必填。
    """

    sight: str = Field(description="视觉：光线、颜色、物体的具体状态")
    sound: str = Field(description="听觉：环境里持续或偶发的声音")
    smell: str = Field(description="嗅觉：空间里的气味")
    touch: str = Field(description="触觉：可触碰之物的质感")
    temperature: str = Field(description="温度与体感")

    def to_prompt_lines(self) -> list[str]:
        """转换为 prompt 行"""
        return [
            f"- 视觉：{self.sight}",
            f"- 听觉：{self.sound}",
            f"- 嗅觉：{self.smell}",
            f"- 触觉：{self.touch}",
            f"- 温度：{self.temperature}",
        ]


class Location(BaseModel):
    """地点卡"""

    id: str
    name: str
    name_en: str = ""
    open_hours: tuple[int, int] = (0, 24)   # 24 小时营业
    travel_cost: int = Field(default=1, ge=0, le=3)
    connections: list[str] = Field(default_factory=list)

    sensory: Sensory
    variants: dict[str, str] = Field(
        default_factory=dict,
        description="时段变体，key 为 TimeSlot 值。缺失的时段回落到通用描述",
    )

    resident_npcs: list[str] = Field(default_factory=list)
    state_fields: dict[str, Any] = Field(
        default_factory=dict,
        description="该地点持久化的状态字段（如货架剩余数量）",
    )

    @field_validator("id")
    @classmethod
    def _validate_id(cls, v: str) -> str:
        if not v or not v.replace("_", "").isalnum():
            raise ValueError(f"地点 id 必须是非空字母数字下划线组合，收到: {v!r}")
        return v

    @field_validator("variants")
    @classmethod
    def _validate_variants(cls, v: dict[str, str]) -> dict[str, str]:
        valid = {s.value for s in TimeSlot}
        unknown = set(v) - valid
        if unknown:
            raise ValueError(
                f"时段变体包含未知时段 {sorted(unknown)}，合法值: {sorted(valid)}"
            )
        return v

    def is_open_at(self, slot: TimeSlot) -> bool:
        """判断该时段是否营业"""
        start, end = self.open_hours
        if start == 0 and end == 24:
            return True
        # 把时段映射到小时区间起点
        hour = _SLOT_START_HOUR[slot.value]
        return start <= hour < end

    def variant_for(self, slot: TimeSlot) -> str:
        """取该时段的地点变体描述，缺失时回落到空串"""
        return self.variants.get(slot.value, "")


_SLOT_START_HOUR: dict[str, int] = {
    "morning": 6,
    "forenoon": 9,
    "noon": 12,
    "afternoon": 14,
    "evening": 18,
    "night": 21,
}


class NPCSpeech(BaseModel):
    """
    NPC 说话方式。

    这是当前实现最大的缺失——原先 NPC 的 personality 是空字符串，
    导致 AI 只能凭空编造，输出必然套路。
    """

    style: str = Field(description="语速、句长、是否主动展开话题")
    accent: str = Field(default="", description="口音特征")
    catchphrase: str = Field(default="", description="口头禅")
    tone: str = Field(default="", description="语气与社交距离（原 register，避免与 BaseModel 冲突）")

    def to_prompt_lines(self) -> list[str]:
        lines = [f"- 说话方式：{self.style}"]
        if self.accent:
            lines.append(f"- 口音：{self.accent}")
        if self.catchphrase:
            lines.append(f"- 口头禅：{self.catchphrase}")
        if self.tone:
            lines.append(f"- 语气：{self.tone}")
        return lines


class NPC(BaseModel):
    """人物卡"""

    id: str
    name: str
    role: str
    age: int | None = None
    background: str = ""
    speech: NPCSpeech
    personality: str

    variants: list[str] = Field(
        default_factory=list,
        description="人设候选池。阶段 C 实现随机抽取，阶段 A 只用第一个",
    )

    def to_prompt_lines(self) -> list[str]:
        lines = [f"## {self.name}（{self.role}）"]
        if self.age:
            lines.append(f"- 年龄：{self.age}")
        if self.background:
            lines.append(f"- 背景：{self.background}")
        lines.append(f"- 性格：{self.personality}")
        lines.extend(self.speech.to_prompt_lines())
        return lines


class MainlineNode(BaseModel):
    """主线节点"""

    id: str
    title: str
    location: str
    requires: list[str] = Field(
        default_factory=list, description="完成该节点所需的已有世界事实"
    )
    grants_facts: list[str] = Field(
        default_factory=list, description="完成该节点后写入的世界事实"
    )
    requires_items: list[str] = Field(
        default_factory=list, description="需要的物品（背包中必须存在）"
    )
    soft_paths: list[str] = Field(
        default_factory=list,
        description="补救路径。设计文档 8.2 要求每个节点至少一条，避免因果链死胡同",
    )

    @field_validator("soft_paths")
    @classmethod
    def _validate_soft_paths(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError(
                "每个主线节点必须定义至少一条 soft_paths（见世界层设计 8.2），"
                "否则玩家可能永久卡死"
            )
        return v


class Mainline(BaseModel):
    """主线定义"""

    title: str
    deadline: dict[str, Any] | None = Field(
        default=None, description="形如 {day: 5, slot: afternoon}"
    )
    nodes: list[MainlineNode]

    @model_validator(mode="after")
    def _validate_node_locations(self) -> Mainline:
        if not self.nodes:
            raise ValueError("主线必须至少有一个节点")
        return self


class World(BaseModel):
    """完整世界定义"""

    id: str
    title: str
    year: int = Field(description="锁定年份。政策会变，不锁年份内容会隐蔽地过时")
    meta: WorldMeta
    rules: WorldRules
    locations: list[Location]
    npcs: list[NPC]
    mainline: Mainline
    facts: dict[str, bool] = Field(
        default_factory=dict, description="世界事实白名单，主线判定的依据"
    )

    @model_validator(mode="after")
    def _validate_cross_references(self) -> World:
        """
        交叉引用校验。

        内容错误是"AI 表现奇怪"的头号原因——地点卡指向不存在的 NPC，
        AI 会静默降级，很难发现。这里在启动时就炸掉。
        """
        errors: list[str] = []

        location_ids = {loc.id for loc in self.locations}
        npc_ids = {npc.id for npc in self.npcs}

        # 地点 id 唯一
        if len(location_ids) != len(self.locations):
            dupes = [i for i in location_ids if [l.id for l in self.locations].count(i) > 1]
            errors.append(f"地点 id 重复: {dupes}")

        # NPC id 唯一
        if len(npc_ids) != len(self.npcs):
            dupes = [i for i in npc_ids if [n.id for n in self.npcs].count(i) > 1]
            errors.append(f"NPC id 重复: {dupes}")

        # 地点可达性引用
        for loc in self.locations:
            for target in loc.connections:
                if target not in location_ids:
                    errors.append(f"地点 {loc.id} 的 connections 指向不存在的 {target}")
            for npc_id in loc.resident_npcs:
                if npc_id not in npc_ids:
                    errors.append(f"地点 {loc.id} 的 resident_npcs 指向不存在的 {npc_id}")

        # 地点图必须连通（从任一地点可达所有地点）
        if self.locations:
            reachable = self._reachable_from(self.locations[0].id)
            unreachable = location_ids - reachable
            if unreachable:
                errors.append(f"地点图不连通，从 {self.locations[0].id} 无法到达: {sorted(unreachable)}")

        # 主线节点引用
        for node in self.mainline.nodes:
            if node.location not in location_ids:
                errors.append(f"主线节点 {node.id} 指向不存在的地点 {node.location}")
            for fact in node.requires:
                if fact not in self.facts:
                    errors.append(f"主线节点 {node.id} 的 requires 引用未声明的事实 {fact}")
            for fact in node.grants_facts:
                if fact not in self.facts:
                    errors.append(f"主线节点 {node.id} 的 grants_facts 引用未声明的事实 {fact}")

        # 截止时间格式
        if self.mainline.deadline:
            slot_val = self.mainline.deadline.get("slot")
            if slot_val is not None and slot_val not in {s.value for s in TimeSlot}:
                errors.append(f"主线截止时间的 slot 非法: {slot_val!r}")

        if errors:
            raise ValueError("世界定义校验失败:\n  - " + "\n  - ".join(errors))
        return self

    def _reachable_from(self, start: str) -> set[str]:
        """从起点出发可达的地点集合（广度优先）"""
        graph = {loc.id: set(loc.connections) for loc in self.locations}
        seen: set[str] = set()
        queue = [start]
        while queue:
            cur = queue.pop()
            if cur in seen:
                continue
            seen.add(cur)
            queue.extend(graph.get(cur, set()) - seen)
        return seen

    # ── 便捷查询 ──────────────────────────────────────

    def get_location(self, location_id: str) -> Location:
        for loc in self.locations:
            if loc.id == location_id:
                return loc
        raise KeyError(f"地点不存在: {location_id}")

    def get_npc(self, npc_id: str) -> NPC:
        for npc in self.npcs:
            if npc.id == npc_id:
                return npc
        raise KeyError(f"NPC 不存在: {npc_id}")


# ══════════════════════════════════════════════════════════
#  运行时状态
# ══════════════════════════════════════════════════════════


class WorldTime(BaseModel):
    """世界时钟"""

    day: int = Field(default=1, ge=1)
    slot: TimeSlot = TimeSlot.MORNING

    def advance(self, slots: int = 1) -> WorldTime:
        """
        推进若干时段。

        注意：只能由「移动」或「原地等待」调用。
        AI 不得推进时间（见世界层设计 5.6）。
        """
        new_day = self.day
        new_slot = self.slot
        for _ in range(max(0, slots)):
            new_slot, crossed = new_slot.next_slot()
            if crossed:
                new_day += 1
        return WorldTime(day=new_day, slot=new_slot)

    def is_after(self, deadline: dict[str, Any]) -> bool:
        """判断当前时间是否已越过给定截止时间"""
        d_day = deadline.get("day")
        d_slot = deadline.get("slot")
        if d_day is None:
            return False
        if self.day != d_day:
            return self.day > d_day
        if d_slot is None:
            return False
        order = [s.value for s in TimeSlot]
        return order.index(self.slot.value) > order.index(d_slot)

    def label_zh(self) -> str:
        return f"第 {self.day} 天 {self.slot.label_zh}"


class NPCState(BaseModel):
    """
    NPC 的运行时状态：印象标签与记忆。

    容量上限来自设计文档 4.4 / 4.5：
      - 印象标签最多 8 条
      - 记忆最多 12 条
    超出时按时间淘汰最旧的（印象标签额外保留最早一条作为第一印象）。
    """

    impression_tags: list[str] = Field(default_factory=list)
    memories: list[str] = Field(default_factory=list)

    MAX_TAGS: ClassVar[int] = 8
    MAX_MEMORIES: ClassVar[int] = 12

    def add_impression(self, tag: str) -> None:
        tag = tag.strip()
        if not tag or tag in self.impression_tags:
            return
        self.impression_tags.append(tag)
        if len(self.impression_tags) > self.MAX_TAGS:
            # 保留最早的（第一印象）+ 最近的 7 条，每次超限淘汰一条中间项。
            # 已由逐步追踪验证：写入 10 条后为 [tag0, tag3..tag9]，
            # 即第一印象与最近项均被保留。
            first = self.impression_tags[0]
            recent = self.impression_tags[-(self.MAX_TAGS - 1):]
            self.impression_tags = [first] + recent

    def add_memory(self, memory: str) -> None:
        memory = memory.strip()
        if not memory or memory in self.memories:
            return
        self.memories.append(memory)
        if len(self.memories) > self.MAX_MEMORIES:
            self.memories = self.memories[-self.MAX_MEMORIES:]

    def is_empty(self) -> bool:
        return not self.impression_tags and not self.memories


class PlayerState(BaseModel):
    """
    玩家运行时状态。

    注意：这是「世界状态」，不是「游戏进度」。
    没有 sceneIndex / stepIndex——进度由 location + time + facts 表达。
    """

    location: str
    time: WorldTime = Field(default_factory=WorldTime)
    inventory: list[str] = Field(default_factory=list)
    facts: dict[str, bool] = Field(default_factory=dict)
    knowledge: list[str] = Field(default_factory=list)
    npc_states: dict[str, NPCState] = Field(default_factory=dict)

    # ── 同行者 ────────────────────────────────────────
    # 跟着玩家一起移动的 NPC。
    #
    # 为什么需要这个字段：玩家可以邀请 NPC 同行（"一起去逛逛吧"），
    # 若系统不记录，NPC 会在玩家移动后凭空消失——这直接破坏世界一致性，
    # 也是产品最初要解决的痛点之一。
    #
    # 约束：同行者必须是世界里存在的 NPC；移动时随玩家一起移动；
    # 到达新地点后，他们与当地常驻 NPC 同时在场。
    companions: list[str] = Field(
        default_factory=list, description="跟随玩家移动的 NPC id 列表"
    )

    # ── 地点进入深度（成本控制）─────────────────────────
    visit_counts: dict[str, int] = Field(
        default_factory=dict, description="每个地点被进入的次数"
    )
    last_visit: dict[str, dict[str, Any]] = Field(
        default_factory=dict, description="每个地点上次离开时的时间"
    )

    def get_npc_state(self, npc_id: str) -> NPCState:
        """取 NPC 状态，不存在则创建"""
        if npc_id not in self.npc_states:
            self.npc_states[npc_id] = NPCState()
        return self.npc_states[npc_id]

    def record_visit(self, location_id: str) -> int:
        """记录一次地点进入，返回这是第几次"""
        count = self.visit_counts.get(location_id, 0) + 1
        self.visit_counts[location_id] = count
        return count

    def visit_depth(self, location_id: str) -> int:
        """当前是第几次进入（用于开场分级）"""
        return self.visit_counts.get(location_id, 0) + 1

    # ── 同行者操作 ────────────────────────────────────

    def add_companion(self, npc_id: str) -> bool:
        """加入同行者。返回是否发生了变化。"""
        if npc_id in self.companions:
            return False
        self.companions.append(npc_id)
        return True

    def remove_companion(self, npc_id: str) -> bool:
        """移出同行者。返回是否发生了变化。"""
        if npc_id not in self.companions:
            return False
        self.companions.remove(npc_id)
        return True

    def present_npcs(self, resident_npcs: list[str]) -> list[str]:
        """
        当前在场的所有 NPC：当地常驻 + 同行者（去重，常驻在前）。

        这是"谁在这个房间里"的唯一来源。AI 只应看到这里返回的人。
        """
        seen: list[str] = []
        for npc_id in list(resident_npcs) + list(self.companions):
            if npc_id not in seen:
                seen.append(npc_id)
        return seen


class WorldContent(BaseModel):
    """世界文件根结构（YAML 顶层）"""

    world: World
    player_start: dict[str, Any] = Field(
        default_factory=dict, description="起始地点、时间、背包"
    )
