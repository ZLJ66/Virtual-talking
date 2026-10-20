"""
主线判定器单元测试（不依赖 HTTP 服务器）

跑法（在 backend 目录）：
    $env:PYTHONIOENCODING='utf-8'
    .\\.venv\\Scripts\\python.exe test_mainline.py

为什么要有这一份，而不只有 test_mainline_api.py：
API 测试覆盖的是「接口能不能用」，这一份覆盖的是「判定逻辑本身对不对」。
前者要起服务器、慢、失败时看不出是哪条规则错了；
后者是纯函数调用，失败信息直接指向具体规则。

项目没有 pytest，沿用 test_specificity.py 的手写断言风格。
"""

from __future__ import annotations

from world_loader import build_initial_player_state, load_world
from mainline import (
    NodeState,
    evaluate_all,
    evaluate_node,
    judge,
    mainline_progress,
    prompt_lines,
)
from main import _build_notice as build_notice
from world_models import PlayerState, TimeSlot, WorldTime

_passed = 0
_failed = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  [OK] {label}")
    else:
        _failed += 1
        print(f"  [FAIL] {label}")
        if detail:
            print(f"         {detail}")


def node_by_id(world, node_id: str):
    for n in world.mainline.nodes:
        if n.id == node_id:
            return n
    raise KeyError(node_id)


def main() -> int:
    content = load_world()
    world = content.world
    start = build_initial_player_state(content)

    print("=" * 60)
    print("主线判定器单元测试")
    print("=" * 60)

    # ── 1. 初始状态：每个节点的判定理由 ──
    print("\n[1] 初始状态判定")
    statuses = {s.node.id: s for s in evaluate_all(world, start)}
    check(
        "宿舍里线上注册可办",
        statuses["enrol_online"].state is NodeState.AVAILABLE,
        str(statuses["enrol_online"].state),
    )
    check(
        "注册处的事判定为「人不在这里」",
        statuses["rts_check"].state is NodeState.WRONG_LOCATION,
        str(statuses["rts_check"].state),
    )
    check(
        "地点名是中文",
        statuses["rts_check"].location_name == "学校注册处",
        statuses["rts_check"].location_name,
    )

    # ── 2. 检查优先级：地点优先于前置事实 ──
    print("\n[2] 检查优先级")
    # 玩家在宿舍、前置事实未完成 —— 应该先报「人不在这里」，
    # 而不是「前置步骤没完成」。否则玩家会以为要先做前置，
    # 做了之后才发现还要跑一趟注册处，白跑。
    check(
        "人在错的地方时先报地点",
        statuses["rts_check"].state is NodeState.WRONG_LOCATION,
    )

    # ── 3. 前置事实缺失 ──
    print("\n[3] 在注册处但前置未完成")
    p = start.model_copy(deep=True)
    p.location = "registry"
    p.time = WorldTime(day=1, slot=TimeSlot.FORENOON)
    p.inventory = ["护照", "CAS 信", "share code"]
    st = evaluate_node(node_by_id(world, "rts_check"), p, world)
    check("报前置步骤没完成", st.state is NodeState.MISSING_FACTS, str(st.state))
    check("原因里没有内部 fact id", "pre_enrolment" not in st.reason, st.reason)

    # ── 4. 材料缺失 ──
    print("\n[4] 前置完成但材料没带")
    p2 = p.model_copy(deep=True)
    p2.facts = dict(p2.facts, pre_enrolment_submitted=True)
    p2.inventory = ["护照", "CAS 信"]  # 缺 share code
    st = evaluate_node(node_by_id(world, "rts_check"), p2, world)
    check("报材料没带齐", st.state is NodeState.MISSING_ITEMS, str(st.state))
    check("原因里点名缺的东西", "share code" in st.reason, st.reason)

    # ── 5. 条件全满足 ──
    print("\n[5] 条件全满足")
    p3 = p2.model_copy(deep=True)
    p3.inventory = ["护照", "CAS 信", "share code"]
    st = evaluate_node(node_by_id(world, "rts_check"), p3, world)
    check("判定为可办", st.state is NodeState.AVAILABLE, str(st.state))
    check("可办时无需解释", st.reason == "", st.reason)

    # ── 6. 判定器拒绝跨地点写入 ──
    print("\n[6] AI 在宿舍声称办完 RTS")
    r = judge(
        world,
        start,
        {"set_fact": {"rts_check_passed": True}},
    )
    check("没有 applied", r.applied == [], str(r.applied))
    check("有一条 rejected", len(r.rejected) == 1, str(r.rejected))
    check("事实未写入", not r.player.facts.get("rts_check_passed"))
    check("玩家状态未被改动", r.player.location == start.location)

    # ── 7. 判定器拒绝撤销 ──
    print("\n[7] 撤销已完成的事实")
    done_state = start.model_copy(deep=True)
    done_state.facts = dict(done_state.facts, pre_enrolment_submitted=True)
    r = judge(world, done_state, {"set_fact": {"pre_enrolment_submitted": False}})
    check("被拒绝", len(r.rejected) == 1, str(r.rejected))
    check("原因提到不可撤销", "不可撤销" in r.rejected[0], r.rejected[0])
    check("事实仍为 true", r.player.facts["pre_enrolment_submitted"] is True)

    # ── 8. 拒绝 AI 移动玩家 / 推进时间 ──
    print("\n[8] AI 越权")
    r = judge(
        world,
        start,
        {"set_location": "registry", "set_time": {"day": 9, "slot": "night"}},
    )
    check("两条都拒绝", len(r.rejected) == 2, str(r.rejected))
    check("地点未变", r.player.location == "dorm", r.player.location)
    check("时间未变", r.player.time.day == 1, str(r.player.time.day))

    # ── 9. 拒绝未知事实 ──
    print("\n[9] 白名单外的事实")
    r = judge(world, start, {"set_fact": {"god_mode": True}})
    check("被拒绝", len(r.rejected) == 1, str(r.rejected))
    check("原因提到白名单", "白名单" in r.rejected[0], r.rejected[0])

    # ── 10. 正常完成一个节点 ──
    print("\n[10] 完成线上注册")
    r = judge(world, start, {"set_fact": {"pre_enrolment_submitted": True}})
    check("applied 一条", len(r.applied) == 1, str(r.applied))
    check("completed 记录节点", r.completed == ["enrol_online"], str(r.completed))
    check("事实写入", r.player.facts["pre_enrolment_submitted"] is True)
    check("获得了 share code", "share code" in r.player.inventory, str(r.player.inventory))
    # notice 由 main._build_notice 生成（面向玩家的措辞），不在 JudgeResult 上。
    # 这里直接调它，保证「办好了」这句话确实存在。
    notice = build_notice(world, r)
    check("有给玩家的提示", bool(notice), repr(notice))
    check("提示提到办好了", "办好了" in notice, notice)

    # ── 11. 一次提交多个事实 ──
    print("\n[11] 一次递交两项")
    p4 = r.player.model_copy(deep=True)
    p4.location = "registry"
    p4.time = WorldTime(day=2, slot=TimeSlot.FORENOON)
    p4.inventory = ["护照", "CAS 信", "share code"]
    p4.facts = dict(p4.facts, rts_check_passed=True)
    r2 = judge(
        world,
        p4,
        {"set_fact": {"student_card_issued": True, "status_letter_obtained": True}},
    )
    check("两项都完成", len(r2.completed) == 2, str(r2.completed))
    check("获得学生证", "学生证" in r2.player.inventory)
    check("获得在读证明", "在读证明" in r2.player.inventory)
    prog = mainline_progress(world, r2.player)
    check("主线全部完成", prog["done"] == 4, str(prog))

    # ── 12. 截止与错过 ──
    print("\n[12] 截止时间")
    p5 = start.model_copy(deep=True)
    p5.time = WorldTime(day=5, slot=TimeSlot.NOON)  # 截止是 afternoon
    check("截止前不算错过", not mainline_progress(world, p5)["missed"])

    p6 = start.model_copy(deep=True)
    p6.time = WorldTime(day=5, slot=TimeSlot.EVENING)  # 已过 afternoon
    check("截止后算错过", mainline_progress(world, p6)["missed"])

    p7 = start.model_copy(deep=True)
    p7.time = WorldTime(day=9, slot=TimeSlot.MORNING)
    p7.mainline_missed = False
    r3 = judge(world, p7, {})
    check("judge 检测到错过", r3.just_missed is True)
    check("写入 missed 标记", r3.player.mainline_missed is True)

    # ── 13. 错过之后不再重复报 ──
    print("\n[13] 错过只报一次")
    p8 = p7.model_copy(deep=True)
    p8.mainline_missed = True
    r4 = judge(world, p8, {})
    check("已标记过则不再报", r4.just_missed is False)

    # ── 14. 因果链无死胡同 ──
    print("\n[14] 错过截止后仍能办理")
    p9 = start.model_copy(deep=True)
    p9.location = "registry"
    p9.time = WorldTime(day=20, slot=TimeSlot.FORENOON)
    p9.mainline_missed = True
    p9.facts = dict(p9.facts, pre_enrolment_submitted=True)
    p9.inventory = ["护照", "CAS 信", "share code"]
    st = evaluate_node(node_by_id(world, "rts_check"), p9, world)
    check(
        "逾期后节点仍可办（不永久卡死）",
        st.state is NodeState.AVAILABLE,
        str(st.state),
    )

    # ── 15. prompt 里不出现内部 id ──
    print("\n[15] prompt 可读性")
    lines = prompt_lines(world, start)
    text = "\n".join(lines)
    check("有主线标题", "安顿下来" in text)
    check("有截止时间", "第 5 天" in text)
    check("不出现 registry", "registry" not in text, text)
    check("不出现 dorm", "dorm" not in text, text)

    # 事实 id 只允许出现在「本回合可能写入的事实」区块里。
    # 那一块是给模型的机器指令，混进叙事行会被当台词念给玩家听，
    # 所以两块必须分开——这里验证叙事部分干净。
    narrative = "\n".join(lines).split("## 本回合可能写入的事实")[0]
    check(
        "叙事部分不含 fact id",
        "pre_enrolment_submitted" not in narrative,
        narrative,
    )
    check(
        "机器指令块给出可抄的 id",
        "pre_enrolment_submitted" in text,
        "开局在宿舍，线上注册可办，应给出对应 id",
    )

    # ── 16. 同行者 ──
    print("\n[16] 同行者校验")
    r5 = judge(world, start, {"add_companion": "sam"})
    check("合法 NPC 可加入", "sam" in r5.player.companions, str(r5.player.companions))
    r6 = judge(world, start, {"add_companion": "nobody"})
    check("未知 NPC 被拒绝", len(r6.rejected) == 1, str(r6.rejected))
    check("未加入", "nobody" not in r6.player.companions)

    print()
    print("=" * 60)
    print(f"通过 {_passed} 项，失败 {_failed} 项")
    print("=" * 60)
    return 0 if _failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
