# Adoption

AG2C adoption has one user-facing action: choose a Git project in the tray application. Users do not author governance files or run enrollment commands on Windows.

## Windows installation

Download `AutoGovern2Code-Setup-Windows-x64.exe` from the [latest GitHub Release](https://github.com/Holosukiyaa/AutoGovern2Code/releases/latest) and double-click it. The per-user installer:

- installs a self-contained AG2C runtime without requiring Python, administrator rights, or Edge WebView2; the tray is a Dear ImGui window (Hello ImGui) and the package ships MinGit next to the app;
- writes this AG2C into local MCP configs (`ag2c mcp install`) and may still copy Skills into known homes as a fallback; the operator entry is **连接 MCP**;
- adds the runtime to the user PATH for agent use;
- starts the tray application and registers it for user startup.

The tray is a local desktop application, not a browser dashboard and not a Windows service. Closing its window hides it to the tray. Governance hooks continue to protect already managed repositories even when the window is hidden.

## Add an existing project

Open AG2C from the tray, select **Add project**, and choose the root of a non-empty Git repository. Enrollment then:

1. detects the repository's tracked top-level areas and native checks;
2. creates an external Manifest, Policy, index, Ledger, hook, and project record;
3. writes only local pointers to `.git/config`;
4. seizes the existing Git repo by setting `core.hooksPath` to AG2C and wrapping every previous hook name (`pre-commit`, `pre-push`, `commit-msg`, …). History and remotes stay in the project's `.git`;
5. leaves the working tree, index, and HEAD unchanged.

A dirty project can be registered, but the tray reports that it needs attention and AG2C refuses to start governed construction until the canonical checkout is clean.

No `.ag2c`, AG2C-managed `AGENTS.md`, `CLAUDE.md`, or receipt is added to the project. The normal project history receives no enrollment commit.

## Daily work

After adoption, click **连接 MCP** in the tray (or run `ag2c mcp install`). That writes a stdio MCP server into Grok, Cursor, Claude, and Codex user configs. The next agent session receives Skill instructions and tools from this AG2C; the user does not paste a copy-prompt again. AG2C does not detect which harness is installed.

The MCP tools discover enrollment through local Git configuration and perform route selection, worktree creation, verification, commit, fast-forward integration, and evidence recording without asking the user to operate governance. Copy-prompt remains a fallback for agents without MCP.

The tray separates three facts:

- **AI entry**: 连接 MCP. One local stdio server carries Skills and live tools.
- **Delivery**: whether the external store and Git guard are connected.
- **Observed records**: finished tasks and what they implemented or fixed.

A finished governed task is process delivery, not product acceptance. Until the project declares contracts or boundary/scenario checks, Product stays undeclared. This avoids treating “Skill installed” or “process finished” as “the product is done.”

## Another machine or clone

Enrollment is intentionally local and does not travel with Git. On another machine, install AG2C, open the tray, and add that clone as a separate project. Its policy and evidence are independent because each clone can have different paths, tools, and worktrees.

If the folder was copied with `.git` intact, local Git config may still point at the previous computer's user-directory store. Add Project or `ag2c doctor --repair` now treats that as stale or relocated: a copied store is rebound to the original project key, and a missing store is re-enrolled on this computer with history marked unrecoverable.

## Stop, resume, or uninstall

The tray keeps three project actions separate:

- **Stop governance** leaves the project in the list, restores the previous `core.hooksPath`, and removes AG2C's local Git pointers. Evidence stays in the external store. **Resume** reconnects that store without a new enrollment while it is still present.
- **Uninstall project** unregisters the clone and deletes that project's governance archive.
- The Windows **uninstaller** removes the AG2C runtime, startup entry, PATH entry, and unmodified packaged Skills. It does not rewrite user repositories. External evidence remains unless you uninstalled the project first.

## Legacy migration

Selecting a repository with tracked `.ag2c` or `.deg` enrollment migrates it to the external store. AG2C preserves the legacy evidence externally and creates one narrow maintenance commit that removes only the legacy governance files and AG2C-managed instruction blocks. Unrelated user instructions remain intact. Migration requires a clean canonical checkout because it changes tracked project content once.

The CLI equivalents, intended for agents and maintainers, are `ag2c setup --project .`, `ag2c upgrade`, `ag2c migrate`, and `ag2c doctor --repair`.
