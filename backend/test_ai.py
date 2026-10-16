"""直接测试 AI 引擎"""
import asyncio
import json
from ai_engine import generate_turn, generate_opening

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
    print("=== 测试 generate_turn ===")
    try:
        result = await generate_turn(scene, profile, world_state, history, player_input)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as e:
        print(f"ERROR: {e}")

    print("\n=== 测试 generate_opening ===")
    try:
        result = await generate_opening(scene, profile, prev_scene_summary=None)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as e:
        print(f"ERROR: {e}")


if __name__ == "__main__":
    asyncio.run(test())
