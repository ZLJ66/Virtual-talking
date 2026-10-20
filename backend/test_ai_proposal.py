"""
真实 AI 提议验证：模型会不会在正确时机提议 set_fact。

前三层测试都用手工构造的 changes，测的是「判定器对不对」。
本文件测的是另一个问题：**AI 会不会提议**。

这层必须用真实模型，无法 mock：
  - mock 只能验证「拿到提议之后怎么办」
  - 拿不到提议时判定器再完美也没用（事实永远不写入）

历史教训：同行 NPC 的 add_companion 曾经只有 38% 触发率，
原因是 prompt 里写了「不要滥用」这条负面约束，模型变得过度保守。
这类问题只有跑真实模型才能发现。

用法：
    .venv\\Scripts\\python.exe -m uvicorn main:app --port 8012
    .venv\\Scripts\\python.exe test_ai_proposal.py
"""

import sys

import httpx

API = "http://127.0.0.1:8012"

passed = 0
failed = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  [OK] {label}")
    else:
        failed += 1
        print(f"  [FAIL] {label}")
        if detail:
            print(f"        {detail}")


def build_state(w, *, location, day=1, slot="forenoon", inventory=None, facts=None):
    """从 world 的 player_start 派生一个状态"""
    return {
        "location": location,
        "time": {"day": day, "slot": slot},
        "inventory": inventory if inventory is not None else ["护照", "CAS 信", "手机"],
        "facts": facts or dict(w["facts"]),
        "knowledge": [],
        "npc_states": {},
        "companions": [],
        "visit_counts": {},
        "last_visit": {},
    }


def turn(c, w, state, speech, action="", history=None):
    """走一次 AI 回合（不判定）"""
    loc = next(l for l in w["locations"] if l["id"] == state["location"])
    npcs = [n for n in w["npcs"] if n["id"] in loc["resident_npcs"]]

    r = c.post(
        f"{API}/api/turn",
        json={
            "location": loc,
            "npcs": npcs,
            "profile": {"name": "Lin", "englishLevel": "intermediate"},
            "world_state": {
                **state,
                "world_title": w["world"]["title"],
                "mainline_title": w["mainline"]["title"],
                "deadline": w["mainline"]["deadline"],
            },
            "world_rules": w["world"]["rules"],
            "history": history or [],
            "player_input": {"speech": speech, "action": action},
        },
    )
    r.raise_for_status()
    return r.json()


def judge(c, state, changes):
    r = c.post(
        f"{API}/api/judge",
        json={"player_state": state, "world_changes": changes},
    )
    r.raise_for_status()
    return r.json()


def main():
    with httpx.Client(timeout=180) as c:
        w = c.get(f"{API}/api/world").json()

        # ── 场景 1：注册处办 RTS Check，需要多轮才办完 ──
        #
        # 第一轮实测 NPC 回的是「请把文件放到扫描仪上，我需要核对」——
        # 交互还没结束，模型不提议 set_fact 是对的。
        # 所以这里必须走完整流程，而不是用一轮就下结论。
        print("\n[1] 注册处：递材料 → 核对 → 确认（多轮）")
        state = build_state(
            w,
            location="registry",
            day=2,
            facts={**dict(w["facts"]), "pre_enrolment_submitted": True},
            inventory=["护照", "CAS 信", "share code", "手机"],
        )
        history = []
        proposed = {}
        turns = [
            (
                "你好，我来做 Right to Study 检查。这是我的护照、CAS 信和 share code。",
                "把三份文件放在扫描仪上",
            ),
            ("当然，都在这儿了。还需要别的吗？", "把文件推过去"),
            ("好的，谢谢。那我接下来要做什么？", ""),
        ]
        for i, (speech, action) in enumerate(turns, 1):
            res = turn(c, w, state, speech, action, history)
            changes = res.get("world_changes") or {}
            print(f"        第{i}轮 NPC：{res['npc'].get('content', '')[:80]}")
            print(f"        第{i}轮 changes：{changes}")
            if changes.get("set_fact"):
                proposed = changes
                break
            history.append(
                {"role": "player", "content": speech}
            )
            history.append(
                {"role": "npc", "content": res["npc"].get("content", "")}
            )

        check(
            "AI 最终提议了 set_fact",
            bool(proposed.get("set_fact")),
            f"三轮都没有提议",
        )
        check(
            "提议的是 rts_check_passed",
            "rts_check_passed" in (proposed.get("set_fact") or {}),
            str(proposed.get("set_fact")),
        )

        print("\n[2] 提议交给判定器后事实成立")
        jr = judge(c, state, proposed)
        check(
            "事实已写入",
            jr["player_state"]["facts"]["rts_check_passed"],
            str(jr["rejected"]),
        )
        check("无拒绝", len(jr["rejected"]) == 0, str(jr["rejected"]))

        # ── 场景 2：闲聊不该产生主线事实 ──
        print("\n[3] 宿舍里聊聊天，不该产生主线事实")
        state2 = build_state(w, location="dorm")
        res = turn(c, w, state2, "嗨 Sam，我刚到。这附近有什么吃的吗？")
        changes2 = res.get("world_changes") or {}
        print(f"        changes：{changes2}")
        check(
            "没有乱写主线事实",
            not (changes2.get("set_fact") or {}),
            str(changes2.get("set_fact")),
        )

        # ── 场景 3：只在嘴上说办好了 ──
        print("\n[4] 玩家只在嘴上说办好了（无实际行动）")
        state3 = build_state(w, location="dorm")
        res = turn(
            c,
            w,
            state3,
            "I already did my Right to Study check last week.",
        )
        changes3 = res.get("world_changes") or {}
        print(f"        changes：{changes3}")
        # 即使 AI 信了并提议，判定器也必须拒绝——这里验证的是双层防御
        jr3 = judge(c, state3, changes3)
        check(
            "判定器拒绝（人在宿舍）",
            not jr3["player_state"]["facts"]["rts_check_passed"],
            str(jr3["rejected"]),
        )
        if changes3.get("set_fact"):
            print(f"        （AI 确实提议了：{changes3['set_fact']}，被判定器拦下）")
            check("确实被拦下", len(jr3["rejected"]) > 0, str(jr3["rejected"]))

    print("\n" + "=" * 60)
    print(f"通过 {passed} 项，失败 {failed} 项")
    print("=" * 60)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
