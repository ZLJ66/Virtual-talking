"""
主线判定器端到端测试

跑法（在 backend 目录）：
    .\\.venv\\Scripts\\python.exe test_mainline_api.py

需要后端在 8012 端口运行：
    .\\.venv\\Scripts\\python.exe -m uvicorn main:app --port 8012
"""

from __future__ import annotations

import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8012"

_passed = 0
_failed = 0


def call(path: str, payload: dict | None = None) -> dict:
    url = BASE + path
    if payload is None:
        req = urllib.request.Request(url)
    else:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}
        )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


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


def main() -> int:
    print("=" * 60)
    print("主线判定器 API 测试")
    print("=" * 60)

    world = call("/api/world")
    start = world["player_start"]

    # ── 1. 初始判定 ──
    print("\n[1] 初始状态判定")
    lines = world["mainline_lines"]
    joined = "\n".join(lines)
    check("宿舍里线上注册可办", "现在就可以办" in joined)
    check("注册处的事标为人不在这里", "人不在这里" in joined)
    check("prompt 里不出现内部 id", "registry" not in joined, joined)
    check("progress 总数 4", world["progress"]["total"] == 4)

    # ── 2. 跨地点作弊被拒 ──
    print("\n[2] 在宿舍谎称办完 RTS（应拒绝）")
    r = call(
        "/api/judge",
        {"player_state": start, "world_changes": {"set_fact": {"rts_check_passed": True}}},
    )
    check("没有 applied", r["applied"] == [], str(r["applied"]))
    check("有 rejected", len(r["rejected"]) == 1, str(r["rejected"]))
    check("拒绝原因提到地点", "学校注册处" in r["rejected"][0], r["rejected"][0])
    check("事实未写入", not r["player_state"]["facts"].get("rts_check_passed"))

    # ── 3. 正常完成线上注册 ──
    print("\n[3] 在宿舍完成线上注册")
    r = call(
        "/api/judge",
        {
            "player_state": start,
            "world_changes": {"set_fact": {"pre_enrolment_submitted": True}},
        },
    )
    check("applied 一条", len(r["applied"]) == 1, str(r["applied"]))
    check("completed 含 enrol_online", r["completed"] == ["enrol_online"], str(r["completed"]))
    check("事实已写入", r["player_state"]["facts"].get("pre_enrolment_submitted") is True)
    check("获得 share code", "share code" in r["player_state"]["inventory"],
          str(r["player_state"]["inventory"]))
    check("有给玩家的提示", "办好了" in r["notice"], r["notice"])
    p1 = r["player_state"]

    # ── 4. 材料没带齐 ──
    print("\n[4] 到注册处但没带 share code（应拒绝）")
    p2 = dict(p1)
    p2["location"] = "registry"
    p2["time"] = {"day": 1, "slot": "forenoon"}
    p2["inventory"] = [i for i in p1["inventory"] if i != "share code"]
    r = call(
        "/api/judge",
        {"player_state": p2, "world_changes": {"set_fact": {"rts_check_passed": True}}},
    )
    check("被拒绝", r["applied"] == [], str(r["applied"]))
    check("原因提到 share code", "share code" in r["rejected"][0], r["rejected"][0])

    # ── 5. 材料带齐 ──
    print("\n[5] 带齐材料办 RTS")
    p3 = dict(p2)
    p3["inventory"] = list(p1["inventory"])
    r = call(
        "/api/judge",
        {"player_state": p3, "world_changes": {"set_fact": {"rts_check_passed": True}}},
    )
    check("通过", len(r["applied"]) == 1, str(r["rejected"]))
    p4 = r["player_state"]

    # ── 6. 连办两项 ──
    print("\n[6] 连办学生证 + 在读证明")
    r = call(
        "/api/judge",
        {
            "player_state": p4,
            "world_changes": {
                "set_fact": {"student_card_issued": True, "status_letter_obtained": True}
            },
        },
    )
    check("两项都完成", len(r["completed"]) == 2, str(r["completed"]))
    check("获得学生证", "学生证" in r["player_state"]["inventory"])
    check("获得在读证明", "在读证明" in r["player_state"]["inventory"])
    check("主线全部完成", r["progress"]["done"] == 4, str(r["progress"]))
    check("提示提到主线完成", "主线全部完成" in r["notice"], r["notice"])

    # ── 7. 撤销被拒 ──
    print("\n[7] 试图撤销已完成的事实")
    r = call(
        "/api/judge",
        {"player_state": p4, "world_changes": {"set_fact": {"rts_check_passed": False}}},
    )
    check("被拒绝", "不可撤销" in r["rejected"][0], str(r["rejected"]))

    # ── 8. 越权被拒 ──
    print("\n[8] AI 试图移动玩家 / 推进时间")
    r = call(
        "/api/judge",
        {
            "player_state": start,
            "world_changes": {
                "set_location": "convenience_store",
                "set_time": {"day": 9, "slot": "night"},
            },
        },
    )
    check("两条都被拒绝", len(r["rejected"]) == 2, str(r["rejected"]))
    check("地点未变", r["player_state"]["location"] == "dorm", r["player_state"]["location"])

    # ── 9. 未知事实被拒 ──
    print("\n[9] 未知事实")
    r = call(
        "/api/judge",
        {"player_state": start, "world_changes": {"set_fact": {"god_mode": True}}},
    )
    check("被拒绝", "白名单" in r["rejected"][0], str(r["rejected"]))

    # ── 10. 移动推进时间并判定截止 ──
    print("\n[10] 移动与截止判定")
    mv = call("/api/move", {"player_state": start, "target": "convenience_store"})
    check("移动成功", mv["ok"] is True)
    check("时间已推进", mv["player_state"]["time"]["slot"] == "forenoon",
          str(mv["player_state"]["time"]))
    check("未错过截止", mv["mainline_just_missed"] is False)

    # 把时间拨到截止之后
    late = dict(mv["player_state"])
    late["time"] = {"day": 5, "slot": "evening"}
    mv2 = call("/api/move", {"player_state": late, "target": "dorm"})
    check("跨越截止被捕获", mv2["mainline_just_missed"] is True)
    check("missed 已置位", mv2["player_state"]["mainline_missed"] is True)
    check("progress 反映错过", mv2["progress"]["missed"] is True)

    # ── 11. 错过之后窗口不再拦截 ──
    print("\n[11] 错过截止后仍能办理（因果链无死胡同）")
    p5 = dict(mv2["player_state"])
    p5["location"] = "registry"
    p5["time"] = {"day": 9, "slot": "night"}
    p5["facts"] = {"pre_enrolment_submitted": True}
    p5["inventory"] = ["护照", "CAS 信", "share code", "手机"]
    r = call(
        "/api/judge",
        {"player_state": p5, "world_changes": {"set_fact": {"rts_check_passed": True}}},
    )
    check("逾期仍可办理", len(r["applied"]) == 1, str(r["rejected"]))

    print()
    print("=" * 60)
    print(f"通过 {_passed} 项，失败 {_failed} 项")
    print("=" * 60)
    return 0 if _failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
