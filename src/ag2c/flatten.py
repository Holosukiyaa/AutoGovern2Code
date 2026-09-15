"""反向开发：热度×肥胖度队列 + 纯搬运门 + 拆分原语 + 胶水/门牌法官。

队列给 boy scout 拆谁；flatten_split 抽出顶层符号到新模块并由源文件再导出；
纯搬运门验收摊平 diff——新增非豁免行的哈希必须全部出现在删除行里。
豁免 import/from 行与新文件开头的模块 docstring。
flatten_glue / flatten_door 判定再导出+调用方分群，以及门牌是否切断。
账单把只改进口记成改路牌，不记行为改动。
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
FLATTEN_GLUE_SCHEMA = "ag2c.flatten-glue.v1"
FLATTEN_DOOR_SCHEMA = "ag2c.flatten-door.v1"

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
    """Classify a unified diff into 搬家 / 改路牌 / 新考卷 / 行为改动."""
    deleted, added_files = parse_unified_diff(diff)
    deleted_fps = {line_fingerprint(line) for line in deleted}
    moves: list[str] = []
    exams: list[str] = []
    retarget: list[str] = []
    behavior: list[dict[str, Any]] = []
    for path, lines in sorted(added_files.items()):
        if is_exam_path(path):
            exams.append(path)
            continue
        exempt = _leading_docstring_fingerprints(lines)
        bad: list[str] = []
        import_new: list[str] = []
        for line in lines:
            if not line.strip():
                continue
            fp = line_fingerprint(line)
            if _is_import_line(line):
                if fp not in deleted_fps:
                    import_new.append(line)
                continue
            if fp in exempt or fp in deleted_fps:
                continue
            bad.append(line)
        if bad:
            behavior.append({"path": path, "lines": bad})
        elif import_new:
            retarget.append(path)
        else:
            moves.append(path)
    return {
        "schema": FLATTEN_BILL_SCHEMA,
        "moves": moves,
        "exams": exams,
        "retarget": retarget,
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
    lines.extend(block("改路牌:", list(bill.get("retarget") or [])))
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


def _defined_names(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in getattr(tree, "body", []):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            found.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    found.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            found.add(node.target.id)
    return found


def _reexports(tree: ast.AST) -> dict[str, str]:
    """Relative imports of names this file does not define (the door handing out side-room stock)."""
    own = _defined_names(tree)
    out: dict[str, str] = {}
    for node in getattr(tree, "body", []):
        if not isinstance(node, ast.ImportFrom) or node.level < 1 or not node.module:
            continue
        for alias in node.names:
            name = alias.asname or alias.name
            if name != "*" and name not in own:
                out[name] = node.module
    return out


def _module_matches_stem(module: str | None, stem: str) -> bool:
    if not module:
        return False
    tail = module.replace("\\", "/").rsplit(".", 1)[-1]
    return tail == stem


def _parse_repo_py(root: Path) -> dict[str, ast.AST]:
    files: dict[str, ast.AST] = {}
    root = root.resolve()
    for path in root.rglob("*.py"):
        if "__pycache__" in path.parts or ".git" in path.parts:
            continue
        try:
            rel = path.resolve().relative_to(root).as_posix()
        except ValueError:
            continue
        try:
            files[rel] = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeError):
            continue
    return files


def _caller_clusters(files: dict[str, ast.AST], door_rel: str) -> list[list[str]]:
    stem = Path(door_rel).stem
    clusters: list[list[str]] = []
    for rel, tree in files.items():
        if rel == door_rel:
            continue
        used: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if not _module_matches_stem(node.module, stem):
                continue
            for alias in node.names:
                name = alias.asname or alias.name
                if name != "*":
                    used.add(name)
        if used:
            clusters.append(sorted(used))
    return clusters


def _clusters_disjoint(clusters: list[list[str]]) -> bool:
    frozen = [frozenset(item) for item in clusters if item]
    for i, left in enumerate(frozen):
        for right in frozen[i + 1 :]:
            if left.isdisjoint(right):
                return True
    return False


def flatten_glue(root: Path, file_rel: str) -> dict[str, Any]:
    """True glue only when the door re-exports AND callers split into disjoint name sets."""
    rel = _posix(file_rel)
    path = (root / rel).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise AG2CError("flatten-glue --file must be inside the repository") from exc
    if not path.is_file():
        raise AG2CError(f"flatten-glue missing file: {rel}")
    if Path(rel).name == "__init__.py":
        return {
            "schema": FLATTEN_GLUE_SCHEMA,
            "file": rel,
            "glue": False,
            "reasons": ["总牌：__init__.py 给人指路，不判胶水"],
            "reexports": {},
            "clusters": [],
        }
    files = _parse_repo_py(root)
    tree = files.get(rel)
    if tree is None:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeError) as exc:
            raise AG2CError(f"flatten-glue cannot parse {rel}: {exc}") from exc
        files[rel] = tree
    imported = _reexports(tree)
    clusters = _caller_clusters(files, rel)
    taken = {name for group in clusters for name in group}
    transferred = {name: module for name, module in imported.items() if name in taken}
    split = _clusters_disjoint(clusters)
    reasons: list[str] = []
    if transferred:
        reasons.append("大门自己不存货，转口: " + ", ".join(transferred))
    if split:
        packed = ["{" + ", ".join(group) + "}" for group in clusters]
        reasons.append("来拿货的人分成两拨，各拿各的: " + " | ".join(packed))
    glue = bool(transferred) and split
    if not reasons:
        reasons.append("没有转口，调用方也不分群。不是胶水。")
    elif not glue:
        reasons.insert(0, "只有一条嫌疑，不立案。")
    return {
        "schema": FLATTEN_GLUE_SCHEMA,
        "file": rel,
        "glue": glue,
        "reasons": reasons,
        "reexports": transferred,
        "clusters": clusters,
    }


def flatten_door(root: Path, *, old: str, side: str, names: list[str]) -> dict[str, Any]:
    """Doorplate is cut only when the old file no longer re-exports names and callers import the side room."""
    wanted = [item.strip() for item in names if str(item).strip()]
    if not wanted:
        raise AG2CError("flatten-door requires --name")
    old_rel = _posix(old)
    side_rel = _posix(side)
    old_path = root / old_rel
    if not old_path.is_file():
        raise AG2CError(f"flatten-door missing old file: {old_rel}")
    files = _parse_repo_py(root)
    tree = files.get(old_rel)
    if tree is None:
        try:
            tree = ast.parse(old_path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeError) as exc:
            raise AG2CError(f"flatten-door cannot parse {old_rel}: {exc}") from exc
    still = [name for name in wanted if name in _reexports(tree)]
    if still:
        return {
            "schema": FLATTEN_DOOR_SCHEMA,
            "old": old_rel,
            "side": side_rel,
            "names": wanted,
            "cut": False,
            "reason": "老大门还在转口 " + ", ".join(still) + "，门牌没改。",
        }
    side_stem = Path(side_rel).stem
    old_stem = Path(old_rel).stem
    wanted_set = set(wanted)
    wrong: list[str] = []
    for rel, other in files.items():
        if rel in {old_rel, side_rel}:
            continue
        for node in ast.walk(other):
            if not isinstance(node, ast.ImportFrom):
                continue
            imported = {(alias.asname or alias.name) for alias in node.names}
            hit = imported & wanted_set
            if not hit:
                continue
            if _module_matches_stem(node.module, side_stem):
                continue
            if _module_matches_stem(node.module, old_stem):
                wrong.append(f"{rel} 仍从老大门拿 {', '.join(sorted(hit))}")
    if wrong:
        return {
            "schema": FLATTEN_DOOR_SCHEMA,
            "old": old_rel,
            "side": side_rel,
            "names": wanted,
            "cut": False,
            "reason": "门牌没改：" + "；".join(wrong),
        }
    return {
        "schema": FLATTEN_DOOR_SCHEMA,
        "old": old_rel,
        "side": side_rel,
        "names": wanted,
        "cut": True,
        "reason": "老大门不再转口，用货的人直接去侧屋。门牌改掉了。",
    }
