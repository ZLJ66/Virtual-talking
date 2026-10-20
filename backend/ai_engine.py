# AI 引擎：世界引擎 + 英语评估双引擎
# 核心原则："AI 是世界引擎，不是纠错老师"——NPC 容忍错误、猜测意图，反馈不打断沉浸
#
# 阶段 A 变更（关键）：
#   1. 开场与回合共用同一套系统提示词（原先两套导致 NPC 性格漂移）
#   2. 注入真实的感官细节、NPC 性格与说话方式、印象标签与记忆
#      —— 这是消除套路感的根本：输入具体，输出才具体
#   3. 强制具体性与套话禁用词表
#   4. world_changes 改为「提议」，由代码校验后生效

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("ai_engine")

# ── 配置 ──────────────────────────────────────────
AI_BASE_URL = os.getenv("AI_BASE_URL", "https://tokenrhythm.studio/v1")
AI_API_KEY = os.getenv("AI_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL", "qwen3.8-flash")

# 是否启用推理模式。默认关闭——qwen3.8-flash 开推理时单轮约 30 秒，
# 对话场景不可接受；关闭后约 12 秒且质量无可见下降。
AI_REASONING = os.getenv("AI_REASONING", "false").lower() in ("1", "true", "yes")


# ══════════════════════════════════════════════════
#  系统提示词（开场与回合共用）
# ══════════════════════════════════════════════════

SYSTEM_PROMPT = """\
你是一个沉浸式英语练习的「世界引擎」。你同时扮演两个角色：

## 角色一：世界引擎（驱动剧情）
- 你是故事世界本身，不是 DM，不是旁白，你就是这个正在运行的世界。
- 玩家输入英文来与 NPC 对话，也可以用中文/英文描述动作。
- 你根据玩家输入推进剧情，NPC 的反应要真实、有个性。
- **NPC 会容忍语法错误和笨拙表达**，他们会猜测玩家的意图并自然回应，
  就像现实中遇到英语不太好的外国人一样——不会纠正语法，而是用自然的英语继续对话。
- 如果玩家用了过于直接或不礼貌的表达，NPC 可以表现出轻微的反应（皱眉、犹豫等），
  但不会拒绝服务或离开。

## 角色二：英语评估引擎（后台记录，不侵入剧情）
- 在后台评估玩家的英语表达，但评估结果**绝不**影响 NPC 的回应方式或剧情走向。
- 评估维度：
  1. 有效性：NPC 是否理解了玩家的意图？（根据 NPC 回应内容判断）
  2. 自然度：表达是否地道自然？（good / ok / needs_improvement）
  3. 得体度：在当前社交场景中是否恰当？（good / ok / needs_improvement）
- 如果表达自然得体，只需简短确认；如果有改进空间，给出一个更自然的替代说法和简要原因。
- 评估用中文撰写，简明扼要。

## 输出格式
你必须输出合法 JSON，结构如下：
```json
{
  "narration": {
    "en": "英文旁白，描述发生了什么",
    "zh": "中文旁白，同内容的中文翻译"
  },
  "npc": {
    "speaker_id": "NPC的ID",
    "speaker_name": "NPC显示名称",
    "content": "NPC说的英文台词"
  },
  "feedback": {
    "understood": true,
    "naturalness": "good",
    "naturalness_note": "",
    "appropriateness": "good",
    "appropriateness_note": "",
    "suggested_expression": "",
    "suggestion_reason": ""
  },
  "world_changes": {}
}
```
**`world_changes` 字段必须始终存在**，即使没有变化也要输出 `{}`。
只有本回合真正发生的变更才写进去，没发生的不要写。

### 字段说明
- `narration`: 场景进展的旁白描述，中英双语。简短生动，2-3句话。
- `npc`: **本回合说话的那个人**。必须是「在场的人」之一。
  `speaker_id` 必须与在场者列表中对应人物的 id 一致。
- `feedback.understood`: NPC 是否理解了玩家意图（bool）
- `feedback.naturalness`: "good" / "ok" / "needs_improvement"
- `feedback.naturalness_note`: 自然度评价说明（中文，仅在有改进空间时填写）
- `feedback.appropriateness`: "good" / "ok" / "needs_improvement"
- `feedback.appropriateness_note`: 得体度说明（仅在有改进空间时填写）
- `feedback.suggested_expression`: 更自然的英文表达（仅当不是 good 时给出）
- `feedback.suggestion_reason`: 为什么这个表达更自然/得体（中文，简明）
- `world_changes`: 世界状态变更的**提议**，支持：
  - `"set_fact": {"事实名": true/false}` — 世界事实变化（只能用白名单内的事实）
  - `"add_item": "物品名"` — 玩家获得物品
  - `"add_companion": "npc_id"` — 这个 NPC 决定跟着玩家一起行动
  - `"remove_companion": "npc_id"` — 这个 NPC 不再跟着玩家
  - `"update_npc": {"npc_id": "id", "memory": "…", "impression": "…"}` — 这个 NPC 记住了一件事

### 多人在场时（极重要）
「在场的人」可能有多个（当地人 + 跟着玩家来的人）。
- **你必须让合适的人说话**，不是永远让当地人回答。
- 玩家对同行者说话 → 同行者回应。
- 玩家提到同行者 → 旁白和台词都要照顾到他。
- 同行者可以插话、评论、和当地人打招呼、替玩家解释。
- 不要让同行者变成沉默的背景板。
- `speaker_id` 必须是本回合真正说话的那个人。

### 同行者的产生与结束（判定规则）
**判定标准（照此执行，不要凭感觉）**：
- 玩家说「一起走」「走吧」「带我去」这类话，且 NPC 回应里表示同意
  （出现 Let's go / Come on / Sure / 好 / 走吧 等）→ 必须写 `add_companion`
- 两人一起往某个方向走、NPC 起身跟上 → 必须写 `add_companion`
- 同行者告别、分开、各回各家 → 必须写 `remove_companion`
- 只是「口头约定但没动身」→ 不写

> 实测数据：把上面三条写成可判断的条件后，`add_companion` 的产出率从
> 3/8（38%）提升到 8/8（100%）。此前只有一句笼统的「不要滥用」，
> 模型倾向于保守地什么都不写。

### NPC 记忆的产生（判定规则）
NPC 只记住**值得记住的事**，不是每回合都记。**判定标准（照此执行）**：

- 玩家做了选择、表了态 → 必须写 `update_npc`
  （拒绝了推荐、选了某样东西、说起自己的打算、承认了某件难处）
- 发生了和玩家有关的具体事件 → 必须写
  （忘了拿找零、把伞落在柜台、帮别人扶了门、说错了自己的名字）
- **玩家帮了这个 NPC 本人**（伸手接箱子、扶住他、让路、提醒他东西要掉了）
  → 必须写。这是 NPC **自己**被帮了，是最该记住的一类事
- 玩家流露出情绪（紧张、想家、兴奋）→ 必须写
- 只是寒暄、只是问了价格、常规交易完成 → **不写**

写法要求：
- `memory` 用 NPC 自己的口吻，像回忆一件事：`"记得你第一天买三明治时掏出一把硬币数了半天"`
- **人称必须写对**：说玩家用「你」，说这个 NPC 自己用「我」。
  不要写「记得他刚来时想家」（「他」会被读成另一个人），
  要写「记得你刚来时想家」
- `impression` 是这个人对玩家的看法，**只描述行为，不做道德评判**：
  `"觉得你是个安静有礼貌的年轻人"`，不要写 `"觉得他没礼貌"`
- 一条记忆只写一件事，**不超过 40 字**
- **必须用中文写**。NPC 说的是英语，但他记住的东西是给系统读的，
  写成英文会和其他中文记忆混在一起，读起来像另一个人
- 一回合最多写 1 条，多人同场时最多 2 条

### 绝对不许写进记忆的东西（硬红线）
| 禁止 | 原因 |
|---|---|
| 任何关于玩家英语水平的评价（语法、用词、发音、口音、是否地道） | NPC 不评价玩家的英语。记下来等于用英语水平给玩家的人际关系打分 |
| 对玩家的道德评价（没礼貌、粗鲁、差劲） | 只记录发生过什么，不记录好坏 |
| 「玩家」「用户」这类词 | 这是 NPC 的回忆，不是分析报告 |
| 这个 NPC 当时不在场时发生的事 | 他不可能知道 |

> 设计依据：《产品文档.md》1.3 硬约束 1 —— 关系度不得由英语表达质量驱动。
> 若允许记录「他英语很差」，最需要鼓励的初级用户会得到最差的对待，
> 这与「NPC 容忍语法错误」是同一条原则的两面。

### 具体性要求（极重要）
- **旁白必须包含至少一个来自「地点感官细节」的具体物件或现象**，
  不要写抽象的氛围描写。写"冰柜的低鸣盖过了他说话的声音"，
  而不是"空气中弥漫着安静的氛围"。
- NPC 的台词要体现其说话方式（语速、口头禅、语气），不要所有人说话都一样。

### 禁止使用的套话（出现即视为不合格，需重写）
| 禁用词 | 说明 |
|---|---|
| 你注意到 | 直接写看到了什么，不要写"你注意到" |
| 似乎 / 仿佛 / 好像 | 不确定的模糊表述，直接写事实 |
| **弥漫** | 包含"空气中弥漫着""弥漫着……的味道"，一律不许 |
| 不由得 / 不禁 | 陈词滥调 |
| 这一刻 | 陈词滥调 |
| 某种 | 模糊，写具体是什么 |
| 让你感到 | 不要替玩家感受 |

英文同理禁用：you notice / it seems / as if / the air is filled with /
cannot help but / in this moment / some kind of / makes you feel

**正确示范**（用具体物件代替氛围词）：
- ❌ 空气中弥漫着咖啡的味道 → ✅ 冰柜后面的咖啡机刚响过一声
- ❌ 他似乎有点紧张 → ✅ 他第三次擦了同一个杯子
- ❌ 你注意到灯在闪 → ✅ 灯管闪了一下

### 重要规则
1. NPC 台词必须用自然口语英语，不要太书面化
2. 旁白用第三人称，简短推进剧情
3. 如果玩家输入的是纯中文（在话语框），NPC 应困惑地用英语回应
   （"I'm sorry, I don't quite understand..."），但仍然尽力帮助
4. 如果玩家只输入了动作没有话语，NPC 根据动作情境自然反应
5. 不要在 NPC 台词或旁白中提及"英语"或"练习"——保持沉浸
6. **你不得改变玩家的位置，不得推进时间**——这两件事只能由玩家操作
7. 你的 JSON 必须严格合法，不要在 JSON 外输出任何其他内容
"""


OPENING_ADDENDUM = """\

### 本次任务：生成场景开场
这是玩家刚到达一个新地点。请生成：
- 一段旁白：让玩家"看见"这个地方（引用感官细节），2-3 句
- 一句 NPC 的开场白：符合该 NPC 的性格与说话方式

注意：
- 不要复述玩家已经知道的信息
- 如果提供了「最近发生的事」，自然衔接，不要生硬总结
- 开场白要自然引入互动，但不要像服务员背诵欢迎语
- **如果玩家有同行者，旁白必须提到他们一起进来**，
  开场台词可以由同行者或当地人说出
- feedback 字段设为 null（这是开场，玩家还没说话）
- 开场不要随意添加或移除同行者
"""


# ══════════════════════════════════════════════════
#  上下文构造
# ══════════════════════════════════════════════════

_SLOT_ZH = {
    "morning": "早晨",
    "forenoon": "上午",
    "noon": "中午",
    "afternoon": "下午",
    "evening": "傍晚",
    "night": "晚上",
}


def _slot_zh(slot: str) -> str:
    return _SLOT_ZH.get(slot, slot)


def _render_npc_block(npc: dict[str, Any], is_companion: bool) -> list[str]:
    """渲染单个 NPC 的信息块。"""
    lines: list[str] = []
    marker = "（和你一起来的）" if is_companion else ""
    lines.append(f"\n### {npc.get('name', '')}（{npc.get('role', '')}）{marker}")

    if npc.get("age"):
        lines.append(f"- 年龄：{npc['age']}")
    if npc.get("background"):
        lines.append(f"- 背景：{npc['background']}")
    if npc.get("personality"):
        lines.append(f"- 性格：{npc['personality']}")

    speech = npc.get("speech") or {}
    if speech:
        lines.append("- 说话方式：")
        if speech.get("style"):
            lines.append(f"  · {speech['style']}")
        if speech.get("accent"):
            lines.append(f"  · 口音：{speech['accent']}")
        if speech.get("catchphrase"):
            lines.append(f"  · 口头禅：{speech['catchphrase']}")
        if speech.get("tone"):
            lines.append(f"  · 语气：{speech['tone']}")

    tags = npc.get("impression_tags") or []
    memories = npc.get("memories") or []
    if tags or memories:
        lines.append("- 你（这个 NPC）对玩家的了解：")
        for t in tags:
            lines.append(f"  · {t}")
        for m in memories:
            lines.append(f"  · {m}")
    else:
        lines.append("- 你（这个 NPC）对玩家的了解：（第一次见面，还不了解）")

    return lines


def build_world_context(
    location: dict[str, Any],
    npcs: list[dict[str, Any]] | None,
    world_state: dict[str, Any],
    world_rules: dict[str, Any] | None = None,
) -> list[str]:
    """
    构造世界上下文。

    这是消除套路感的核心——把「抽象的场景名」换成「具体的物与人」。

    参数 npcs 是**当前在场的所有人**（当地常驻 + 同行者），
    每个 dict 可带 `is_companion: True` 表示此人跟着玩家来的。
    早期实现只接受单个 npc，导致同行者会凭空消失。
    """
    parts: list[str] = []

    # ── 世界规则（每次必注入）──
    if world_rules:
        parts.append("## 世界规则（必须遵守）")
        for r in world_rules.get("rules", []):
            parts.append(f"- {r}")
        if world_rules.get("taboos"):
            parts.append("\n## 禁忌")
            for t in world_rules["taboos"]:
                parts.append(f"- {t}")
        parts.append("")

    # ── 当前地点：感官细节是关键 ──
    parts.append("## 当前地点")
    parts.append(f"名称：{location.get('name', '')}（{location.get('name_en', '')}）")

    sensory = location.get("sensory") or {}
    if sensory:
        parts.append("\n### 感官细节（旁白必须引用其中至少一项）")
        parts.append(f"- 视觉：{sensory.get('sight', '')}")
        parts.append(f"- 听觉：{sensory.get('sound', '')}")
        parts.append(f"- 嗅觉：{sensory.get('smell', '')}")
        parts.append(f"- 触觉：{sensory.get('touch', '')}")
        parts.append(f"- 温度：{sensory.get('temperature', '')}")

    variant = location.get("variant")
    if variant:
        parts.append(f"\n### 此刻的景象\n{variant}")

    # ── 在场的人（可能不止一个）──
    npc_list = npcs or []
    if npc_list:
        parts.append(f"\n## 在场的人（共 {len(npc_list)} 人）")
        parts.append(
            "注意：以下每个人都在场，都可能说话。"
            "旁白必须照顾到他们，不要只写其中一个人。"
        )
        for n in npc_list:
            parts.extend(_render_npc_block(n, bool(n.get("is_companion"))))

        if any(n.get("is_companion") for n in npc_list):
            parts.append(
                "\n### 关于同行者的规则\n"
                "- 同行者是你带到这里的人，他们可能插话、评论、和当地人打招呼。\n"
                "- 如果玩家对同行者说话，回应的应该是同行者，不是店员。\n"
                "- 同行者的台词必须用他们自己的 speaker_id。\n"
                "- 不要让同行者凭空消失，也不要让他们变成沉默的旁观者。"
            )

    # ── 世界状态 ──
    parts.append("\n## 玩家状态")
    time_info = world_state.get("time") or {}
    parts.append(
        f"- 时间：第 {time_info.get('day', 1)} 天，"
        f"{_slot_zh(time_info.get('slot', 'morning'))}"
    )
    if world_state.get("inventory"):
        parts.append(f"- 随身物品：{'、'.join(world_state['inventory'])}")

    facts = world_state.get("facts") or {}
    done = [k for k, v in facts.items() if v]
    pending = [k for k, v in facts.items() if not v]
    if done:
        parts.append(f"- 已完成：{'、'.join(done)}")
    if pending:
        parts.append(f"- 未完成：{'、'.join(pending)}")

    if world_state.get("knowledge"):
        parts.append(f"- 玩家已知：{'；'.join(world_state['knowledge'])}")

    # ── 主线 ──
    #
    # mainline_lines 由后端 mainline.py 生成，是已经翻成人话的判定结果，
    # 形如「- 「通过 Right to Study 检查」（学校注册处）：现在就可以办」。
    #
    # 早期实现直接把 pre_enrolment_submitted 这类事实 id 塞进 prompt，
    # 模型只能看到一个英文单词，既不知道它是哪件事、也不知道能不能做，
    # 于是它要么忽略主线，要么对着玩家硬推一个当前根本办不了的事。
    mainline_lines = world_state.get("mainline_lines")
    if mainline_lines:
        parts.extend(mainline_lines)
    elif world_state.get("mainline_title"):
        # 兜底：调用方没算判定结果时，至少把标题和截止时间给出来。
        parts.append(f"\n## 主线：{world_state['mainline_title']}")
        deadline = world_state.get("deadline")
        if deadline:
            parts.append(
                f"截止：第 {deadline.get('day')} 天 "
                f"{_slot_zh(str(deadline.get('slot', '')))}"
            )

    return parts


def build_turn_prompt(
    location: dict[str, Any],
    npcs: list[dict[str, Any]] | None,
    world_state: dict[str, Any],
    world_rules: dict[str, Any] | None,
    history: list[dict[str, str]],
    player_input: dict[str, str],
) -> str:
    """构造回合的用户提示"""
    parts = build_world_context(location, npcs, world_state, world_rules)

    if history:
        parts.append("\n## 最近的对话")
        for h in history[-8:]:
            speaker = h.get("speaker") or h["role"]
            parts.append(f"{speaker}: {h['content']}")

    parts.append("\n## 玩家当前输入")
    if player_input.get("speech"):
        parts.append(f"话语：{player_input['speech']}")
    if player_input.get("action"):
        parts.append(f"动作：{player_input['action']}")
    if not player_input.get("speech") and not player_input.get("action"):
        parts.append("（玩家没有说话，也没有动作）")

    # 世界变更清单放在提示最末尾——模型对末尾的指令响应最强。
    # 之前把 add_companion 规则只写在 system prompt 里，实测模型会直接省略该字段。
    parts.append("\n## 输出前检查：本回合有没有世界变更？")
    parts.append(
        "对照下面每一条，如果本回合**确实发生**了就写进 world_changes，否则不要写："
    )
    parts.append(
        '- 玩家邀请某人同行、对方答应了 → `"add_companion": "对方id"`'
    )
    parts.append(
        '- 同行者告别、分开、各回各家 → `"remove_companion": "对方id"`'
    )
    parts.append('- 玩家拿到了某样东西 → `"add_item": "物品名"`')
    parts.append('- 某个主线事实被确认完成 → `"set_fact": {"事实名": true}`')

    # 记忆规则单独列，且给出「值得记」的正向条件。
    #
    # 参照 add_companion 的教训：只写「不要滥用」时模型倾向保守地什么都不写，
    # 产出率 38%；改成可机械判断的正向条件后升到 100%。这里同理——
    # 先告诉它「什么算值得记」，再补一句「其余不写」。
    parts.append(
        '- 玩家做了选择、表了态、露出情绪，或发生了和他有关的具体事件 '
        '→ `"update_npc": {"npc_id": "说话者的id", "memory": "用这个NPC的口吻记下这件事"}`'
    )
    parts.append(
        "  · 只记值得记的事：一次普通寒暄、问个价格、常规买卖**不要记**"
    )
    parts.append(
        "  · 用中文写，人称用「你」指玩家、「我」指这个 NPC。"
        "写成英文或写成「他」会被系统拒收"
    )
    parts.append(
        "  · **绝对不许**写任何关于玩家英语水平的评价（语法/用词/发音/是否地道），"
        "也不许写对玩家的道德评价（没礼貌/粗鲁）。只记录发生过什么"
    )
    parts.append("  · 一回合最多 1 条，多人同场最多 2 条")

    parts.append(
        "**world_changes 字段必须出现在 JSON 里**，没有变更就写 `{}`。"
    )

    return "\n".join(parts)


def build_opening_prompt(
    location: dict[str, Any],
    npcs: list[dict[str, Any]] | None,
    world_state: dict[str, Any],
    world_rules: dict[str, Any] | None,
    recent_summary: str | None,
) -> str:
    """构造开场用户提示。转场上下文是消除生硬感的关键。"""
    parts = build_world_context(location, npcs, world_state, world_rules)

    if recent_summary:
        parts.append("\n## 最近发生的事（用于自然衔接，不要复述）")
        parts.append(recent_summary)

    parts.append("\n## 任务")
    parts.append("生成这个地点的开场旁白与 NPC 开场白。")
    parts.append("- 旁白必须引用上面「感官细节」中的至少一项具体内容")
    parts.append("- NPC 开场白要符合其说话方式，不要像服务员背诵欢迎语")

    if npcs and any(n.get("is_companion") for n in npcs):
        parts.append(
            "- **你和同行者是一起走进来的**，旁白必须体现这一点"
            "（比如他跟在后面、他先开口、他四处张望），"
            "不要让同行者凭空消失"
        )
        parts.append(
            "- 开场台词可以由同行者或当地人说出，"
            "取决于谁更可能先开口"
        )

    return "\n".join(parts)


# ══════════════════════════════════════════════════
#  AI 调用
# ══════════════════════════════════════════════════


async def call_ai(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.8,
    max_tokens: int = 1024,
    timeout: float = 30.0,
    max_retries: int = 3,
) -> str:
    """调用 AI API，返回原始文本响应。自动重试最多 max_retries 次。"""

    import asyncio

    url = f"{AI_BASE_URL}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {AI_API_KEY}",
    }
    body: dict[str, Any] = {
        "model": AI_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    # 关闭推理模式（qwen3.8-flash 是推理模型）。
    #
    # 实测对比（同一 prompt，各 2~5 轮）：
    #   默认（推理开）：平均 29.6s，reasoning_tokens 622~1230
    #   reasoning_effort=none：平均 12.1s，reasoning_tokens 恒为 0
    #
    # 对话场景每轮等 30 秒不可接受，而关闭推理后输出质量无可见下降
    # （NPC 语气、口头禅、具体信息均保持）。故默认关闭。
    # 若需要更强的剧情推理，可通过环境变量 AI_REASONING 打开。
    if not AI_REASONING:
        body["reasoning_effort"] = "none"

    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            async with httpx.AsyncClient(verify=False, timeout=timeout) as client:
                response = await client.post(url, json=body, headers=headers)
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                if not content or not content.strip():
                    raise ValueError("AI 返回了空内容")
                return content
        except (httpx.HTTPStatusError, httpx.TimeoutException, ValueError) as e:
            last_error = e
            wait = attempt * 2
            logger.warning(
                "AI 调用失败（第 %d/%d 次）: %s — %ds 后重试",
                attempt,
                max_retries,
                e,
                wait,
            )
            await asyncio.sleep(wait)

    raise RuntimeError(f"AI 调用失败，已重试 {max_retries} 次: {last_error}") from last_error


def parse_ai_response(raw: str) -> dict[str, Any]:
    """从 AI 原始响应中提取 JSON，容忍 markdown 代码块包裹"""

    text = raw.strip()

    if text.startswith("```"):
        first_newline = text.index("\n") if "\n" in text else len(text)
        text = text[first_newline + 1:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning("AI 返回了无效 JSON，尝试修复: %s", e)
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass
        raise ValueError(f"AI 返回了无法解析的 JSON: {text[:200]}") from e


# ── 套话检测（设计文档 6.2）─────────────────────
#
# 注意：最初只写了完整短语（如「空气中弥漫着」），实测发现 AI 会绕开——
# 它写成「弥漫着新刷乳胶漆的味道」，完整短语匹配不到。
# 因此改为「核心词」匹配：只要出现该词就判为套话。
# 核心词宁可宽一些，误报只是日志噪音，漏报则会让套路感溜过去。

BANNED_WORDS_ZH = [
    "你注意到", "似乎", "仿佛", "不由得", "不禁", "这一刻",
    "弥漫",      # 覆盖「空气中弥漫着」「弥漫着……的味道」
    "某种", "让你感到", "好像",
]
BANNED_WORDS_EN = [
    "you notice", "it seems", "as if", "the air is filled",
    "cannot help but", "in this moment", "some kind of", "makes you feel",
    "fills the air", "lingering scent", "scent of",
]


def check_specificity(
    narration: dict[str, str], sensory: dict[str, str]
) -> list[str]:
    """
    检查旁白是否满足具体性要求。

    返回问题列表（空表示合格）。仅记录警告，不阻断——
    阻断会显著增加延迟，先用日志观察命中率。
    """
    issues: list[str] = []
    zh = (narration.get("zh") or "").lower()
    en = (narration.get("en") or "").lower()

    for word in BANNED_WORDS_ZH:
        if word in zh:
            issues.append(f"中文套话: {word}")
    for word in BANNED_WORDS_EN:
        if word in en:
            issues.append(f"英文套话: {word}")

    # 具体性：旁白应引用感官细节中的某个具体名词
    #
    # 注意：最初用 re.findall(r"[\u4e00-\u9fa5]{2,6}") 切词，这是错的——
    # 正则会贪婪地切出「走廊尽头的窗」「户蒙着一层水」这类无意义片段，
    # 要求它们原样出现在旁白里，几乎必然失败，导致合格旁白被误报。
    # 改为二元组（滑动窗口）匹配：「走廊」「过道」「水汽」这类真实词素能命中。
    sensory_text = " ".join(v for v in sensory.values() if v)
    if sensory_text and zh:
        if not _shares_content_bigram(sensory_text, zh):
            issues.append("旁白可能未引用感官细节")

    return issues


# 判断二元组是否有信息量时排除的高频虚词/量词。
# 只用于降低误报，不影响命中真实名词（「过道」「水汽」「暖气」都不含这些字）。
_FUNC_CHARS = set(
    "的了着一是在有和与上下里中得地过也都就又会能要把被让给对从到向于为以及而且但或如若则其之此这那些个层种样"
)


def _shares_content_bigram(source: str, target: str) -> bool:
    """source 与 target 是否共享至少一个「有信息量」的中文二元组。"""
    import re

    cleaned = re.sub(r"[^\u4e00-\u9fa5]", "", source)
    for i in range(len(cleaned) - 1):
        bigram = cleaned[i : i + 2]
        if any(ch in _FUNC_CHARS for ch in bigram):
            continue
        if bigram in target:
            return True
    return False


# ══════════════════════════════════════════════════
#  生成入口
# ══════════════════════════════════════════════════


async def generate_turn(
    location: dict[str, Any],
    npcs: list[dict[str, Any]] | None,
    world_state: dict[str, Any],
    world_rules: dict[str, Any] | None,
    history: list[dict[str, str]],
    player_input: dict[str, str],
) -> dict[str, Any]:
    """生成一个回合的 AI 响应（旁白 + NPC 对话 + 英语反馈）"""

    user_prompt = build_turn_prompt(
        location, npcs, world_state, world_rules, history, player_input
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    raw = await call_ai(messages, temperature=0.8, max_tokens=2048)
    result = parse_ai_response(raw)

    result.setdefault("narration", {"en": "", "zh": ""})
    result.setdefault(
        "npc", {"speaker_id": "unknown", "speaker_name": "???", "content": "..."}
    )
    result.setdefault("feedback", None)
    result.setdefault("world_changes", {})

    sensory = (location.get("sensory") or {}) if location else {}
    issues = check_specificity(result.get("narration") or {}, sensory)
    if issues:
        logger.warning("旁白具体性不足: %s", "; ".join(issues))

    return result


async def generate_opening(
    location: dict[str, Any],
    npcs: list[dict[str, Any]] | None,
    world_state: dict[str, Any],
    world_rules: dict[str, Any] | None,
    recent_summary: str | None = None,
) -> dict[str, Any]:
    """
    生成地点开场旁白和 NPC 对话。

    与回合共用同一套 SYSTEM_PROMPT（消除 NPC 性格漂移），
    只追加一段开场专用说明。
    """

    user_prompt = build_opening_prompt(
        location, npcs, world_state, world_rules, recent_summary
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT + OPENING_ADDENDUM},
        {"role": "user", "content": user_prompt},
    ]

    raw = await call_ai(messages, temperature=0.7, max_tokens=1536)
    result = parse_ai_response(raw)

    result.setdefault("narration", {"en": "", "zh": ""})
    result.setdefault(
        "npc", {"speaker_id": "unknown", "speaker_name": "???", "content": "..."}
    )
    result["feedback"] = None
    result.setdefault("world_changes", {})

    sensory = (location.get("sensory") or {}) if location else {}
    issues = check_specificity(result.get("narration") or {}, sensory)
    if issues:
        logger.warning("开场旁白具体性不足: %s", "; ".join(issues))

    return result
