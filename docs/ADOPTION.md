# Adoption

AG2C adoption has one user-facing action: choose a Git project in the tray application. Users do not author governance files or run enrollment commands on Windows.

## Windows installation

Download `AutoGovern2Code-Setup-Windows-x64.exe` from the [latest GitHub Release](https://github.com/Holosukiyaa/AutoGovern2Code/releases/latest) and double-click it. The per-user installer:

- installs a self-contained AG2C runtime without requiring Python or administrator rights;
- installs the same Skill for Codex, Claude Code, and generic Agent Skills locations;
- adds the runtime to the user PATH for agent use;
- starts the tray application and registers it for user startup.

The tray is a local desktop application, not a browser dashboard and not a Windows service. Closing its window hides it to the tray. Governance hooks continue to protect already managed repositories even when the window is hidden.

## Add an existing project

Open AG2C from the tray, select **Add project**, and choose the root of a non-empty Git repository. Enrollment then:

1. detects the repository's tracked top-level areas and native checks;
2. creates an external Manifest, Policy, index, Ledger, hook, and project record;
3. writes only local pointers to `.git/config`;
4. preserves and delegates any existing `pre-commit` hook;
5. leaves the working tree, index, and HEAD unchanged.

A dirty project can be registered, but the tray reports that it needs attention and AG2C refuses to start governed construction until the canonical checkout is clean.

No `.ag2c`, AG2C-managed `AGENTS.md`, `CLAUDE.md`, or receipt is added to the project. The normal project history receives no enrollment commit.

## Daily work

After adoption, use the coding agent normally. A compatible harness selects `ag2c-governed-development`, which discovers enrollment through local Git configuration. The Skill performs route selection, worktree creation, verification, commit, fast-forward integration, and evidence recording without asking the user to operate governance.

The tray separates three facts:

- **Agent entry ready**: at least one supported harness has the current Skill.
- **Delivery enforced**: the project has a valid external store and active Git guard.
- **Agent observed**: at least one completed task contains successful management evidence.

This distinction avoids claiming that an installed Skill has already controlled an AI task.

## Another machine or clone

Enrollment is intentionally local and does not travel with Git. On another machine, install AG2C, open the tray, and add that clone as a separate project. Its policy and evidence are independent because each clone can have different paths, tools, and worktrees.

If the folder was copied with `.git` intact, local Git config may still point at the previous computer's user-directory store. Add Project or `ag2c doctor --repair` now treats that as stale or relocated: a copied store is rebound to the original project key, and a missing store is re-enrolled on this computer with history marked unrecoverable.

## Stop managing or uninstall

**Stop managing** in the tray restores the previous `core.hooksPath`, removes AG2C's local Git pointers, and removes the project from the list. Evidence remains in the external store by default.

The Windows uninstaller removes the runtime, startup entry, PATH entry, and unmodified packaged Skills. It does not rewrite user repositories or erase external project evidence.

## Legacy migration

Selecting a repository with tracked `.ag2c` or `.deg` enrollment migrates it to the external store. AG2C preserves the legacy evidence externally and creates one narrow maintenance commit that removes only the legacy governance files and AG2C-managed instruction blocks. Unrelated user instructions remain intact. Migration requires a clean canonical checkout because it changes tracked project content once.

The CLI equivalents, intended for agents and maintainers, are `ag2c setup --project .`, `ag2c upgrade`, `ag2c migrate`, and `ag2c doctor --repair`.
