from __future__ import annotations

import hashlib
import os
import secrets
import shutil
from pathlib import Path
from typing import Iterable

from .errors import AG2CError

SKILL_NAME = "ag2c-governed-development"
GOVERNANCE_SKILL_NAME = "ag2c-governance-update"
PACKAGED_SKILLS = (SKILL_NAME, GOVERNANCE_SKILL_NAME)
SUPPORTED_HARNESSES = ("codex", "claude", "agents")


def skill_source(name: str = SKILL_NAME) -> Path:
    source = Path(__file__).with_name("skills") / name
    if not (source / "SKILL.md").is_file():
        raise AG2CError(f"packaged AG2C Skill is missing: {name}")
    return source


def skill_digest(path: Path) -> str:
    digest = hashlib.sha256()
    for file in sorted((item for item in path.rglob("*") if item.is_file()), key=lambda item: item.as_posix()):
        digest.update(file.relative_to(path).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(file.read_bytes())
    return digest.hexdigest()


def default_skill_roots() -> dict[str, Path]:
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    return {
        "codex": codex_home / "skills",
        "claude": Path.home() / ".claude" / "skills",
        "agents": Path.home() / ".agents" / "skills",
    }


def _install_at(destination_root: Path, name: str = SKILL_NAME) -> Path:
    destination = destination_root.resolve() / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink():
        raise AG2CError(f"refusing to replace a symlinked Skill directory: {destination}")
    if destination.exists() and not destination.is_dir():
        raise AG2CError(f"refusing to replace a non-directory Skill path: {destination}")
    staging = destination.parent / f".{name}-{secrets.token_hex(4)}.tmp"
    backup = destination.parent / f".{name}-{secrets.token_hex(4)}.backup"
    replaced = False
    installed = False
    try:
        shutil.copytree(skill_source(name), staging)
        if destination.exists():
            os.replace(destination, backup)
            replaced = True
        os.replace(staging, destination)
        installed = True
    except Exception:
        if replaced and not destination.exists() and backup.exists():
            os.replace(backup, destination)
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)
        if installed and backup.exists():
            shutil.rmtree(backup)
    return destination


def install_skills(
    destination_root: Path | None = None,
    harnesses: Iterable[str] | None = None,
) -> list[dict[str, str]]:
    selected = tuple(dict.fromkeys(harnesses or SUPPORTED_HARNESSES))
    unknown = sorted(set(selected) - set(SUPPORTED_HARNESSES))
    if unknown:
        raise AG2CError("unsupported AI harness: " + ", ".join(unknown))
    if destination_root is not None:
        destinations = [("custom", destination_root)]
    else:
        roots = default_skill_roots()
        destinations = [(name, roots[name]) for name in selected]
    installed: list[dict[str, str]] = []
    seen: set[Path] = set()
    for harness, root in destinations:
        resolved = root.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        path = _install_at(resolved, SKILL_NAME)
        _install_at(resolved, GOVERNANCE_SKILL_NAME)
        installed.append({"harness": harness, "path": str(path), "digest": skill_digest(path)})
    if not installed:
        raise AG2CError("no AI harness Skill destination was selected")
    return installed


def remove_skills(
    destination_root: Path | None = None,
    harnesses: Iterable[str] | None = None,
) -> list[dict[str, str]]:
    selected = tuple(dict.fromkeys(harnesses or SUPPORTED_HARNESSES))
    unknown = sorted(set(selected) - set(SUPPORTED_HARNESSES))
    if unknown:
        raise AG2CError("unsupported AI harness: " + ", ".join(unknown))
    if destination_root is not None:
        destinations = [("custom", destination_root)]
    else:
        roots = default_skill_roots()
        destinations = [(name, roots[name]) for name in selected]
    removed: list[dict[str, str]] = []
    seen: set[Path] = set()
    for harness, root in destinations:
        destination = root.resolve() / SKILL_NAME
        if destination in seen:
            continue
        seen.add(destination)
        status = "absent"
        if destination.is_symlink() or (destination.exists() and not destination.is_dir()):
            status = "preserved-non-directory"
        elif destination.is_dir():
            if skill_digest(destination) == skill_digest(skill_source(SKILL_NAME)):
                shutil.rmtree(destination)
                status = "removed"
            else:
                status = "preserved-modified"
        companion = root.resolve() / GOVERNANCE_SKILL_NAME
        if companion.is_dir() and skill_digest(companion) == skill_digest(skill_source(GOVERNANCE_SKILL_NAME)):
            shutil.rmtree(companion)
        removed.append({"harness": harness, "path": str(destination), "status": status})
    return removed


def harness_status() -> list[dict[str, object]]:
    roots = default_skill_roots()
    packaged_digest = skill_digest(skill_source())
    commands = {"codex": "codex", "claude": "claude", "agents": None}
    result: list[dict[str, object]] = []
    for harness in SUPPORTED_HARNESSES:
        destination = roots[harness].resolve() / SKILL_NAME
        executable = shutil.which(commands[harness]) if commands[harness] else None
        detected = bool(executable) or (harness == "agents" and roots[harness].parent.exists())
        installed = (destination / "SKILL.md").is_file()
        integrated = installed and skill_digest(destination) == packaged_digest
        if integrated:
            state = "ready"
        elif detected:
            state = "skill-missing"
        else:
            state = "not-detected"
        result.append(
            {
                "harness": harness,
                "detected": detected,
                "executable": executable,
                "skill_path": str(destination),
                "skill_installed": installed,
                "integrated": integrated,
                "state": state,
            }
        )
    return result


def install_skill(destination_root: Path | None = None) -> Path:
    return Path(install_skills(destination_root, ("codex",))[0]["path"])
