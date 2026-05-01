# Changelog

All notable changes to **nostos** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

For each release, the authoritative source is the GitHub release notes at
https://github.com/prodrom3/nostos/releases. This file is a consolidated, auditable in-repo mirror.

## [Unreleased]

No unreleased changes.

## [1.4.3] - 2026-05-01

### Changed

- `extras/topic_rules/default.toml`: three retargeted aliases driven by operator feedback.
  - **Offsec branding**: canonical form switched from `offensive-security` to the shorter, more idiomatic `offsec`. `offensive-security` and `offensivesecurity` now both alias to `offsec` (the previous `offsec -> offensive-security` mapping was the reverse direction).
  - **Web pentest**: `web-penetration-testing` now collapses to `websec` instead of `pentest`. Web pentest is more naturally a subset of web-security work than of general pentest tooling, and this leaves `pentest` for the broader pentest-tool category.

Operators who already imported the 1.4.2 default set should re-import (`nostos topics import extras/topic_rules/default.toml`, default `--merge` will overlay the new directions on top of the old ones since alias-overlay is "incoming wins") and then re-curate (`nostos topics apply`).

## [1.4.2] - 2026-05-01

### Changed

- `extras/topic_rules/default.toml`: 15 additional alias entries covering universal collapses for security tooling. The bundled rule set now ships **2 deny + 64 alias** entries (was 2 + 49). New collapses:
  - **XSS family**: `xss-exploitation`, `xss-vulnerability`, `cross-site-scripting` -> `xss`.
  - **Greenbone / OpenVAS family**: `gvm`, `greenbone-community-edition`, `greenbone-vulnerability-management` -> `greenbone`; `openvas-scanner` -> `openvas`. (Greenbone is the rebranded OpenVAS suite; GVM is the same project under its enterprise name.)
  - **Metasploit family**: `metasploit-payloads`, `launch-metasploit` -> `metasploit`.
  - **Brute-force**: `brute-force`, `brute-force-attacks` -> `bruteforce`.
  - **Web testing**: `web-penetration-testing` -> `pentest`; `web-application` -> `websec`.
  - **Linux noise**: `linux-hacking-tools` -> `linux`.
  - **Typo**: `offensivesecurity` -> `offensive-security`.

Operators who already imported `default.toml` under 1.4.0 / 1.4.1 can pick up the new entries with `nostos topics import extras/topic_rules/default.toml` (default `--merge`) followed by `nostos topics apply` to retroactively curate the index.

## [1.4.1] - 2026-05-01

### Added

- **`nostos tags`** subcommand (plural - distinct from `nostos tag` which edits one repo's tags). Prints every tag currently attached to one or more repos, sorted by attachment count descending then name. Flags: `--include-orphans` also lists tag rows with zero attached repos; `--prune-orphans` deletes them after listing; `--json` for machine-readable output.
- `core.index.list_tags_with_counts(conn, *, include_orphans=False)` and `core.index.prune_orphan_tags(conn)` helpers. Orphan tags are rows in the `tags` table no longer referenced by any `repo_tags` row, typically left behind after `topics apply` rewrites alias-source tags. They are invisible to `nostos list --tag X` queries (which join through `repo_tags`) and reusable if a future repo gets the same topic, so pruning is purely cosmetic.

### Fixed

- CI: ruff F401 unused-import in `core/topic_rules.py` removed (`config_dir` was imported but never referenced).
- CI: Python 3.10 test matrix now installs `tomli` so the `parse_rules_from_text` / `dump_rules` test surface exercises the same code paths as 3.11+ (where `tomllib` is stdlib).

## [1.4.0] - 2026-05-01

### Added

- **`nostos add --auto-tags`** and **`nostos refresh --auto-tags`** opt-in flags. After cloning (or during refresh), the upstream host's API is queried for the repo's "topics" field and the values are merged into the local tag list. Works against GitHub, GitLab, and Gitea (hosted and self-hosted). Opsec gates from `~/.config/nostos/auth.toml` apply: hosts not configured are silently skipped. Repos marked `--quiet-upstream` always bypass the probe.
- `[add] auto_tags = true | false` knob in `~/.nostosrc` to set the default for `nostos add` per machine. CLI flag overrides the config value.
- **`nostos topics`** subcommand to manage topic curation rules with eight sub-verbs: `list`, `deny`, `allow`, `alias`, `unalias`, `export`, `import`, `apply`. Rules persist in `$XDG_CONFIG_HOME/nostos/topic_rules.toml` (atomic write, `0600` on Unix). The deny list drops junk topics entirely; the alias map collapses synonym sprawl (e.g. `penetration-testing` -> `pentest`, `red-teaming` -> `redteam`) so `nostos list --tag pentest` resolves regardless of how an upstream maintainer spelled the topic.
- `topics export [PATH]` writes the current rules as TOML to PATH or stdout. `topics import FILE` loads a rules document with `--merge` (default; unions deny lists and overlays alias maps) or `--replace` (overwrites local rules). Both accept `-` for stdin, so `curl ... | nostos topics import -` and `nostos topics export | ssh other-host nostos topics import -` work.
- `topics apply` retroactively curates tag state on already-indexed repos so importing rules (or editing them via `deny` / `alias`) fixes the index, not just future imports. `--repo PATH_OR_ID` targets one repo; `--dry-run` previews changes without writing; `--json` emits a machine-readable summary. Idempotent.
- `extras/topic_rules/default.toml`: bundled curated rule set (2 deny + 49 aliases) that anyone can import as a starting point. Conservative: only obvious junk is denied, no language or distro topics are dropped.
- New module `core/topic_rules.py` exposes `TopicRules`, `load_rules`, `save_rules`, `parse_rules_from_text`, `dump_rules`, `merge_rules`. Hand-rolled TOML serializer keeps the zero-runtime-dep invariant.
- `topics` field added to `GitHubProbe`, `GitLabProbe`, and `GiteaProbe` results (no extra HTTP request: the field is already in the providers' main repo response).
- 43 new tests covering rules apply / save / load / round-trip, `topics` CLI verbs end-to-end (including stdin import and JSON summary shape), `add --auto-tags` / `refresh --auto-tags` flow with rules applied, and `apply` retroactive cleanup. Suite total: 522 (up from 479).

### Changed

- **`nostos tag`** now accepts `~tag` as a remove prefix in addition to `-tag`. argparse parses bare `-tag` as an unknown option flag, so the hyphen form previously required the `--` end-of-options separator (`nostos tag <repo> -- -old +new`). The new tilde form sidesteps the gotcha entirely (`nostos tag <repo> ~old +new`). The hyphen form still works after `--` for back-compat.
- README updated with new examples for `--auto-tags`, `nostos topics`, `topics import / export`, `topics apply`, and the bundled default rule set. Verb table gains a `topics` row.
- Bash and zsh completions extended for the new flags and sub-verbs.

## [1.3.0] - 2026-04-17

### Changed

- **Logs now live under `$XDG_DATA_HOME/nostos/logs/`** (default `~/.local/share/nostos/logs/` on Linux / macOS, `%LOCALAPPDATA%\nostos\logs\` on Windows) instead of `./logs/` relative to the install root. This fixes the pipx gotcha where log files were silently buried inside the pipx venv (`~/.local/pipx/venvs/nostos/lib/.../logs`) and lost on every `pipx reinstall`. The new location sits alongside the metadata index, is created with `0700` perms on Unix, and survives reinstalls.
- `nostos update` now suggests `pip install --upgrade nostos` (PyPI) as the upgrade command for pip-installed users instead of `pip install --upgrade git+https://github.com/prodrom3/nostos.git`. The git URL remains in the notes for operators who prefer tracking git HEAD.

### Documentation

- README: env-vars table expanded with `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, and the Windows `APPDATA` / `LOCALAPPDATA` fallbacks.
- README: Logging section rewritten to reflect the new log location.
- Repository restructure: long-form reference content moved into `docs/` (architecture, upstream probes, bundle schema, vault); README condensed from ~1180 to ~360 lines.
- New enterprise-oriented root files: `CHANGELOG.md`, `CONTRIBUTING.md`, `MAINTAINERS.md`.
- README header: replaced the (now-dead) `prodrom3/gitpulse/assets/...` image with an inline ASCII banner.

## [1.2.0] - 2026-04-17

### Added

- `nostos completion` subcommand with `show`, `install`, and `uninstall` verbs. Auto-detects the operator's shell (`$SHELL`, overridable with `$NOSTOS_SHELL` or `--shell`) and manages an idempotent block in the appropriate rc file (`~/.bashrc`, `~/.zshrc`, `~/.config/fish/conf.d/nostos.fish`).
- Managed blocks are wrapped in stable `# BEGIN nostos completion` / `# END nostos completion` markers so re-running `install` replaces the block if the generated snippet changes between versions, and `uninstall` removes it without parsing the whole rc file.
- 27 new tests in `tests/test_completion.py` covering shell detection, `strip_block` / `upsert_block` idempotency, install happy-path / replace / create-missing-file, uninstall removes / no-op paths, and `show` subcommand behaviour.

### Changed

- `argcomplete >= 3.0` is now a **required** dependency (was an optional `[completion]` extra). One ~70 KB pure-Python dependency on every install, in exchange for tab-completion working out of the box.
- Completion snippets are emitted via `register-python-argcomplete --shell {bash,zsh,fish}` (native output). This sidesteps the bash-syntax bridge that was tripping up zsh users who hadn't carefully ordered `compinit` and `bashcompinit` in their rc file.
- README "Shell tab-completion" section rewritten around `nostos completion install`.

### Fixed

- The `_python-argcomplete: function definition file not found` error that appeared on Kali zsh after a manual `eval "$(register-python-argcomplete nostos)"`. The new install path renders zsh-native completion code (`#compdef nostos`) with no bash-shim dependency.

## [1.1.0] - 2026-04-17

### Added

- Portable bundle schema **v2** (reader accepts both v1 and v2, writer emits v2). Per repo, new fields: `path_relative_to_home` (forward-slash path under `$HOME`, or `null`) and `local_name` (basename hint for the clone directory). Envelope: `source_host` and `source_platform` for diagnostics.
- Cross-OS import resolution algorithm:
  1. Apply `--remap` to the absolute path.
  2. If that path is a live git repo, register it.
  3. Else if `path_relative_to_home` resolves under local `$HOME`, register.
  4. Else if `--no-clone`, register metadata-only with the post-remap path.
  5. Else if `remote_url` is set, clone to `<clone-dir>/<local_name>` using the hardened clone routine (`--no-checkout`, git hooks disabled via `GIT_CONFIG_*`; CVE-2024-32002 / 32004 / 32465 mitigated).
  6. Else skip with a hint.
- New import flags: `--clone-dir DIR` (default: `clone_dir` in `~/.nostosrc`, falling back to `$HOME`), `--no-clone` (metadata-only; never touch the network), `--clone-workers N` (default 4).
- `--dry-run` on `nostos import` prints a per-entry plan (already present / will be cloned / bare register / cannot resolve).
- Public API additions in `core.portable`: `plan_import()` and `resolve_entry_path()`; `READABLE_SCHEMAS = frozenset({1, 2})`.
- 23 new tests in `tests/test_portable.py` covering the full resolution algorithm, clone-on-import happy path and failure counting, and schema-1 forward compatibility through the CLI.

### Changed

- `import_bundle()` gained three keyword-only parameters (`clone_missing`, `clone_dir`, `clone_workers`). Default `clone_missing=True`; pass `False` for the old offline behavior.
- `--dry-run` output is now human-readable per entry before the JSON summary (use `--json` for machine output only).

### Backwards compatibility

- Schema-1 bundles (from earlier nostos and from gitpulse) import on 1.1.0+. They simply hit the clone-or-register fallback paths instead of the new home-relative shortcut.

## [1.0.0] - 2026-04-16

### Added

- Initial release under the name **nostos** (Greek "homecoming" - a direct semantic match for what `git pull` does).
- Full fleet-management CLI: `pull`, `add`, `list`, `show`, `tag`, `note`, `triage`, `rm`, `refresh`, `digest`, `dashboard`, `vault`, `export`, `import`, `update`, `doctor`, `attack`.
- Hardened clone routine (`add URL`): `--no-checkout` with git hooks disabled via `GIT_CONFIG_*` env vars. Mitigates CVE-2024-32002 / 32004 / 32465.
- Metadata index (SQLite, 0600, WAL, secure_delete) at `$XDG_DATA_HOME/nostos/index.db` for tags, status, notes, provenance, cached upstream metadata.
- Upstream probe layer for GitHub, GitLab, Gitea (hosted and self-hosted) gated by per-host auth config in `~/.config/nostos/auth.toml`. Fail-closed: only configured hosts are ever contacted.
- Portable export / import bundle (schema v1): stable JSON, redaction flag, path remap.
- Obsidian vault bridge (`vault export` and `vault sync`), weekly `digest`, static HTML `dashboard`, ATT&CK tagging helpers, self-update via `nostos update`.
- SSH connection multiplexing via `ControlMaster` on Unix for faster fetches.
- Signal-safe graceful Ctrl+C with partial-summary output.
- GitHub Actions CI on ubuntu / windows / macOS x Python 3.10-3.13; PyPI publishing via trusted publishing (OIDC).

### Rename from gitpulse

- `gitpulse` was squatted on PyPI by unrelated projects, blocking publishing. This release is a **clean break** to the `nostos` name. No compatibility shim.
- Breaking changes: CLI command, PyPI package, config file (`~/.gitpulserc` -> `~/.nostosrc`), watchlist (`~/.gitpulse_repos` -> `~/.nostos_repos`), data dir, self-update endpoint.
- Migration path for existing gitpulse users: `gitpulse export --out fleet.json` on the old install, then `pipx install nostos && nostos import fleet.json` on the new install.

[Unreleased]: https://github.com/prodrom3/nostos/compare/v1.3.0...HEAD
[1.3.0]: https://github.com/prodrom3/nostos/releases/tag/v1.3.0
[1.2.0]: https://github.com/prodrom3/nostos/releases/tag/v1.2.0
[1.1.0]: https://github.com/prodrom3/nostos/releases/tag/v1.1.0
[1.0.0]: https://github.com/prodrom3/nostos/releases/tag/v1.0.0
