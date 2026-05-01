# nostos

[![CI](https://github.com/prodrom3/nostos/actions/workflows/ci.yml/badge.svg)](https://github.com/prodrom3/nostos/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](./LICENSE)
[![Version](https://img.shields.io/badge/version-1.4.2-orange.svg)](./VERSION)
[![PyPI](https://img.shields.io/pypi/v/nostos.svg)](https://pypi.org/project/nostos/)
[![Platforms](https://img.shields.io/badge/platforms-Linux%20%7C%20macOS%20%7C%20Windows-lightgrey.svg)](#compatibility)

```
                     __
   ____  ____  _____/ /_____  _____
  / __ \/ __ \/ ___/ __/ __ \/ ___/
 / / / / /_/ (__  ) /_/ /_/ (__  )
/_/ /_/\____/____/\__/\____/____/

  the homecoming - a fleet of git repositories
```

> **nostos** is a Python CLI for batch-updating and curating fleets of git repositories in parallel. Built for developers and platform teams who maintain dozens - or hundreds - of cloned repositories and need a reliable, auditable, scriptable way to keep them in sync.

---

## Overview

nostos is three tools in one:

1. A **batch-pull engine** that walks a directory tree (and/or a curated index), discovers every git repository it can reach, and updates them concurrently. Dirty trees, detached HEADs, and missing upstreams are reported and skipped, never overwritten.
2. A **metadata index** (SQLite) recording identity, provenance, tags, notes, and triage status for every repository in your fleet.
3. An **upstream probe layer** that queries GitHub, GitLab, and Gitea - hosted and self-hosted - for health signals (archived, stars, last push, latest release, license). Fail-closed by default: only hosts listed in `~/.config/nostos/auth.toml` are ever contacted.

Use cases:

- **Developers with many cloned repos** that drift. `nostos ~/projects` pulls them all in parallel; dirty trees and detached HEADs are reported, never overwritten.
- **Curated project collections** - anyone who ingests new repos from blog posts, papers, or colleague pointers. `nostos add <url>` clones and captures provenance in one step; `nostos triage` walks the new intake; `nostos list --tag python --untouched-over 90` answers "what have I stopped using?" in milliseconds.
- **Upstream health monitoring** for tracked open-source projects. `nostos refresh` caches archived status, last push, and latest release; `nostos list --upstream-archived` surfaces repos whose upstream has been archived or taken down.
- **Build boxes and mirror hosts** maintaining read-only clones. JSON output and deterministic exit codes make nostos safe to embed in cron and CI.
- **Cross-machine fleet replication.** `nostos export` / `nostos import` ship your fleet (metadata plus clone-on-import) between machines, with path remapping for cross-OS moves.

---

## Quick start

```bash
pipx install nostos                         # or: pip install nostos
nostos completion install                   # enable shell tab-completion

nostos --dry-run                            # preview updates under cwd
nostos ~/projects --workers 16              # pull in parallel

nostos add https://github.com/org/tool.git --tag recon
nostos list --tag recon --untouched-over 90
nostos triage                               # classify new intake
```

No third-party runtime dependencies beyond `argcomplete` (required for tab-completion, bundled with every install).

---

## Installation

### Requirements

| Component | Minimum | Recommended |
| --- | --- | --- |
| Python | 3.10 | 3.12+ |
| Git | 2.25 | **2.45.1+** (nostos warns at startup on versions with CVE-2024-32002 / 32004 / 32465) |
| OS | Linux / macOS / Windows | - |

### Install

```bash
# Isolated (recommended)
pipx install nostos

# System-wide
pip install nostos

# From source
git clone https://github.com/prodrom3/nostos.git
cd nostos && pip install .
```

Verify with `nostos --version` and `nostos --help`.

### Shell tab-completion

```bash
nostos completion install        # auto-detects your shell
exec $SHELL                      # reload
nostos <TAB><TAB>                # lists all verbs
```

`install` is idempotent and writes a managed block into `~/.bashrc`, `~/.zshrc`, or `~/.config/fish/conf.d/nostos.fish`. Remove with `nostos completion uninstall`. Native Windows shells (PowerShell / cmd) are not supported by argcomplete upstream; use Git Bash or WSL.

---

## Usage

nostos is verb-first: `nostos <verb> [args]`. An invocation without a verb is an implicit `pull`, so old scripts and cron jobs keep working.

| Verb | Purpose |
| --- | --- |
| `pull` (default) | Batch-update discovered repositories. |
| `add` | Ingest a local path or remote URL into the metadata index. |
| `list` | Filter and print the repo fleet. |
| `show` | Print full metadata for one repo. |
| `tag` | Add or remove tags on a repo. |
| `tags` | List every tag in the index with attachment counts; optionally prune orphans. |
| `note` | Append a timestamped note. |
| `triage` | Walk newly-added repos interactively and classify them. |
| `refresh` | Fetch upstream metadata. Opsec-gated. See [docs/upstream-probes.md](docs/upstream-probes.md). |
| `topics` | Manage topic curation rules (deny / alias) applied when `--auto-tags` imports upstream topics. |
| `digest` | Weekly changeset report (zero network). |
| `dashboard` | Render a static HTML fleet health report. |
| `vault` | Obsidian vault bridge (`export` / `sync`). See [docs/vault.md](docs/vault.md). |
| `export` / `import` | Portable JSON bundles for cross-machine / backup. See [docs/bundle-schema.md](docs/bundle-schema.md). |
| `update` | Self-update. Auto-detects source / pipx / pip install. |
| `doctor` | Index integrity check; `--fix` auto-remediates safe issues. |
| `attack` | MITRE ATT&CK technique lookup + tagging helper. |
| `completion` | Shell tab-completion setup. |
| `rm` | Remove a repo from the index (optionally `--purge` the clone). |

Every verb has `--help`. Every verb that lists or returns results supports `--json`.

### Key flags - `nostos pull`

| Flag | Default | Description |
| --- | --- | --- |
| `path` | cwd | Root directory to scan. |
| `--from-index` | off | Pull every repo registered in the metadata index. |
| `--dry-run` | off | List discovered repos without pulling. |
| `--fetch-only` | off | Fetch from remotes; do not merge or rebase. |
| `--tags` | off | Also fetch all git tags. |
| `--rebase` | off | Use `git pull --rebase`. |
| `--depth N` | 5 | Directory-scan depth limit. |
| `--workers N` | 8 | Concurrent worker threads. |
| `--timeout N` | 120 | Seconds before a git operation is killed. |
| `--exclude PATTERN...` | - | Glob patterns to skip repos by directory name. |
| `--json` | off | Machine-readable output. |
| `-q`, `--quiet` | off | Suppress progress; print only the summary. |

Every pulled repo is automatically registered in the metadata index with an updated `last_touched_at`.

### Examples

```bash
# Daily batch pull
nostos ~/projects

# CI-friendly: quiet, JSON, fetch-only
nostos --fetch-only --quiet --json | jq '.counts'

# Ingest + triage
nostos add https://github.com/org/tool.git --tag recon --source "blog:orange.tw"
nostos triage

# Ingest with auto-fetched repo topics from the upstream host (requires auth.toml)
nostos add https://github.com/r4ulcl/Mythic-OSEP-CheatSheet --tag osep,c2 --auto-tags

# Backfill topics across the whole fleet on the next refresh
nostos refresh --all --auto-tags

# Curate the imported topics: drop junk, collapse synonyms
nostos topics deny foo hacktoberfest ubuntu
nostos topics alias red-teaming redteam
nostos topics alias penetration-testing pentest
nostos topics list
nostos refresh --all --auto-tags         # re-curate the fleet

# Share rules across machines or with colleagues
nostos topics export > team-rules.toml
nostos topics import team-rules.toml             # default: merge with local rules
nostos topics import team-rules.toml --replace   # overwrite local rules
curl -sS https://example.com/rules.toml | nostos topics import -   # via stdin

# Quick start: import the curated default rule set bundled with nostos
nostos topics import extras/topic_rules/default.toml

# Retroactively curate tags already in the index after editing rules
nostos topics apply --dry-run     # preview what would change
nostos topics apply               # apply for real (idempotent)
nostos topics apply --repo /path/to/one/repo

# Find C2 tools you haven't touched in 90 days
nostos list --tag c2 --untouched-over 90

# Portable backup
nostos export --out fleet.json
nostos import fleet.json --clone-dir ~/repos   # on another machine
```

---

## Configuration

Optional INI file at `~/.nostosrc`. CLI flags always override file values.

```ini
[defaults]
depth         = 5
workers       = 8
timeout       = 120
max_log_files = 20
rebase        = false
clone_dir     = /home/user/repos

[exclude]
patterns = archived-*, .backup-*, vendor-*

[add]
auto_tags = false             # default. Set true to make `nostos add` always
                              # fetch repo topics from the upstream host.
```

### Environment variables

| Variable | Effect |
| --- | --- |
| `NO_COLOR` | Disables ANSI color when set to any non-empty value. |
| `NOSTOS_SHELL` | Overrides `$SHELL` when detecting the target shell for `nostos completion`. Accepts `bash` / `zsh` / `fish`. |
| `GITHUB_TOKEN`, etc. | Referenced via `token_env = "..."` in `~/.config/nostos/auth.toml` for upstream probes. |
| `XDG_CONFIG_HOME` | Relocates `~/.config/nostos/` (default `~/.config`). |
| `XDG_DATA_HOME` | Relocates `~/.local/share/nostos/` - the index DB **and** the `logs/` subdirectory (default `~/.local/share`). |
| `APPDATA` / `LOCALAPPDATA` | Windows fallbacks when the XDG variables are unset: config lives under `%APPDATA%\nostos\`, data under `%LOCALAPPDATA%\nostos\`. |

Precedence, highest to lowest: **CLI flags** -> **`~/.nostosrc`** -> **built-in defaults**.

---

## Core concepts

### Metadata index

SQLite at `$XDG_DATA_HOME/nostos/index.db` (default `~/.local/share/nostos/index.db`, `0600` perms, WAL mode, `secure_delete=ON`). One row per repository plus tags, timestamped notes, provenance, and triage status. Every verb reads from and writes to this file; the batch `pull` auto-registers every repo it touches.

| Column | Description |
| --- | --- |
| `path` | Absolute, `realpath`-normalised. Unique. |
| `remote_url` | `origin` remote (HTTPS credentials stripped). |
| `source` | Free-text provenance (`"blog:..."`, `"auto-discovered"`, `"legacy-watchlist"`). |
| `status` | `new`, `reviewed`, `in-use`, `dropped`, `flagged`. |
| `quiet` | Opsec flag: never probe upstream for this repo. |
| `added_at` / `last_touched_at` | ISO-8601 UTC timestamps. |
| tags / notes | Many-to-many tags; append-only timestamped notes. |

For at-rest confidentiality, place `$XDG_DATA_HOME/nostos/` on a disk-layer encrypted volume (LUKS / FileVault / BitLocker). nostos ships no built-in DB encryption by design.

### Upstream probes

`nostos refresh` populates cached upstream health (archived, stars, last push, release, license) for each repo, gated by `~/.config/nostos/auth.toml`. Unconfigured hosts are never contacted. Fail-closed invariants are documented in [docs/upstream-probes.md](docs/upstream-probes.md).

### Portable bundles

`nostos export` / `nostos import` serialise the metadata index as a schema-versioned JSON bundle. The import path resolves each entry against the local filesystem (direct match, `$HOME`-relative match, `--remap`) and clones repos that carry a `remote_url` but do not exist locally. Full schema and algorithm in [docs/bundle-schema.md](docs/bundle-schema.md).

### Obsidian vault

`nostos vault export` turns the index into one markdown file per repo with YAML frontmatter. `nostos vault sync` reconciles operator edits to `status` / `tags` back into the DB. Details and Dataview queries in [docs/vault.md](docs/vault.md).

---

## Output

### Human-readable

```
  [1/9] updated: /home/user/projects/repo-a
  [2/9] up-to-date: /home/user/projects/repo-d
  [3/9] skipped: /home/user/projects/repo-e

--- Summary ---
Updated (3): ...
Skipped (1): /home/user/projects/repo-e - dirty working tree
Total: 9 | Updated: 3 | Up-to-date: 5 | Skipped: 1 | Failed: 0
```

### JSON

```bash
nostos --json | jq '.counts'
```

Progress lines go to `stderr`; `--json` output on `stdout` stays clean for pipes.

---

## CI / automation

| Exit code | Meaning |
| --- | --- |
| `0` | All discovered repos updated or already up-to-date. |
| `1` | At least one repo failed to update. |

Skipped repositories (dirty, detached, no upstream) do **not** fail the run - they are surfaced in the summary for review.

```yaml
# GitHub Actions
- name: Refresh vendored clones
  run: |
    nostos ./vendor --quiet --json > /tmp/nostos.json
    jq '.counts' /tmp/nostos.json
```

```cron
# crontab
*/30 * * * *  /usr/local/bin/nostos ~/projects --quiet --fetch-only
```

---

## Logging

Each run writes a timestamped log file to `$XDG_DATA_HOME/nostos/logs/` (default `~/.local/share/nostos/logs/` on Linux / macOS, `%LOCALAPPDATA%\nostos\logs\` on Windows) alongside the metadata index - so logs survive `pipx reinstall` and are always findable regardless of install method. Example filename: `2026-04-17_14-30-00.log`. Rotated to the most recent 20 (configurable via `max_log_files`). Files are `0600`; the `logs/` directory is `0700` on Unix. HTTPS credentials of the form `https://user:token@host/` are sanitized to `https://***@host/` before being written.

---

## Security

nostos treats git operations on untrusted working directories as an attack surface, and the metadata index as an intelligence artifact. Defense-in-depth applies at both layers.

| Control | Description |
| --- | --- |
| Git version check | Startup warning on git < 2.45.1 (CVE-2024-32002 / 32004 / 32465). |
| Safe remote clone | `add <url>` clones with `--no-checkout` and disables hooks via `GIT_CONFIG_*`. |
| Credential redaction | HTTPS credentials stripped from all logs and from `remote_url` values in the index. |
| File permissions | Logs and index DB `0600`; config and data dirs `0700` (Unix). |
| Ownership checks | `~/.nostosrc`, `auth.toml`, and legacy watchlist rejected if not owned by the invoking user or world-writable. |
| Repository ownership | Repos not owned by the current user are skipped on Unix. |
| Symlink protection | The `logs/` directory is rejected if it is a symlink. |
| No shell injection | Every subprocess call uses list arguments; `shell=True` is never used. |
| Index hardening | SQLite `journal_mode=WAL`, `secure_delete=ON`, `foreign_keys=ON`; deleted rows overwritten on disk. |
| Probe fail-closed | Upstream probes only contact hosts listed in `auth.toml`; `--offline` hard-disables the network layer. |
| Per-repo quiet flag | `add --quiet-upstream` makes a repo ineligible for upstream probes; the probe layer never queries or logs these repos. |
| Token hygiene | Tokens sourced from env vars by default, sent as `Authorization: Bearer`, redacted from every log and error path. |

Report security issues privately via a [GitHub security advisory](https://github.com/prodrom3/nostos/security/advisories/new). See [SECURITY.md](SECURITY.md) for the full disclosure process.

---

## Compatibility

| OS | Python 3.10 | 3.11 | 3.12 | 3.13 |
| --- | :---: | :---: | :---: | :---: |
| Ubuntu (latest) | ✓ | ✓ | ✓ | ✓ |
| macOS (latest)  | ✓ | ✓ | ✓ | ✓ |
| Windows (latest) | ✓ | ✓ | ✓ | ✓ |

CI exercises every cell of this matrix on every push and pull request.

---

## Architecture

See [docs/architecture.md](docs/architecture.md) for the module layout, dependency graph, and end-to-end flows (`pull`, `add` -> `triage`, `import`).

---

## Versioning & support

nostos follows [Semantic Versioning](https://semver.org/) 2.0. Breaking changes appear only in new major versions and are called out in [CHANGELOG.md](CHANGELOG.md) and the corresponding GitHub release notes.

- **Stable:** CLI flags, exit codes, JSON output schema, bundle schema (reader accepts all versions in `READABLE_SCHEMAS`).
- **Internal:** the `core/` Python API is not a supported public API; import at your own risk.

Current version: see [`VERSION`](./VERSION) and `nostos --version`.

Response expectations (best-effort, non-commercial): see [MAINTAINERS.md](MAINTAINERS.md).

---

## Project documents

| File | Purpose |
| --- | --- |
| [CHANGELOG.md](CHANGELOG.md) | Per-release change log (mirrors GitHub releases). |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Dev setup, test / lint / mypy workflow, PR style. |
| [MAINTAINERS.md](MAINTAINERS.md) | Primary maintainer, escalation path, release authority. |
| [SECURITY.md](SECURITY.md) | Private disclosure process. |
| [LICENSE](LICENSE) | MIT. |

Deep-dive docs under [`docs/`](docs/):

| File | Topic |
| --- | --- |
| [docs/architecture.md](docs/architecture.md) | Module layout, dependency graph, run / intake / import flows. |
| [docs/upstream-probes.md](docs/upstream-probes.md) | Upstream probe auth, commands, opsec invariants. |
| [docs/bundle-schema.md](docs/bundle-schema.md) | Portable bundle format v2 and import resolution algorithm. |
| [docs/vault.md](docs/vault.md) | Obsidian vault bridge and narrow two-way sync. |

---

## License

Released under the [MIT License](./LICENSE). Authored by [prodrom3](https://github.com/prodrom3); maintained by the **radamic** organization.
