# gitpulse

[![CI](https://github.com/prodrom3/gitpulse/actions/workflows/ci.yml/badge.svg)](https://github.com/prodrom3/gitpulse/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](./LICENSE)
[![Version](https://img.shields.io/badge/version-2.1.0-orange.svg)](./VERSION)
[![Platforms](https://img.shields.io/badge/platforms-Linux%20%7C%20macOS%20%7C%20Windows-lightgrey.svg)](#compatibility)

> **gitpulse** is a zero-dependency Python CLI for batch-updating fleets of git repositories in parallel. It is built for developers and platform teams who maintain dozens - or hundreds - of cloned repositories and need a reliable, auditable, scriptable way to keep them in sync.

<p align="center">
  <img width="420" height="420" src="https://github.com/prodrom3/gitpulse/assets/7604466/91c585dc-ef92-48f1-8461-60b4fcbcfb6d" alt="gitpulse logo">
</p>

---

## Table of Contents

**Getting started**
- [Overview](#overview)
  - [Feature highlights](#feature-highlights)
  - [Use cases](#use-cases)
- [Quick Start](#quick-start)
- [Installation](#installation)
  - [Requirements](#requirements)
  - [Verifying the install](#verifying-the-install)

**Using gitpulse**
- [Usage](#usage)
  - [CLI reference](#cli-reference)
  - [Examples](#examples)
- [Configuration](#configuration)
  - [Environment variables](#environment-variables)
  - [Precedence](#precedence-highest-to-lowest)
- [Metadata index](#metadata-index)
  - [Layout](#layout)
  - [Security properties](#security-properties)
  - [Recommended intake workflow](#recommended-intake-workflow)
  - [Migration from the legacy watchlist](#migration-from-the-legacy-watchlist)
- [Output](#output)
  - [Human-readable](#human-readable)
  - [JSON](#json)

**Operations & security**
- [CI / Automation Integration](#ci--automation-integration)
  - [Exit codes](#exit-codes)
  - [GitHub Actions example](#github-actions-example)
  - [Cron example](#cron-example)
- [Logging](#logging)
- [Security](#security)
  - [Reporting vulnerabilities](#reporting-vulnerabilities)

**Reference & project**
- [Compatibility](#compatibility)
- [Architecture](#architecture)
  - [Module layout](#module-layout)
  - [Module dependencies](#module-dependencies)
  - [Run flow](#run-flow)
- [Versioning & Support](#versioning--support)
- [Contributing](#contributing)
- [License](#license)

---

## Overview

gitpulse is two tools in one:

1. A **batch-pull engine** that walks a directory tree (and/or the metadata index), discovers every git repository it can reach, and updates them concurrently. Predictable in batch: repositories with uncommitted changes, detached HEADs, or missing upstreams are reported and skipped, never overwritten. Hung operations are terminated on a configurable timeout, and every run leaves a timestamped log behind for audit.
2. A **metadata index** (SQLite) that records identity, provenance, tags, notes, and triage status for every repository in the fleet. Designed for teams that ingest many new GitHub projects each week and need to stay on top of what they have, where it came from, and what still matters.

### Feature Highlights

| Capability | Summary |
| --- | --- |
| **Metadata index** | SQLite at `$XDG_DATA_HOME/gitpulse/index.db` (0600, WAL, secure_delete). One row per repo plus tags, notes, provenance, triage status. |
| **Ingest workflow** | `gitpulse add <url>` clones (hardened) and records source, tags, note, status in one step. |
| **Triage queue** | `gitpulse triage` walks newly-added repos and classifies them interactively. |
| **Fleet search** | `gitpulse list --tag c2 --untouched-over 90` answers operational questions in milliseconds. |
| **Parallel updates** | Producer / consumer thread pool with configurable worker count. |
| **Safe-by-default** | Dirty trees, detached HEADs, and untracked branches are skipped, never merged into. |
| **Remote safe-clone** | `add <url>` uses `--no-checkout` + `GIT_CONFIG_*` to disable hooks (CVE-2024-32002 / 32004 / 32465 mitigated). |
| **Dry-run & fetch-only** | Preview discovery; check for incoming commits without merging. |
| **Rebase mode** | `--rebase` for teams enforcing linear history. |
| **SSH multiplexing** | ControlMaster reuses a single SSH session across repositories on the same host (Unix). |
| **Exclude patterns** | `--exclude 'archived-*' 'vendor-*'` - glob-based filtering. |
| **Timeout protection** | Kills hung git operations after N seconds. |
| **Config file** | Persistent defaults in `~/.gitpulserc`; CLI flags always override. |
| **JSON output** | Stable machine-readable schema on every list / show / pull command. |
| **Graceful interruption** | Ctrl+C cancels pending work and prints a partial summary. |
| **Hardened logging** | Timestamped, rotated logs (0600 perms); credentials stripped from output. |
| **Deterministic exit codes** | `0` on success, `1` on any failure - safe for CI and cron. |

### Use Cases

- Platform / DevEx teams keeping shared tool repositories fresh on developer workstations.
- Build boxes or mirror hosts that maintain read-only clones of upstream projects.
- Onboarding automation that bootstraps and refreshes a curated set of team repositories.
- Release engineers reconciling many long-lived checkouts before a coordinated change.

---

## Quick Start

```bash
git clone https://github.com/prodrom3/gitpulse.git
cd gitpulse

# Preview: what would be updated under the current directory?
python gitpulse.py --dry-run

# Update every repo under a given path, 16 workers, 60s timeout
python gitpulse.py ~/projects --workers 16 --timeout 60

# Ingest a new tool you just heard about, then triage this week's intake
python gitpulse.py add https://github.com/org/new-tool.git --tag recon
python gitpulse.py triage

# Answer "what c2 tools do I have that I haven't touched in 90 days?"
python gitpulse.py list --tag c2 --untouched-over 90
```

No packages, virtualenvs, or build steps required - only Python 3.10+ and `git`.

---

## Installation

### Requirements

| Component | Minimum | Recommended | Notes |
| --- | --- | --- | --- |
| Python | 3.10 | 3.12+ | No third-party runtime dependencies. |
| Git | 2.25 | **2.45.1+** | gitpulse warns at startup on versions affected by CVE-2024-32002 / 32004 / 32465. |
| OS | Linux / macOS / Windows | - | SSH multiplexing is Unix-only; all other features are cross-platform. |

### Option 1 - Run directly from source

```bash
git clone https://github.com/prodrom3/gitpulse.git
cd gitpulse
python gitpulse.py --help
```

### Option 2 - Install as a system command

```bash
git clone https://github.com/prodrom3/gitpulse.git
cd gitpulse
pip install .
gitpulse --help     # available on $PATH
```

### Option 3 - Install into an isolated environment

```bash
pipx install git+https://github.com/prodrom3/gitpulse.git
```

### Verifying the install

```bash
gitpulse --version        # prints the package version
gitpulse --help           # prints usage
```

---

## Usage

gitpulse is a verb-first CLI: `gitpulse <verb> [args]`. Invocations without a verb are treated as an implicit `pull` so every prior script / CI pipeline keeps working.

```
gitpulse [verb] [options]
```

| Verb | Purpose |
| --- | --- |
| `pull` (default) | Batch-update discovered repositories. |
| `add` | Ingest a local path or remote URL into the metadata index. |
| `list` | Filter and print the repo fleet. |
| `show` | Print full metadata (identity, tags, notes, git state) for one repo. |
| `tag` | Add or remove tags on a repo. |
| `note` | Append a timestamped note to a repo. |
| `triage` | Walk newly-added repos interactively and classify them. |
| `rm` | Remove a repo from the index (optionally `--purge` the clone). |

### CLI reference

Every verb supports `--help`. Common flags are summarised below.

#### `gitpulse pull` (default)

| Flag | Default | Description |
| --- | --- | --- |
| `path` | cwd | Root directory to scan for repositories. |
| `--dry-run` | off | List discovered repos without pulling. |
| `--fetch-only` | off | Fetch from remotes; do not merge or rebase. |
| `--rebase` | off | Use `git pull --rebase` instead of merge. |
| `--depth N` | 5 | Maximum directory-scan depth. |
| `--workers N` | 8 | Concurrent worker threads. |
| `--timeout N` | 120 | Seconds before a git operation is killed. |
| `--exclude PATTERN...` | - | Glob patterns to skip repos by directory name. |
| `--from-index` | off | Pull every repository registered in the metadata index. |
| `--json` | off | Emit machine-readable JSON output. |
| `-q`, `--quiet` | off | Suppress per-repo progress; print only the summary. |

Every touched repo is automatically registered in the metadata index and its `last_touched_at` is updated, so `list` / `show` / `triage` reflect reality without extra effort.

#### `gitpulse add PATH_OR_URL`

| Flag | Description |
| --- | --- |
| `--tag TAG` (repeatable / comma-separated) | Attach tag(s). |
| `--source TEXT` | Free-text provenance (e.g. `blog:orange.tw, 2026-04-12`). |
| `--note TEXT` | Initial free-text note. |
| `--status {new,reviewed,in-use,dropped,flagged}` | Initial triage status. |
| `--quiet-upstream` | Opsec flag: never query upstream metadata for this repo (Phase 2). |
| `--clone-dir DIR` | When the target is a URL, clone into this directory. |

#### `gitpulse list`

| Flag | Description |
| --- | --- |
| `--tag TAG` | Only repos carrying this tag. |
| `--status STATUS` | Only repos in this triage status. |
| `--untouched-over DAYS` | Only repos not pulled / shown in the last `DAYS` days. |
| `--json` | Emit a JSON document instead of a coloured table. |

#### `gitpulse show PATH_OR_ID`, `tag`, `note`, `triage`, `rm`

See `gitpulse <verb> --help` for the full surface of each. Notable: `tag` takes `+t` / `-t` / bare `t` tokens; `rm --purge --yes` deletes the clone on disk after explicit confirmation.

### Examples

```bash
# --- Batch pull (the original gitpulse) ---

# Update everything under the current directory
gitpulse

# Update repos under a specific path
gitpulse ~/projects

# Preview which repos would be updated
gitpulse --dry-run

# Check what's new across all repos without merging
gitpulse --fetch-only

# Rebase-style updates, 16 workers, 60s timeout
gitpulse --rebase --workers 16 --timeout 60

# Pull every repo registered in the metadata index
gitpulse pull --from-index

# JSON output for scripting
gitpulse --json | jq '.counts'

# --- Metadata workflow (ingest -> triage -> use) ---

# Ingest a new tool pointed out in a blog post
gitpulse add https://github.com/org/recon-tool.git \
  --tag recon,passive \
  --source "blog:orange.tw, 2026-04-12" \
  --note "mentioned for OOB DNS recon"

# List everything tagged c2 that you haven't opened in 90 days
gitpulse list --tag c2 --untouched-over 90

# Walk through this week's intake
gitpulse triage

# Look up one tool
gitpulse show org/recon-tool

# Quick tag adjustments
gitpulse tag ~/tools/recon-tool +passive -old

# Flag an upstream-compromised tool
gitpulse tag /tools/suspect +flagged
gitpulse note /tools/suspect "upstream owner changed 2026-04-09"

# Retire something
gitpulse rm ~/tools/obsolete-thing --purge --yes
```

---

## Configuration

gitpulse reads an optional INI file at `~/.gitpulserc`. CLI flags always take precedence over file values.

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
```

### Environment Variables

| Variable | Effect |
| --- | --- |
| `NO_COLOR` | When set to any non-empty value, disables ANSI color output. |

### Precedence (highest to lowest)

1. Command-line flags
2. `~/.gitpulserc`
3. Built-in defaults

---

## Metadata index

gitpulse keeps a **metadata index** - a single SQLite file at `$XDG_DATA_HOME/gitpulse/index.db` (default `~/.local/share/gitpulse/index.db`) - that records one row per repository plus tags, free-text notes, provenance, and triage status. Every verb in the CLI reads from and writes to this index; batch `pull` automatically registers every touched repo.

### Layout

| Column | Description |
| --- | --- |
| `path` | Absolute, `realpath`-normalised local path. Unique. |
| `remote_url` | `origin` remote (sanitised; HTTPS credentials stripped). |
| `source` | Provenance: `"blog:orange.tw, 2026-04-12"`, `"auto-discovered"`, `"legacy-watchlist"`, etc. |
| `added_at` / `last_touched_at` | ISO-8601 UTC timestamps. |
| `status` | `new`, `reviewed`, `in-use`, `dropped`, `flagged`. |
| `quiet` | Opsec flag: never query upstream metadata for this repo (Phase 2). |
| tags + notes | Many-to-many tags; append-only timestamped notes. |

### Security properties

The index reveals the operator's full toolchain. It is treated as an intelligence artifact.

- DB file is created `0600` on Unix; parent directory `0700`.
- PRAGMAs on every connection: `journal_mode=WAL`, `secure_delete=ON`, `foreign_keys=ON`. Deleted rows are overwritten on disk, not just marked free.
- The file lives **outside** any repository, under XDG. An accidental `git add .` cannot pick it up.
- For at-rest confidentiality, put `$XDG_DATA_HOME/gitpulse/` on an encrypted volume (LUKS / FileVault / BitLocker). gitpulse ships no built-in encryption; disk-layer protection is the right layer for this threat model.

### Recommended intake workflow

```mermaid
flowchart LR
    intel[Blog / tweet /<br/>colleague pointer]
    add[gitpulse add URL<br/>--tag recon,passive<br/>--source 'blog:...']
    triage[gitpulse triage<br/>classify, tag, note]
    list[gitpulse list<br/>--tag c2<br/>--untouched-over 90]
    pull[gitpulse pull<br/>--from-index]

    intel --> add --> triage --> list
    list --> pull
    pull -. updates last_touched_at .-> list
```

### Migration from the legacy watchlist

The old `~/.gitpulse_repos` file is imported on first run of any verb (`source='legacy-watchlist'`, `status='reviewed'`) and then renamed to `~/.gitpulse_repos.migrated`. The operation is idempotent. The legacy top-level flags `--add`, `--remove`, `--list`, and `--watchlist` keep working for one release and emit a one-line deprecation notice mapping them to their new verbs.

Supported URL schemes for `gitpulse add`: `https://`, `http://`, `git@host:user/repo`, `ssh://`, `git://`. Remote adds use the hardened safe-clone path (hooks disabled via `GIT_CONFIG_*`; `--no-checkout` followed by explicit checkout) to mitigate CVE-2024-32002 / 32004 / 32465.

---

## Output

### Human-readable

```
  [1/9] updated: /home/user/projects/repo-a
  [2/9] up-to-date: /home/user/projects/repo-d
  [3/9] skipped: /home/user/projects/repo-e
  ...

--- Summary ---

Updated (3):
  /home/user/projects/repo-a
  /home/user/projects/repo-b
  /home/user/projects/tools/repo-c

Already up-to-date (5):
  ...

Skipped (1):
  /home/user/projects/repo-e - dirty working tree (uncommitted changes)

Failed (0):

Total: 9 | Updated: 3 | Up-to-date: 5 | Skipped: 1 | Failed: 0
```

With `--fetch-only`, repositories with incoming commits are reported as **Fetched** and include the commit count.

### JSON

With `--json`, stdout is a single JSON document:

```json
{
  "total": 9,
  "counts": {
    "updated": 3,
    "fetched": 0,
    "up_to_date": 5,
    "skipped": 1,
    "failed": 0
  },
  "repositories": [
    {
      "path": "/home/user/projects/repo-a",
      "status": "updated",
      "reason": null,
      "branch": "main",
      "remote_url": "git@github.com:org/repo-a.git"
    }
  ]
}
```

Progress lines go to `stderr`, so `--json` output remains pipeable to `jq`, dashboards, or downstream tooling.

---

## CI / Automation Integration

### Exit Codes

| Code | Meaning |
| --- | --- |
| `0` | All discovered repositories updated or already up-to-date. |
| `1` | At least one repository failed to update. |

Skipped repositories (dirty, detached, no upstream) do **not** fail the run - they are surfaced in the summary for review.

### GitHub Actions example

```yaml
- name: Refresh vendored clones
  run: |
    python gitpulse.py ./vendor --quiet --json > /tmp/gitpulse.json
    jq '.counts' /tmp/gitpulse.json
```

### Cron example

```cron
*/30 * * * *  /usr/local/bin/gitpulse ~/projects --quiet --fetch-only
```

Combine with JSON output to feed dashboards (Prometheus text exporter, Grafana Loki, ELK, etc.).

---

## Logging

Each run writes a timestamped log file to `./logs/` (relative to the gitpulse install root), e.g. `2026-04-02_14-30-00.log`. Log files are automatically rotated - only the most recent 20 are kept (configurable via `max_log_files` in `~/.gitpulserc`). Files are created with owner-only (0600) permissions, and HTTPS credentials of the form `https://user:token@host/` are sanitized to `https://***@host/` before being written.

---

## Security

gitpulse treats git operations on untrusted working directories as an attack surface, and treats the metadata index as an intelligence artifact. Defense-in-depth applies at both layers:

| Control | Description |
| --- | --- |
| **Git version check** | Startup warning on git < 2.45.1 (CVE-2024-32002, CVE-2024-32004, CVE-2024-32465). |
| **Safe remote clone** | `gitpulse add <url>` clones with `--no-checkout` and disables hooks via `GIT_CONFIG_*` env vars, then checks out in a second step. |
| **Credential redaction** | HTTPS credentials stripped from all log and summary output, and from `remote_url` values written to the index. |
| **Strict file permissions** | Log files and the metadata index DB chmod-ed to `0600`; data and config directories to `0700` (Unix). |
| **Ownership checks** | `~/.gitpulserc` and legacy `~/.gitpulse_repos` rejected if not owned by the invoking user or world-writable (Unix). |
| **Repository ownership** | Repos not owned by the current user are skipped on Unix. |
| **Symlink protection** | The `logs/` directory is rejected if it is a symlink. |
| **No shell injection** | Every subprocess call uses list arguments; `shell=True` is never used. |
| **Index hardening** | SQLite PRAGMAs `journal_mode=WAL`, `secure_delete=ON`, `foreign_keys=ON` applied on every connection. Deleted rows are overwritten on disk. |
| **No network by default** | Phase 1 issues zero outbound connections. Upstream probes arriving in Phase 2 will be opt-in globally and opt-out per repo (`--quiet-upstream`). |

### At-rest confidentiality

The index reveals the operator's full toolchain. gitpulse deliberately ships **no** built-in DB encryption (adding a runtime dep would expand the supply-chain surface). Instead: place `$XDG_DATA_HOME/gitpulse/` on a disk-layer encrypted volume (LUKS on Linux, FileVault on macOS, BitLocker on Windows). That is the right layer for this threat model.

### Reporting Vulnerabilities

Please report security issues privately by opening a [GitHub security advisory](https://github.com/prodrom3/gitpulse/security/advisories/new) rather than filing a public issue. Public issue reports are acceptable only for **already-disclosed** CVEs or clearly non-sensitive hardening suggestions.

---

## Compatibility

| OS | Python 3.10 | 3.11 | 3.12 | 3.13 |
| --- | :---: | :---: | :---: | :---: |
| Ubuntu (latest) | ✓ | ✓ | ✓ | ✓ |
| macOS (latest)  | ✓ | ✓ | ✓ | ✓ |
| Windows (latest) | ✓ | ✓ | ✓ | ✓ |

CI exercises every cell of this matrix on every push and pull request. See the [CI workflow](.github/workflows/ci.yml) and the ["CI" badge](https://github.com/prodrom3/gitpulse/actions/workflows/ci.yml) at the top of this file for current build status.

---

## Architecture

### Module layout

```
gitpulse.py                 # thin entrypoint -> core.cli.run
core/
├── cli.py                  # argparse subparsers, legacy flag shim, default-verb injection
├── paths.py                # XDG-compliant paths ($XDG_CONFIG_HOME / $XDG_DATA_HOME)
├── index.py                # SQLite metadata index: schema, migrations, CRUD, PRAGMAs
├── config.py               # ~/.gitpulserc loader + safety checks
├── discovery.py            # depth-limited directory walk, exclude globs, ownership check
├── logging_config.py       # logs/ setup, rotation, symlink protection
├── models.py               # RepoResult, RepoStatus dataclasses
├── output.py               # human + JSON summaries, ANSI colour handling
├── updater.py              # per-repo pull / fetch, git version guard, SSH multiplexing
├── watchlist.py            # hardened clone (used by `add`) + legacy watchlist readers
└── commands/
    ├── pull.py             # verb: pull (default)
    ├── add.py              # verb: add
    ├── list_cmd.py         # verb: list
    ├── show.py             # verb: show
    ├── tag.py              # verb: tag
    ├── note.py             # verb: note
    ├── triage.py           # verb: triage
    ├── rm.py               # verb: rm
    └── _common.py          # shared helpers (error reporter, watchlist migration)
```

### Module dependencies

```mermaid
flowchart LR
    entry[gitpulse.py<br/>entrypoint]
    cli[core.cli<br/>subparsers + shim]
    paths[core.paths<br/>XDG]
    idx[core.index<br/>SQLite]
    cmds[core.commands.*<br/>one module per verb]
    config[core.config]
    logcfg[core.logging_config]
    discovery[core.discovery]
    updater[core.updater]
    watchlist[core.watchlist<br/>safe-clone]
    output[core.output]
    models[core.models]

    entry --> cli --> cmds
    cmds --> idx
    cmds --> config
    cmds --> logcfg
    cmds --> discovery
    cmds --> updater
    cmds --> watchlist
    cmds --> output
    idx --> paths
    updater --> models
    output --> models
    watchlist -. invokes hardened clone for `add` .-> updater
```

### Run flow: `gitpulse pull`

```mermaid
flowchart TD
    start([gitpulse invoked]) --> rewrite[Rewrite legacy flags<br/>inject default verb]
    rewrite --> disp[Dispatch to<br/>core.commands.pull.run]
    disp --> mig[First-run watchlist<br/>migration into index]
    mig --> rc[Load ~/.gitpulserc]
    rc --> src{Source of repos}
    src -->|--from-index| idx[Read metadata index]
    src -->|directory| scan[Walk directory tree]
    src -->|both| idx
    src -->|both| scan
    idx --> dedup[Deduplicate]
    scan --> dedup
    dedup --> pool[ThreadPoolExecutor<br/>N workers]
    pool --> state[Per-repo: check state<br/>detached / dirty / no upstream?]
    state -->|not pullable| skip[Skip with reason]
    state -->|pullable| fetch[git fetch]
    fetch --> mode{fetch-only?}
    mode -->|yes| report[Record behind count]
    mode -->|no| pull[git pull / --rebase]
    skip --> collect[Collect result]
    report --> collect
    pull --> collect
    collect --> register[Auto-register in index<br/>+ update last_touched_at]
    register --> summary[Print summary<br/>human or JSON]
    summary --> done([Exit 0 / 1])
```

### Intake flow: `gitpulse add` -> `triage`

```mermaid
flowchart LR
    url[URL or path<br/>from intel feed]
    add[gitpulse add<br/>hardened clone]
    index[(metadata index)]
    triage[gitpulse triage<br/>interactive loop]
    list[gitpulse list<br/>filters]
    show[gitpulse show<br/>per-repo view]

    url --> add
    add -->|status=new| index
    index --> triage
    triage -->|status=in-use / flagged / dropped<br/>tags + notes| index
    index --> list
    index --> show
```

---

## Versioning & Support

gitpulse follows [Semantic Versioning](https://semver.org/) 2.0. Breaking changes are introduced only in a new **major** version and are called out in the release notes.

- **Stable:** CLI flags and exit codes.
- **Stable:** JSON output schema.
- **Internal:** the `core/` Python API is not a supported public API - import at your own risk.

Current version: see [`VERSION`](./VERSION) and `gitpulse --version`.

---

## Contributing

Contributions are welcome. Before opening a pull request:

1. Run the local gate:
   ```bash
   python -m unittest discover -s tests -v
   python -m mypy core/ gitpulse.py
   python -m ruff check core/ gitpulse.py tests/
   ```
2. Add or update tests for behavior changes.
3. Keep the change focused - one logical unit per PR.

For larger features, please open an issue first to align on scope.

---

## License

Released under the [MIT License](./LICENSE).

---

Authored by [prodrom3](https://github.com/prodrom3). Maintained by the **radamic** organization.
