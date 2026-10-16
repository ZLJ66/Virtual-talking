# AI 引擎：世界引擎 + 英语评估双引擎
# 核心原则："AI 是世界引擎，不是纠错老师"——NPC 容忍错误、猜测意图，反馈不打断沉浸

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

# ── 提示词模板 ────────────────────────────────────

SYSTEM_PROMPT = """\
你是一个沉浸式英语练习的「世界引擎」。你同时扮演两个角色：

## 角色一：世界引擎（驱动剧情）
- 你是故事世界本身，不是 DM，不是旁白，你就是这个正在运行的世界。
- 玩家输入英文来与 NPC 对话，也可以用中文/英文描述动作。
- 你根据玩家输入推进剧情，NPC 的反应要真实、有个性。
- **NPC 会容忍语法错误和笨拙表达**，他们会猜测玩家的意图并自然回应，就像现实中遇到英语不太好的外国人一样——不会纠正语法，而是用自然的英语继续对话。
- 如果玩家用了过于直接或不礼貌的表达，NPC 可以表现出轻微的反应（皱眉、犹豫等），但不会拒绝服务或离开。

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
  "completes_scene": false,
  "world_changes": {}
}
```

### 字段说明
- `narration`: 场景进展的旁白描述，中英双语。简短生动，2-3句话。
- `npc`: NPC 的回应台词。必须是自然口语英语，符合该 NPC 的性格和身份。
- `feedback.understood`: NPC 是否理解了玩家意图（bool）
- `feedback.naturalness`: "good"（地道自然）/ "ok"（能理解但不地道）/ "needs_improvement"（有明显语法错误或中式英语）
- `feedback.naturalness_note`: 自然度评价说明（中文，仅在有改进空间时填写）
- `feedback.appropriateness`: "good"（得体）/ "ok"（稍显直接）/ "needs_improvement"（过于粗鲁或不当）
- `feedback.appropriateness_note`: 得体度说明（仅在有改进空间时填写）
- `feedback.suggested_expression`: 更自然的英文表达（仅当 naturalness 或 appropriateness 不是 good 时给出）
- `feedback.suggestion_reason`: 为什么这个表达更自然/得体（中文，简明）
- `completes_scene`: 当前场景的目标是否已完成（bool）
- `world_changes`: 世界状态变化，支持：
  - `"add_item": "物品名"` — 玩家获得物品
  - `"set_quest": {"id": "quest_id", "status": "active/completed/failed"}` — 任务状态变化
  - `"set_npc": "NPC当前情绪或状态描述"` — NPC 状态更新

### 重要规则
1. NPC 台词必须用自然口语英语，不要太书面化
2. 旁白用第三人称，简短推进剧情
3. 如果玩家输入的是纯中文（在话语框），NPC 应困惑地用英语回应（"I'm sorry, I don't quite understand..."），但仍然尽力帮助
4. 如果玩家只输入了动作没有话语，NPC 根据动作情境自然反应
5. `completes_scene` 只在场景目标明确达成时为 true
6. 不要在 NPC 台词或旁白中提及"英语"或"练习"——保持沉浸
7. 你的 JSON 必须严格合法，不要在 JSON 外输出任何其他内容
"""


def build_user_prompt(
    scene: dict[str, Any],
    profile: dict[str, Any],
    world_state: dict[str, Any],
    history: list[dict[str, str]],
    player_input: dict[str, str],
) -> str:
    """构造包含完整上下文的用户提示"""

    parts: list[str] = []

    # ── 场景信息 ──
    parts.append("## 当前场景")
    parts.append(f"名称：{scene['title']}")
    parts.append(f"描述：{scene['description']}")
    parts.append(f"目标：{scene['goal']}")
    parts.append(f"地点：{scene['location']}")
    if scene.get("npcs"):
        for npc in scene["npcs"]:
            parts.append(f"NPC：{npc['name']}（{npc.get('role', '')}）- {npc.get('personality', '')}")

    # ── 角色信息 ──
    parts.append("\n## 玩家角色")
    parts.append(f"英语水平：{profile.get('englishLevel', 'beginner')}")
    if profile.get("name"):
        parts.append(f"名字：{profile['name']}")

    # ── 世界状态 ──
    if world_state.get("inventory"):
        parts.append(f"\n## 背包物品：{', '.join(world_state['inventory'])}")
    active_quests = [q for q in world_state.get("quests", []) if q.get("status") == "active"]
    if active_quests:
        parts.append(f"进行中任务：{', '.join(q.get('id', '') for q in active_quests)}")

    # ── 对话历史 ──
    if history:
        parts.append("\n## 对话历史（最近几轮）")
        for h in history[-8:]:  # 最多 8 条，避免上下文过长
            parts.append(f"{h['role']}: {h['content']}")

    # ── 当前输入 ──
    parts.append("\n## 玩家当前输入")
    if player_input.get("speech"):
        parts.append(f"话语：{player_input['speech']}")
    if player_input.get("action"):
        parts.append(f"动作：{player_input['action']}")
    if not player_input.get("speech") and not player_input.get("action"):
        parts.append("（无输入，仅有动作）")

    return "\n".join(parts)


# ── 场景开场提示词 ─────────────────────────────────

OPENING_SYSTEM_PROMPT = """\
你是一个沉浸式英语练习的「世界引擎」。你正在为一个新的场景生成开场旁白和 NPC 对话。

输出格式同上，但不需要 feedback 字段（设为 null）。只需要：
```json
{
  "narration": { "en": "...", "zh": "..." },
  "npc": { "speaker_id": "...", "speaker_name": "...", "content": "..." },
  "feedback": null,
  "completes_scene": false,
  "world_changes": {}
}
```

规则：
1. 旁白自然过渡到新场景，如果有上一场景的信息，做自然衔接
2. NPC 的开场白要符合场景，自然引入互动
3. 保持简短，旁白 2-3 句，NPC 台词 1-2 句
4. 严格输出合法 JSON，不要输出其他内容
"""


# ── AI 调用核心 ────────────────────────────────────

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
    body = {
        "model": AI_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

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
            logger.warning("AI 调用失败（第 %d/%d 次）: %s — %ds 后重试", attempt, max_retries, e, wait)
            await asyncio.sleep(wait)

    raise RuntimeError(f"AI 调用失败，已重试 {max_retries} 次: {last_error}") from last_error


def parse_ai_response(raw: str) -> dict[str, Any]:
    """从 AI 原始响应中提取 JSON，容忍 markdown 代码块包裹"""

    text = raw.strip()

    # 去掉 markdown 代码块包裹（如 ```json ... ```）
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
        # 尝试找到 JSON 起止位置
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass
        raise ValueError(f"AI 返回了无法解析的 JSON: {text[:200]}") from e


async def generate_turn(
    scene: dict[str, Any],
    profile: dict[str, Any],
    world_state: dict[str, Any],
    history: list[dict[str, str]],
    player_input: dict[str, str],
) -> dict[str, Any]:
    """
    生成一个回合的 AI 响应（旁白 + NPC 对话 + 英语反馈）

    返回结构：
    {
        "narration": { "en": ..., "zh": ... },
        "npc": { "speaker_id": ..., "speaker_name": ..., "content": ... },
        "feedback": { ... } | null,
        "completes_scene": bool,
        "world_changes": { ... }
    }
    """
    user_prompt = build_user_prompt(scene, profile, world_state, history, player_input)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    raw = await call_ai(messages, temperature=0.8, max_tokens=2048)
    result = parse_ai_response(raw)

    # 确保必要字段存在
    result.setdefault("narration", {"en": "", "zh": ""})
    result.setdefault("npc", {"speaker_id": "unknown", "speaker_name": "???", "content": "..."})
    result.setdefault("feedback", None)
    result.setdefault("completes_scene", False)
    result.setdefault("world_changes", {})

    return result


async def generate_opening(
    scene: dict[str, Any],
    profile: dict[str, Any],
    prev_scene_summary: str | None = None,
) -> dict[str, Any]:
    """
    生成场景开场旁白和 NPC 对话

    返回结构同 generate_turn，但 feedback 为 null
    """
    parts: list[str] = []
    parts.append("## 新场景")
    parts.append(f"名称：{scene['title']}")
    parts.append(f"描述：{scene['description']}")
    parts.append(f"目标：{scene['goal']}")
    parts.append(f"地点：{scene['location']}")
    if scene.get("npcs"):
        for npc in scene["npcs"]:
            parts.append(f"NPC：{npc['name']}（{npc.get('role', '')}）- {npc.get('personality', '')}")
    parts.append(f"\n玩家英语水平：{profile.get('englishLevel', 'beginner')}")
    if prev_scene_summary:
        parts.append(f"\n上一场景总结：{prev_scene_summary}")

    messages = [
        {"role": "system", "content": OPENING_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(parts)},
    ]

    raw = await call_ai(messages, temperature=0.7, max_tokens=1536)
    result = parse_ai_response(raw)

    result.setdefault("narration", {"en": "", "zh": ""})
    result.setdefault("npc", {"speaker_id": "unknown", "speaker_name": "???", "content": "..."})
    result.setdefault("feedback", None)
    result.setdefault("completes_scene", False)
    result.setdefault("world_changes", {})

    return result
