"""多人对话测试：验证 AI 会不会按玩家对不同人说的话拆成多句。

背景：玩家实测发现两个问题——
  1. 一段话里先对 A 说、再对 B 说，AI 把两件事都当成对 A 说的
  2. 多个 NPC 在场时，永远只有一个人说话，另一人从不插话

根因是输出契约只有单个 `npc` 对象，模型即使理解也**没有地方放第二句**。
改成 `lines` 数组后，这里验证模型是否真的会用。

运行：先起后端（默认 8000），然后
    python test_multi_speaker.py
端口不同时：TEST_BASE=http://localhost:8011 python test_multi_speaker.py
"""

from __future__ import annotations

import os
import sys

import httpx

BASE = os.getenv("TEST_BASE", "http://localhost:8000")

LOCATION = {
    "id": "convenience_store",
    "name": "便利店",
    "name_en": "Corner Shop",
    "sensory": {
        "sight": "冷柜的白光照着货架，第三层空了一格",
        "sound": "冰柜嗡嗡低鸣，门铃偶尔响一声",
        "smell": "纸箱和洗衣粉混在一起的味道",
        "touch": "门把手很凉",
        "temperature": "比外面暖一些",
    },
    "variant": "傍晚，店里没什么人",
    "open_hours": [0, 24],
    "resident_npcs": ["raj"],
}

NPCS = [
    {
        "id": "raj",
        "name": "Raj",
        "role": "店主",
        "age": 54,
        "background": "印度裔，在这条街开店二十年",
        "personality": "话少，观察力强，对熟客放松",
        "speech": {
            "style": "句子很短",
            "accent": "印度口音",
            "catchphrase": "mate",
            "tone": "平和",
        },
        "impression_tags": [],
        "memories": [],
        "is_companion": False,
    },
    {
        "id": "sam",
        "name": "Sam",
        "role": "室友",
        "age": 19,
        "background": "本地学生，刚认识",
        "personality": "话多，爱开玩笑，有点自来熟",
        "speech": {
            "style": "语速快，句子连成串",
            "accent": "曼彻斯特口音",
            "catchphrase": "You alright?",
            "tone": "随意",
        },
        "impression_tags": [],
        "memories": [],
        "is_companion": True,
    },
]


def base_world_state() -> dict:
    return {
        "time": {"day": 1, "slot": "evening"},
        "facts": {},
        "knowledge": [],
        "npc_states": {},
    }


def post_turn(speech: str, action: str, history: list[dict] | None = None) -> dict:
    payload = {
        "location": LOCATION,
        "npcs": NPCS,
        "profile": {
            "englishLevel": "intermediate",
            "learningGoal": "daily",
            "practiceMode": "immersive",
        },
        "world_state": base_world_state(),
        "world_rules": None,
        "history": history or [],
        "player_input": {"speech": speech, "action": action},
    }
    r = httpx.post(f"{BASE}/api/turn", json=payload, timeout=90.0)
    if r.status_code >= 400:
        print(f"HTTP {r.status_code}: {r.text[:800]}")
    r.raise_for_status()
    return r.json()


def show(tag: str, resp: dict) -> list[dict]:
    lines = resp.get("lines") or []
    print(f"\n{'=' * 66}\n{tag}\n{'=' * 66}")
    print(f"旁白：{resp['narration']['zh'][:100]}")
    for i, ln in enumerate(lines):
        to = ln.get("reply_to", "?")
        to_zh = "玩家" if to == "player" else to
        print(f"  [{i}] {ln['speaker_name']}（→{to_zh}）: {ln['content']}")
    print(f"  → 共 {len(lines)} 句")
    return lines


def check(tag: str, ok: bool, detail: str = "") -> bool:
    print(f"  {'[PASS]' if ok else '[FAIL]'} {tag}{(' — ' + detail) if detail else ''}")
    return ok


def main() -> int:
    print(f"目标后端：{BASE}")
    results: list[bool] = []

    # ── 用例 1：一段话对两个人说，动作里指明先问谁 ──
    resp = post_turn(
        speech="How much is this? And Sam, what do you think of this brand?",
        action="先把罐头举给 Raj 看，然后转向 Sam",
    )
    lines = show("用例1：对两个人分别说话（价格问 Raj，意见问 Sam）", resp)
    results.append(
        check("拆成 2 句以上", len(lines) >= 2, f"实际 {len(lines)} 句")
    )
    speakers = {ln["speaker_id"] for ln in lines}
    results.append(
        check("两个 NPC 都说话了", len(speakers) >= 2, f"说话者 {speakers}")
    )
    results.append(
        check("第 1 句回应玩家", lines[0].get("reply_to") == "player")
    )

    # ── 用例 2：问一个两边都有关的问题，应触发 NPC 互相接话 ──
    resp = post_turn(
        speech="You two know each other?",
        action="看看 Raj，又看看 Sam",
    )
    lines = show("用例2：问「你们俩认识吗」（两边都有关）", resp)
    results.append(check("至少 2 句", len(lines) >= 2, f"实际 {len(lines)} 句"))
    results.append(check("第 1 句回应玩家", lines[0].get("reply_to") == "player"))

    # ── 用例 3：只问一个人，被问的人必须直接回答 ──
    #
    # 这里不断言「只能有 1 句」：实测 Sam 会补一句
    # 「I was looking for something smaller too」，这是同行者自然的插话，
    # 正是我们要的行为（用户明确要求「NPC 有时候也应该会插话」）。
    # 真正要防的是「被问的人不回答、由别人代答」和「每回合都硬凑两句」。
    resp = post_turn(
        speech="Do you have this in a smaller size?",
        action="把罐头放回货架",
    )
    lines = show("用例3：只问 Raj（被问者必须直接回答）", resp)
    results.append(
        check(
            "第 1 句是 Raj 说的",
            lines[0]["speaker_id"] == "raj",
            f"实际 {lines[0]['speaker_id']}",
        )
    )
    results.append(check("第 1 句回应玩家", lines[0].get("reply_to") == "player"))

    # ── 用例 4：只对 Sam 说话，不该由 Raj 抢答 ──
    resp = post_turn(
        speech="Sam, are you coming to the enrolment thing tomorrow?",
        action="转头只对 Sam 说",
    )
    lines = show("用例4：只对同行者 Sam 说话", resp)
    results.append(
        check(
            "第 1 句是 Sam 说的",
            lines[0]["speaker_id"] == "sam",
            f"实际 {lines[0]['speaker_id']}",
        )
    )

    # ── 用例 5：历史里两个 NPC 都说过话，模型要能分清 ──
    history = [
        {"role": "player", "content": "How much is this?"},
        {"role": "npc", "content": "Raj: Two pounds fifty, mate."},
        {"role": "player", "content": "Sam, you want one too?"},
        {"role": "npc", "content": "Sam: Nah, I'm skint."},
    ]
    resp = post_turn(
        speech="What does skint mean?",
        action="看着 Sam",
        history=history,
    )
    lines = show("用例5：历史含两个说话人（应知道在问谁）", resp)
    results.append(
        check(
            "回应者是 Sam",
            lines[0]["speaker_id"] == "sam",
            f"实际 {lines[0]['speaker_id']}",
        )
    )

    passed = sum(1 for r in results if r)
    print(f"\n{'=' * 66}\n结果：{passed}/{len(results)} 通过\n{'=' * 66}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
