# gitpulse

[![CI](https://github.com/prodrom3/gitpulse/actions/workflows/ci.yml/badge.svg)](https://github.com/prodrom3/gitpulse/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](./LICENSE)
[![Version](https://img.shields.io/badge/version-2.0.0-orange.svg)](./VERSION)
[![Platforms](https://img.shields.io/badge/platforms-Linux%20%7C%20macOS%20%7C%20Windows-lightgrey.svg)](#compatibility)

> **gitpulse** is a zero-dependency Python CLI for batch-updating fleets of git repositories in parallel. It is built for developers and platform teams who maintain dozens - or hundreds - of cloned repositories and need a reliable, auditable, scriptable way to keep them in sync.

<p align="center">
  <img width="420" height="420" src="https://github.com/prodrom3/gitpulse/assets/7604466/91c585dc-ef92-48f1-8461-60b4fcbcfb6d" alt="gitpulse logo">
</p>

---

## Table of Contents

- [Overview](#overview)
- [Quick Start](#quick-start)
- [Installation](#installation)
- [Usage](#usage)
- [Configuration](#configuration)
- [Watchlist](#watchlist)
- [Output](#output)
- [CI / Automation Integration](#ci--automation-integration)
- [Logging](#logging)
- [Security](#security)
- [Compatibility](#compatibility)
- [Architecture](#architecture)
- [Versioning & Support](#versioning--support)
- [Contributing](#contributing)
- [License](#license)

---

## Overview

gitpulse walks a directory tree (and/or a persistent watchlist), discovers every git repository it can reach, and updates them concurrently. It is designed to be predictable in batch: repositories with uncommitted changes, detached HEADs, or missing upstreams are reported and skipped - never overwritten. Hung operations are terminated on a configurable timeout, and every run leaves a timestamped log behind for audit.

### Feature Highlights

| Capability | Summary |
| --- | --- |
| **Parallel updates** | Producer/consumer thread pool with configurable worker count. |
| **Safe-by-default** | Dirty trees, detached HEADs, and untracked branches are skipped, never merged into. |
| **Watchlist** | Track repositories scattered across filesystems in `~/.gitpulse_repos`. |
| **Remote clone** | `--add <url>` clones HTTPS/SSH remotes with hooks disabled (CVE-2024-32002/32004/32465 mitigated). |
| **Dry-run & fetch-only** | Preview discovery; check for incoming commits without merging. |
| **Rebase mode** | `--rebase` for teams enforcing linear history. |
| **SSH multiplexing** | ControlMaster reuses a single SSH session across repositories on the same host (Unix). |
| **Exclude patterns** | `--exclude 'archived-*' 'vendor-*'` - glob-based filtering. |
| **Timeout protection** | Kills hung git operations after N seconds. |
| **Config file** | Persistent defaults in `~/.gitpulserc`; CLI flags always override. |
| **JSON output** | Machine-readable summary for dashboards, `jq`, or CI pipelines. |
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

```
gitpulse [path] [options]
```

### CLI Reference

| Flag | Argument | Default | Description |
| --- | --- | --- | --- |
| `path` | directory | cwd | Root directory to scan for repositories. |
| `-v`, `--version` | - | - | Print version and exit. |
| `--dry-run` | - | off | List discovered repos without pulling. |
| `--fetch-only` | - | off | Fetch from remotes; do not merge or rebase. |
| `--rebase` | - | off | Use `git pull --rebase` instead of merge. |
| `--depth` | `N` | 5 | Maximum directory-scan depth. |
| `--workers` | `N` | 8 | Concurrent worker threads. |
| `--timeout` | `N` | 120 | Seconds before a git operation is killed. |
| `--exclude` | `PATTERN...` | - | Glob patterns to skip repos by directory name. |
| `--json` | - | off | Emit machine-readable JSON output. |
| `-q`, `--quiet` | - | off | Suppress per-repo progress; print only the summary. |
| `--add` | `PATH_OR_URL` | - | Add a local path or remote URL to the watchlist. |
| `--remove` | `PATH` | - | Remove an entry from the watchlist. |
| `--list` | - | - | Print the watchlist. |
| `--watchlist` | - | off | Pull only watchlist repos (combine with `path` to also scan a directory). |
| `--clone-dir` | `DIR` | cwd | Directory to clone remote repos into (with `--add <url>`). |

### Examples

```bash
# Update everything under the current directory
python gitpulse.py

# Update repos under a specific path
python gitpulse.py ~/projects

# Preview which repos would be updated
python gitpulse.py --dry-run

# Check what's new across all repos without merging
python gitpulse.py --fetch-only

# Rebase-style updates, 16 workers, 60s timeout
python gitpulse.py --rebase --workers 16 --timeout 60

# Restrict directory traversal
python gitpulse.py --depth 2

# Skip archived and temporary repos
python gitpulse.py --exclude 'archived-*' 'temp-*'

# JSON output for scripting
python gitpulse.py --json | jq '.counts'

# Quiet mode for CI - only summary, no progress
python gitpulse.py --quiet

# Watchlist workflows
python gitpulse.py --add ~/projects/important-api
python gitpulse.py --add https://github.com/org/repo.git --clone-dir ~/repos
python gitpulse.py --list
python gitpulse.py --watchlist
python gitpulse.py --remove ~/projects/deprecated
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

## Watchlist

For repositories scattered across multiple directories, use the **watchlist** (`~/.gitpulse_repos`) instead of - or alongside - directory scanning. The file is a newline-delimited list of absolute paths; blank lines and lines beginning with `#` are ignored.

```bash
# Add local repositories
python gitpulse.py --add ~/projects/important-api
python gitpulse.py --add ~/work/frontend

# Add a remote by URL (clones first, then records the local path)
python gitpulse.py --add https://github.com/org/repo.git
python gitpulse.py --add git@gitlab.com:team/project.git

# Clone into a specific directory
python gitpulse.py --add https://github.com/org/repo.git --clone-dir ~/repos

# Inspect
python gitpulse.py --list

# Pull everything in the watchlist
python gitpulse.py --watchlist

# Combine: watchlist + ad-hoc directory scan
python gitpulse.py --watchlist ~/other-repos

# Remove
python gitpulse.py --remove ~/projects/deprecated
```

Supported URL schemes: `https://`, `http://`, `git@host:user/repo`, `ssh://`, `git://`.
Stale entries (deleted or moved repos) are reported as a warning and do not block the rest of the run. The watchlist file is subject to the same ownership and permission checks as the config file on Unix.

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

gitpulse treats git operations on untrusted working directories as an attack surface and applies defense-in-depth:

| Control | Description |
| --- | --- |
| **Git version check** | Startup warning on git < 2.45.1 (CVE-2024-32002, CVE-2024-32004, CVE-2024-32465). |
| **Safe remote clone** | `--add <url>` clones with `--no-checkout` and disables hooks via `GIT_CONFIG_*` env vars, then checks out in a second step. |
| **Credential redaction** | HTTPS credentials stripped from all log and summary output. |
| **Strict file permissions** | Log files chmod-ed to 0600 (Unix). |
| **Ownership checks** | `~/.gitpulserc` and `~/.gitpulse_repos` rejected if not owned by the invoking user or world-writable (Unix). |
| **Repository ownership** | Repos not owned by the current user are skipped on Unix. |
| **Symlink protection** | The `logs/` directory is rejected if it is a symlink. |
| **No shell injection** | Every subprocess call uses list arguments; `shell=True` is never used. |

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
gitpulse.py                 # thin entrypoint: signals, thread pool, orchestration
core/
├── cli.py                  # argparse, version resolution
├── config.py               # ~/.gitpulserc loader + safety checks
├── discovery.py            # depth-limited directory walk, exclude globs, ownership check
├── logging_config.py       # logs/ setup, rotation, symlink protection
├── models.py               # RepoResult, RepoStatus dataclasses
├── output.py               # human + JSON summaries, ANSI color handling
├── updater.py              # per-repo pull/fetch, git version guard, SSH multiplexing
└── watchlist.py            # ~/.gitpulse_repos add / remove / list / safe-clone
```

### Module dependencies

```mermaid
flowchart LR
    entry[gitpulse.py<br/>entrypoint]
    cli[core.cli]
    config[core.config]
    logcfg[core.logging_config]
    discovery[core.discovery]
    watchlist[core.watchlist]
    updater[core.updater]
    output[core.output]
    models[core.models]

    entry --> cli
    entry --> config
    entry --> logcfg
    entry --> discovery
    entry --> watchlist
    entry --> updater
    entry --> output
    cli --> config
    discovery --> config
    updater --> models
    output --> models
    watchlist -. clone .-> updater
```

### Run flow

```mermaid
flowchart TD
    start([gitpulse invoked]) --> parse[Parse CLI args]
    parse --> rc[Load ~/.gitpulserc]
    rc --> src{Source of repos}
    src -->|watchlist| wl[Read ~/.gitpulse_repos]
    src -->|directory| scan[Walk directory tree]
    src -->|both| wl
    src -->|both| scan
    wl --> dedup[Deduplicate]
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
    collect --> summary[Print summary<br/>human or JSON]
    summary --> done([Exit 0 / 1])
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
