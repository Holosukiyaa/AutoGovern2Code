"""Extracted by flatten-split."""
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
from .util import digest_file, digest_json, path_matches
from .households import CENSUS_SCHEMA, CODE_SUFFIXES, _CENSUS_CACHE, _census_cache_key, _census_freshness, _code_direct_children, _direct_named_dirs, _history, _include_roots, _last_source_change, _matches, _matches_include, _version, coerce_jurisdiction, expired_renewals, file_card_summary, file_latest_commits

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
    from . import __version__ as running_code_version

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
        freshness = _census_freshness(previous, scope_digest, declaration_digest, running_code_version)
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
