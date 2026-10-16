"""测试 AI 引擎 - 查看原始响应"""
import asyncio
import json
from ai_engine import call_ai, SYSTEM_PROMPT, build_user_prompt

scene = {
    "title": "便利店",
    "description": "你刚抵达英国，拖着行李走进街角一家便利店，想买点东西垫垫肚子。",
    "goal": "付完钱并取回找零",
    "location": "英国街角便利店",
    "npcs": [{"id": "cashier", "name": "Cashier", "role": "收银员", "personality": "友善但忙碌"}]
}
profile = {"englishLevel": "beginner", "name": "Alex"}
world_state = {"inventory": ["三明治", "矿泉水"], "quests": [], "npcStates": {}}
history = [
    {"role": "narration", "content": "You grab a sandwich and head to the counter."},
    {"role": "npc", "content": "That'll be 6.50, please."},
]
player_input = {"speech": "Give me my change.", "action": "指着收银台上的零钱"}


async def test():
    user_prompt = build_user_prompt(scene, profile, world_state, history, player_input)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    print("=== 原始 AI 响应 ===")
    try:
        raw = await call_ai(messages, temperature=0.8, max_tokens=1024)
        print(repr(raw[:1000]))
        print("---")
        print(raw[:1000])
    except Exception as e:
        print(f"ERROR: {e}")


if __name__ == "__main__":
    asyncio.run(test())
