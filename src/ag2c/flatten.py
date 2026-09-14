"""反向开发：热度×肥胖度队列 + 纯搬运门 + 拆分原语。

队列给 boy scout 拆谁；flatten_split 抽出顶层符号到新模块并由源文件再导出；
纯搬运门验收摊平 diff——新增非豁免行的哈希必须全部出现在删除行里。
豁免 import/from 行与新文件开头的模块 docstring。
"""
from __future__ import annotations

import ast
import hashlib
import re
from pathlib import Path
from typing import Any

from .errors import AG2CError
from .gitops import git
from .softcap import SOFTCAP_ROOT

FLATTEN_QUEUE_SCHEMA = "ag2c.flatten-queue.v1"
FLATTEN_CHECK_SCHEMA = "ag2c.flatten-check.v1"
FLATTEN_SPLIT_SCHEMA = "ag2c.flatten-split.v1"
FLATTEN_BILL_SCHEMA = "ag2c.flatten-bill.v1"

_IMPORT_RE = re.compile(r"^[ \t]*(import |from )")
_DOCSTRING_OPEN_RE = re.compile(r'^[ \t]*("""|\'\'\')')


def line_fingerprint(line: str) -> str:
    return hashlib.sha256(line.encode("utf-8")).hexdigest()


def _is_import_line(line: str) -> bool:
    return bool(_IMPORT_RE.match(line))


def _leading_docstring_fingerprints(lines: list[str]) -> set[str]:
    """Fingerprints of a leading module docstring in an added-line sequence."""
    i = 0
    while i < len(lines) and (not lines[i].strip() or _is_import_line(lines[i]) or lines[i].lstrip().startswith("from __future__")):
        i += 1
    if i >= len(lines):
        return set()
    match = _DOCSTRING_OPEN_RE.match(lines[i])
    if not match:
        return set()
    quote = match.group(1)
    found: set[str] = set()
    while i < len(lines):
        found.add(line_fingerprint(lines[i]))
        if lines[i].rstrip().endswith(quote) and (lines[i].count(quote) >= 2 or len(found) > 1):
            break
        i += 1
    return found


def parse_unified_diff(diff: str) -> tuple[list[str], dict[str, list[str]]]:
    """Return (deleted lines, {path: added lines in order})."""
    deleted: list[str] = []
    added: dict[str, list[str]] = {}
    path = ""
    for raw in diff.splitlines():
        if raw.startswith("+++ "):
            body = raw[4:].strip()
            if body.startswith("b/"):
                body = body[2:]
            path = "" if body == "/dev/null" else body
            continue
        if raw.startswith("--- ") or raw.startswith("@@") or raw.startswith("diff "):
            continue
        if raw.startswith("+"):
            if path:
                added.setdefault(path, []).append(raw[1:])
            continue
        if raw.startswith("-"):
            deleted.append(raw[1:])
    return deleted, added


def pure_move_violations(diff: str) -> list[str]:
    """Added non-exempt lines whose fingerprint is missing from deleted lines."""
    deleted, added_files = parse_unified_diff(diff)
    deleted_fps = {line_fingerprint(line) for line in deleted}
    violations: list[str] = []
    for path, lines in added_files.items():
        exempt = _leading_docstring_fingerprints(lines)
        for line in lines:
            if not line.strip() or _is_import_line(line):
                continue
            fp = line_fingerprint(line)
            if fp in exempt or fp in deleted_fps:
                continue
            violations.append(f"{path}:{line}")
    return violations


def is_exam_path(path: str) -> bool:
    posix = path.replace("\\", "/")
    name = posix.rsplit("/", 1)[-1]
    if name.startswith("test_") and name.endswith(".py"):
        return True
    if posix.startswith("tests/") or "/tests/" in posix:
        return posix.endswith(".py")
    return posix.endswith(".py") and (posix.startswith("pack/exams/") or "/pack/exams/" in posix)


def flatten_bill(diff: str) -> dict[str, Any]:
    """Classify a unified diff into 搬家 / 新考卷 / 行为改动."""
    deleted, added_files = parse_unified_diff(diff)
    deleted_fps = {line_fingerprint(line) for line in deleted}
    moves: list[str] = []
    exams: list[str] = []
    behavior: list[dict[str, Any]] = []
    for path, lines in sorted(added_files.items()):
        if is_exam_path(path):
            exams.append(path)
            continue
        exempt = _leading_docstring_fingerprints(lines)
        bad: list[str] = []
        for line in lines:
            if not line.strip() or _is_import_line(line):
                continue
            fp = line_fingerprint(line)
            if fp in exempt or fp in deleted_fps:
                continue
            bad.append(line)
        if bad:
            behavior.append({"path": path, "lines": bad})
        else:
            moves.append(path)
    return {
        "schema": FLATTEN_BILL_SCHEMA,
        "moves": moves,
        "exams": exams,
        "behavior": behavior,
    }


def format_flatten_bill(bill: dict[str, Any]) -> str:
    def block(title: str, rows: list[str]) -> list[str]:
        out = [title]
        if rows:
            out.extend(f"  {row}" for row in rows)
        else:
            out.append("  （无）")
        return out

    lines = block("搬家:", list(bill.get("moves") or []))
    lines.extend(block("新考卷:", list(bill.get("exams") or [])))
    behavior_rows = []
    for item in bill.get("behavior") or []:
        path = str(item.get("path") or "")
        snippets = list(item.get("lines") or [])[:3]
        if snippets:
            behavior_rows.append(f"{path}: {snippets[0].strip()}")
        else:
            behavior_rows.append(path)
    lines.extend(block("行为改动:", behavior_rows))
    return "\n".join(lines) + "\n"


def _commit_count(root: Path, rel: str) -> int:
    try:
        text = str(git(root, "rev-list", "--count", "HEAD", "--", rel, check=False) or "0").strip()
        return max(0, int(text or "0"))
    except (ValueError, OSError, TypeError):
        return 0


def flatten_queue(root: Path, *, under: str | None = None) -> list[dict[str, Any]]:
    """Python files under ``under`` ranked by lines * git-commit-count.

    Default ``under`` is src/ag2c when that folder exists (AG2C-self). Pass a
    relative directory to rank a foreign worktree.
    """
    root = root.resolve()
    relative = (under or "").replace("\\", "/").strip().strip("/")
    if relative in {".."} or relative.startswith("../"):
        raise AG2CError("flatten-queue --under must be inside the repository")
    if not relative:
        relative = SOFTCAP_ROOT.as_posix()
    base = (root / relative).resolve()
    try:
        base.relative_to(root)
    except ValueError as exc:
        raise AG2CError("flatten-queue --under must be inside the repository") from exc
    items: list[dict[str, Any]] = []
    if not base.is_dir():
        return items
    for path in sorted(base.rglob("*.py")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        try:
            rel = path.resolve().relative_to(root).as_posix()
        except ValueError:
            continue
        lines = len(text.splitlines())
        heat = _commit_count(root, rel)
        items.append({"path": rel, "lines": lines, "heat": heat, "score": lines * heat})
    items.sort(key=lambda item: (-int(item["score"]), str(item["path"])))
    return items


def _top_level_nodes(tree: ast.Module) -> dict[str, ast.stmt]:
    found: dict[str, ast.stmt] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            found[node.name] = node
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    found[target.id] = node
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            found[node.target.id] = node
    return found


def _posix(rel: str) -> str:
    return rel.replace("\\", "/").lstrip("./")


def flatten_split(
    root: Path,
    *,
    source: str,
    dest: str,
    names: list[str],
    dry_run: bool = False,
) -> dict[str, Any]:
    """Copy named top-level defs from source into dest; source re-exports them."""
    root = root.resolve()
    source_rel = _posix(source)
    dest_rel = _posix(dest)
    wanted = [item.strip() for item in names if str(item).strip()]
    if not wanted:
        raise AG2CError("flatten-split requires --name")
    if source_rel == dest_rel:
        raise AG2CError("flatten-split source and dest must differ")
    if Path(source_rel).parent.as_posix() != Path(dest_rel).parent.as_posix():
        raise AG2CError("flatten-split dest must be in the same directory as source")
    src_path = root / source_rel
    dest_path = root / dest_rel
    if not src_path.is_file():
        raise AG2CError(f"flatten-split source missing: {source_rel}")
    if dest_path.exists() and not dry_run:
        raise AG2CError(f"flatten-split dest already exists: {dest_rel}")
    text = src_path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        raise AG2CError(f"flatten-split cannot parse {source_rel}: {exc}") from exc
    index = _top_level_nodes(tree)
    missing = [name for name in wanted if name not in index]
    if missing:
        raise AG2CError("flatten-split unknown names: " + ", ".join(missing))
    lines = text.splitlines(keepends=True)
    ranges: list[tuple[int, int, str]] = []
    seen: set[int] = set()
    for name in wanted:
        node = index[name]
        if id(node) in seen:
            continue
        seen.add(id(node))
        start = int(node.lineno)
        decorators = getattr(node, "decorator_list", None) or []
        if decorators:
            start = min(start, int(decorators[0].lineno))
        end = int(node.end_lineno or node.lineno)
        ranges.append((start, end, name))
    ranges.sort()
    payload: dict[str, Any] = {
        "schema": FLATTEN_SPLIT_SCHEMA,
        "source": source_rel,
        "dest": dest_rel,
        "names": wanted,
        "ranges": [{"name": name, "start": start, "end": end} for start, end, name in ranges],
        "dry_run": bool(dry_run),
    }
    if dry_run:
        return payload
    blocks = ["".join(lines[start - 1 : end]) for start, end, _name in ranges]
    new_lines = lines[:]
    for start, end, _name in sorted(ranges, key=lambda item: item[0], reverse=True):
        del new_lines[start - 1 : end]
    collapsed: list[str] = []
    blanks = 0
    for line in new_lines:
        if line.strip() == "":
            blanks += 1
            if blanks <= 2:
                collapsed.append(line if line.endswith("\n") else line + "\n")
            continue
        blanks = 0
        collapsed.append(line)
    new_lines = collapsed
    import_mod = Path(dest_rel).stem
    import_line = "from ." + import_mod + " import " + ", ".join(wanted) + "\n"
    insert_at = 0
    idx = 0
    while idx < len(new_lines) and not new_lines[idx].strip():
        idx += 1
    if idx < len(new_lines):
        opened = _DOCSTRING_OPEN_RE.match(new_lines[idx])
        if opened:
            quote = opened.group(1)
            if new_lines[idx].count(quote) >= 2 and new_lines[idx].rstrip().endswith(quote):
                idx += 1
            else:
                idx += 1
                while idx < len(new_lines) and quote not in new_lines[idx]:
                    idx += 1
                if idx < len(new_lines):
                    idx += 1
        insert_at = idx
    for i, line in enumerate(new_lines):
        if i < insert_at or line[:1] in " \t":
            continue
        stripped = line.strip()
        if stripped.startswith("from __future__") or stripped.startswith("import ") or stripped.startswith("from "):
            insert_at = i + 1
    if insert_at < len(new_lines) and new_lines[insert_at].strip() != "":
        new_lines.insert(insert_at, "\n")
    new_lines.insert(insert_at, import_line)
    body = "".join(new_lines)
    if not body.endswith("\n"):
        body += "\n"
    src_path.write_text(body.rstrip("\n") + "\n", encoding="utf-8")
    pieces: list[str] = []
    for block in blocks:
        chunk = block if block.endswith("\n") else block + "\n"
        if pieces:
            pieces.append("\n")
        pieces.append(chunk)
    header = '"""Extracted by flatten-split."""\nfrom __future__ import annotations\n\n'
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_text(header + "".join(pieces).rstrip("\n") + "\n", encoding="utf-8")
    payload["written"] = True
    return payload
