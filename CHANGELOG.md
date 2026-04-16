# Changelog

All notable changes to **nostos** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

For each release, the authoritative source is the GitHub release notes at
https://github.com/prodrom3/nostos/releases. This file is a consolidated, auditable in-repo mirror.

## [Unreleased]

No unreleased changes.

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

[Unreleased]: https://github.com/prodrom3/nostos/compare/v1.2.0...HEAD
[1.2.0]: https://github.com/prodrom3/nostos/releases/tag/v1.2.0
[1.1.0]: https://github.com/prodrom3/nostos/releases/tag/v1.1.0
[1.0.0]: https://github.com/prodrom3/nostos/releases/tag/v1.0.0
