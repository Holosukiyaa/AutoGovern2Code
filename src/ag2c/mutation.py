"""变异金丝雀：对产品代码施加一处语义变异，检验测试套件是否有牙。

眼镜蛇条款（《历史案例审计》洞 3）：checker 数"测试通过数"，不数断言质量——
AI 可以写形同虚设的测试，通过率 100% 什么都没证明。变异测试内化进金丝雀：
系统故意改坏一行产品代码，测试套件必须红；不红 = 变异存活 = 测试空心，报警。

与门禁金丝雀（cli._canary）的分工：门禁金丝雀在 tests/ 投放失败用例，验的是
"门禁拦不拦"；变异金丝雀改 src/ 产品代码，验的是"测试咬不咬"。

变异定位用 tokenize 而非 AST 行号——操作符节点的位置信息不可靠，token 流
天然跳过字符串与注释，位置精确到列。
"""
from __future__ import annotations

import io
import random
import tokenize
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: 单点变异算子：比较符翻转。语义必变且语法必合法。
_OP_FLIPS = {
    "==": "!=",
    "!=": "==",
    "<": ">=",
    ">": "<=",
    "<=": ">",
    ">=": "<",
}


@dataclass(frozen=True)
class Mutation:
    """一处可应用的语义变异，位置精确到 token。"""

    line: int  # 1-based
    col: int  # 0-based
    original: str
    replacement: str
    description: str


def find_mutations(source: str) -> list[Mutation]:
    """列出源码里所有单点变异候选。无候选 = 这个文件没有可变异的逻辑点。"""
    found: list[Mutation] = []
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for token in tokens:
            if token.type == tokenize.OP and token.string in _OP_FLIPS:
                flipped = _OP_FLIPS[token.string]
                found.append(
                    Mutation(token.start[0], token.start[1], token.string, flipped, f"比较符 {token.string}→{flipped}")
                )
            elif token.type == tokenize.NAME and token.string in ("True", "False"):
                flipped = "False" if token.string == "True" else "True"
                found.append(
                    Mutation(token.start[0], token.start[1], token.string, flipped, f"布尔 {token.string}→{flipped}")
                )
            elif token.type == tokenize.NUMBER and token.string.isdigit():
                bumped = str(int(token.string) + 1)
                found.append(
                    Mutation(token.start[0], token.start[1], token.string, bumped, f"数字 {token.string}→{bumped}")
                )
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return []
    return found


def pick_mutation(source: str, rng: random.Random) -> Mutation | None:
    """从候选中随机选一处。随机选点让金丝雀每次咬不同的位置。"""
    candidates = find_mutations(source)
    return rng.choice(candidates) if candidates else None


def apply_mutation(source: str, mutation: Mutation) -> str:
    """应用变异。位置与原文不符时抛 AssertionError——宁可炸也不写错文件。"""
    lines = source.splitlines(keepends=True)
    line = lines[mutation.line - 1]
    actual = line[mutation.col : mutation.col + len(mutation.original)]
    if actual != mutation.original:
        raise AssertionError(
            f"mutation position mismatch at {mutation.line}:{mutation.col}: "
            f"expected {mutation.original!r}, found {actual!r}"
        )
    lines[mutation.line - 1] = (
        line[: mutation.col] + mutation.replacement + line[mutation.col + len(mutation.original) :]
    )
    return "".join(lines)


def mutation_targets(manifest, policy) -> list[Path]:
    """可变异的产品代码：带 unittest 解析 checker 的 floor 房间里的 .py 文件。

    测试文件本身被排除——变异测试文件证明不了产品代码被测试 pinning 住。
    房间的 checker 里没有 unittest 解析器时，变异存活只能说明"这个房间本来
    就没有测试门禁"，不算空心证据，因此不选。
    """
    targets: set[Path] = set()
    for card in policy.cards:
        if card.card_type != "floor":
            continue
        try:
            checkers = [policy.checker(checker_id) for checker_id in card.checkers]
        except StopIteration:
            continue
        if not any(checker.parse == "unittest" for checker in checkers):
            continue
        for scope in card.scopes:
            if scope.ownership != "primary":
                continue
            root = manifest.target_root(scope.target_id)
            for include in scope.includes:
                for matched in root.glob(include):
                    # "src/**" 只产出目录本身；房间声明的语义是"整棵子树"。
                    paths = matched.rglob("*") if matched.is_dir() else [matched]
                    for path in paths:
                        if not path.is_file() or path.suffix != ".py":
                            continue
                        parts = set(path.parts)
                        if "tests" in parts or path.name.startswith("test_"):
                            continue
                        targets.add(path)
    return sorted(targets)


def run_mutation_canary(
    manifest, policy, *, actor: str, reason: str, seed: int | None = None, target: str | None = None
) -> tuple[dict[str, Any], int]:
    """跑一次变异金丝雀。返回 (结果 dict, 退出码)。

    语义与门禁金丝雀相反：checker 失败（测试变红）才是好消息——变异被杀，
    测试有牙；全部通过 = 变异存活 = 测试空心化，canary failed 并报警。
    文件无论如何都会被还原；index/census 自毒按金丝雀模式见证。

    target（可选）：定向变异指定文件（path_spec 或仓内相对路径），文件内
    变异点仍随机。用途：危房名单里的变异存活记录靠"同文件演习通过"销案，
    随机选文件可能永远摇不中——定向复跑让已修复的空心区能正式摘帽。
    """
    from .checks import run_checks
    from .household_commands import review_census
    from .households import census_report
    from .index import build_index
    from .ledger import append_event
    from .slicer import compile_slice

    rng = random.Random(seed)
    target_root = manifest.target_root(manifest.targets[0].target_id)
    if target:
        # 归一化：剥掉 path_spec 前缀，统一成仓内相对路径
        relative_input = target.partition(":")[2] if ":" in target else target
        chosen = (target_root / relative_input).resolve()
        allowed = {path.resolve() for path in mutation_targets(manifest, policy)}
        if chosen not in allowed:
            result = {
                "schema": "ag2c.canary.v1",
                "mode": "mutation",
                "canary": "error",
                "reason": f"target-not-mutable: {target} 不在可变异集合（需要带 unittest 门禁的 floor 房间内的产品代码）",
                "actor": actor,
            }
            append_event(manifest.ledger_path, "canary", result)
            return result, 2
        candidates = [chosen]
    else:
        candidates = mutation_targets(manifest, policy)
        rng.shuffle(candidates)

    def _stale_households() -> set[str]:
        report = census_report(manifest, policy)
        return {item["id"] for item in report["households"] if item["freshness"] != "current"}

    chosen: Path | None = None
    mutation: Mutation | None = None
    original = ""
    for path in candidates:
        try:
            # newline="" 关闭换行转换：读入与还原都必须保留原始字节，
            # 否则 CRLF 文件会被"还原"成 LF，在 Git 眼里就是未声明的改动。
            with open(path, encoding="utf-8", newline="") as handle:
                source = handle.read()
        except OSError:
            continue
        picked = pick_mutation(source, rng)
        if picked is not None:
            chosen, mutation, original = path, picked, source
            break
    if chosen is None or mutation is None:
        no_candidate_reason = (
            f"no-mutation-candidate: 目标文件 {target} 里没有可变异点（比较符/布尔/数字）"
            if target
            else "no-mutation-candidate: 受治理产品代码里没有可变异点"
        )
        result = {
            "schema": "ag2c.canary.v1",
            "mode": "mutation",
            "canary": "error",
            "reason": no_candidate_reason,
            "actor": actor,
        }
        append_event(manifest.ledger_path, "canary", result)
        return result, 2

    relative = chosen.relative_to(target_root).as_posix()
    path_spec = f"{manifest.targets[0].target_id}:{relative}"
    pre_stale = _stale_households()
    canary_caused: set[str] = set()
    try:
        with open(chosen, "w", encoding="utf-8", newline="") as handle:
            handle.write(apply_mutation(original, mutation))
        # 与门禁金丝雀同理：先刷新索引快照，再见证自致陈旧的房间，
        # 让门禁评估变异本身而不是拒绝金丝雀的足迹。
        build_index(manifest, policy)
        canary_caused = _stale_households() - pre_stale
        if canary_caused:
            review_census(
                target_root,
                card_ids=sorted(canary_caused),
                all_cards=False,
                actor=actor,
                reason=f"mutation canary footprint: attest self-mutated {path_spec}",
            )
        entry_slice = compile_slice(
            manifest,
            policy,
            path_specs=[path_spec],
            contract_specs=[],
            goal="canary: mutation testing",
            all_mode=False,
        )
        report = run_checks(
            manifest,
            policy,
            entry_slice,
            all_mode=False,
            ledger_path=manifest.ledger_path,
            task_id="canary",
        )
        failed = [item for item in report["results"] if item["status"] not in {"passed", "skipped"}]
        killed = bool(failed)
        result = {
            "schema": "ag2c.canary.v1",
            "mode": "mutation",
            "canary": "passed" if killed else "failed",
            "target": path_spec,
            "mutation": f"{mutation.description}（{relative}:{mutation.line}）",
            "caught_by": [item["id"] for item in failed],
            "checkers_run": len(report["results"]),
            "actor": actor,
            "reason": reason,
        }
        append_event(manifest.ledger_path, "canary", result)
        return result, 0 if killed else 1
    finally:
        # 还原原文；索引与普查见证同步还原，不给后续治理动作留障碍。
        with open(chosen, "w", encoding="utf-8", newline="") as handle:
            handle.write(original)
        try:
            build_index(manifest, policy)
            restored = _stale_households() & canary_caused
            if restored:
                review_census(
                    target_root,
                    card_ids=sorted(restored),
                    all_cards=False,
                    actor=actor,
                    reason="mutation canary cleanup: re-attest restored rooms",
                )
        except Exception:
            import sys

            print("AG2C warning: index refresh failed after mutation canary cleanup", file=sys.stderr)
