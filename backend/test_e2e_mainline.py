"""
主线端到端验证：走完整条主线，验证整条链路而不是单个函数。

三层测试的分工：
  test_mainline.py      纯单元，直接调用判定函数，失败信息指向具体规则
  test_mainline_api.py  走 HTTP，验证接口契约（字段名、状态码、序列化）
  本文件                走完整剧情：移动 → 判定 → 推进 → 逾期，
                        验证这些动作串起来之后世界是否仍然自洽

之所以需要第三层：前两层都假设「一次只有一个动作」，而真实游玩是
连续的。比如「在便利店被拒之后回宿舍能不能办成」这种跨地点的
前后关系，单元测试覆盖不到。

本文件不调用真实模型——那部分在 test_ai_proposal.py。

用法（需要先启动后端）：
    .venv\\Scripts\\python.exe -m uvicorn main:app --port 8012
    .venv\\Scripts\\python.exe test_e2e_mainline.py
"""

import copy
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


def get_world(c):
    r = c.get(f"{API}/api/world")
    r.raise_for_status()
    return r.json()


def judge(c, state, changes):
    r = c.post(
        f"{API}/api/judge",
        json={"player_state": state, "world_changes": changes},
    )
    r.raise_for_status()
    return r.json()


def move(c, state, target):
    r = c.post(
        f"{API}/api/move",
        json={"player_state": state, "target": target},
    )
    r.raise_for_status()
    return r.json()


def wait(c, state):
    r = c.post(f"{API}/api/wait", json={"player_state": state})
    r.raise_for_status()
    return r.json()


def main():
    with httpx.Client(timeout=120) as c:
        w = get_world(c)
        state = w["player_start"]

        print("\n[1] 初始状态")
        check("地点是宿舍", state["location"] == "dorm", state["location"])
        check("事实全为 false", not any(state["facts"].values()), state["facts"])
        check("主线有 4 个节点", w["progress"]["total"] == 4, str(w["progress"]))
        check("4 个节点都还没完成", w["progress"]["done"] == 0, str(w["progress"]))

        print("\n[2] 在宿舍谎称办完 RTS（AI 常犯的错）")
        res = judge(c, state, {"set_fact": {"rts_check_passed": True}})
        check("事实未被写入", not res["player_state"]["facts"]["rts_check_passed"])
        check("被拒绝", len(res["rejected"]) > 0, str(res["rejected"]))
        # 检查顺序里「地点」优先于「前置」：玩家站在宿舍时，
        # 先告诉他站错了地方，比让他去凑前置步骤更有用——
        # 否则他会以为「凑齐前置就能在宿舍办」，白跑一趟。
        reason = res["rejected"][0] if res["rejected"] else ""
        check("原因先提到地点", "注册处" in reason, reason)

        print("\n[3] 移动到便利店")
        res = move(c, state, "convenience_store")
        check("移动成功", res["ok"], res["reason"])
        state = res["player_state"]
        check(
            "时间推进了",
            state["time"] != w["player_start"]["time"],
            str(state["time"]),
        )

        print("\n[4] 在便利店谎称办完 RTS")
        res = judge(c, state, {"set_fact": {"rts_check_passed": True}})
        check("事实未被写入", not res["player_state"]["facts"]["rts_check_passed"])
        check("被拒绝", len(res["rejected"]) > 0, str(res["rejected"]))
        reason = res["rejected"][0] if res["rejected"] else ""
        check("原因提到地点", "注册处" in reason, reason)

        print("\n[5] 回宿舍完成线上注册（合法）")
        res = move(c, state, "dorm")
        state = res["player_state"]
        res = judge(c, state, {"set_fact": {"pre_enrolment_submitted": True}})
        check(
            "事实已写入",
            res["player_state"]["facts"]["pre_enrolment_submitted"],
            str(res["player_state"]["facts"]),
        )
        check("无拒绝", len(res["rejected"]) == 0, str(res["rejected"]))
        check(
            "节点标记完成",
            "完成线上注册" in res["progress"]["done_titles"],
            str(res["progress"]["done_titles"]),
        )
        state = res["player_state"]

        print("\n[6] 前进到注册处（需要白天）")
        res = move(c, state, "registry")
        if not res["ok"]:
            print(f"       注册处未开门（{res['reason']}），原地等待")
            for _ in range(6):
                res = wait(c, state)
                state = res["player_state"]
                if res.get("ok"):
                    break
            res = move(c, state, "registry")
        check("到达注册处", res["ok"], res["reason"])
        state = res["player_state"]
        check("人在注册处", state["location"] == "registry", state["location"])
        check(
            "线上注册已发 share code",
            "share code" in state["inventory"],
            str(state["inventory"]),
        )

        print("\n[7] 注册处但把 CAS 信落在宿舍（缺材料）")
        # 线上注册节点会 grants_items: [share code]，
        # 所以到这里 share code 已经在背包里了。缺的只能是别的。
        state["inventory"] = [i for i in state["inventory"] if i != "CAS 信"]
        res = judge(c, state, {"set_fact": {"rts_check_passed": True}})
        check("事实未被写入", not res["player_state"]["facts"]["rts_check_passed"])
        reason = res["rejected"][0] if res["rejected"] else ""
        check("原因提到材料", "没带" in reason or "材料" in reason, reason)
        check("原因点名缺哪一份", "CAS 信" in reason, reason)

        print("\n[8] 回宿舍拿 CAS 信后再办 RTS Check")
        res = move(c, state, "dorm")
        state = res["player_state"]
        state["inventory"] = list(state["inventory"]) + ["CAS 信"]
        res = move(c, state, "registry")
        state = res["player_state"]
        check("回到注册处", res["ok"], res["reason"])
        res = judge(c, state, {"set_fact": {"rts_check_passed": True}})
        check(
            "事实已写入",
            res["player_state"]["facts"]["rts_check_passed"],
            str(res["rejected"]),
        )
        check("无拒绝", len(res["rejected"]) == 0, str(res["rejected"]))
        state = res["player_state"]

        print("\n[9] 连续领取学生证与在读证明")
        res = judge(c, state, {"set_fact": {"student_card_issued": True}})
        check(
            "学生证已发",
            res["player_state"]["facts"]["student_card_issued"],
            str(res["rejected"]),
        )
        state = res["player_state"]
        res = judge(c, state, {"set_fact": {"status_letter_obtained": True}})
        check(
            "在读证明已拿到",
            res["player_state"]["facts"]["status_letter_obtained"],
            str(res["rejected"]),
        )
        state = res["player_state"]

        print("\n[10] 主线完成度")
        check("4 个节点全部完成", res["progress"]["done"] == 4, str(res["progress"]))
        check("未逾期", not res["progress"]["missed"], str(res["progress"]))
        check(
            "无待办",
            res["progress"]["pending_titles"] == [],
            str(res["progress"]["pending_titles"]),
        )

        print("\n[11] 逾期后仍可办理（防死胡同）")
        # 这里专门验证带 window 的节点。rts_check 的窗口是
        # day1 forenoon ~ day5 afternoon，把时间推到 day9 已远超窗口。
        # 若窗口在逾期后仍然拦截，这个节点就永远做不了 = 死胡同。
        #
        # 必须 deepcopy：dict 赋值只复制引用，直接改 late["time"]
        # 会连带改掉 w["player_start"]，污染后面的用例。
        late = copy.deepcopy(w["player_start"])
        late["time"] = {"day": 9, "slot": "evening"}
        late["location"] = "registry"
        late["inventory"] = list(late["inventory"]) + ["share code"]
        late["facts"] = dict(late["facts"])
        late["facts"]["pre_enrolment_submitted"] = True
        res = judge(c, late, {"set_fact": {"rts_check_passed": True}})
        check("逾期标志出现", res["just_missed"], str(res["progress"]))
        check("窗口不再拦截", res["progress"]["missed"] is True, str(res["progress"]))
        check(
            "仍能完成节点",
            res["player_state"]["facts"]["rts_check_passed"],
            str(res["rejected"]),
        )
        check("提示里有补救路径", len(res["mainline_lines"]) > 0)

        print("\n[11b] 未逾期时窗口照常拦截")
        early = copy.deepcopy(w["player_start"])
        # day1 morning 早于窗口起点 forenoon
        early["location"] = "registry"
        early["inventory"] = list(early["inventory"]) + ["share code"]
        early["facts"] = dict(early["facts"])
        early["facts"]["pre_enrolment_submitted"] = True
        res = judge(c, early, {"set_fact": {"rts_check_passed": True}})
        check(
            "事实未被写入",
            not res["player_state"]["facts"]["rts_check_passed"],
            str(res["player_state"]["time"]),
        )
        reason = res["rejected"][0] if res["rejected"] else ""
        check("原因提到办理时间", "办理" in reason or "时间" in reason, reason)

        print("\n[12] AI 不得移动玩家 / 推进时间")
        res = judge(
            c,
            state,
            {
                "set_location": "registry",
                "set_time": {"day": 99, "slot": "night"},
            },
        )
        check("地点未变", res["player_state"]["location"] == "registry")
        check("时间未变", res["player_state"]["time"] == state["time"])
        check("两条都被拒绝", len(res["rejected"]) == 2, str(res["rejected"]))

    print("\n" + "=" * 60)
    print(f"通过 {passed} 项，失败 {failed} 项")
    print("=" * 60)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
