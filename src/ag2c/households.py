"""Directory jurisdictions and explicit, versioned census evidence."""
from __future__ import annotations

import hashlib
import json
import os
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import AG2CError, ConfigurationError, WidenError
from .index import _discover_files, _git, primary_owners, scope_matches
from .model import Card, Manifest, Policy, Scope


def _notify_gate(manifest: Manifest, problems: list[str]) -> None:
    """Best-effort notification; never breaks the gate itself."""
    try:
        from .notify import KIND_GATE_BLOCK, notify
        notify(manifest.project_id, KIND_GATE_BLOCK, "户籍门禁拦截", "\n".join(problems[:5]))
    except Exception:
        pass
from .util import digest_file, digest_json, path_matches


CODE_SUFFIXES = frozenset({".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".css", ".scss", ".sass", ".less", ".html", ".vue", ".svelte", ".rs", ".go", ".c", ".h", ".cpp", ".cs", ".java", ".kt", ".sh", ".ps1", ".bat", ".cmd", ".sql"})
CENSUS_SCHEMA = "ag2c.census.v1"
LIFECYCLES = frozenset({"current", "legacy", "retired"})
GRAINS = frozenset({"subtree", "directory", "module", "file"})
MEANINGS = frozenset({"none", "named"})
CONTRACTS = frozenset({"none", "partial", "machine"})
DECIDERS = frozenset({"none", "machine", "confirm"})
SPANS = frozenset({"none", "folder", "file"})
SPAN_LABELS = {"none": "未打标", "folder": "整夹一张", "file": "一文件一张"}
SPAN_ALIASES = {
    "none": "none",
    "未打标": "none",
    "folder": "folder",
    "整夹一张": "folder",
    "file": "file",
    "一文件一张": "file",
}
JURISDICTION_FIELDS = frozenset({"capability", "implementation", "status", "entrypoints", "grain", "meaning", "contract", "decider", "span"})
RECORD_BLOCK_ISSUES = frozenset(
    {
        "opaque-claimed",
        "undecomposed-directory",
        "child-unclaimed",
        "child-not-proper-subset",
        "grain-overflow",
        "span-unlabeled",
        "span-file-gap",
        "exploring-expired",
    }
)
GRAIN_RANK = {"subtree": 0, "directory": 1, "module": 2, "file": 3}
MEANING_RANK = {"none": 0, "named": 1}
CONTRACT_RANK = {"none": 0, "partial": 1, "machine": 2}
DECIDER_RANK = {"none": 0, "machine": 1, "confirm": 2}
STRATEGY_RANKS = {
    "grain": GRAIN_RANK,
    "meaning": MEANING_RANK,
    "contract": CONTRACT_RANK,
    "decider": DECIDER_RANK,
}
RENEWAL_SCHEMA = "ag2c.household-renewal.v1"
RENEWAL_FILENAME = "household-renewals.json"
DEFAULT_SUNSET_DAYS = 30


def coerce_jurisdiction(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ConfigurationError("jurisdiction must be an object")
    unknown = set(value) - JURISDICTION_FIELDS
    if unknown:
        raise ConfigurationError("unknown jurisdiction fields: " + ", ".join(sorted(unknown)))
    entrypoints = value.get("entrypoints", [])
    if entrypoints is None:
        entrypoints = []
    return {
        "capability": value.get("capability"),
        "implementation": value.get("implementation"),
        "status": value.get("status"),
        "entrypoints": list(entrypoints),
        "grain": str(value.get("grain") or "subtree"),
        "meaning": str(value.get("meaning") or "none"),
        "contract": str(value.get("contract") or "none"),
        "decider": str(value.get("decider") or "none"),
        "span": normalize_span(value.get("span")),
    }


def normalize_span(value: Any) -> str:
    text = str(value or "none").strip()
    span = SPAN_ALIASES.get(text, "")
    if span not in SPANS:
        raise ConfigurationError(f"coverage tag must be 未打标, 整夹一张, or 一文件一张: {value}")
    return span


def file_card_summary(policy: Policy, path: str) -> str:
    for card in policy.cards:
        if card.card_type != "knowledge" or card.jurisdiction is not None:
            continue
        includes = [pattern for scope in card.scopes for pattern in scope.includes]
        if includes == [path]:
            return card.summary
    return ""


def design_summary_for_file(policy: Policy, household: dict[str, Any] | None, path: str) -> str:
    declaration = coerce_jurisdiction((household or {}).get("jurisdiction")) or {}
    span = str(declaration.get("span") or "none")
    if span == "folder":
        return str((household or {}).get("summary") or "")
    if span == "file":
        return file_card_summary(policy, path)
    return ""


def assert_monotonic(old: dict[str, Any], new: dict[str, Any]) -> None:
    changed = False
    for field, ranks in STRATEGY_RANKS.items():
        previous = str(old.get(field) or "")
        current = str(new.get(field) or "")
        if previous not in ranks or current not in ranks:
            raise WidenError(f"unknown {field} value: {previous} -> {current}")
        if ranks[current] < ranks[previous]:
            raise WidenError(f"cannot loosen {field} from {previous} to {current}")
        if ranks[current] > ranks[previous]:
            changed = True
    if not changed:
        raise AG2CError("tighten requires at least one stricter grain, meaning, contract, or decider")


def renewal_path(manifest: Manifest) -> Path:
    return manifest.state_dir / RENEWAL_FILENAME


def households_covering_path(report: dict[str, Any], target: str, path: str) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for item in report.get("households") or []:
        if not item.get("jurisdiction"):
            continue
        for scope in item.get("scopes") or []:
            if str(scope.get("target_id") or scope.get("target") or "") != target:
                continue
            includes = list(scope.get("includes") or scope.get("include") or [])
            excludes = list(scope.get("excludes") or scope.get("exclude") or [])
            if any(path_matches(path, pattern) for pattern in includes) and not any(path_matches(path, pattern) for pattern in excludes):
                matches.append(item)
                break
    return matches


def household_guidance(report: dict[str, Any]) -> list[dict[str, Any]]:
    payload = []
    for item in report.get("households") or []:
        declaration = item.get("jurisdiction") or {}
        if not declaration:
            continue
        identity = str(item.get("identity") or "exploring")
        payload.append(
            {
                "id": item["id"],
                "title": item.get("title"),
                "identity": identity,
                "explained": identity == "named",
                "grain": declaration.get("grain"),
                "meaning": declaration.get("meaning"),
                "contract": declaration.get("contract"),
                "decider": declaration.get("decider"),
                "span": declaration.get("span"),
                "span_label": SPAN_LABELS.get(str(declaration.get("span") or "none"), "未打标"),
                "status": declaration.get("status"),
                "capability": declaration.get("capability"),
                "implementation": declaration.get("implementation"),
                "leaf": bool(item.get("leaf")),
                "child_directories": list(item.get("child_directories") or []),
                "named_directories": list(item.get("named_directories") or []),
                "unclaimed_directories": list(item.get("unclaimed_directories") or []),
                "files": list(item.get("files") or []) if item.get("leaf") else [],
            }
        )
    return payload


def scan_references(root: Path, needles: list[str], skip_paths: set[str]) -> list[str]:
    hits: list[str] = []
    useful = [needle.replace("\\", "/").strip("/") for needle in needles if needle and needle not in {".", "/"}]
    if not useful:
        return hits
    skip = {path.replace("\\", "/") for path in skip_paths}
    skip_dirs = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in skip_dirs and not name.startswith(".")]
        for name in filenames:
            relative = Path(dirpath, name).relative_to(root).as_posix()
            if relative in skip:
                continue
            try:
                text = Path(dirpath, name).read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for needle in useful:
                if needle in text:
                    hits.append(f"{relative}:{needle}")
                    break
    return hits


def load_renewals(manifest: Manifest) -> dict[str, Any]:
    path = renewal_path(manifest)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict) or raw.get("schema") != RENEWAL_SCHEMA or not isinstance(raw.get("cards"), dict):
        return {}
    return {str(key): value for key, value in raw["cards"].items() if isinstance(value, dict)}


def acknowledge_exploring(manifest: Manifest, policy: Policy, *, actor: str, reason: str, sunset_days: int = DEFAULT_SUNSET_DAYS) -> int:
    """Record the current child set of exploring households without naming them.

    Each renewal carries an expires_at sunset date; after it passes the
    household is treated as unrenewed and blocks census recording.
    """
    report = census_report(manifest, policy)
    cards = load_renewals(manifest)
    added = 0
    now = datetime.now(timezone.utc)
    timestamp = now.isoformat()
    from datetime import timedelta
    expires = (now + timedelta(days=sunset_days)).isoformat()
    for item in report.get("households") or []:
        if item.get("identity") != "exploring":
            continue
        card_id = str(item["id"])
        if card_id in cards:
            continue
        cards[card_id] = {
            "renewed_at": timestamp,
            "expires_at": expires,
            "actor": actor,
            "reason": reason,
            "child_directories": list(item.get("child_directories") or []),
        }
        added += 1
    if not added:
        return 0
    path = renewal_path(manifest)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps({"schema": RENEWAL_SCHEMA, "cards": cards}, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return added


def expired_renewals(manifest: Manifest) -> list[str]:
    """Card ids whose exploring renewal has passed its sunset date."""
    now = datetime.now(timezone.utc)
    expired: list[str] = []
    for card_id, record in load_renewals(manifest).items():
        expires = str(record.get("expires_at") or "")
        if not expires:
            continue  # legacy record without sunset — treat as still valid
        try:
            if datetime.fromisoformat(expires) < now:
                expired.append(card_id)
        except ValueError:
            continue
    return expired


def directory_scope(pattern: str) -> str:
    if pattern == "**":
        return "."
    if not pattern.endswith("/**"):
        raise ConfigurationError(f"jurisdiction scope must be a directory/**, not a document: {pattern}")
    directory = pattern[:-3]
    if not directory or any(part in {"", ".", ".."} for part in directory.split("/")) or any(char in directory for char in "*?[]:\\"):
        raise ConfigurationError(f"invalid jurisdiction directory: {pattern}")
    return directory


def file_scope(pattern: str) -> str:
    """文件粒度户口（grain=file，t59）的 scope：精确文件路径，不是 glob、不是目录。

    存在的理由：删除门只认户口，而目录户口覆盖不了"删单个文件"——根文件与
    活跃房间内的单文件需要一个能精确命中、能退役、能确认的最小户口。
    """
    if pattern == "**" or pattern.endswith("/**") or any(char in pattern for char in "*?["):
        raise ConfigurationError(f"file-grain jurisdiction scope must be an exact file path, not a glob: {pattern}")
    normalized = pattern.replace("\\", "/").strip("/")
    if not normalized or any(part in {"", ".", ".."} for part in normalized.split("/")) or ":" in normalized:
        raise ConfigurationError(f"invalid file-grain jurisdiction path: {pattern}")
    return normalized


def validate_declarations(cards: list[Card], relations: list) -> None:
    by_id = {card.card_id: card for card in cards}
    for card in cards:
        declaration = card.jurisdiction
        if declaration is None:
            continue
        if card.card_type != "knowledge" or not isinstance(declaration, dict):
            raise ConfigurationError(f"jurisdiction requires a knowledge card object: {card.card_id}")
        declaration.update(coerce_jurisdiction(declaration) or {})
        if set(declaration) - JURISDICTION_FIELDS:
            raise ConfigurationError(f"unknown jurisdiction fields: {card.card_id}")
        for field in ("capability", "implementation"):
            if not isinstance(declaration.get(field), str) or not declaration[field].strip():
                raise ConfigurationError(f"jurisdiction requires {field}: {card.card_id}")
        if declaration.get("status") not in LIFECYCLES or not card.scopes:
            raise ConfigurationError(f"jurisdiction requires lifecycle and directory scopes: {card.card_id}")
        if declaration.get("grain") not in GRAINS:
            raise ConfigurationError(f"jurisdiction grain must be subtree, directory, module, or file: {card.card_id}")
        if declaration.get("meaning") not in MEANINGS:
            raise ConfigurationError(f"jurisdiction meaning must be none or named: {card.card_id}")
        if declaration.get("contract") not in CONTRACTS:
            raise ConfigurationError(f"jurisdiction contract must be none, partial, or machine: {card.card_id}")
        if declaration.get("decider") not in DECIDERS:
            raise ConfigurationError(f"jurisdiction decider must be none, machine, or confirm: {card.card_id}")
        if declaration.get("span") not in SPANS:
            raise ConfigurationError(f"jurisdiction span must be none, folder, or file: {card.card_id}")
        is_file_grain = declaration.get("grain") == "file"
        for scope in card.scopes:
            for pattern in (*scope.includes, *scope.excludes):
                if is_file_grain:
                    file_scope(pattern)
                else:
                    directory_scope(pattern)
        entries = declaration.get("entrypoints", [])
        if not isinstance(entries, list) or any(not isinstance(item, str) or not item or item.startswith("/") or ":" in item or "\\" in item or ".." in item.split("/") for item in entries):
            raise ConfigurationError(f"invalid jurisdiction entrypoints: {card.card_id}")
    successors: dict[str, str] = {}
    for relation in relations:
        if relation.relation_type != "replaced_by":
            continue
        source, target = by_id[relation.source], by_id[relation.target]
        if not source.jurisdiction or not target.jurisdiction or source.card_id in successors:
            raise ConfigurationError("replacement requires two jurisdictions and one successor")
        if source.jurisdiction["status"] == "current" or source.jurisdiction["capability"] != target.jurisdiction["capability"]:
            raise ConfigurationError("replacement must connect an old implementation to the same capability")
        successors[source.card_id] = target.card_id
    for card_id in successors:
        visited: set[str] = set()
        current = card_id
        while current in successors:
            if current in visited:
                raise ConfigurationError(f"replacement cycle: {card_id}")
            visited.add(current)
            current = successors[current]


def _posix_dir(path: str) -> str:
    text = str(path).replace("\\", "/").strip().strip("/")
    return text or "."


def _include_roots(card: Card) -> list[tuple[str, str]]:
    # 文件粒度户口（grain=file，t59）的 include 是精确文件路径，不是 dir/**：
    # 此时"根"就是文件本身，重叠检测按精确路径比较即可。
    roots: list[tuple[str, str]] = []
    for scope in card.scopes:
        for pattern in scope.includes:
            if pattern.endswith("/**") or pattern == "**":
                roots.append((scope.target_id, directory_scope(pattern)))
            else:
                roots.append((scope.target_id, pattern))
    return roots


def _exclude_roots(card: Card) -> set[tuple[str, str]]:
    # 与 _include_roots 同口径（t59）：文件粒度户口的 exclude 是精确文件
    # 路径，原样作为根；目录户口的 exclude 仍是 dir/**。
    found: set[tuple[str, str]] = set()
    for scope in card.scopes:
        for pattern in scope.excludes:
            if pattern.endswith("/**") or pattern == "**":
                found.add((scope.target_id, directory_scope(pattern)))
            else:
                found.add((scope.target_id, pattern))
    return found


def _file_directory(path: str) -> str:
    parent = _posix_dir(str(Path(path).parent))
    return "." if parent in {".", ""} else parent


def _direct_child_of(directory: str, root: str) -> str | None:
    directory = _posix_dir(directory)
    root = _posix_dir(root)
    if directory == root:
        return None
    if root == ".":
        child = directory.split("/", 1)[0]
        return child if child not in {"", "."} else None
    prefix = root + "/"
    if not directory.startswith(prefix):
        return None
    return root + "/" + directory[len(prefix) :].split("/", 1)[0]


def _is_proper_subdir(child: str, parent: str) -> bool:
    child = _posix_dir(child)
    parent = _posix_dir(parent)
    if parent == ".":
        return child not in {"", "."}
    return child.startswith(parent + "/")


def _direct_named_dirs(parent: Card, child: Card) -> set[tuple[str, str]]:
    named: set[tuple[str, str]] = set()
    for child_target, child_dir in _include_roots(child):
        for parent_target, parent_dir in _include_roots(parent):
            if child_target != parent_target or child_dir == parent_dir or not _is_proper_subdir(child_dir, parent_dir):
                continue
            direct = _direct_child_of(child_dir, parent_dir)
            if direct == child_dir:
                named.add((child_target, child_dir))
    return named


def _code_direct_children(card: Card, matched: list[dict[str, Any]]) -> list[tuple[str, str]]:
    children: set[tuple[str, str]] = set()
    for artifact in matched:
        if not artifact.get("code"):
            continue
        directory = _file_directory(str(artifact["path"]))
        for target, root in _include_roots(card):
            if artifact["target"] != target:
                continue
            child = _direct_child_of(directory, root)
            if child:
                children.add((target, child))
    return sorted(children)


def census_path(manifest: Manifest) -> Path:
    return manifest.state_dir / "census.json"


def _history(manifest: Manifest) -> dict:
    path = census_path(manifest)
    if not path.is_file():
        from .ledger import inspect_ledger

        errors, events = inspect_ledger(manifest.ledger_path)
        if errors:
            raise AG2CError("census ledger is invalid: " + "; ".join(errors))
        if any(event.get("event_type") == "census-reviewed" for event in events):
            raise AG2CError("census history is missing while the append-only ledger contains reviewed records")
        return {"schema": CENSUS_SCHEMA, "records": []}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AG2CError(f"census history is unreadable: {exc}") from exc
    if not isinstance(state, dict) or state.get("schema") != CENSUS_SCHEMA or not isinstance(state.get("records"), list):
        raise AG2CError("census history has an invalid schema")
    for record in state["records"]:
        if not isinstance(record, dict) or not all(key in record for key in ("id", "card_id", "digest", "surveyed_at")) or record["digest"] != digest_json({key: value for key, value in record.items() if key != "digest"}):
            raise AG2CError("census history record digest is invalid")
    from .ledger import inspect_ledger

    errors, events = inspect_ledger(manifest.ledger_path)
    if errors:
        raise AG2CError("census ledger is invalid: " + "; ".join(errors))
    recorded = {record["id"]: record for event in events if event.get("event_type") == "census-reviewed" for record in event.get("payload", {}).get("records", [])}
    previous: dict[str, str] = {}
    for record in state["records"]:
        if recorded.get(record["id"]) != record or record.get("previous") != previous.get(record["card_id"]):
            raise AG2CError("census history does not match its append-only ledger")
        previous[record["card_id"]] = record["id"]
    if set(recorded) != {record["id"] for record in state["records"]}:
        raise AG2CError("census history is incomplete compared with its ledger")
    return state


def _version(root: Path) -> str:
    version_file = root / "VERSION"
    if version_file.is_file():
        return version_file.read_text(encoding="utf-8").strip()[:160]
    try:
        import tomllib

        path = root / "pyproject.toml"
        if path.is_file():
            return str(tomllib.loads(path.read_text(encoding="utf-8")).get("project", {}).get("version", ""))
        path = root / "package.json"
        if path.is_file():
            return str(json.loads(path.read_text(encoding="utf-8")).get("version", ""))
    except (OSError, ValueError, TypeError):
        return ""
    return ""


def _matches(card: Card, target: str, path: str) -> bool:
    return any(scope_matches(scope, target, path) for scope in card.scopes)


def _matches_include(card: Card, target: str, path: str) -> bool:
    return any(
        scope.target_id == target and any(path_matches(path, pattern) for pattern in scope.includes)
        for scope in card.scopes
    )


def _latest_change_in_scope(latest: dict[str, dict[str, str]], scope: Scope) -> dict[str, str] | None:
    """Most recent bulk-log entry inside a scope, or None when the window misses it."""
    for path, info in latest.items():
        if any(path_matches(path, pattern) for pattern in scope.includes) and not any(
            path_matches(path, pattern) for pattern in scope.excludes
        ):
            return info
    return None


def _last_source_change(
    manifest: Manifest,
    card: Card,
    latest_by_root: dict[str, dict[str, dict[str, str]]] | None = None,
) -> list[dict]:
    changes = []
    for scope in card.scopes:
        root = manifest.target_root(scope.target_id)
        # Bulk path: one cached `git log --name-only` per repo head replaces a
        # per-scope `git log -1` subprocess for every card in the report.
        info = _latest_change_in_scope(latest_by_root.get(str(root), {}), scope) if latest_by_root is not None else None
        if info is not None:
            changes.append({"target": scope.target_id, **info})
            continue
        # Fallback: the bulk window (--max-count) may miss ancient files, and
        # scopes matching nothing must come back empty either way.
        patterns = [f":(glob){pattern}" for pattern in scope.includes]
        patterns.extend(f":(glob,exclude){pattern}" for pattern in scope.excludes)
        output = str(_git(root, "log", "-1", "--format=%H%n%cI%n%s", "--", *patterns) or "").splitlines()
        if len(output) >= 3:
            changes.append({"target": scope.target_id, "commit": output[0], "changed_at": output[1], "summary": output[2]})
    return changes


_FILE_COMMIT_CACHE: dict[tuple[str, str], dict[str, dict[str, str]]] = {}
_CENSUS_CACHE: dict[tuple[Any, ...], dict[str, Any]] = {}


def _dirty_file_stats(root: Path, porcelain: str) -> list[Any]:
    """Content proxy for dirty paths.

    Porcelain names *which* files changed but says nothing about their
    content, so editing an already-dirty file must still move the census
    cache key — otherwise a long-lived process (MCP server, tray) records or
    serves a stale report. mtime_ns+size is the same proxy pyc invalidation
    uses; we never hash file content here. Untracked directories need their
    files expanded because editing a file inside does not move the directory
    mtime. Anything unparseable/unstattable still lands in the key as a
    marker, and a catastrophic failure bubbles up to the caller's ``None``
    fallback (no cache is always correct).
    """
    stats: list[Any] = []
    for line in porcelain.splitlines():
        if len(line) < 4:
            continue
        rel = line[3:].split(" -> ")[-1].strip().strip('"')
        if not rel:
            continue
        candidate = root / rel
        try:
            if candidate.is_dir():
                for child in sorted(candidate.rglob("*")):
                    if child.is_file():
                        child_stat = child.stat()
                        stats.append((child.relative_to(root).as_posix(), int(child_stat.st_mtime_ns), int(child_stat.st_size)))
            else:
                file_stat = candidate.stat()
                stats.append((rel, int(file_stat.st_mtime_ns), int(file_stat.st_size)))
        except OSError:
            stats.append((rel, "unstattable"))
    return stats


def _census_cache_key(manifest: Manifest, policy: Policy) -> tuple[Any, ...] | None:
    try:
        policy_path = Path(policy.path)
        policy_stat = policy_path.stat()
        parts: list[Any] = [str(policy_path), int(policy_stat.st_mtime_ns), int(policy_stat.st_size)]
        # Census and renewal state feed the report; without them in the key a
        # record written by this process stays invisible to later reports.
        for state_file in (census_path(manifest), renewal_path(manifest)):
            if state_file.is_file():
                state_stat = state_file.stat()
                parts.extend([str(state_file), int(state_stat.st_mtime_ns), int(state_stat.st_size)])
            else:
                parts.append((str(state_file), "absent"))
        for target in manifest.targets:
            root = manifest.target_root(target.target_id)
            head = str(_git(root, "rev-parse", "HEAD") or "")
            dirty = str(_git(root, "status", "--porcelain") or "")
            # 检出根路径必须在 key 里：canonical 与任务 worktree 共享 policy/state
            # 文件，HEAD 与 dirty 状态相同的瞬间（如任务刚开工）会碰撞；内容相同
            # 时无害，但「碰撞即同内容」是运气不是设计。
            parts.extend([str(root), target.target_id, head, hashlib.sha256(dirty.encode("utf-8", "replace")).hexdigest()])
            parts.extend(_dirty_file_stats(root, dirty))
        return tuple(parts)
    except Exception:
        return None


def file_latest_commits(root: Path, head: str = "") -> dict[str, dict[str, str]]:
    key = (str(root), head)
    cached = _FILE_COMMIT_CACHE.get(key)
    if cached is not None:
        return cached
    latest: dict[str, dict[str, str]] = {}
    raw = str(_git(root, "log", "--pretty=format:%H%x09%cI%x09%s", "--name-only", "--no-renames", "--max-count=2000") or "")
    commit = changed_at = summary = ""
    for line in raw.splitlines():
        if not line:
            commit = ""
            continue
        if "\t" in line:
            parts = line.split("\t", 2)
            if len(parts) == 3 and len(parts[0]) >= 7 and all(ch in "0123456789abcdef" for ch in parts[0][:7].lower()):
                commit, changed_at, summary = parts
                continue
        path = line.replace("\\", "/").lstrip("./")
        if commit and path and path not in latest:
            latest[path] = {"commit": commit, "changed_at": changed_at, "summary": summary}
    _FILE_COMMIT_CACHE[key] = latest
    return latest


def census_report(manifest: Manifest, policy: Policy) -> dict[str, Any]:
    cache_key = _census_cache_key(manifest, policy)
    if cache_key is not None:
        cached = _CENSUS_CACHE.get(cache_key)
        if cached is not None:
            return cached
    artifacts: list[dict] = []
    revisions: dict[str, dict] = {}
    signals: list[dict] = []
    for target in manifest.targets:
        root = manifest.target_root(target.target_id)
        paths, states, head, dirty = _discover_files(root, target)
        revisions[target.target_id] = {"commit": head, "version": _version(root), "dirty_paths": dirty}
        for relative in paths:
            path = root / relative
            if not path.is_file():
                continue
            safe = path.resolve().is_relative_to(root.resolve())
            artifact = {"target": target.target_id, "path": relative, "digest": digest_file(path) if safe else "outside-target", "code": path.suffix.lower() in CODE_SUFFIXES, "state": states.get(relative, "tracked")}
            artifacts.append(artifact)
            if safe and path.name in {"package.json", "main.tsx", "main.jsx", "vite.config.ts", "next.config.js", "next.config.ts", "next.config.mjs"}:
                signals.append({"target": target.target_id, "path": relative, "kind": "frontend-entry-candidate"})
            if safe and artifact["code"] and path.suffix.lower() in {".ts", ".tsx", ".js", ".jsx"}:
                source = path.read_text(encoding="utf-8", errors="replace")
                for engine in ("@xyflow/react", "@flowgram.ai/free-layout-editor", "@flowgram.ai/fixed-layout-editor"):
                    if engine in source:
                        signals.append({"target": target.target_id, "path": relative, "kind": "canvas-engine-reference", "engine": engine})
    jurisdictions = [card for card in policy.cards if card.jurisdiction is not None]
    records = _history(manifest)["records"]
    latest = {record["card_id"]: record for record in records if isinstance(record, dict) and "card_id" in record}
    expired_set = set(expired_renewals(manifest))
    gaps: list[dict] = []
    directories: dict[tuple[str, str], dict] = {}
    for artifact in artifacts:
        if not artifact["code"]:
            continue
        owners = [card.card_id for card in jurisdictions if _matches(card, artifact["target"], artifact["path"])]
        directory = str(Path(artifact["path"]).parent).replace("\\", "/")
        group = directories.setdefault((artifact["target"], directory), {"target": artifact["target"], "path": directory, "files": [], "owners": set(), "unowned": 0, "ambiguous": 0})
        group["files"].append(artifact["path"])
        group["owners"].update(owners)
        if len(owners) != 1:
            kind = "unowned" if not owners else "ambiguous"
            group[kind] += 1
            gaps.append({"code": f"code-{kind}", "target": artifact["target"], "path": artifact["path"], "cards": owners})
    reports = []
    for card in [item for item in policy.cards if item.card_type == "floor" or item.jurisdiction is not None]:
        matched = [item for item in artifacts if _matches(card, item["target"], item["path"])]
        floors = [relation.target for relation in policy.relations if relation.source == card.card_id and relation.relation_type == "explains"]
        replacements = [relation.target for relation in policy.relations if relation.source == card.card_id and relation.relation_type == "replaced_by"]
        # Exclude metadata fields that don't affect jurisdiction/behavior,
        # so adding new optional fields doesn't invalidate all census records.
        card_dict = {k: v for k, v in asdict(card).items() if k not in ("budget_lines", "budget_chars", "budget_ast_nodes", "optional", "maturity")}
        # Same exclusion for checker metadata: budget_seconds is a cost-governance
        # knob, not jurisdiction/behavior — and old code (without the field) must
        # compute the same digest as new code across a merge boundary.
        checker_dicts = [{k: v for k, v in asdict(policy.checker(checker)).items() if k != "budget_seconds"} for checker in card.checkers]
        declaration_digest = digest_json({"card": card_dict, "floors": floors, "replacements": replacements, "checkers": checker_dicts})
        scope_digest = digest_json([{key: item[key] for key in ("target", "path", "digest")} for item in matched])
        previous = latest.get(card.card_id)
        freshness = "never" if previous is None else "current" if previous.get("scope_digest") == scope_digest and previous.get("declaration_digest") == declaration_digest else "stale"
        issues: list[dict] = []
        declaration = coerce_jurisdiction(card.jurisdiction) or {}
        included = [item for item in artifacts if declaration and _matches_include(card, item["target"], item["path"])]
        child_dirs = _code_direct_children(card, included) if declaration else []
        named_dirs: set[tuple[str, str]] = set()
        same_glob = False
        if declaration:
            for other in jurisdictions:
                if other.card_id == card.card_id:
                    continue
                named_dirs.update(_direct_named_dirs(card, other))
                if set(_include_roots(other)) & set(_include_roots(card)):
                    same_glob = True
        unclaimed = [item for item in child_dirs if item not in named_dirs]
        identity = "floor"
        if declaration:
            if not floors:
                issues.append({"code": "floor-link-missing"})
            for item in matched:
                actual = {owner.card_id for owner in primary_owners(policy, item["target"], item["path"])}
                if not actual or not actual.issubset(set(floors)):
                    issues.append({"code": "floor-scope-mismatch", "path": item["path"]})
                    break
            if declaration["status"] != "current" and not replacements:
                issues.append({"code": "replacement-missing"})
            if declaration["status"] == "retired" and any(item["code"] for item in matched):
                issues.append({"code": "retired-code-remains"})
            if declaration.get("contract") == "machine" and not any(
                policy.checker(checker_id).implementation == declaration["implementation"] for checker_id in card.checkers
            ):
                issues.append({"code": "implementation-check-missing"})
            for checker_id in card.checkers:
                checker = policy.checker(checker_id)
                # A checker with no implementation claim is a room tool (e.g. a
                # unittest suite), not an implementation proof: it never mismatches.
                # A bare git-diff checker is toothless either way.
                if checker.command[:3] == ("git", "diff", "--check"):
                    issues.append({"code": "implementation-check-mismatch", "checker": checker_id})
                elif checker.implementation and checker.implementation != declaration["implementation"]:
                    issues.append({"code": "implementation-check-mismatch", "checker": checker_id})
                if any(
                    other.implementation
                    and other.implementation != checker.implementation
                    and (other.command, other.cwd, other.target_id) == (checker.command, checker.cwd, checker.target_id)
                    for other in policy.checkers
                ):
                    issues.append({"code": "implementation-check-reused", "checker": checker_id})
            for entry in declaration.get("entrypoints", []):
                if not any(item["path"] == entry for item in matched):
                    issues.append({"code": "entrypoint-missing", "path": entry})
            if declaration.get("contract") == "partial" and not declaration.get("entrypoints"):
                issues.append({"code": "entrypoint-missing"})
            if declaration.get("grain") == "module" and child_dirs:
                issues.append({"code": "grain-overflow", "paths": [f"{target}:{path}" for target, path in child_dirs]})
            if same_glob and declaration.get("meaning") == "named":
                issues.append({"code": "child-not-proper-subset"})
            if declaration.get("meaning") == "named" and unclaimed:
                issues.append({"code": "child-unclaimed", "paths": [f"{target}:{path}" for target, path in unclaimed]})
                issues.append({"code": "undecomposed-directory"})
                issues.append({"code": "opaque-claimed"})
            span = str(declaration.get("span") or "none")
            if declaration.get("meaning") == "named" and span == "none":
                issues.append({"code": "span-unlabeled"})
            if declaration.get("meaning") == "named" and span == "file":
                missing = [
                    item["path"]
                    for item in matched
                    if item.get("code") and not file_card_summary(policy, str(item["path"]))
                ]
                if missing:
                    issues.append({"code": "span-file-gap", "paths": missing[:40]})
            issue_codes = {issue["code"] for issue in issues}
            if declaration.get("status") in {"legacy", "retired"} and any(item["code"] for item in matched):
                identity = "leftover"
            elif "opaque-claimed" in issue_codes or "grain-overflow" in issue_codes or "span-file-gap" in issue_codes:
                identity = "opaque"
            elif declaration.get("meaning") == "named":
                identity = "named"
            else:
                identity = "exploring"
                # Sunset clause: expired exploring renewals block census recording.
                if card.card_id in expired_set:
                    issues.append({"code": "exploring-expired"})
                    identity = "opaque"
        if any(item["digest"] == "outside-target" for item in matched):
            issues.append({"code": "source-outside-target"})
        scoped_signals = [item for item in signals if _matches(card, item["target"], item["path"])]
        engines = sorted({item["engine"] for item in scoped_signals if "engine" in item})
        reports.append(
            {
                "id": card.card_id,
                "kind": card.card_type,
                "title": card.title,
                "summary": card.summary,
                "jurisdiction": declaration,
                "identity": identity,
                "leaf": not child_dirs,
                "child_directories": [f"{target}:{path}" for target, path in child_dirs],
                "named_directories": [f"{target}:{path}" for target, path in sorted(named_dirs)],
                "unclaimed_directories": [f"{target}:{path}" for target, path in unclaimed],
                "scopes": [asdict(scope) for scope in card.scopes],
                "floors": floors,
                "replaced_by": replacements,
                "checkers": list(card.checkers),
                "issues": issues,
                "freshness": freshness,
                "last_census": previous,
                "history": [record for record in records if record.get("card_id") == card.card_id][-12:],
                "scope_digest": scope_digest,
                "declaration_digest": declaration_digest,
                "file_count": len(matched),
                "code_count": sum(item["code"] for item in matched),
                "files": [f'{item["target"]}:{item["path"]}' for item in matched],
                "signals": scoped_signals,
                "canvas_engines": engines,
            }
        )
    capabilities: dict[str, list[dict]] = defaultdict(list)
    for report in reports:
        if report["jurisdiction"]:
            capabilities[report["jurisdiction"]["capability"]].append(report)
    implementations = []
    for capability, members in sorted(capabilities.items()):
        current = sorted({item["jurisdiction"]["implementation"] for item in members if item["jurisdiction"]["status"] == "current"})
        implementations.append({"capability": capability, "current": current, "cards": [item["id"] for item in members], "competing": len(current) > 1})
        if len(current) > 1:
            for item in members:
                if item["jurisdiction"]["status"] == "current":
                    item["issues"].append({"code": "competing-current-implementations", "capability": capability})
    latest_by_root: dict[str, dict[str, dict[str, str]]] = {}
    for target in manifest.targets:
        target_root = manifest.target_root(target.target_id)
        target_head = str(_git(target_root, "rev-parse", "HEAD") or "").strip()
        if target_head:
            latest_by_root[str(target_root)] = file_latest_commits(target_root, target_head)
    for item in reports:
        item["checker_details"] = [asdict(policy.checker(checker_id)) for checker_id in item["checkers"]]
        item["last_source_change"] = _last_source_change(manifest, policy.card(item["id"]), latest_by_root)
        if item["last_census"]:
            timestamp = datetime.fromisoformat(item["last_census"]["surveyed_at"])
            item["census_age_days"] = max(0, (datetime.now(timezone.utc) - timestamp).days)
    identities = Counter(item.get("identity") or "floor" for item in reports if item.get("jurisdiction"))
    # 证据锚（存量迁移期）：带 provides 的知识卡逐张锚定 references 的真实符号，
    # 锚错进 anchor_warnings——普查报告可见，run_checks 再接入 warning-history。
    from .anchors import provides_anchor_warnings

    anchor_warnings = provides_anchor_warnings(manifest, policy)
    report = {"schema": CENSUS_SCHEMA, "observed_at": datetime.now(timezone.utc).isoformat(), "required": policy.household_required, "project": manifest.project_id, "revisions": revisions, "households": reports, "gaps": gaps, "directories": [{**value, "owners": sorted(value["owners"])} for _, value in sorted(directories.items())], "implementations": implementations, "signals": signals, "anchor_warnings": anchor_warnings, "counts": {"jurisdictions": len(jurisdictions), "code_files": sum(item["code"] for item in artifacts), "unowned": sum(item["code"] == "code-unowned" for item in gaps), "ambiguous": sum(item["code"] == "code-ambiguous" for item in gaps), "exploring": identities.get("exploring", 0), "named": identities.get("named", 0), "opaque": identities.get("opaque", 0), "leftover": identities.get("leftover", 0), "freshness": dict(Counter(item["freshness"] for item in reports))}}
    if cache_key is not None:
        _CENSUS_CACHE[cache_key] = report
    return report


def required_households(report: dict, entry_slice: dict) -> list[dict]:
    paths = entry_slice.get("entries", {}).get("paths", [])
    if not paths:
        return [item for item in report["households"] if item["jurisdiction"]]
    qualified = {f'{item["target"]}:{item["path"]}' for item in paths}
    # A household is required when its files are touched or its card is a
    # DIRECT slice hit. Context cards (relation walk, marked direct=False)
    # carry knowledge only and owe no checker runs.
    direct_cards = {card["id"] for card in entry_slice.get("cards", []) if card.get("direct", True)}
    return [item for item in report["households"] if item["jurisdiction"] and (qualified.intersection(item["files"]) or item["id"] in direct_cards)]


def enforce_households(manifest: Manifest, policy: Policy, entry_slice: dict, checker_ids: set[str]) -> None:
    if not policy.household_required:
        return
    report = census_report(manifest, policy)
    entries = entry_slice.get("entries", {}).get("paths", [])
    selected_paths = {(item["target"], item["path"]) for item in entries}
    problems = [f'{item["code"]}:{item["target"]}:{item["path"]}' for item in report["gaps"] if not entries or (item["target"], item["path"]) in selected_paths]
    for target, path in selected_paths:
        if Path(path).suffix.lower() in CODE_SUFFIXES:
            owners = [card for card in policy.cards if card.jurisdiction and _matches(card, target, path)]
            if len(owners) != 1:
                problems.append(f"changed-code-without-unique-household:{target}:{path}")
    for item in required_households(report, entry_slice):
        # Optional floor cards are advisory: they don't block verify.
        try:
            card = policy.card(item["id"]) if item["id"] else None
        except StopIteration:
            card = None
        if card is not None and card.optional and card.card_type == "floor":
            continue
        problems.extend(f'{issue["code"]}:{item["id"]}' for issue in item["issues"])
        if item["freshness"] != "current":
            problems.append(f'census-{item["freshness"]}:{item["id"]}')
        missing = set(item["checkers"]) - checker_ids
        if missing:
            problems.append(f'implementation-check-not-selected:{item["id"]}:{",".join(sorted(missing))}')
    if problems:
        _notify_gate(manifest, problems)
        raise AG2CError("household gate blocked:\n- " + "\n- ".join(problems[:40]))
