"""AI 监管（agent-review）：verify 机器项全过后的对抗性复审。

三条铁律（见《AG2C-监管者设计》）：
1. 信息隔离——监管只看画像 + diff + 机器检查原始输出，永远看不到 worker 自述。
2. 对抗性框架——任务是"找出这次交付失败的方式"，不是"检查是否合格"。
3. 评语必须带证据——fail 项缺物证引用（path:line / machine:<checker> / portrait:<定位>）的裁决被机器判作废。

监管不可用（未配置 / 调用失败 / 裁决作废）时降级为仅机器检查并在证据里
记录缺口"本次缺 AI 监管"；政策 regulator.strict（默认 true，fail-closed）下
不许合并，由 tasks.verify_task 负责拦截。连续缺席进危房名单（hazard.py
regulator-absent）——沉默本身即警情。

V1 = 一次 LLM 调用：无工具循环、无联网、无多轮。prompt 是系统资产，随版本演进。
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from pathlib import Path
from typing import Any

from .gitops import git
from .model import Policy, RegulatorConfig

PROMPT_VERSION = "agent-review.v3"

#: fail 项的证据必须指向三样物证之一中可核的位置（三形其一）：
#:   path:line        —— diff/代码位置（tasks.py:347）
#:   machine:<checker> —— 机器结果条目（machine:check.python）
#:   portrait:<定位>   —— 画像小节（portrait:承诺②）
#: 空证据与散文证据（"见机器输出"）依旧判作废。
_EVIDENCE_REF = re.compile(r"[\w./\\\-一-鿿]+:\d+|machine:[\w.\-]+|portrait:\S+")

#: 9.10 安达信条款：模型名 → 厂商家族。监管与 worker 同族 = 假异构。
_MODEL_FAMILIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("openai", ("gpt", "o1", "o3", "o4", "openai", "chatgpt")),
    ("anthropic", ("claude", "anthropic")),
    ("google", ("gemini", "palm", "bard", "google")),
    ("xai", ("grok", "xai")),
    ("moonshot", ("kimi", "moonshot")),
    ("deepseek", ("deepseek",)),
    ("alibaba", ("qwen", "tongyi")),
    ("meta", ("llama", "meta")),
    ("mistral", ("mistral", "mixtral", "codestral")),
    ("cohere", ("command", "cohere")),
)


def model_family(model: str) -> str:
    """归一化模型名到厂商家族；未知模型返回其归一化自身（只有精确撞名才算同族）。

    "openai/gpt-4o" → openai；"claude-sonnet-4-5" → anthropic；"kimi-k3" → moonshot。
    """
    normalized = model.strip().lower()
    if "/" in normalized:  # vendor/model 形式取模型段
        normalized = normalized.split("/")[-1]
    token = re.split(r"[^a-z0-9]+", normalized)[0] if normalized else ""
    for family, prefixes in _MODEL_FAMILIES:
        if any(token.startswith(prefix) for prefix in prefixes):
            return family
    return token or "unknown"


def same_family(regulator_model: str, worker_model: str) -> bool:
    """监管模型与 worker 模型是否同族。任一侧为空时不判定（配置未完成）。"""
    if not regulator_model.strip() or not worker_model.strip():
        return False
    return model_family(regulator_model) == model_family(worker_model)

#: diff 与单文件内容的体积上限，防止提示词爆炸。
_MAX_DIFF_CHARS = 100_000
_MAX_FILE_CHARS = 20_000

_SYSTEM_PROMPT = """你是交付监管，不是验收员。你的唯一任务是找出这次交付失败的方式。

你只有三样物证：
1. 画像——施工前锁定的承诺（做完后什么是真的）；
2. diff——实际改动的全部代码；
3. 机器检查的原始结果——测试、预算、查重等确定性检查的报告。

你看不到施工者的任何自述、解释与辩解，也永远不要索要。评语只看物证。

审查规则：
- 逐条核对画像里的每个承诺：承诺 X，在 diff 或机器证据里真的兑现了吗？指得出位置吗？
- 前置审加料：画像里标注了哪些是用户没明说、施工者自行添加的内容（加料清单）。逐条问：这条添加服务用户目标吗？还是为施工者自己方便加的（过度设计、顺手重构、夹带私货）？加料失控是 reject 理由。
- 对抗性读 diff：专挑边界条件、错误处理、空输入、与既有代码的重复逻辑。
- 每条 fail 必须给出证据位置，三形其一：path:line（代码/diff 位置，如 tasks.py:347）、machine:<checker>（机器结果条目，如 machine:check.python）、portrait:<定位>（画像小节，如 portrait:承诺②）。没有证据或证据不是这三形的批评是废话，会被机器判作废。
- 机器已经判过的事项（测试通过、预算达标、删除门的退役链与 confirm 保险丝）不要重复裁决，把注意力留给机器判不了的：承诺兑现、逻辑对错、复用与写法约定。

只输出一个 JSON 对象，不要输出任何其他文字：
{
  "verdict": "pass 或 reject",
  "items": [{"name": "检查项", "status": "pass 或 fail", "evidence": "path:line 或 machine:<checker> 或 portrait:<定位>（fail 必填）", "comment": "评语"}],
  "summary": "一句话总评；reject 时必须写明修哪、怎么算修好"
}"""


class RegulatorError(Exception):
    """监管调用或裁决解析失败——由 run_agent_review 降级吸收。"""


def build_messages(
    portrait: str,
    diff_text: str,
    machine_summary: str,
    *,
    self_grading_declared: bool = False,
    portrait_amendments: list[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    """拼监管提示词。输入只有画像 + diff + 机器报告，物理上不含 worker 自述。"""
    banner = ""
    if self_grading_declared:
        banner = (
            "## 审查级别提升（巴林条款）\n\n"
            "本任务已申报同时修改产品代码与验证它的测试（自我阅卷）。"
            "请重点核对：测试改动是否削弱断言、删除用例、放宽门槛以迁就产品改动。\n\n"
        )
    if portrait_amendments:
        lines = ["## 画像修订史（开工后画像被更换过）", ""]
        for item in portrait_amendments:
            lines.append(
                "- {} actor={} reason={} old={} new={}".format(
                    item.get("occurred_at", "?"),
                    item.get("actor", "?"),
                    item.get("reason", "?"),
                    str(item.get("old_digest", ""))[:12],
                    str(item.get("new_digest", ""))[:12],
                )
            )
        lines.append("")
        lines.append(
            "下方画像是最新版，旧画像只剩 digest 存证。请裁决：每次修订是市长指名的纠偏"
            "（理由具体、指向用户目标），还是施工者为方便自己的自利漂移（放宽承诺、删难点）？"
            "后者是 reject 理由。"
        )
        banner += "\n".join(lines) + "\n\n"
    from .portrait import portrait_inference_section

    additions = portrait_inference_section(portrait)
    additions_block = ""
    if additions:
        additions_block = (
            "## AI 加料清单（用户没明说、施工者自行添加的内容）\n\n"
            + additions
            + "\n\n逐条裁决：这条添加服务用户目标吗？加料失控（过度设计、顺手重构、夹带私货）是 reject 理由。\n\n"
        )
    user = (
        banner
        + "## 画像（当初锁定的承诺）\n\n" + (portrait.strip() or "（无画像）")
        + "\n\n" + additions_block
        + "## 机器检查结果\n\n" + (machine_summary.strip() or "（无机器检查记录）")
        + "\n\n## diff（实际改动）\n\n" + (diff_text.strip() or "（无改动）")
    )
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def parse_verdict(text: str) -> dict[str, Any]:
    """从模型输出中提取裁决 JSON。容忍代码围栏，拒绝任何非 JSON 输出。"""
    candidate = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", candidate, re.S)
    if fence:
        candidate = fence.group(1)
    elif not candidate.startswith("{"):
        start, end = candidate.find("{"), candidate.rfind("}")
        if start == -1 or end <= start:
            raise RegulatorError("regulator output is not JSON")
        candidate = candidate[start : end + 1]
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise RegulatorError(f"regulator verdict is malformed JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise RegulatorError("regulator verdict must be a JSON object")
    return value


def verdict_problems(verdict: dict[str, Any]) -> list[str]:
    """机器校验裁决。返回问题清单；空清单 = 裁决有效。

    铁律 3 在这里强制执行：fail 项缺 file:line 证据 → 裁决作废。
    """
    problems: list[str] = []
    outcome = str(verdict.get("verdict", "")).strip()
    if outcome not in {"pass", "reject"}:
        problems.append(f"verdict must be pass|reject, got {outcome!r}")
    items = verdict.get("items")
    if not isinstance(items, list) or not items:
        problems.append("items must be a non-empty list")
        items = [] if not isinstance(items, list) else items
    fails = 0
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            problems.append(f"items[{index}] must be an object")
            continue
        status = str(item.get("status", "")).strip()
        if status not in {"pass", "fail"}:
            problems.append(f"items[{index}].status must be pass|fail, got {status!r}")
            continue
        if not str(item.get("comment", "") or "").strip():
            problems.append(f"items[{index}] ({item.get('name', '?')}) has an empty comment")
        if status == "fail":
            fails += 1
            evidence = str(item.get("evidence", "") or "").strip()
            if not _EVIDENCE_REF.search(evidence):
                problems.append(
                    f"items[{index}] ({item.get('name', '?')}) is fail without a file:line / machine:<checker> / portrait:<section> evidence reference"
                )
    if outcome == "reject" and fails == 0:
        problems.append("verdict is reject but no item is fail")
    if outcome == "pass" and fails:
        problems.append("verdict is pass but some items are fail")
    return problems


def extract_usage(body: Any, model: str) -> dict[str, Any] | None:
    """从 OpenAI 兼容响应抠 {model, input, output}。缺字段不虚构。"""
    if not isinstance(body, dict):
        return None
    usage = body.get("usage")
    if not isinstance(usage, dict):
        return None
    raw_in = usage.get("prompt_tokens", usage.get("input_tokens"))
    raw_out = usage.get("completion_tokens", usage.get("output_tokens"))
    if not isinstance(raw_in, (int, float)) or not isinstance(raw_out, (int, float)):
        return None
    if raw_in < 0 or raw_out < 0:
        return None
    return {
        "model": model,
        "input": int(raw_in),
        "output": int(raw_out),
        "source": "regulator-api",
    }


def _with_usage(result: dict[str, Any], usage: dict[str, Any] | None) -> dict[str, Any]:
    if usage:
        result["usage"] = usage
    return result


def complete_chat(config: RegulatorConfig, messages: list[dict[str, str]]) -> tuple[str, dict[str, Any] | None]:
    """一次 OpenAI 兼容调用，同时返回 usage（没有则为 None）。"""
    url = config.endpoint.rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    api_key = os.environ.get(config.api_key_env, "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = json.dumps(
        {"model": config.model, "messages": messages, "temperature": 0},
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=config.timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # 网络/HTTP/解析失败统一降级，不炸 verify
        raise RegulatorError(f"regulator call failed: {exc}") from exc
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RegulatorError(f"regulator response has no message content: {body!r:.200}") from exc
    if not isinstance(content, str) or not content.strip():
        raise RegulatorError("regulator returned an empty message")
    return content, extract_usage(body, config.model)


def call_chat(config: RegulatorConfig, messages: list[dict[str, str]]) -> str | tuple[str, dict[str, Any] | None]:
    """一次 OpenAI 兼容调用。无重试、无流式——V1 故意保持哑。

    生产返回 (content, usage)；测试 mock 仍可返回纯 str。
    """
    return complete_chat(config, messages)


def _machine_summary(report: dict[str, Any]) -> str:
    lines: list[str] = []
    for item in report.get("results") or []:
        lines.append(
            f"[{item.get('status')}] {item.get('id')} (stage={item.get('stage')}, exit={item.get('exit_code')})"
        )
    acceptance = report.get("acceptance")
    if acceptance:
        lines.append("acceptance: " + str(acceptance))
    return "\n".join(lines)


def _collect_diff(worktree: Path, source_head: str) -> str:
    """diff = 已跟踪改动的 git diff + 未跟踪新文件的全文（截断）。"""
    parts = [git(worktree, "diff", source_head)]
    porcelain = git(worktree, "status", "--porcelain")
    for line in porcelain.splitlines():
        if not line.startswith("?? "):
            continue
        relative = line[3:].strip().strip('"')
        candidate = worktree / relative
        if not candidate.is_file():
            continue
        try:
            content = candidate.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        parts.append(f"--- 新文件（未跟踪）: {relative}\n{content[:_MAX_FILE_CHARS]}")
    return "\n\n".join(part for part in parts if part.strip())[:_MAX_DIFF_CHARS]


def run_agent_review(
    worktree: Path,
    task: dict[str, Any],
    policy: Policy,
    machine_report: dict[str, Any],
) -> dict[str, Any]:
    """跑一次监管。永不抛异常——不可用一律返回 outcome=unavailable 并记缺口。

    outcome:
    - passed      监管裁决 pass
    - rejected    监管裁决 reject（打回；verify 不许过）
    - unavailable 未配置 / 调用失败 / 裁决作废；证据里记"本次缺 AI 监管"
    """
    config = policy.regulator
    if config is None or not config.enabled:
        return {
            "outcome": "unavailable",
            "reason": "not-configured",
            "prompt_version": PROMPT_VERSION,
            "gap": "本次缺 AI 监管",
        }
    base: dict[str, Any] = {"prompt_version": PROMPT_VERSION, "model": config.model}
    if not config.allow_same_family and same_family(config.model, config.worker_model):
        # 9.10 安达信条款纵深防御：policy 被手改绕过 configure_regulator 时，
        # 运行时仍拒绝假异构监管；strict 下 verify 拦截，非 strict 记缺口降级。
        return {
            **base,
            "outcome": "unavailable",
            "reason": f"same-family: regulator {model_family(config.model)} == worker {model_family(config.worker_model)}",
            "gap": "监管与 worker 同族（安达信条款），本次缺独立 AI 监管",
        }
    usage: dict[str, Any] | None = None
    try:
        diff_text = _collect_diff(worktree, str(task["source"]["head"]))
        portrait = str(task.get("portrait") or "")
        declaration = task.get("entry", {}).get("touches_verification")
        self_grading = isinstance(declaration, dict) and bool(declaration.get("declared"))
        amendments = [
            {key: item.get(key) for key in ("occurred_at", "actor", "reason", "old_digest", "new_digest")}
            for item in task.get("interventions", [])
            if isinstance(item, dict) and item.get("kind") == "portrait-amended"
        ]
        messages = build_messages(
            portrait,
            diff_text,
            _machine_summary(machine_report),
            self_grading_declared=self_grading,
            portrait_amendments=amendments,
        )
        raw = call_chat(config, messages)
        usage = None
        if isinstance(raw, tuple):
            raw, usage = raw[0], raw[1] if len(raw) > 1 else None
        verdict = parse_verdict(raw)
    except RegulatorError as exc:
        return _with_usage(
            {**base, "outcome": "unavailable", "reason": str(exc), "gap": "本次缺 AI 监管"},
            usage,
        )
    except Exception as exc:  # git 失败等意外同样降级，不炸 verify
        return _with_usage(
            {**base, "outcome": "unavailable", "reason": f"unexpected: {exc}", "gap": "本次缺 AI 监管"},
            usage,
        )
    problems = verdict_problems(verdict)
    if problems:
        return _with_usage(
            {
                **base,
                "outcome": "unavailable",
                "reason": "invalid-verdict: " + "; ".join(problems),
                "verdict": verdict,
                "gap": "本次缺 AI 监管（裁决作废）",
            },
            usage,
        )
    return _with_usage(
        {
            **base,
            "outcome": "passed" if verdict["verdict"] == "pass" else "rejected",
            "verdict": verdict,
        },
        usage,
    )
