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
CENSUS_SKILL_NAME = "ag2c-directory-census"
PACKAGED_SKILLS = (SKILL_NAME, GOVERNANCE_SKILL_NAME, CENSUS_SKILL_NAME)
SUPPORTED_HARNESSES = ("codex", "claude", "cursor", "agents")

SKILL_ENTRY_PROMPT = """This Git repository is managed by AutoGovern2Code (AG2C) {package_version}.

Install or refresh the AG2C Skills into THIS agent's own skills directory. Do not edit product files to do it.

Every time you receive this prompt, make sure this agent holds THIS AutoGovern2Code's Skills. Latest means this AutoGovern2Code's packaged copy, not the internet and not a higher version from another AG2C.

Required Skill versions (replace the installed copy if missing or different):
{required}

1. Read `version:` from each installed SKILL.md frontmatter. A missing version is stale.
2. If the installed version or digest is not exactly a Required line above, replace the whole skill folder. Do not keep a folder because one already exists, and do not keep a higher version from elsewhere.
3. Source, in order:
   - this repo's {skill_docs}, if present
   - otherwise run: ag2c skill install
   Typical skills homes: Codex ~/.codex/skills ; Claude Code ~/.claude/skills ; Cursor ~/.cursor/skills ; other Agent Skills hosts ~/.agents/skills. If your product uses another folder, use that.
4. Confirm required versions with: ag2c skill version
5. Then in this repository run: ag2c guard status
6. File-changing work follows ag2c-governed-development. Tree investigation (彻查/普查) follows ag2c-directory-census. Knowledge-card edits follow ag2c-governance-update. Do not git commit on the canonical checkout.

Git delivery stays blocked until work goes through an AG2C task worktree. Installing the Skill is only the entry.
"""


def skill_frontmatter_version(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    if not text.startswith("---"):
        return ""
    finish = text.find("\n---", 3)
    if finish < 0:
        return ""
    for line in text[3:finish].splitlines():
        key, separator, value = line.partition(":")
        if separator and key.strip() == "version":
            return value.strip().strip("'\"")
    return ""


def packaged_skill_identity(name: str = SKILL_NAME) -> dict[str, str]:
    from . import __version__

    source = skill_source(name)
    version = skill_frontmatter_version(source / "SKILL.md") or __version__
    return {"name": name, "version": version, "digest": skill_digest(source)}


def packaged_skills_report() -> dict[str, object]:
    from . import __version__

    return {
        "package": __version__,
        "skills": [packaged_skill_identity(name) for name in PACKAGED_SKILLS],
    }


def skill_entry_prompt(*, project: Path | None = None) -> str:
    from . import __version__

    root = (project or Path.cwd()).resolve()
    identities = [packaged_skill_identity(name) for name in PACKAGED_SKILLS]
    required = "\n".join(
        f"   - {item['name']} version {item['version']} digest {item['digest'][:12]}"
        for item in identities
    )
    skill_docs = " and ".join(f"docs/skills/{name}" for name in PACKAGED_SKILLS)
    text = SKILL_ENTRY_PROMPT.format(
        package_version=__version__,
        required=required,
        skill_docs=skill_docs,
    ).strip() + "\n"
    local = root / "docs" / "skills" / "ag2c-governed-development" / "SKILL.md"
    if local.is_file():
        text += f"\nLocal skill copy in this repo:\n{local}\n"
    return text


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
        "cursor": Path.home() / ".cursor" / "skills",
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
        for name in PACKAGED_SKILLS:
            if name == SKILL_NAME:
                continue
            _install_at(resolved, name)
        identity = packaged_skill_identity(SKILL_NAME)
        installed.append(
            {
                "harness": harness,
                "path": str(path),
                "digest": skill_digest(path),
                "version": identity["version"],
            }
        )
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
        for name in PACKAGED_SKILLS:
            if name == SKILL_NAME:
                continue
            companion = root.resolve() / name
            if companion.is_dir() and skill_digest(companion) == skill_digest(skill_source(name)):
                shutil.rmtree(companion)
        removed.append({"harness": harness, "path": str(destination), "status": status})
    return removed


def harness_status() -> list[dict[str, object]]:
    roots = default_skill_roots()
    packaged_digest = skill_digest(skill_source())
    commands = {"codex": "codex", "claude": "claude", "cursor": "cursor", "agents": None}
    result: list[dict[str, object]] = []
    for harness in SUPPORTED_HARNESSES:
        destination = roots[harness].resolve() / SKILL_NAME
        executable = shutil.which(commands[harness]) if commands[harness] else None
        detected = bool(executable) or (
            (harness == "agents" and roots[harness].parent.exists())
            or (harness == "cursor" and (Path.home() / ".cursor").exists())
        )
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
