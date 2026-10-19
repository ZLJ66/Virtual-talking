"""
同行 NPC 端到端测试。

验证场景：玩家在宿舍遇到室友 Sam，聊着说好一起去杂货店，
到达后 Sam 必须仍然在场并能说话。
"""

import asyncio
import sys

from ai_engine import generate_opening, generate_turn
from world_loader import load_world

SAMPLE_DORM = {
    "id": "dorm",
    "name": "宿舍",
    "name_en": "Student Hall",
    "sensory": {
        "sight": "走廊尽头的窗户蒙着一层水汽",
        "sound": "隔壁房间传来行李箱轮子刮过地板的声音",
        "smell": "新刷的乳胶漆味混着纸箱的木浆味",
        "touch": "门把手冰凉，漆掉了一小块",
        "temperature": "楼道里比外面暖和，暖气片刚响过一声",
    },
    "variant": "",
    "open_hours": [0, 24],
    "resident_npcs": ["sam"],
}

SAMPLE_SHOP = {
    "id": "grocer",
    "name": "杂货店",
    "name_en": "Corner Grocer",
    "sensory": {
        "sight": "货架间的过道窄得只能侧身",
        "sound": "冰柜的压缩机嗡了一声又停了",
        "smell": "纸箱和洗衣粉混在一起的味道",
        "touch": "购物篮的提手有点黏",
        "temperature": "门口灌进来的风带着凉意",
    },
    "variant": "",
    "open_hours": [0, 24],
    "resident_npcs": ["raj"],
}

SAM = {
    "id": "sam",
    "name": "Sam",
    "role": "室友",
    "age": 20,
    "background": "本地学生，二年级，住隔壁房间",
    "personality": "话多、热心，喜欢自嘲",
    "speech": {
        "style": "语速快，用缩略语和俚语",
        "verbal_tics": "经常用 mate 和 right then",
    },
    "impression_tags": ["first_meeting"],
    "memories": ["在宿舍走廊第一次见面"],
    "is_companion": False,
}

RAJ = {
    "id": "raj",
    "name": "Raj",
    "role": "店员",
    "age": 35,
    "background": "经营这家杂货店多年，见过各种学生",
    "personality": "寡言，但记得熟客",
    "speech": {"style": "简短，句子不完整", "verbal_tics": "常说 same as before"},
    "impression_tags": [],
    "memories": [],
    "is_companion": False,
}

WORLD_STATE_BASE = {
    "location": "grocer",
    "time": {"day": 1, "slot": "morning"},
    "inventory": [],
    "facts": {"enrolled": False, "bank_account": False},
    "knowledge": [],
    "world_title": "英国留学第一周",
    "mainline_title": "安顿下来",
    "deadline": {"day": 3, "slot": "afternoon"},
    "companions": [],
}

PROFILE = {"englishLevel": "intermediate", "name": "Wei", "narrationLanguage": "both"}


def _dump(result: dict, label: str) -> None:
    print(f"\n{'=' * 70}")
    print(f"  {label}")
    print(f"{'=' * 70}")
    narr = result.get("narration") or {}
    print(f"[旁白 EN] {narr.get('en', '')}")
    print(f"[旁白 ZH] {narr.get('zh', '')}")
    npc = result.get("npc") or {}
    print(f"[说话人] {npc.get('speaker_name')} (id={npc.get('speaker_id')})")
    print(f"[台词]   {npc.get('content')}")
    wc = result.get("world_changes") or {}
    print(f"[世界变更] {wc if wc else '（无）'}")


async def test_companion_present():
    """核心测试：Sam 作为同行者到了杂货店，应该能说话。"""
    print("\n" + "#" * 70)
    print("# 测试 1：同行者在场（Sam 跟着到杂货店）")
    print("#" * 70)

    world_state = {**WORLD_STATE_BASE, "companions": ["sam"]}

    # 场景 A：开场——旁白必须提到两人一起进来
    opening = await generate_opening(
        location=SAMPLE_SHOP,
        npcs=[RAJ, {**SAM, "is_companion": True}],
        world_state=world_state,
        world_rules=None,
        recent_summary="玩家和室友 Sam 说好一起去杂货店买点东西。",
    )
    _dump(opening, "开场（Sam 同行）")

    narr_zh = (opening.get("narration") or {}).get("zh", "")
    narr_en = (opening.get("narration") or {}).get("en", "")
    mentioned = any(k in (narr_zh + narr_en) for k in ("Sam", "室友", "一起", "两人"))
    print(f"\n>>> 旁白是否提到同行者：{'✅ 是' if mentioned else '❌ 否'}")

    # 场景 B：玩家对 Sam 说话
    turn = await generate_turn(
        location=SAMPLE_SHOP,
        npcs=[RAJ, {**SAM, "is_companion": True}],
        world_state=world_state,
        world_rules=None,
        history=[
            {"role": "narration", "content": "你和 Sam 一起走进杂货店。"},
            {"role": "npc", "content": "Right then. What can I get you?"},
        ],
        player_input={
            "speech": "Sam, what do you usually get here?",
            "action": "指了指货架",
        },
    )
    _dump(turn, "玩家对 Sam 说话")

    speaker = (turn.get("npc") or {}).get("speaker_id")
    print(f"\n>>> 回应者：{speaker}")
    print(f">>> {'✅ Sam 回应了' if speaker == 'sam' else '⚠️ 不是 Sam 回应'}")


async def test_add_companion():
    """测试 AI 是否能产出 add_companion。"""
    print("\n" + "#" * 70)
    print("# 测试 2：邀请同行（AI 应产出 add_companion）")
    print("#" * 70)

    turn = await generate_turn(
        location=SAMPLE_DORM,
        npcs=[SAM],
        world_state={**WORLD_STATE_BASE, "location": "dorm", "companions": []},
        world_rules=None,
        history=[
            {"role": "narration", "content": "Sam 靠在门框上，问你要不要一起出去转转。"},
        ],
        player_input={
            "speech": "Yeah, let's go together. I need to grab some groceries.",
            "action": "",
        },
    )
    _dump(turn, "玩家邀请 Sam 同行")

    wc = turn.get("world_changes") or {}
    has_add = "add_companion" in wc
    print(f"\n>>> world_changes.add_companion: {wc.get('add_companion', '（无）')}")
    print(f">>> {'✅ 正确产出 add_companion' if has_add else '⚠️ 未产出 add_companion'}")


async def test_remove_companion():
    """测试 AI 是否能产出 remove_companion。"""
    print("\n" + "#" * 70)
    print("# 测试 3：同行者告别（AI 应产出 remove_companion）")
    print("#" * 70)

    turn = await generate_turn(
        location=SAMPLE_DORM,
        npcs=[{**SAM, "is_companion": True}],
        world_state={**WORLD_STATE_BASE, "location": "dorm", "companions": ["sam"]},
        world_rules=None,
        history=[
            {"role": "narration", "content": "你们回到宿舍楼，Sam 停在 214 门口。"},
            {"role": "npc", "content": "This is me. Catch you later, yeah?"},
        ],
        player_input={
            "speech": "Yeah, see you later. Thanks for showing me around.",
            "action": "",
        },
    )
    _dump(turn, "Sam 告别")

    wc = turn.get("world_changes") or {}
    has_remove = "remove_companion" in wc
    print(f"\n>>> world_changes.remove_companion: {wc.get('remove_companion', '（无）')}")
    print(f">>> {'✅ 正确产出 remove_companion' if has_remove else '⚠️ 未产出 remove_companion'}")


async def main():
    # 加载世界，确认内容未损坏
    content = load_world()
    print(f"世界加载正常：{content.world.title}")
    print(f"  NPC: {[n.id for n in content.world.npcs]}")
    print(f"  地点: {[loc.id for loc in content.world.locations]}")

    await test_companion_present()
    await test_add_companion()
    await test_remove_companion()

    print("\n" + "=" * 70)
    print("测试完成")
    print("=" * 70)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()) or 0)
