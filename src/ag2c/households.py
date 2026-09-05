"""Directory jurisdictions and explicit, versioned census evidence."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import AG2CError, ConfigurationError
from .index import _discover_files, _git, _scope_matches, primary_owners
from .model import Card, Manifest, Policy
from .util import digest_file, digest_json


CODE_SUFFIXES = frozenset({".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".css", ".scss", ".sass", ".less", ".html", ".vue", ".svelte", ".rs", ".go", ".c", ".h", ".cpp", ".cs", ".java", ".kt", ".sh", ".ps1", ".bat", ".cmd", ".sql"})
CENSUS_SCHEMA = "ag2c.census.v1"
LIFECYCLES = frozenset({"current", "legacy", "retired"})


def directory_scope(pattern: str) -> str:
    if pattern == "**":
        return "."
    if not pattern.endswith("/**"):
        raise ConfigurationError(f"jurisdiction scope must be a directory/**, not a document: {pattern}")
    directory = pattern[:-3]
    if not directory or any(part in {"", ".", ".."} for part in directory.split("/")) or any(char in directory for char in "*?[]:\\"):
        raise ConfigurationError(f"invalid jurisdiction directory: {pattern}")
    return directory


def validate_declarations(cards: list[Card], relations: list) -> None:
    by_id = {card.card_id: card for card in cards}
    for card in cards:
        declaration = card.jurisdiction
        if declaration is None:
            continue
        if card.card_type != "knowledge" or not isinstance(declaration, dict):
            raise ConfigurationError(f"jurisdiction requires a knowledge card object: {card.card_id}")
        if set(declaration) - {"capability", "implementation", "status", "entrypoints"}:
            raise ConfigurationError(f"unknown jurisdiction fields: {card.card_id}")
        for field in ("capability", "implementation"):
            if not isinstance(declaration.get(field), str) or not declaration[field].strip():
                raise ConfigurationError(f"jurisdiction requires {field}: {card.card_id}")
        if declaration.get("status") not in LIFECYCLES or not card.scopes:
            raise ConfigurationError(f"jurisdiction requires lifecycle and directory scopes: {card.card_id}")
        for scope in card.scopes:
            for pattern in (*scope.includes, *scope.excludes):
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
    return any(_scope_matches(scope, target, path) for scope in card.scopes)


def _last_source_change(manifest: Manifest, card: Card) -> list[dict]:
    changes = []
    for scope in card.scopes:
        patterns = [f":(glob){pattern}" for pattern in scope.includes]
        patterns.extend(f":(glob,exclude){pattern}" for pattern in scope.excludes)
        output = str(_git(manifest.target_root(scope.target_id), "log", "-1", "--format=%H%n%cI%n%s", "--", *patterns) or "").splitlines()
        if len(output) >= 3:
            changes.append({"target": scope.target_id, "commit": output[0], "changed_at": output[1], "summary": output[2]})
    return changes


_FILE_COMMIT_CACHE: dict[tuple[str, str], dict[str, dict[str, str]]] = {}


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
        declaration_digest = digest_json({"card": asdict(card), "floors": floors, "replacements": replacements, "checkers": [asdict(policy.checker(checker)) for checker in card.checkers]})
        scope_digest = digest_json([{key: item[key] for key in ("target", "path", "digest")} for item in matched])
        previous = latest.get(card.card_id)
        freshness = "never" if previous is None else "current" if previous.get("scope_digest") == scope_digest and previous.get("declaration_digest") == declaration_digest else "stale"
        issues: list[dict] = []
        declaration = card.jurisdiction or {}
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
            if declaration["status"] != "retired" and not card.checkers:
                issues.append({"code": "implementation-check-missing"})
            for checker_id in card.checkers:
                checker = policy.checker(checker_id)
                if checker.implementation != declaration["implementation"] or checker.command[:3] == ("git", "diff", "--check"):
                    issues.append({"code": "implementation-check-mismatch", "checker": checker_id})
                if any(other.implementation and other.implementation != checker.implementation and (other.command, other.cwd, other.target_id) == (checker.command, checker.cwd, checker.target_id) for other in policy.checkers):
                    issues.append({"code": "implementation-check-reused", "checker": checker_id})
            for entry in declaration.get("entrypoints", []):
                if not any(item["path"] == entry for item in matched):
                    issues.append({"code": "entrypoint-missing", "path": entry})
        if any(item["digest"] == "outside-target" for item in matched):
            issues.append({"code": "source-outside-target"})
        scoped_signals = [item for item in signals if _matches(card, item["target"], item["path"])]
        engines = sorted({item["engine"] for item in scoped_signals if "engine" in item})
        reports.append({"id": card.card_id, "kind": card.card_type, "title": card.title, "summary": card.summary, "jurisdiction": declaration, "scopes": [asdict(scope) for scope in card.scopes], "floors": floors, "replaced_by": replacements, "checkers": list(card.checkers), "issues": issues, "freshness": freshness, "last_census": previous, "history": [record for record in records if record.get("card_id") == card.card_id][-12:], "scope_digest": scope_digest, "declaration_digest": declaration_digest, "file_count": len(matched), "code_count": sum(item["code"] for item in matched), "files": [f'{item["target"]}:{item["path"]}' for item in matched], "signals": scoped_signals, "canvas_engines": engines})
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
    for item in reports:
        item["checker_details"] = [asdict(policy.checker(checker_id)) for checker_id in item["checkers"]]
        item["last_source_change"] = _last_source_change(manifest, policy.card(item["id"]))
        if item["last_census"]:
            timestamp = datetime.fromisoformat(item["last_census"]["surveyed_at"])
            item["census_age_days"] = max(0, (datetime.now(timezone.utc) - timestamp).days)
    return {"schema": CENSUS_SCHEMA, "observed_at": datetime.now(timezone.utc).isoformat(), "required": policy.household_required, "project": manifest.project_id, "revisions": revisions, "households": reports, "gaps": gaps, "directories": [{**value, "owners": sorted(value["owners"])} for _, value in sorted(directories.items())], "implementations": implementations, "signals": signals, "counts": {"jurisdictions": len(jurisdictions), "code_files": sum(item["code"] for item in artifacts), "unowned": sum(item["code"] == "code-unowned" for item in gaps), "ambiguous": sum(item["code"] == "code-ambiguous" for item in gaps), "freshness": dict(Counter(item["freshness"] for item in reports))}}


def required_households(report: dict, entry_slice: dict) -> list[dict]:
    paths = entry_slice.get("entries", {}).get("paths", [])
    if not paths:
        return [item for item in report["households"] if item["jurisdiction"]]
    qualified = {f'{item["target"]}:{item["path"]}' for item in paths}
    return [item for item in report["households"] if item["jurisdiction"] and (qualified.intersection(item["files"]) or item["id"] in {card["id"] for card in entry_slice.get("cards", [])})]


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
        problems.extend(f'{issue["code"]}:{item["id"]}' for issue in item["issues"])
        if item["freshness"] != "current":
            problems.append(f'census-{item["freshness"]}:{item["id"]}')
        missing = set(item["checkers"]) - checker_ids
        if missing:
            problems.append(f'implementation-check-not-selected:{item["id"]}:{",".join(sorted(missing))}')
    if problems:
        raise AG2CError("household gate blocked:\n- " + "\n- ".join(problems[:40]))
