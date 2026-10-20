"""
update_npc 产出率统计

为什么需要这个文件：单次成功不能证明规则可靠。add_companion 当初
就是「看起来能用」，实测 8 次只写了 3 次（38%）。这里用同样的方法
量一下 update_npc 的产出率，并对比「值得记」与「不值得记」两类输入。

期望：
  - 值得记的输入 → 高产出率（规则有效）
  - 不值得记的输入 → 低产出率（没有过度记录）

后者同样重要：如果每回合都写，记忆会在 20 回合内被寒暄塞满，
真正重要的事反而被淘汰掉。

跑法：先启动 uvicorn --port 8014，再跑本文件
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

# 端口从环境变量读，避免每次改端口都要改文件。
# 默认 8014，与文件头的启动说明一致。
BASE = os.environ.get("TEST_BASE", "http://127.0.0.1:8014")


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


def get(path: str) -> dict[str, Any]:
    with urllib.request.urlopen(BASE + path, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


# 值得记：做了选择 / 表了态 / 露情绪 / 发生具体事件
#
# 注意：每条都必须是**在宿舍、和 Sam 之间**能真实发生的事。
# 这个坑踩了两次：
#   ① 早期有一条「把伞落在便利店柜台」——那是 Raj 该记的事，
#      Sam 根本不在场，模型正确地没有写，却被算成了失败。
#   ② 后来有一条「我要原味不要奶酪，奶酪让我难受」——在宿舍里
#      对室友说挑三明治的偏好，场景对不上，模型同样正确地没写。
#
# 两次都是「测试用例设计错了，会让人去改本来正确的代码」。
# 现在每条都先问一遍：这件事在宿舍里、对着 Sam，说得通吗？
#
# 实测对比（每例 4 次）：
#   场景对不上的旧用例 → 0/4 ~ 2/4
#   场景对得上的新用例 → 3/4 ~ 4/4
MEMORABLE = [
    ("表露情绪", "I really miss home. My mum used to make tea every morning.", "把手机屏保翻过来看了一眼"),
    ("做出选择", "I'd rather walk to the shop than take the bus. I need the air.", "把公交卡扔回抽屉"),
    ("具体事件", "I've got a bruise on my arm from the flight. The suitcase fell on me.", "卷起袖子"),
    ("说起打算", "I want to join the football club, but I've never played properly.", "挠了挠后颈"),
    ("承认难处", "I don't really understand the enrolment steps. There are too many.", "把那张纸翻过来又翻回去"),
    ("帮助他人", "Here, let me take that. You've got your hands full.", "伸手去接 Sam 手里的箱子"),
]

# 不值得记：寒暄 / 问价 / 常规交易
FORGETTABLE = [
    ("寒暄", "Hi. How are you?", ""),
    ("问价", "How much is this?", "拿起一罐可乐"),
    ("常规交易", "A coffee please.", "递过零钱"),
    ("问路", "Where's the toilet?", ""),
    ("重复提问", "Sorry, how much is this again?", ""),
    ("客套道谢", "Thanks. Bye.", "推开门"),
]


def run_batch(world_data, cases, label: str) -> tuple[int, int]:
    player = world_data["player_start"]
    locations = {loc["id"]: loc for loc in world_data["locations"]}
    npcs = {n["id"]: n for n in world_data["npcs"]}

    hits = 0
    total = 0
    for name, speech, action in cases:
        loc = locations["dorm"]
        req = {
            "location": {
                "id": "dorm",
                "name": loc["name"],
                "name_en": loc["name_en"],
                "sensory": loc["sensory"],
                "variant": "",
                "open_hours": loc["open_hours"],
                "resident_npcs": loc["resident_npcs"],
            },
            "npcs": [
                {
                    "id": "sam",
                    "name": npcs["sam"]["name"],
                    "role": npcs["sam"]["role"],
                    "age": npcs["sam"]["age"],
                    "background": npcs["sam"]["background"],
                    "personality": npcs["sam"]["personality"],
                    "speech": npcs["sam"]["speech"],
                    "impression_tags": [],
                    "memories": [],
                    "is_companion": False,
                }
            ],
            "profile": {"englishLevel": "intermediate", "narrationLanguage": "both"},
            "world_state": {
                "location": "dorm",
                "time": {"day": 1, "slot": "morning"},
                "inventory": player["inventory"],
                "facts": player["facts"],
                "knowledge": [],
                "world_title": world_data["world"]["title"],
                "mainline_title": world_data["mainline"]["title"],
                "deadline": world_data["mainline"]["deadline"],
                "companions": [],
                "mainline_lines": world_data.get("mainline_lines", []),
            },
            "world_rules": world_data["world"].get("rules"),
            "history": [],
            "player_input": {"speech": speech, "action": action},
        }
        try:
            resp = post("/api/turn", req)
        except urllib.error.URLError as e:
            print(f"  [{label}] {name}: 请求失败 {e}")
            continue

        total += 1
        changes = resp.get("world_changes") or {}
        has = "update_npc" in changes
        if has:
            # 光看「模型写没写」不够——写了但被判定器拒收，等于没记住。
            # 所以产出率按「模型写了 ∧ 判定器接受」计。
            judged = post(
                "/api/judge",
                {"player_state": player, "world_changes": changes},
            )
            mem_rej = [r for r in judged.get("rejected", []) if "update_npc" in r]
            accepted = not mem_rej
            upd = changes["update_npc"]
            item = upd[0] if isinstance(upd, list) else upd
            mem = item.get("memory") or item.get("impression") or ""
            if accepted:
                hits += 1
                print(f"  [{label}] {name}: ✅ {mem}")
            else:
                print(f"  [{label}] {name}: ⚠ 写了但被拒 {mem} → {mem_rej}")
        else:
            print(f"  [{label}] {name}: — 没写 (changes={list(changes.keys())})")

    return hits, total


def main() -> int:
    world_data = get("/api/world")

    # 跑 2 轮聚合，而不是 1 轮。
    #
    # 实测：同两条用例在 3 轮里各命中 2 次，但单轮可能两条都落空。
    # 6 个样本时，真实产出率 75% 的单轮结果会在 50%~100% 之间跳，
    # 噪声 ±17%。用单轮结果卡 70% 门槛，会周期性地误报失败，
    # 把人骗去改本来正确的 prompt。
    #
    # 12 个样本把噪声压到 ±8% 左右，足以发现真正的回归
    # （prompt 被改坏时产出率会掉到 0~20%，而不是掉到 60%）。
    ROUNDS = 2

    print("── 值得记的输入 ──")
    mem_hits = mem_total = 0
    for r in range(ROUNDS):
        print(f"  第 {r+1} 轮")
        h, t = run_batch(world_data, MEMORABLE, f"记{r+1}")
        mem_hits += h
        mem_total += t
    print(f"  合计 {mem_hits}/{mem_total} = {mem_hits/max(mem_total,1):.0%}")

    print("\n── 不值得记的输入 ──")
    fog_hits = fog_total = 0
    for r in range(ROUNDS):
        print(f"  第 {r+1} 轮")
        h, t = run_batch(world_data, FORGETTABLE, f"忘{r+1}")
        fog_hits += h
        fog_total += t
    print(f"  合计 {fog_hits}/{fog_total} = {fog_hits/max(fog_total,1):.0%}")

    print(f"\n{'='*50}")
    mem_rate = mem_hits / max(mem_total, 1)
    fog_rate = fog_hits / max(fog_total, 1)

    ok = True
    # 值得记的产出率下限 65%。实测稳定在 70~85%，
    # 设 65% 留出噪声余量；prompt 坏掉时会掉到 20% 以下，仍能报警。
    if mem_rate < 0.65:
        print(f"[FAIL] 值得记的产出率过低：{mem_rate:.0%} < 65%")
        ok = False
    else:
        print(f"[OK] 值得记的产出率 {mem_rate:.0%}")

    # 不值得记的上限 20%。实测是 0%，但完全禁止寒暄记忆不现实——
    # 偶尔一次「记得你第一次来就打了招呼」是合理的，不该算失败。
    if fog_rate > 0.20:
        print(f"[FAIL] 不值得记的产出率过高：{fog_rate:.0%} > 20%")
        ok = False
    else:
        print(f"[OK] 不值得记的产出率 {fog_rate:.0%}")

    print("ALL PASSED" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except urllib.error.URLError as e:
        print(f"无法连接后端 {BASE}：{e}")
        raise SystemExit(1) from e
