"""
NPC 记忆的 AI 侧端到端测试

需要真实后端（会调用真实模型，产生费用与延迟）。

跑法：
    .venv\\Scripts\\python.exe -m uvicorn main:app --port 8013
    .venv\\Scripts\\python.exe test_npc_memory_ai.py

端口可用环境变量 TEST_BASE 覆盖。

本文件与 test_npc_memory.py 的分工：
    test_npc_memory.py     纯单元测试，不联网，测判定逻辑
    test_npc_memory_ai.py  真实模型，测「模型到底会不会写 update_npc」

为什么必须分开：单元测试能保证「写了就该记下来」，
但不能保证「该写的时候模型真的会写」。
add_companion 当初就是单元测试全过、实测只写 3/8。
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

BASE = os.environ.get("TEST_BASE", "http://127.0.0.1:8013")

_passed = 0
_failed = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"[OK] {name}")
    else:
        _failed += 1
        print(f"[FAIL] {name}" + (f" —— {detail}" if detail else ""))


def get(path: str) -> dict[str, Any]:
    with urllib.request.urlopen(BASE + path, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        BASE + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read().decode("utf-8"))


def build_turn(
    world_data: dict[str, Any],
    *,
    location_id: str = "dorm",
    npc_ids: list[str] | None = None,
    speech: str = "",
    action: str = "",
    memories: list[str] | None = None,
    impressions: list[str] | None = None,
    history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """构造一次 /api/turn 请求体。"""
    loc = next(l for l in world_data["locations"] if l["id"] == location_id)
    npc_by_id = {n["id"]: n for n in world_data["npcs"]}
    ids = npc_ids or [loc["resident_npcs"][0]]
    player = world_data["player_start"]

    npcs = []
    for nid in ids:
        n = npc_by_id[nid]
        npcs.append(
            {
                "id": n["id"],
                "name": n["name"],
                "role": n["role"],
                "age": n["age"],
                "background": n["background"],
                "personality": n["personality"],
                "speech": n["speech"],
                "impression_tags": impressions or [],
                "memories": memories or [],
                "is_companion": nid not in loc["resident_npcs"],
            }
        )

    return {
        "location": {
            "id": loc["id"],
            "name": loc["name"],
            "name_en": loc["name_en"],
            "sensory": loc["sensory"],
            "variant": "",
            "open_hours": loc["open_hours"],
            "resident_npcs": loc["resident_npcs"],
        },
        "npcs": npcs,
        "profile": {"englishLevel": "intermediate", "narrationLanguage": "both"},
        "world_state": {
            "location": location_id,
            "time": {"day": 1, "slot": "morning"},
            "inventory": player["inventory"],
            "facts": player["facts"],
            "knowledge": [],
            "world_title": world_data["world"]["title"],
            "mainline_title": world_data["mainline"]["title"],
            "deadline": world_data["mainline"]["deadline"],
            "companions": [i for i in ids if i not in loc["resident_npcs"]],
            "mainline_lines": world_data.get("mainline_lines", []),
        },
        "world_rules": world_data["world"].get("rules"),
        "history": history or [],
        "player_input": {"speech": speech, "action": action},
    }


def extract_memory(resp: dict[str, Any]) -> tuple[bool, str]:
    """从 /api/turn 响应里取出模型写的记忆，返回 (是否写了, 文本)。"""
    changes = resp.get("world_changes") or {}
    upd = changes.get("update_npc")
    if upd is None:
        return False, ""
    item = upd[0] if isinstance(upd, list) else upd
    if not isinstance(item, dict):
        return False, ""
    return True, (item.get("memory") or item.get("impression") or "")


def reply_text(resp: dict[str, Any]) -> str:
    """
    把响应里的旁白与 NPC 台词拼成一段纯文本。

    narration 是 {"en": ..., "zh": ...}，npc 是 {"content": ...}，
    都不能直接拼字符串。早期版本写 resp.get("npc_reply")，
    拿到的是 dict，一拼就 TypeError。
    """
    parts: list[str] = []
    narr = resp.get("narration")
    if isinstance(narr, dict):
        parts.extend(str(v) for v in narr.values() if v)
    elif isinstance(narr, str):
        parts.append(narr)

    npc = resp.get("npc")
    if isinstance(npc, dict):
        content = npc.get("content")
        if isinstance(content, str):
            parts.append(content)
    elif isinstance(npc, str):
        parts.append(npc)

    return " ".join(parts)


def main() -> int:
    world_data = get("/api/world")

    print("\n── 一、记忆进入 prompt ──")
    resp = post(
        "/api/turn",
        build_turn(
            world_data,
            speech="Hey Sam, do you remember my mug?",
            action="指了指桌上的马克杯",
            memories=["记得你第一天把马克杯忘在水槽里，我帮你收了起来"],
            impressions=["觉得你有点丢三落四，但人挺好"],
        ),
    )
    reply = reply_text(resp)
    check("请求成功返回", bool(reply), f"resp={list(resp.keys())}")
    # 模型不一定复述记忆原文，只要求回应不是第一次见面的口吻
    first_meeting = any(
        w in reply for w in ("第一次见", "初次见面", "Nice to meet", "first time")
    )
    check("带着记忆时不表现出初次见面", not first_meeting, reply[:80])

    print("\n── 二、初次见面要有提示 ──")
    resp = post(
        "/api/turn",
        build_turn(world_data, speech="Hi. I'm new here.", action="站在门口"),
    )
    reply = reply_text(resp)
    check("无记忆时请求成功", bool(reply))

    print("\n── 三、值得记的事要写 update_npc ──")
    memorable = [
        (
            "表露情绪",
            "I really miss home. My mum used to make tea every morning.",
            "把手机屏保翻过来看了一眼",
        ),
        (
            "具体事件",
            "I've got a bruise on my arm from the flight. The suitcase fell on me.",
            "卷起袖子",
        ),
        (
            "承认难处",
            "I don't really understand the enrolment steps. There are too many.",
            "把那张纸翻过来又翻回去",
        ),
    ]
    for name, speech, action in memorable:
        resp = post("/api/turn", build_turn(world_data, speech=speech, action=action))
        wrote, mem = extract_memory(resp)
        check(f"「{name}」写了记忆", wrote, "没写 update_npc")
        if wrote:
            check(f"「{name}」记忆非空", bool(mem.strip()), mem)

    print("\n── 四、不值得记的事不要写 ──")
    forgettable = [
        ("寒暄", "Hi. How are you?", ""),
        ("问价", "How much is this?", "拿起一罐可乐"),
        ("客套道谢", "Thanks. Bye.", "推开门"),
    ]
    for name, speech, action in forgettable:
        resp = post("/api/turn", build_turn(world_data, speech=speech, action=action))
        wrote, mem = extract_memory(resp)
        check(f"「{name}」没写记忆", not wrote, mem)

    print("\n── 五、不在场的 NPC 不能有记忆 ──")
    # Raj 是便利店的，这一回合玩家在宿舍。就算模型写了 raj，
    # 判定器也必须拒收——这是代码的责任，不是模型的责任。
    resp = post(
        "/api/turn",
        build_turn(
            world_data,
            location_id="dorm",
            npc_ids=["sam"],
            speech="I bought a sandwich from Raj earlier.",
            action="",
        ),
    )
    changes = resp.get("world_changes") or {}
    upd = changes.get("update_npc")
    items = upd if isinstance(upd, list) else ([upd] if upd else [])
    wrote_raj = any(isinstance(i, dict) and i.get("npc_id") == "raj" for i in items)
    if wrote_raj:
        judged = post(
            "/api/judge",
            {"player_state": world_data["player_start"], "world_changes": changes},
        )
        rejected = judged.get("rejected", [])
        check(
            "模型给不在场的 raj 写记忆时被拒收",
            any("raj" in r for r in rejected),
            f"rejected={rejected}",
        )
    else:
        check("模型没有给不在场的 raj 写记忆", True)

    print("\n── 六、英语质量评价必须被拒收 ──")
    # 直接构造一条违规提议，验证判定器（不依赖模型会不会写）
    judged = post(
        "/api/judge",
        {
            "player_state": world_data["player_start"],
            "world_changes": {
                "update_npc": {
                    "npc_id": "sam",
                    "memory": "觉得他英语说得很差，语法错误很多",
                }
            },
        },
    )
    check(
        "英语质量评价被拒收",
        any("英语" in r or "质量" in r for r in judged.get("rejected", [])),
        f"rejected={judged.get('rejected')}",
    )

    print("\n" + "=" * 50)
    print(f"通过 {_passed} 项，失败 {_failed} 项")
    if _failed:
        print("FAILED")
        return 1
    print("ALL PASSED")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except urllib.error.URLError as e:
        print(f"无法连接后端 {BASE}：{e}")
        print("请先启动：.venv\\Scripts\\python.exe -m uvicorn main:app --port 8013")
        raise SystemExit(1) from e
