"""稳定性测试：同一场景重复多次，看 add/remove_companion 的产出率。"""

import asyncio

from ai_engine import generate_turn

SAM = {
    "id": "sam",
    "name": "Sam",
    "role": "室友",
    "age": 20,
    "background": "本地学生，二年级",
    "personality": "话多、热心",
    "speech": {"style": "语速快", "verbal_tics": "常说 mate"},
    "impression_tags": ["first_meeting"],
    "memories": [],
}

DORM = {
    "id": "dorm",
    "name": "宿舍",
    "name_en": "Student Hall",
    "sensory": {
        "sight": "走廊尽头的窗户蒙着一层水汽",
        "sound": "隔壁房间传来行李箱轮子刮过地板的声音",
        "smell": "新刷的乳胶漆味混着纸箱的木浆味",
        "touch": "门把手冰凉",
        "temperature": "楼道里比外面暖和",
    },
    "variant": "",
    "open_hours": [0, 24],
    "resident_npcs": ["sam"],
}

BASE = {
    "location": "dorm",
    "time": {"day": 1, "slot": "evening"},
    "inventory": [],
    "facts": {"enrolled": False},
    "knowledge": [],
    "world_title": "英国留学第一周",
    "mainline_title": "安顿下来",
    "deadline": {"day": 3, "slot": "afternoon"},
    "companions": [],
}

ADD_HISTORY = [
    {"role": "narration", "content": "Sam 靠在门框上，问你要不要一起出去转转。"},
]
ADD_INPUT = {
    "speech": "Yeah, let's go together. I need to grab some groceries.",
    "action": "",
}

REMOVE_HISTORY = [
    {"role": "narration", "content": "你们回到宿舍楼，Sam 停在 214 门口。"},
    {"role": "npc", "content": "This is me. Catch you later, yeah?"},
]
REMOVE_INPUT = {
    "speech": "Yeah, see you later. Thanks for showing me around.",
    "action": "",
}

ROUNDS = 5


async def run(kind: str, history, player_input, companions):
    key = "add_companion" if kind == "add" else "remove_companion"
    hits = 0
    for i in range(ROUNDS):
        turn = await generate_turn(
            location=DORM,
            npcs=[{**SAM, "is_companion": kind == "remove"}],
            world_state={**BASE, "companions": companions},
            world_rules=None,
            history=history,
            player_input=player_input,
        )
        wc = turn.get("world_changes") or {}
        got = key in wc
        hits += got
        print(f"  [{i + 1}/{ROUNDS}] {key}={wc.get(key, '—')} {'✅' if got else '❌'}")
    return hits


async def main():
    print("=" * 60)
    print("add_companion 稳定性")
    print("=" * 60)
    a = await run("add", ADD_HISTORY, ADD_INPUT, [])

    print()
    print("=" * 60)
    print("remove_companion 稳定性")
    print("=" * 60)
    r = await run("remove", REMOVE_HISTORY, REMOVE_INPUT, ["sam"])

    print()
    print(f"add_companion:    {a}/{ROUNDS}")
    print(f"remove_companion: {r}/{ROUNDS}")


asyncio.run(main())
