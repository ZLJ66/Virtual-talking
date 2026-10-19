"""
具体性检测器单元测试。

背景：原实现用 re.findall(r"[\u4e00-\u9fa5]{2,6}") 切词，
会贪婪切出「走廊尽头的窗」这类片段，导致合格旁白被误报。
改为二元组匹配后，需要验证「该命中的命中，不该误报的不误报」。
"""

from ai_engine import _shares_content_bigram, check_specificity

SENSORY = {
    "sight": "走廊尽头的窗户蒙着一层水汽",
    "sound": "隔壁房间传来行李箱轮子刮过地板的声音",
    "smell": "新刷的乳胶漆味混着纸箱的木浆味",
    "touch": "门把手冰凉，漆掉了一小块",
    "temperature": "楼道里比外面暖和，暖气片刚响过一声",
}

# (旁白, 期望是否有具体性, 说明)
CASES = [
    (
        "走廊里的暖气片发出一声尖锐的金属撞击声，在尽头那扇蒙着水汽的窗户前回荡。",
        True,
        "命中「走廊」「暖气」「水汽」",
    ),
    (
        "运动鞋在油毡地板上发出吱吱声，架子上的纸箱散发出一股淡淡的洗衣粉味。",
        True,
        "命中「纸箱」",
    ),
    (
        "他把一摞袋子从暖气片旁抽出来，新刷的乳胶漆味混着木浆味飘过来。",
        True,
        "命中「暖气」「乳胶漆」「木浆」",
    ),
    (
        "她靠在狭窄过道的墙上，指着货架上的罐头。",
        False,
        "感官里没有「过道」「货架」「罐头」，应判为未引用",
    ),
    (
        "空气安静极了，气氛有些微妙，一切都慢了下来。",
        False,
        "纯抽象描写，无任何具体物件，应判为未引用",
    ),
]

# 已知局限（不视为 bug，但需记录）：
# 二元组匹配对「通用词」无免疫力。例如感官里写了「隔壁房间传来……」，
# 那么旁白只要出现「房间」二字就算命中，哪怕它写的是「房间里安静极了」。
# 这种误判方向是「放过不具体的旁白」，属于漏报而非误报，
# 代价可接受；若将来要收紧，应改为「具体名词表」而非二元组。

# 套话检测用例：(旁白, 期望命中的套话关键词或 None)
BANNED_CASES = [
    ("空气中弥漫着咖啡的味道。", "弥漫"),
    ("弥漫着新刷乳胶漆的味道。", "弥漫"),
    ("他似乎在犹豫。", "似乎"),
    ("他第三次擦了同一个杯子。", None),
    ("冰柜后面的咖啡机刚响过一声。", None),
]


def test_specificity():
    print("=" * 70)
    print("具体性检测")
    print("=" * 70)
    ok = 0
    for narration, expected, note in CASES:
        issues = check_specificity({"zh": narration, "en": ""}, SENSORY)
        has_specific = not any("感官细节" in i for i in issues)
        passed = has_specific == expected
        ok += passed
        mark = "✅" if passed else "❌"
        print(
            f"{mark} 期望={'有' if expected else '无'} "
            f"实际={'有' if has_specific else '无'} | {note}"
        )
        if not passed:
            print(f"   旁白：{narration}")
            print(f"   问题：{issues}")
    print(f"\n{ok}/{len(CASES)} 通过\n")
    return ok == len(CASES)


def test_banned():
    print("=" * 70)
    print("套话检测")
    print("=" * 70)
    ok = 0
    for narration, expected in BANNED_CASES:
        issues = check_specificity({"zh": narration, "en": ""}, {})
        actual = None
        for issue in issues:
            if issue.startswith("中文套话: "):
                actual = issue.replace("中文套话: ", "")
                break
        passed = actual == expected
        ok += passed
        mark = "✅" if passed else "❌"
        print(f"{mark} 期望={expected or '无'} 实际={actual or '无'} | {narration}")
    print(f"\n{ok}/{len(BANNED_CASES)} 通过\n")
    return ok == len(BANNED_CASES)


if __name__ == "__main__":
    a = test_specificity()
    b = test_banned()
    print("=" * 70)
    print(f"总计：{'全部通过' if a and b else '有失败项'}")
    print("=" * 70)
    raise SystemExit(0 if a and b else 1)
