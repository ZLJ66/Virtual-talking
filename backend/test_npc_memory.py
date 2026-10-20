"""
NPC 记忆与印象标签的单元测试

设计依据：《世界层设计.md》4.4 / 4.5

分三层验证：
1. 数据结构层 —— NPCState 的容量上限与淘汰策略
2. 校验层 —— 什么能记、什么不能记（这是红线所在）
3. 集成层 —— 节点完成时自动写入记忆

跑法：.venv\\Scripts\\python.exe test_npc_memory.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from mainline import judge
from npc_memory import (
    MAX_IMPRESSION_CHARS,
    MAX_MEMORY_CHARS,
    MAX_UPDATES_PER_TURN,
    apply_update_npc,
    present_npc_ids,
    remember_node_completion,
)
from world_loader import build_initial_player_state, load_world, move_to
from world_models import NPCState, TimeSlot, WorldTime

_passed = 0
_failed = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"[OK] {label}")
    else:
        _failed += 1
        print(f"[FAIL] {label}" + (f"\n       {detail}" if detail else ""))


# ══════════════════════════════════════════════════════════
#  一、数据结构层
# ══════════════════════════════════════════════════════════


def test_npc_state_capacity() -> None:
    print("\n── 一、数据结构层 ──")

    # 记忆上限 12，超出淘汰最旧的
    s = NPCState()
    for i in range(20):
        s.add_memory(f"记忆{i}")
    check(
        f"记忆上限 {NPCState.MAX_MEMORIES} 条",
        len(s.memories) == NPCState.MAX_MEMORIES,
        f"实际 {len(s.memories)} 条",
    )
    check(
        "记忆淘汰最旧的（保留最近 12 条）",
        s.memories[-1] == "记忆19" and s.memories[0] == "记忆8",
        f"首条 {s.memories[0]}，末条 {s.memories[-1]}",
    )

    # 印象标签上限 8，保留最早一条 + 最近 7 条
    s2 = NPCState()
    for i in range(12):
        s2.add_impression(f"印象{i}")
    check(
        f"印象上限 {NPCState.MAX_TAGS} 条",
        len(s2.impression_tags) == NPCState.MAX_TAGS,
        f"实际 {len(s2.impression_tags)} 条",
    )
    check(
        "印象保留第一印象（印象0）",
        s2.impression_tags[0] == "印象0",
        f"首条 {s2.impression_tags[0]}",
    )
    check(
        "印象保留最近的（印象11）",
        s2.impression_tags[-1] == "印象11",
        f"末条 {s2.impression_tags[-1]}",
    )

    # 重复写入不产生副本
    s3 = NPCState()
    s3.add_memory("同一件事")
    s3.add_memory("同一件事")
    check("重复记忆不重复写入", len(s3.memories) == 1, f"实际 {len(s3.memories)} 条")

    # 空白内容被忽略
    s4 = NPCState()
    s4.add_memory("   ")
    s4.add_impression("")
    check("空白内容不写入", s4.is_empty())


# ══════════════════════════════════════════════════════════
#  二、校验层：什么不能记
# ══════════════════════════════════════════════════════════


def test_rejections(world, player) -> None:
    print("\n── 二、校验层：拒收规则 ──")

    def rejected(memory: str, npc_id: str = "sam") -> bool:
        _, rej = apply_update_npc(
            world, player, {"update_npc": {"npc_id": npc_id, "memory": memory}}
        )
        return len(rej) > 0

    # 硬红线 1：英语表达质量（产品文档 1.3 硬约束 1）
    quality_cases = [
        "觉得他英语说得不好",
        "记得他语法错了三次",
        "知道他的口音很重",
        "觉得他的用词不地道",
        "记得他发音不准",
    ]
    for case in quality_cases:
        check(f"拒收英语质量评价：{case}", rejected(case))

    # 硬红线 2：道德评判（设计文档 4.4：只记录行为，不记录评价）
    judgment_cases = ["觉得他没礼貌", "认为他很粗鲁", "觉得这人很差劲"]
    for case in judgment_cases:
        check(f"拒收道德评判：{case}", rejected(case))

    # 硬红线 3：元词汇
    meta_cases = ["玩家说想找注册处", "用户问了很多问题", "AI 判断他很紧张"]
    for case in meta_cases:
        check(f"拒收元词汇：{case}", rejected(case))

    # 硬红线 4：不在场
    check(
        "拒收不在场者的记忆（raj 不在宿舍）",
        rejected("知道他常来买三明治", npc_id="raj"),
    )

    # 硬红线 5：不存在的 NPC
    check("拒收不存在的 NPC", rejected("某件事", npc_id="nobody"))

    # 长度
    check(
        f"拒收超过 {MAX_MEMORY_CHARS} 字的记忆",
        rejected("记" * (MAX_MEMORY_CHARS + 1)),
    )
    check(
        "接受刚好等于上限的记忆",
        not rejected("记" * MAX_MEMORY_CHARS),
    )
    check(
        f"拒收超过 {MAX_IMPRESSION_CHARS} 字的印象",
        len(
            apply_update_npc(
                world,
                player,
                {"update_npc": {"npc_id": "sam", "impression": "印" * (MAX_IMPRESSION_CHARS + 1)}},
            )[1]
        )
        > 0,
    )

    # 空内容
    check(
        "拒收空记忆",
        len(apply_update_npc(world, player, {"update_npc": {"npc_id": "sam"}})[1]) > 0,
    )


def test_acceptance(world, player) -> None:
    print("\n── 三、校验层：可接受的内容 ──")

    good_cases = [
        "记得你第一天拖着两个行李箱进门，先问的是插座在哪",
        "知道你拒绝了推荐的芝士味，选了原味",
        "记得你把伞落在柜台，第二天回来取",
        "知道你想家，提过家里的猫",
    ]
    for case in good_cases:
        applied, rej = apply_update_npc(
            world, player, {"update_npc": {"npc_id": "sam", "memory": case}}
        )
        check(f"接受：{case[:18]}…", len(applied) == 1 and not rej, f"applied={applied} rej={rej}")

    # 行为描述（不含评价）应当接受
    applied, rej = apply_update_npc(
        world,
        player,
        {"update_npc": {"npc_id": "sam", "memory": "记得他把杯子推回柜台就走了"}},
    )
    check("接受纯行为描述（不含道德评价）", len(applied) == 1 and not rej)

    # impression 与 memory 同时写
    applied, rej = apply_update_npc(
        world,
        player,
        {
            "update_npc": {
                "npc_id": "sam",
                "memory": "记得你帮他搬了箱子",
                "impression": "觉得你是个热心的人",
            }
        },
    )
    check("同时写记忆与印象", len(applied) == 2 and not rej, f"applied={applied}")


def test_person_normalization(world, player) -> None:
    print("\n── 四、校验层：人称归一化 ──")

    # 实测模型会写「记得他第一次见面时…」，注入 prompt 后
    # 「你（这个 NPC）对玩家的了解：· 记得他…」会把「他」读成另一个人。
    cases = [
        ("记得他第一次见面时帮我扶住纸箱", "记得你第一次见面时帮我扶住纸箱"),
        ("记得她刚来时想家", "记得你刚来时想家"),
        ("觉得他是个热心的人", "觉得你是个热心的人"),
        ("知道他常来买三明治", "知道你常来买三明治"),
        # 句中的人称不该被改：这里的「他」可能指别人
        ("记得他妈妈做的茶很好喝", "记得你妈妈做的茶很好喝"),
    ]
    for raw, want in cases:
        applied, rej = apply_update_npc(
            world, player, {"update_npc": {"npc_id": "sam", "memory": raw}}
        )
        stored = player.npc_states.get("sam")
        got = stored.memories[-1] if stored and stored.memories else ""
        check(
            f"人称归一：{raw}",
            got == want,
            f"期望 {want!r}，实际 {got!r}，rej={rej}",
        )
        # 清理，避免影响后续用例
        if stored and stored.memories:
            stored.memories.pop()

    # 纯英文记忆必须拒收
    _, rej = apply_update_npc(
        world,
        player,
        {"update_npc": {"npc_id": "sam", "memory": "He saw me struggling with the form."}},
    )
    check("拒收纯英文记忆", len(rej) > 0, f"rej={rej}")

    # 中英混杂（专有名词）应当接受
    applied, rej = apply_update_npc(
        world,
        player,
        {"update_npc": {"npc_id": "sam", "memory": "记得你问 Right to Study 是什么"}},
    )
    check("接受含专有名词的中文记忆", len(applied) == 1 and not rej, f"rej={rej}")


def test_limits(world, player) -> None:
    print("\n── 四、校验层：数量与格式 ──")

    # 超过每回合上限
    items = [{"npc_id": "sam", "memory": f"第{i}件事"} for i in range(MAX_UPDATES_PER_TURN + 1)]
    _, rej = apply_update_npc(world, player, {"update_npc": items})
    check(
        f"拒收超过 {MAX_UPDATES_PER_TURN} 条的批量更新",
        any("最多" in r for r in rej),
        f"rej={rej}",
    )

    # 同一 NPC 一回合两条
    _, rej = apply_update_npc(
        world,
        player,
        {
            "update_npc": [
                {"npc_id": "sam", "memory": "第一件事"},
                {"npc_id": "sam", "memory": "第二件事"},
            ]
        },
    )
    check("拒收同一 NPC 一回合写两条", any("只能写一条" in r for r in rej), f"rej={rej}")

    # 格式错误
    _, rej = apply_update_npc(world, player, {"update_npc": "字符串不是对象"})
    check("拒收非对象格式", len(rej) > 0)

    # 缺 npc_id
    _, rej = apply_update_npc(world, player, {"update_npc": {"memory": "某件事"}})
    check("拒收缺少 npc_id", len(rej) > 0)


# ══════════════════════════════════════════════════════════
#  五、集成层：节点完成自动写入
# ══════════════════════════════════════════════════════════


def test_node_completion_memory(world, player) -> None:
    print("\n── 五、集成层：节点完成自动写记忆 ──")

    p = player.model_copy(deep=True)
    p.time = WorldTime(day=1, slot=TimeSlot.MORNING)

    present = present_npc_ids(world, p)
    check("宿舍在场者有 sam", "sam" in present, f"present={present}")

    r = judge(world, p, {"set_fact": {"pre_enrolment_submitted": True}})
    check("节点完成", r.completed == ["enrol_online"], f"completed={r.completed}")
    check(
        "在场者被记录到 remembered",
        r.remembered == ["sam"],
        f"remembered={r.remembered}",
    )

    sam_mem = r.player.npc_states["sam"].memories
    check(
        "sam 记住了这件事",
        any("完成线上注册" in m for m in sam_mem),
        f"memories={sam_mem}",
    )
    check(
        "记忆读起来自然（无重复动词）",
        not any("办成了「完成" in m for m in sam_mem),
        f"memories={sam_mem}",
    )

    # 不在场者不该被写入
    check(
        "不在场者（raj）没有记忆",
        "raj" not in r.player.npc_states
        or not r.player.npc_states["raj"].memories,
        f"raj={r.player.npc_states.get('raj')}",
    )


def test_companion_remembers(world, player) -> None:
    print("\n── 六、集成层：同行者也该记住 ──")

    p = player.model_copy(deep=True)
    p.time = WorldTime(day=1, slot=TimeSlot.FORENOON)
    p.add_companion("sam")  # 带着室友一起去注册处

    p, _ = move_to(world, p, "registry")
    p.record_visit("registry")

    present = present_npc_ids(world, p)
    check(
        "注册处在场者 = 当地 elaine + 同行 sam",
        set(present) == {"elaine", "sam"},
        f"present={present}",
    )

    # 先办线上注册（前置）
    p.facts["pre_enrolment_submitted"] = True
    p.inventory.append("share code")

    r = judge(world, p, {"set_fact": {"rts_check_passed": True}})
    check("RTS 检查完成", "rts_check" in r.completed, f"completed={r.completed}")
    check(
        "两个在场者都记住了",
        set(r.remembered) == {"elaine", "sam"},
        f"remembered={r.remembered}",
    )


def test_ai_and_code_coexist(world, player) -> None:
    print("\n── 七、集成层：AI 提议与代码直写共存 ──")

    p = player.model_copy(deep=True)
    p.time = WorldTime(day=1, slot=TimeSlot.MORNING)

    r = judge(
        world,
        p,
        {
            "set_fact": {"pre_enrolment_submitted": True},
            "update_npc": {
                "npc_id": "sam",
                "memory": "记得你进门第一件事是找插座",
            },
        },
    )
    mems = r.player.npc_states["sam"].memories
    check(
        "节点记忆与 AI 记忆都在",
        any("完成线上注册" in m for m in mems) and any("插座" in m for m in mems),
        f"memories={mems}",
    )


def test_memory_flows_to_prompt(world, player) -> None:
    print("\n── 八、注入：记忆进入 prompt ──")

    from ai_engine import build_world_context

    p = player.model_copy(deep=True)
    r = judge(
        world,
        p,
        {"update_npc": {"npc_id": "sam", "memory": "记得你拖着两个行李箱进门"}},
    )

    loc = world.get_location(r.player.location)
    sam = world.get_npc("sam")
    npc_payload = {
        "id": sam.id,
        "name": sam.name,
        "role": sam.role,
        "age": sam.age,
        "background": sam.background,
        "personality": sam.personality,
        "speech": sam.speech.model_dump(),
        "impression_tags": r.player.npc_states["sam"].impression_tags,
        "memories": r.player.npc_states["sam"].memories,
        "is_companion": False,
    }
    lines = build_world_context(
        {
            "id": loc.id,
            "name": loc.name,
            "name_en": loc.name_en,
            "sensory": loc.sensory.model_dump(),
            "variant": loc.variant_for(r.player.time.slot),
            "open_hours": list(loc.open_hours),
            "resident_npcs": loc.resident_npcs,
        },
        [npc_payload],
        {
            "location": r.player.location,
            "time": {"day": 1, "slot": "morning"},
            "inventory": r.player.inventory,
            "facts": r.player.facts,
            "knowledge": [],
            "world_title": world.title,
            "mainline_title": world.mainline.title,
            "deadline": world.mainline.deadline,
            "companions": [],
        },
    )
    text = "\n".join(lines)
    check(
        "记忆出现在 prompt 里",
        "拖着两个行李箱进门" in text,
        f"片段：{text[text.find('对玩家的了解'):][:120] if '对玩家的了解' in text else '未找到区块'}",
    )


def test_first_meeting_hint(world, player) -> None:
    print("\n── 九、注入：初次见面要有提示 ──")

    from ai_engine import _render_npc_block

    sam = world.get_npc("sam")
    block = _render_npc_block(
        {
            "id": sam.id,
            "name": sam.name,
            "role": sam.role,
            "age": sam.age,
            "background": sam.background,
            "personality": sam.personality,
            "speech": sam.speech.model_dump(),
            "impression_tags": [],
            "memories": [],
        },
        False,
    )
    text = "\n".join(block)
    check(
        "无记忆时提示「第一次见面」",
        "第一次见面" in text,
        f"片段：{text[-80:]}",
    )


# ══════════════════════════════════════════════════════════

def main() -> int:
    content = load_world()
    world = content.world
    player = build_initial_player_state(content)

    test_npc_state_capacity()
    test_rejections(world, player)
    test_acceptance(world, player)
    test_person_normalization(world, player)
    test_limits(world, player)
    test_node_completion_memory(world, player)
    test_companion_remembers(world, player)
    test_ai_and_code_coexist(world, player)
    test_memory_flows_to_prompt(world, player)
    test_first_meeting_hint(world, player)

    print(f"\n{'='*50}")
    print(f"通过 {_passed} 项，失败 {_failed} 项")
    if _failed:
        print("FAILED")
        return 1
    print("ALL PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
