"""台词归一化测试：`normalize_lines` 的纯函数行为。

为什么需要这一组：`test_multi_speaker.py` 打的是真实模型，
能验证「模型会不会用 lines」，但验证不了「模型不听话时我们兜不兜得住」。
真实模型偶尔返回旧格式、把 lines 写成对象、或者漏掉 speaker_id，
这些分支必须靠构造输入来测——不能等模型哪天抽风才暴露。

运行：python test_lines_normalize.py（不需要后端，不花钱）
"""

from __future__ import annotations

import sys

from ai_engine import MAX_LINES, apply_lines, normalize_lines


def check(tag: str, ok: bool, detail: str = "") -> bool:
    print(f"  {'[OK]' if ok else '[FAIL]'} {tag}{(' — ' + detail) if detail else ''}")
    return ok


def main() -> int:
    results: list[bool] = []

    # ── 一、正常形状 ──
    print("\n── 一、正常形状 ──")

    payload = {
        "lines": [
            {"speaker_id": "raj", "speaker_name": "Raj", "content": "Two fifty, mate."},
            {
                "speaker_id": "sam",
                "speaker_name": "Sam",
                "content": "Bit steep.",
                "reply_to": "raj",
            },
        ]
    }
    lines = normalize_lines(payload)
    results.append(check("两项都保留", len(lines) == 2, f"实际 {len(lines)}"))
    results.append(check("第 1 句 reply_to 被设为 player", lines[0]["reply_to"] == "player"))
    results.append(check("第 2 句 reply_to 保持不变", lines[1]["reply_to"] == "raj"))
    results.append(check("内容原样保留", lines[1]["content"] == "Bit steep."))

    # ── 二、旧格式兼容：只有 npc ──
    print("\n── 二、旧格式兼容 ──")

    legacy = {
        "npc": {"speaker_id": "raj", "speaker_name": "Raj", "content": "Aye."}
    }
    lines = normalize_lines(legacy)
    results.append(check("npc 被转成 1 项 lines", len(lines) == 1, f"实际 {len(lines)}"))
    results.append(check("说话人正确", lines[0]["speaker_id"] == "raj"))

    # ── 三、模型把 lines 写成单个对象 ──
    print("\n── 三、形状异常 ──")

    as_object = {
        "lines": {"speaker_id": "raj", "speaker_name": "Raj", "content": "Aye."}
    }
    lines = normalize_lines(as_object)
    results.append(check("单对象被包成数组", len(lines) == 1 and lines[0]["speaker_id"] == "raj"))

    as_string = {"lines": "Raj: Two fifty, mate."}
    lines = normalize_lines(as_string)
    results.append(
        check(
            "字符串 lines 退回占位（不崩溃）",
            len(lines) == 1 and lines[0]["speaker_id"] == "unknown",
            f"实际 {lines[0]['speaker_id']}",
        )
    )

    # ── 四、空台词必须被剔除 ──
    print("\n── 四、空台词剔除 ──")

    with_blank = {
        "lines": [
            {"speaker_id": "raj", "speaker_name": "Raj", "content": "   "},
            {"speaker_id": "sam", "speaker_name": "Sam", "content": "Real line."},
        ]
    }
    lines = normalize_lines(with_blank)
    results.append(
        check(
            "空白台词被丢掉，剩下那句升为第 1 句",
            len(lines) == 1 and lines[0]["speaker_id"] == "sam",
            f"实际 {[l['speaker_id'] for l in lines]}",
        )
    )

    all_blank = {
        "lines": [
            {"speaker_id": "raj", "speaker_name": "Raj", "content": ""},
        ]
    }
    lines = normalize_lines(all_blank)
    results.append(check("全空时给占位，不返回空数组", len(lines) == 1, f"实际 {len(lines)}"))

    # ── 五、数量上限 ──
    print("\n── 五、数量上限 ──")

    many = {
        "lines": [
            {"speaker_id": f"n{i}", "speaker_name": f"N{i}", "content": f"Line {i}."}
            for i in range(6)
        ]
    }
    lines = normalize_lines(many)
    results.append(
        check(f"截断到 {MAX_LINES} 项", len(lines) == MAX_LINES, f"实际 {len(lines)}")
    )
    results.append(check("按顺序保留前几项", lines[0]["speaker_id"] == "n0"))

    # ── 六、缺字段补默认值 ──
    print("\n── 六、缺字段 ──")

    missing = {"lines": [{"content": "No id, no name."}]}
    lines = normalize_lines(missing)
    results.append(
        check(
            "缺 speaker_id 不崩溃（留空字符串）",
            lines[0]["speaker_id"] == "",
            f"实际 {lines[0]['speaker_id']!r}",
        )
    )
    results.append(check("缺 reply_to 默认 player", lines[0]["reply_to"] == "player"))

    # ── 七、apply_lines 双向同步 ──
    print("\n── 七、apply_lines 同步 npc ──")

    p = {"lines": [{"speaker_id": "raj", "speaker_name": "Raj", "content": "Aye."}]}
    out = apply_lines(p)
    results.append(check("lines 已写入", isinstance(out["lines"], list)))
    results.append(
        check("npc 等于 lines[0]", out["npc"] == out["lines"][0], f"实际 {out['npc']}")
    )

    p2 = {"npc": {"speaker_id": "sam", "speaker_name": "Sam", "content": "Yo."}}
    out2 = apply_lines(p2)
    results.append(
        check("只有 npc 时 lines 被补出", len(out2["lines"]) == 1 and out2["lines"][0]["speaker_id"] == "sam")
    )

    p3 = {}
    out3 = apply_lines(p3)
    results.append(check("全空也不崩（占位一句）", len(out3["lines"]) == 1))

    passed = sum(1 for r in results if r)
    print(f"\n{'=' * 50}\n通过 {passed} 项，失败 {len(results) - passed} 项\n{'=' * 50}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
