"""反向开发：热度×肥胖度队列 + 纯搬运门。

队列给 boy scout 拆谁；纯搬运门验收摊平 diff——新增非豁免行的哈希必须
全部出现在删除行里。豁免 import/from 行与新文件开头的模块 docstring。
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from .gitops import git
from .softcap import SOFTCAP_ROOT

FLATTEN_QUEUE_SCHEMA = "ag2c.flatten-queue.v1"
FLATTEN_CHECK_SCHEMA = "ag2c.flatten-check.v1"

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


def _commit_count(root: Path, rel: str) -> int:
    try:
        text = str(git(root, "rev-list", "--count", "HEAD", "--", rel, check=False) or "0").strip()
        return max(0, int(text or "0"))
    except (ValueError, OSError, TypeError):
        return 0


def flatten_queue(root: Path) -> list[dict[str, Any]]:
    """src/ag2c Python files ranked by lines * git-commit-count."""
    root = root.resolve()
    base = root / SOFTCAP_ROOT
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
