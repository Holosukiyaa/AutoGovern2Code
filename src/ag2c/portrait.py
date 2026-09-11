"""画像 lint：too-thin / 验证层 / 加料清单 / 含糊词。"""
from __future__ import annotations

_PORTRAIT_MIN_CHARS = 60

# A portrait must declare HOW its done-states will be checked (the
# verification layer), not only WHAT will be true.
_PORTRAIT_LAYER_MARKERS = (
    "机器验证",
    "实机",
    "用户确认",
    "验证",
    "测试",
    "输出",
    "截图",
    "断言",
    "点击",
    "assert",
    "test",
    "verify",
    "verified",
    "exit",
    "screenshot",
    "output",
)

# 加料清单（反向引导收口）：画像必须说清哪些是用户没明说、AI 自行添加的。
# 要么给 Inferences/推断/加料 段落，要么明确声明"无加料"——沉默等同于隐瞒。
_PORTRAIT_INFERENCE_MARKERS = ("inferences:", "inference:", "推断", "加料")
_PORTRAIT_NO_ADDITION_PHRASES = ("无加料", "无推断", "无 ai 添加", "无ai添加", "no inference", "no additions")


def portrait_inference_section(portrait: str) -> str:
    """提取画像的加料清单段原文（供 start/orient 浮现给人、供监管前置审查）。

    机器不做语义判断：返回标记行到下一个已知段落标题（或文末）之间的原文，
    让"看见"发生在人侧和监管侧。显式无加料声明返回空串。
    """
    text = str(portrait or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    if any(phrase in lowered for phrase in _PORTRAIT_NO_ADDITION_PHRASES):
        return ""
    start = -1
    for marker in _PORTRAIT_INFERENCE_MARKERS:
        index = lowered.find(marker)
        if index >= 0 and (start < 0 or index < start):
            start = index
    if start < 0:
        return ""
    rest = text[start:]
    # 已知段落标题出现时截断（加料段通常在最后，但防御性处理）
    for header in ("Done looks like", "Surfaces", "Out of result", "验证层"):
        cut = rest.find(header, 1)
        if cut > 0:
            rest = rest[:cut]
    return rest.strip()

# Vague phrases can never serve as acceptance criteria. A negated use
# ("不再是…", "不…") is a checkable anti-claim and stays legal.
_PORTRAIT_VAGUE_PHRASES = (
    "正常工作",
    "没有问题",
    "没问题",
    "正常运行",
    "正常显示",
    "能用",
    "好用",
    "优化",
    "完善",
    "合理",
    "works as expected",
    "work as expected",
    "works correctly",
    "works properly",
    "as expected",
    "no issues",
    "it works",
)


def lint_portrait(portrait: str) -> list[str]:
    """Result-gate lint: reject portraits an outsider could never check.

    Three rules, each returning a named violation:
    - too-thin: under _PORTRAIT_MIN_CHARS of substance;
    - no-verification-layer: no marker saying how done-states get checked;
    - vague-phrase: a weasel phrase used as a claim (negations exempt).
    """
    violations: list[str] = []
    text = portrait.strip()
    if len(text) < _PORTRAIT_MIN_CHARS:
        violations.append(f"too-thin: portrait has {len(text)} chars, need at least {_PORTRAIT_MIN_CHARS}")
    lowered = text.lower()
    if not any(marker in text or marker in lowered for marker in _PORTRAIT_LAYER_MARKERS):
        violations.append(
            "no-verification-layer: declare how each done-state gets checked "
            "(机器验证 / 实机 / 用户确认 / 测试 / 输出 / assert / test / verify ...)"
        )
    if not any(marker in lowered for marker in _PORTRAIT_INFERENCE_MARKERS) and not any(
        phrase in lowered for phrase in _PORTRAIT_NO_ADDITION_PHRASES
    ):
        violations.append(
            "no-inference-ledger: declare what the AI added beyond the user's words "
            "(Inferences: ...)，或明确声明 无加料——沉默等同于隐瞒"
        )
    for phrase in _PORTRAIT_VAGUE_PHRASES:
        start = 0
        haystack = lowered if phrase.isascii() else text
        while True:
            index = haystack.find(phrase, start)
            if index < 0:
                break
            prefix = haystack[max(0, index - 5) : index]
            if not any(neg in prefix for neg in ("不", "no ", "not ", "n't")):
                violations.append(f"vague-phrase: '{phrase}' is not a checkable claim; state what an outsider can verify")
                break
            start = index + len(phrase)
    return violations
