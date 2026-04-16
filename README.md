# nostos

[![CI](https://github.com/prodrom3/nostos/actions/workflows/ci.yml/badge.svg)](https://github.com/prodrom3/nostos/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](./LICENSE)
[![Version](https://img.shields.io/badge/version-1.1.0-orange.svg)](./VERSION)
[![PyPI](https://img.shields.io/pypi/v/nostos.svg)](https://pypi.org/project/nostos/)
[![Platforms](https://img.shields.io/badge/platforms-Linux%20%7C%20macOS%20%7C%20Windows-lightgrey.svg)](#compatibility)

> **nostos** is a zero-dependency Python CLI for batch-updating fleets of git repositories in parallel. It is built for developers and platform teams who maintain dozens - or hundreds - of cloned repositories and need a reliable, auditable, scriptable way to keep them in sync.

<p align="center">
  <img width="420" height="420" src="https://github.com/prodrom3/nostos/assets/7604466/91c585dc-ef92-48f1-8461-60b4fcbcfb6d" alt="nostos logo">
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

**Using nostos**
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
- [Upstream probes](#upstream-probes)
  - [Supported providers](#supported-providers)
  - [Auth config: ~/.config/nostos/auth.toml](#auth-config-confignostosauthtoml)
  - [Commands](#commands)
  - [Probe flow](#probe-flow)
  - [Opsec invariants](#opsec-invariants)
- [Weekly digest](#weekly-digest)
- [Obsidian vault export](#obsidian-vault-export)
  - [Configure the vault path](#configure-the-vault-path)
  - [What gets written](#what-gets-written)
  - [Narrow two-way sync (as of 2.5.0)](#narrow-two-way-sync-as-of-250)
- [Portable export and import](#portable-export-and-import)
  - [Export](#export)
  - [Import](#import)
  - [Bundle schema (stable)](#bundle-schema-stable)
- [Self-update](#self-update)
  - [Install-method detection](#install-method-detection)
  - [Commands](#commands-1)
  - [Behaviour per install method](#behaviour-per-install-method)
  - [Opsec properties](#opsec-properties-1)
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

nostos is three tools in one:

1. A **batch-pull engine** that walks a directory tree (and/or the metadata index), discovers every git repository it can reach, and updates them concurrently. Predictable in batch: repositories with uncommitted changes, detached HEADs, or missing upstreams are reported and skipped, never overwritten. Hung operations are terminated on a configurable timeout, and every run leaves a timestamped log behind for audit.
2. A **metadata index** (SQLite) that records identity, provenance, tags, notes, and triage status for every repository in the fleet. Designed for teams that ingest many new GitHub projects each week and need to stay on top of what they have, where it came from, and what still matters.
3. An **upstream probe layer** that queries GitHub, GitLab, and Gitea (hosted or self-hosted) for health signals - archived status, last push, latest release, license, stars - with **strict fail-closed opsec**: only configured hosts are ever contacted, per-repo `quiet` flags suppress any network call about that repo, and `--offline` hard-disables the network layer.

### Feature Highlights

| Capability | Summary |
| --- | --- |
| **Metadata index** | SQLite at `$XDG_DATA_HOME/nostos/index.db` (0600, WAL, secure_delete). One row per repo plus tags, notes, provenance, triage status. |
| **Upstream probes** | `nostos refresh` fetches archived / stars / last push / latest release for GitHub, GitLab, Gitea (hosted + self-hosted). Opsec-gated by `~/.config/nostos/auth.toml`; unconfigured hosts are never contacted. |
| **Supply-chain early warning** | `nostos list --upstream-archived` surfaces tools whose upstream has been archived (ownership change, takedown). |
| **Staleness view** | `nostos list --upstream-dormant 365` lists upstreams with no push in a year; `--upstream-stale 30` finds entries whose local cache is behind. |
| **Ingest workflow** | `nostos add <url>` clones (hardened) and records source, tags, note, status in one step. |
| **Triage queue** | `nostos triage` walks newly-added repos and classifies them interactively. |
| **Fleet search** | `nostos list --tag c2 --untouched-over 90` answers operational questions in milliseconds. |
| **Parallel updates** | Producer / consumer thread pool with configurable worker count. |
| **Safe-by-default** | Dirty trees, detached HEADs, and untracked branches are skipped, never merged into. |
| **Remote safe-clone** | `add <url>` uses `--no-checkout` + `GIT_CONFIG_*` to disable hooks (CVE-2024-32002 / 32004 / 32465 mitigated). |
| **Dry-run & fetch-only** | Preview discovery; check for incoming commits without merging. |
| **Rebase mode** | `--rebase` for teams enforcing linear history. |
| **SSH multiplexing** | ControlMaster reuses a single SSH session across repositories on the same host (Unix). |
| **Exclude patterns** | `--exclude 'archived-*' 'vendor-*'` - glob-based filtering. |
| **Timeout protection** | Kills hung git operations after N seconds. |
| **Config file** | Persistent defaults in `~/.nostosrc`; CLI flags always override. |
| **JSON output** | Stable machine-readable schema on every list / show / pull / refresh command. |
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
git clone https://github.com/prodrom3/nostos.git
cd nostos

# Preview: what would be updated under the current directory?
python nostos.py --dry-run

# Update every repo under a given path, 16 workers, 60s timeout
python nostos.py ~/projects --workers 16 --timeout 60

# Ingest a new tool you just heard about, then triage this week's intake
python nostos.py add https://github.com/org/new-tool.git --tag recon
python nostos.py triage

# Answer "what c2 tools do I have that I haven't touched in 90 days?"
python nostos.py list --tag c2 --untouched-over 90
```

No packages, virtualenvs, or build steps required - only Python 3.10+ and `git`.

---

## Installation

### Requirements

| Component | Minimum | Recommended | Notes |
| --- | --- | --- | --- |
| Python | 3.10 | 3.12+ | No third-party runtime dependencies. |
| Git | 2.25 | **2.45.1+** | nostos warns at startup on versions affected by CVE-2024-32002 / 32004 / 32465. |
| OS | Linux / macOS / Windows | - | SSH multiplexing is Unix-only; all other features are cross-platform. |

### Option 1 - Run directly from source

```bash
git clone https://github.com/prodrom3/nostos.git
cd nostos
python nostos.py --help
```

### Option 2 - Install as a system command

```bash
git clone https://github.com/prodrom3/nostos.git
cd nostos
pip install .
nostos --help     # available on $PATH
```

### Option 3 - Install into an isolated environment

```bash
pipx install git+https://github.com/prodrom3/nostos.git
```

### Verifying the install

```bash
nostos --version        # prints the package version
nostos --help           # prints usage
```

### Shell tab-completion (optional)

nostos supports tab-completion for all verbs and flags via [argcomplete](https://kislyuk.github.io/argcomplete/). This is entirely opt-in; nostos has no hard dependency on it.

**1. Install argcomplete into the same environment as nostos:**

```bash
# pipx install
pipx inject nostos argcomplete

# venv install
pip install 'nostos[completion]'

# system-wide via your package manager (examples)
sudo apt install python3-argcomplete     # Debian / Ubuntu / Kali
brew install argcomplete                 # macOS (Homebrew)
```

**2. Register the completion script for your shell:**

**bash** (Linux, macOS, Git Bash, WSL):

```bash
# one-time, recommended: enable global argcomplete
activate-global-python-argcomplete --user

# or per-command in ~/.bashrc
eval "$(register-python-argcomplete nostos)"
```

**zsh** (Kali default, macOS default since Catalina):

```bash
# Add to ~/.zshrc once
autoload -U bashcompinit && bashcompinit
eval "$(register-python-argcomplete nostos)"
```

Then open a new shell (or `source ~/.zshrc` / `source ~/.bashrc`) and try:

```bash
nostos <TAB><TAB>          # lists all verbs
nostos pull --<TAB><TAB>   # lists all pull flags
```

**fish:**

```fish
register-python-argcomplete --shell fish nostos | source
```

Add the same line to `~/.config/fish/config.fish` to persist.

**Windows PowerShell / cmd:** argcomplete does not officially support native Windows shells. Use Git Bash, WSL, or Windows Terminal + WSL for tab-completion. Everything else in nostos works fine on native Windows.

If tab-completion isn't firing after setup, verify argcomplete can see the marker:

```bash
python -c "import argcomplete, sys; print(argcomplete.__version__)"
grep -l PYTHON_ARGCOMPLETE_OK $(which nostos)
```

---

## Usage

nostos is a verb-first CLI: `nostos <verb> [args]`. Invocations without a verb are treated as an implicit `pull` so every prior script / CI pipeline keeps working.

```
nostos [verb] [options]
```

| Verb | Purpose |
| --- | --- |
| `pull` (default) | Batch-update discovered repositories. |
| `add` | Ingest a local path or remote URL into the metadata index. |
| `list` | Filter and print the repo fleet. |
| `show` | Print full metadata (identity, tags, notes, git state, upstream) for one repo. |
| `tag` | Add or remove tags on a repo. |
| `note` | Append a timestamped note to a repo. |
| `triage` | Walk newly-added repos interactively and classify them. |
| `refresh` | Fetch upstream metadata (stars, archived, last push, release). Opsec-gated. |
| `digest` | Weekly changeset report over the local index (zero network). |
| `vault export` | Render the index into an Obsidian vault (DB -> markdown). |
| `vault sync` | Read operator edits to `status` / `tags` in the vault back into the DB, then regenerate every file. |
| `export` | Write a schema-versioned JSON bundle of the index (portable; supports redaction). |
| `import` | Load a bundle into the index (merge by default; `--replace` wipes; `--remap` rewrites paths). |
| `update` | Check for / apply a nostos self-update. Auto-detects source clone / pipx / pip. |
| `doctor` | Index health check: stale paths, missing remotes, orphan vault files. `--fix` auto-remediates. |
| `attack list` | Print the built-in MITRE ATT&CK technique lookup table. |
| `attack tag` | Tag a repo with ATT&CK technique IDs (shorthand for `+attack:TNNNN`). |
| `rm` | Remove a repo from the index (optionally `--purge` the clone). |

### CLI reference

Every verb supports `--help`. Common flags are summarised below.

#### `nostos pull` (default)

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

#### `nostos add PATH_OR_URL`

| Flag | Description |
| --- | --- |
| `--tag TAG` (repeatable / comma-separated) | Attach tag(s). |
| `--source TEXT` | Free-text provenance (e.g. `blog:orange.tw, 2026-04-12`). |
| `--note TEXT` | Initial free-text note. |
| `--status {new,reviewed,in-use,dropped,flagged}` | Initial triage status. |
| `--quiet-upstream` | Opsec flag: never query upstream metadata for this repo (Phase 2). |
| `--clone-dir DIR` | When the target is a URL, clone into this directory. |

#### `nostos list`

| Flag | Description |
| --- | --- |
| `--tag TAG` | Only repos carrying this tag. |
| `--status STATUS` | Only repos in this triage status. |
| `--untouched-over DAYS` | Only repos not pulled / shown in the last `DAYS` days. |
| `--json` | Emit a JSON document instead of a coloured table. |

#### `nostos show PATH_OR_ID`, `tag`, `note`, `triage`, `rm`

See `nostos <verb> --help` for the full surface of each. Notable: `tag` takes `+t` / `-t` / bare `t` tokens; `rm --purge --yes` deletes the clone on disk after explicit confirmation.

### Examples

```bash
# --- Batch pull (the original nostos) ---

# Update everything under the current directory
nostos

# Update repos under a specific path
nostos ~/projects

# Preview which repos would be updated
nostos --dry-run

# Check what's new across all repos without merging
nostos --fetch-only

# Rebase-style updates, 16 workers, 60s timeout
nostos --rebase --workers 16 --timeout 60

# Pull every repo registered in the metadata index
nostos pull --from-index

# JSON output for scripting
nostos --json | jq '.counts'

# --- Metadata workflow (ingest -> triage -> use) ---

# Ingest a new tool pointed out in a blog post
nostos add https://github.com/org/recon-tool.git \
  --tag recon,passive \
  --source "blog:orange.tw, 2026-04-12" \
  --note "mentioned for OOB DNS recon"

# List everything tagged c2 that you haven't opened in 90 days
nostos list --tag c2 --untouched-over 90

# Walk through this week's intake
nostos triage

# Look up one tool
nostos show org/recon-tool

# Quick tag adjustments
nostos tag ~/tools/recon-tool +passive -old

# Flag an upstream-compromised tool
nostos tag /tools/suspect +flagged
nostos note /tools/suspect "upstream owner changed 2026-04-09"

# Retire something
nostos rm ~/tools/obsolete-thing --purge --yes
```

---

## Configuration

nostos reads an optional INI file at `~/.nostosrc`. CLI flags always take precedence over file values.

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
2. `~/.nostosrc`
3. Built-in defaults

---

## Metadata index

nostos keeps a **metadata index** - a single SQLite file at `$XDG_DATA_HOME/nostos/index.db` (default `~/.local/share/nostos/index.db`) - that records one row per repository plus tags, free-text notes, provenance, and triage status. Every verb in the CLI reads from and writes to this index; batch `pull` automatically registers every touched repo.

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
- For at-rest confidentiality, put `$XDG_DATA_HOME/nostos/` on an encrypted volume (LUKS / FileVault / BitLocker). nostos ships no built-in encryption; disk-layer protection is the right layer for this threat model.

### Recommended intake workflow

```mermaid
flowchart LR
    intel[Blog / tweet /<br/>colleague pointer]
    add[nostos add URL<br/>--tag recon,passive<br/>--source 'blog:...']
    triage[nostos triage<br/>classify, tag, note]
    list[nostos list<br/>--tag c2<br/>--untouched-over 90]
    pull[nostos pull<br/>--from-index]

    intel --> add --> triage --> list
    list --> pull
    pull -. updates last_touched_at .-> list
```

### Migration from the legacy watchlist

The old `~/.nostos_repos` file is imported on first run of any verb (`source='legacy-watchlist'`, `status='reviewed'`) and then renamed to `~/.nostos_repos.migrated`. The operation is idempotent. The legacy top-level flags `--add`, `--remove`, `--list`, and `--watchlist` keep working for one release and emit a one-line deprecation notice mapping them to their new verbs.

Supported URL schemes for `nostos add`: `https://`, `http://`, `git@host:user/repo`, `ssh://`, `git://`. Remote adds use the hardened safe-clone path (hooks disabled via `GIT_CONFIG_*`; `--no-checkout` followed by explicit checkout) to mitigate CVE-2024-32002 / 32004 / 32465.

---

## Upstream probes

`nostos refresh` populates a cached snapshot of each repo's **upstream** health into the index: stars, forks, open issues, archived status, default branch, license, last push, latest release. The snapshot lives next to the repo row in the `upstream_meta` table and has a configurable TTL (default 7 days).

Everything here is **opt-in and fail-closed by default**. A fresh install with no `auth.toml` issues zero outbound calls; `refresh` simply reports that every repo was skipped because its host is not authorised. That is the correct behaviour - nostos will never enumerate your full toolchain to a third party it has not been explicitly told about.

### Supported providers

| Provider | Hosted | Self-hosted | API base |
| --- | --- | --- | --- |
| GitHub | `github.com` | GHE (Enterprise) | `/api/v3` on GHE |
| GitLab | `gitlab.com` | any host | `/api/v4` |
| Gitea | - | any host | `/api/v1` |

For `github.com` and `gitlab.com` the provider is inferred. For every other host you must set `provider = "github"` / `"gitlab"` / `"gitea"` explicitly in `auth.toml`; nostos never guesses.

### Auth config: `~/.config/nostos/auth.toml`

Created automatically under `0700` inside `$XDG_CONFIG_HOME/nostos/`. The file itself **must** be `0600` and owned by the invoking user; otherwise nostos refuses to read it.

```toml
[hosts."github.com"]
token_env = "GITHUB_TOKEN"          # preferred: source from env var

[hosts."gitlab.com"]
token_env = "GITLAB_TOKEN"

[hosts."git.internal.corp"]
provider  = "gitlab"                # required for non-standard hosts
token_env = "CORP_GITLAB_TOKEN"

[hosts."gitea.lab.local"]
provider  = "gitea"
token_env = "HOMELAB_GITEA_TOKEN"

[defaults]
allow_unknown = false               # keep fail-closed; true lets unconfigured
                                    # hosts be probed unauthenticated
```

- `token_env` is always preferred over inline `token`. A token rotates with the environment and never ends up in the file.
- Unknown hosts are skipped unconditionally unless `defaults.allow_unknown = true`.
- Tokens are sent as `Authorization: Bearer <token>` and are **never** logged or included in error messages (verified by test).

### Commands

```bash
# Default: refresh stale (>7d) cache entries for configured hosts only
nostos refresh

# Refresh every registered repo regardless of cache age
nostos refresh --all

# Refresh one repo
nostos refresh --repo ~/tools/recon-kit

# Change the TTL window
nostos refresh --since 30

# Hard kill switch - zero network traffic, prints what would be refreshed
nostos refresh --offline

# JSON summary for scripting
nostos refresh --json
```

### Probe flow

```mermaid
flowchart TD
    start([nostos refresh]) --> auth[Load auth.toml<br/>enforce 0600 perms]
    auth --> pick{Target set}
    pick -->|--repo R| one[Single repo]
    pick -->|--all| everyone[All repos]
    pick -->|default| stale[Stale only<br/>cache older than --since]
    one --> loop
    everyone --> loop
    stale --> loop
    loop[For each target] --> q{quiet=1?}
    q -->|yes| skip1[Skip silently<br/>no network, no log]
    q -->|no| parse[Parse remote URL<br/>-> host / owner / name]
    parse --> host{host in auth.toml?}
    host -->|no| skip2[Skip silently<br/>fail-closed]
    host -->|yes| offline{--offline?}
    offline -->|yes| skip3[Log 'would refresh'<br/>no network]
    offline -->|no| probe[Provider API call<br/>GitHub / GitLab / Gitea]
    probe --> ok{success?}
    ok -->|yes| write[Upsert upstream_meta]
    ok -->|no| err[Record fetch_error<br/>in upstream_meta]
    skip1 --> next[next target]
    skip2 --> next
    skip3 --> next
    write --> next
    err --> next
    next --> loop
```

### Operational questions you can answer now

```bash
# What did upstream archive recently?
nostos refresh --all --json | jq -r '.errors[] | .path'   # errors first
nostos list --upstream-archived

# Which of my tools upstream has been dormant for more than a year?
nostos list --upstream-dormant 365

# What's in my index but has never been probed?
nostos list --upstream-stale 0

# Check one tool's full state (local + upstream) at a glance
nostos show org/name
```

### Opsec invariants

Stated precisely because these are load-bearing for red-team use:

1. A host that does **not** appear in `auth.toml` is never contacted (unless `allow_unknown = true`).
2. A repo with `quiet = 1` is never probed, never logged at info level.
3. `--offline` produces zero outbound traffic and never fails open if the flag is misread.
4. Tokens live in environment variables by default; when inline, they are still excluded from every log path (`ProbeError.args` and `__str__` both verified by test).
5. The auth file is rejected if its permissions are not `0600` or if it is not owned by the invoking user on Unix.
6. No aggregate metrics, telemetry, or third-party analytics. The only network traffic leaves the machine towards the providers you have explicitly authenticated.

---

## Weekly digest

`nostos digest` produces a read-only, zero-network changeset report over the metadata index. Run it on Monday mornings to see what moved in your fleet, what needs attention, and what supply-chain flags are still outstanding.

```bash
nostos digest                     # 7-day window, 90d stale, 365d dormant
nostos digest --since 14          # widen the window
nostos digest --json | jq .       # machine-readable for dashboards
nostos digest --json | jq '.counts'
```

The report always includes these sections (fixed-shape JSON with `schema: 1`):

| Section | What it contains |
| --- | --- |
| `counts` | Total repo count and per-status breakdown. |
| `added` | Repos ingested within `--since DAYS`. Path, tags, source. |
| `refreshed` | Repos whose upstream cache was refreshed within the window. Path, archived flag, last push, latest release. |
| `archived` | All repos currently flagged as archived upstream. Always surfaced until the operator acts on it (supply-chain signal). |
| `flagged` | All repos with `status = 'flagged'`. |
| `stale_local` | Repos with `last_touched_at` older than `--stale DAYS` (or `NULL`). |
| `dormant` | Repos whose upstream had no push in `--dormant DAYS`. |

Pipe the JSON output into a Slack webhook, Grafana Loki, a ticketing system, or a cron-triggered Monday email - the schema is stable.

---

## Obsidian vault export

`nostos vault export` writes one markdown file per repo into an Obsidian vault, with YAML frontmatter that Obsidian renders as native Properties (tags become clickable, upstream fields become dataview-queryable). This turns your fleet into a browsable, searchable knowledge base without running a separate database.

### Configure the vault path

Add the vault to `~/.nostosrc`:

```ini
[vault]
path   = /home/user/obsidian/red-team
subdir = repos
```

Or override per-run: `nostos vault export --path ~/obsidian/red-team --subdir tools`.

### What gets written

Each repo produces `<vault>/<subdir>/<slug>.md` where `slug` is `<owner>-<name>` from the upstream metadata (or the repo path's basename when there is no upstream record). Example frontmatter:

```yaml
---
nostos_id: 42
path: "/home/user/tools/recon-kit"
remote_url: "git@github.com:org/recon-kit.git"
source: "blog:orange.tw, 2026-04-12"
status: "in-use"
quiet: false
added: "2026-04-12T10:00:00+00:00"
last_touched: "2026-04-15T14:00:00+00:00"
tags: ["recon", "passive"]
upstream:
  provider: "github"
  host: "github.com"
  owner: "org"
  name: "recon-kit"
  stars: 1243
  archived: false
  default_branch: "main"
  last_push: "2026-04-11T00:00:00Z"
  latest_release: "v2.3.1"
  license: "MIT"
  fetched_at: "2026-04-15T13:00:00+00:00"
---

# org/recon-kit

*Exported by nostos 2.3.0 on 2026-04-15T14:10:00+00:00*

## Description

(upstream description here)

## Notes

- **2026-04-12T10:05:00+00:00** - "mentioned for OOB DNS recon"
- **2026-04-14T09:30:00+00:00** - "used in demo"
```

### Narrow two-way sync (as of 2.5.0)

The vault is reconciliable with the DB, but **on a deliberately narrow surface**. `nostos vault sync` reads operator edits to `status` and `tags` out of each file's frontmatter, applies them to the DB, and then regenerates every `.md` from the reconciled state.

| Field | Writer | Sync behaviour |
| --- | --- | --- |
| `status` | operator (Obsidian Properties) | vault wins, DB is updated on next `vault sync` |
| `tags` | operator (Obsidian Properties) | vault wins, DB tag set is replaced to match |
| `upstream.*` | `nostos refresh` | DB wins, vault values are regenerated on sync |
| `last_touched`, `remote_url`, `path`, `added`, `nostos_id` | nostos | DB wins, regenerated on sync |
| Note body (Markdown) | nostos (via `nostos note`) | DB wins, body is regenerated on sync; vault edits to the Notes section are ignored |

The two sides never write to the same field, so there is no merge-conflict surface and no precedence timestamp needed. Orphan vault files (whose `nostos_id` no longer matches a repo in the DB) are reported, not deleted; the operator decides.

```bash
# Edit tags / status in Obsidian, then pull them into the DB
nostos vault sync

# JSON summary for scripting / cron
nostos vault sync --json

# Override the vault path per invocation
nostos vault sync --path ~/other-vault
```

`nostos vault export` is still supported and useful as a one-shot "rebuild from DB" operation (for example right after a large `nostos refresh`); `vault sync` is the right daily verb because it also catches any tag/status curation you did in Obsidian.

Note: the vault contains the same sensitive operator context as the index (tags, sources, notes, upstream metadata). Treat the vault directory with the same opsec posture as `$XDG_DATA_HOME/nostos/`: files are written `0600` and the `repos` subdirectory is created `0700` on Unix; keep the vault on an encrypted volume at rest.

### Dataview queries once you have exported

```
TABLE status, upstream.stars, upstream.archived, upstream.last_push
FROM "repos"
WHERE contains(tags, "c2") AND !upstream.archived
SORT upstream.stars DESC
```

```
TABLE status, upstream.last_push
FROM "repos"
WHERE upstream.archived = true
```

---

## Portable export and import

`nostos export` writes a schema-versioned JSON bundle of the metadata index; `nostos import` re-applies one. Use this for backup, cross-machine migration, team onboarding, or sharing a redacted tool inventory with a collaborator.

### Export

```bash
# Stdout (default) - pipes cleanly into ssh / scp / archivers
nostos export > nostos-$(date +%Y%m%d).json

# To a file (chmod 0600 on Unix)
nostos export --out /backup/nostos.json

# Redact notes, source, and remote_url - safe to share
nostos export --out share.json --redact --pretty
```

The bundle is schema-versioned (`schema` integer at the top level). `nostos` 1.1.0+ writes schema **2** and reads both schema 1 (legacy gitpulse / earlier nostos) and schema 2. See the schema block below for the full field list.

### Import

```bash
# Default: additive merge into the current index. Clones any repo
# entries whose local path does not resolve but that carry a remote_url.
nostos import bundle.json

# From stdin - end-to-end pipe between machines
nostos export | ssh ops-box "nostos import -"

# Cross-machine path rewrite (Alice's paths -> Bob's paths)
nostos import bundle.json --remap /home/alice:/home/bob

# Explicit clone destination (beats ~/.nostosrc clone_dir, beats $HOME)
nostos import bundle.json --clone-dir ~/repos

# Metadata-only: never touch the network, even for unresolved entries
nostos import bundle.json --no-clone

# Parallel cloning (default: 4)
nostos import bundle.json --clone-workers 8

# Wipe-and-replace mode (privileged; requires --yes for non-interactive use)
nostos import bundle.json --replace --yes

# Preview: print the resolution plan, per-entry, then exit
nostos import bundle.json --dry-run
```

**Resolution algorithm (per entry):**

1. Apply `--remap` rules to the bundle's absolute `path`.
2. If that path exists locally and is a git repo, register it.
3. Otherwise, if the entry carries `path_relative_to_home` (schema 2 only), try `$HOME/<that>`; register if present.
4. Otherwise, if `--no-clone` is set, register the entry with its post-remap path as a placeholder (no file mirror).
5. Otherwise, if `remote_url` is set, clone to `<clone-dir>/<local_name>` using the same hardened clone routine as `nostos add` (`--no-checkout`, git hooks disabled).
6. Otherwise, skip the entry and print a hint.

The resolution reason for each entry is visible in `--dry-run` and in the `resolution` breakdown of the JSON summary.

**Merge semantics (default):**
- Repos in the bundle that are not in the local index are **added**.
- Repos that already exist locally keep their **status, source, and quiet flag** unchanged. Local operator decisions always win.
- Tags are **unioned** (duplicates dropped).
- Notes are **appended** (we cannot tell which are "new" without content hashing; append is the right default).
- `upstream` metadata from the bundle is written as the current cached value. Run `nostos refresh` afterwards to rebuild it from live providers.

**Replace semantics (`--replace`):**
- Local index is **wiped** first, then the bundle is applied fresh.
- Without `--yes` the command prompts interactively; empty / `n` aborts with exit code 1.
- Typical use: disaster recovery, migrating to a new host, rotating workstations.

**Clone-on-import:**
- Cloning happens in a second pass after all resolvable entries are registered, parallelised across `--clone-workers`. A clone failure leaves the entry out of the index on that pass (count in `clone_failed`); re-running the import retries only the missing ones.
- `clone_dir` defaults to `clone_dir` in `~/.nostosrc`, falling back to `$HOME`.
- Hooks are disabled via `GIT_CONFIG_*` env vars to mitigate CVE-2024-32002 / 32004 / 32465.

### Bundle schema (stable)

Current format (schema 2, written by nostos 1.1.0+):

```json
{
  "schema": 2,
  "exported_at": "2026-04-17T15:30:00+00:00",
  "nostos_version": "1.1.0",
  "source_host": "alice-workstation",
  "source_platform": "linux",
  "redacted": false,
  "repos": [
    {
      "path": "/home/alice/tools/repo",
      "path_relative_to_home": "tools/repo",
      "local_name": "repo",
      "remote_url": "git@github.com:org/repo.git",
      "source": "blog:...",
      "status": "in-use",
      "quiet": false,
      "added_at": "2026-04-12T10:00:00+00:00",
      "last_touched_at": "2026-04-15T14:00:00+00:00",
      "tags": ["recon", "passive"],
      "notes": [{"body": "...", "created_at": "..."}],
      "upstream": {
        "provider": "github",
        "host": "github.com",
        "owner": "org",
        "name": "repo",
        "stars": 42,
        "archived": false,
        "...": "..."
      }
    }
  ]
}
```

**Field semantics:**

| Field | Added in | Purpose |
|---|---|---|
| `schema` | 1 | Integer, selects read/write rules. Current writer emits `2`. |
| `exported_at` | 1 | ISO-8601 UTC timestamp of when the bundle was produced. |
| `nostos_version` | 1 | Informational - the nostos version that wrote the bundle. |
| `source_host` | 2 | Hostname of the exporting machine. For debugging import mismatches. |
| `source_platform` | 2 | Platform name (linux / darwin / windows). Informational. |
| `redacted` | 1 | `true` when notes/source/remote_url were stripped at export time. |
| `repos[].path` | 1 | Original absolute path on the exporting host. Primary key. |
| `repos[].path_relative_to_home` | 2 | Same path expressed relative to `$HOME` (forward slashes), or `null` if the path was not under `$HOME`. The cross-OS resolution fallback. |
| `repos[].local_name` | 2 | Basename hint used when cloning into `--clone-dir` on import. |
| `repos[].remote_url` | 1 | The `origin` URL. Used as the clone source when no local path resolves. |
| `repos[].source` through `repos[].upstream` | 1 | Unchanged from schema 1. |

A schema-1 bundle (missing the three schema-2 fields) imports cleanly on nostos 1.1.0+ via the resolution algorithm's fallbacks.

---

## Self-update

`nostos update` compares the running version against the latest GitHub release and - if requested - applies the upgrade for your install method.

This is the only command that reaches out to `github.com` in default configuration. It is an opt-in network call triggered by the user's explicit command; `--offline` hard-disables it. The release check issues **one** HTTPS GET to `api.github.com/repos/prodrom3/nostos/releases/latest`; no telemetry, no aggregate reporting.

### Install-method detection

```mermaid
flowchart TD
    start([nostos update]) --> detect[Detect install method]
    detect --> src{.git at install root?<br/>remote points at nostos?}
    src -->|yes| source[source clone<br/>upgrade: git -C ROOT pull --ff-only]
    src -->|no| pipx{pipx list --json has nostos?}
    pipx -->|yes| pipxm[pipx install<br/>upgrade: pipx upgrade nostos]
    pipx -->|no| pip[pip install<br/>upgrade command printed, never auto-run]
```

### Commands

```bash
# Report-only: is there a newer release?
nostos update --check

# Apply the upgrade for the auto-detected method (prompts to confirm)
nostos update

# Non-interactive apply (for cron / CI - use with care)
nostos update --yes

# Offline mode: print local state only, no network
nostos update --offline
```

### Behaviour per install method

| Install | `nostos update` does | Notes |
| --- | --- | --- |
| Source clone | `git -C <root> pull --ff-only` | Fast-forward only; any local commits block the upgrade explicitly. |
| pipx | `pipx upgrade nostos` | Standard pipx venv upgrade. |
| pip | Prints the recommended `pip install --upgrade ...` command | Never invoked automatically; the right invocation depends on `--user`, venv, or system-wide state, and often needs sudo. |

### Opsec properties

- `--offline` produces zero outbound traffic.
- Token is read from `GITHUB_TOKEN` when set; otherwise the call is unauthenticated (60 req/hour, plenty for interactive use).
- Tokens are never logged or included in error messages.
- No `shell=True` in the upgrade subprocess calls; arguments are always passed as a list.
- A non-zero return code from the upgrade surfaces as an `UpdateError` with the subprocess output; the command exits 1 and the operator can re-run manually.

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
    python nostos.py ./vendor --quiet --json > /tmp/nostos.json
    jq '.counts' /tmp/nostos.json
```

### Cron example

```cron
*/30 * * * *  /usr/local/bin/nostos ~/projects --quiet --fetch-only
```

Combine with JSON output to feed dashboards (Prometheus text exporter, Grafana Loki, ELK, etc.).

---

## Logging

Each run writes a timestamped log file to `./logs/` (relative to the nostos install root), e.g. `2026-04-02_14-30-00.log`. Log files are automatically rotated - only the most recent 20 are kept (configurable via `max_log_files` in `~/.nostosrc`). Files are created with owner-only (0600) permissions, and HTTPS credentials of the form `https://user:token@host/` are sanitized to `https://***@host/` before being written.

---

## Security

nostos treats git operations on untrusted working directories as an attack surface, and treats the metadata index as an intelligence artifact. Defense-in-depth applies at both layers:

| Control | Description |
| --- | --- |
| **Git version check** | Startup warning on git < 2.45.1 (CVE-2024-32002, CVE-2024-32004, CVE-2024-32465). |
| **Safe remote clone** | `nostos add <url>` clones with `--no-checkout` and disables hooks via `GIT_CONFIG_*` env vars, then checks out in a second step. |
| **Credential redaction** | HTTPS credentials stripped from all log and summary output, and from `remote_url` values written to the index. |
| **Strict file permissions** | Log files and the metadata index DB chmod-ed to `0600`; data and config directories to `0700` (Unix). |
| **Ownership checks** | `~/.nostosrc` and legacy `~/.nostos_repos` rejected if not owned by the invoking user or world-writable (Unix). |
| **Repository ownership** | Repos not owned by the current user are skipped on Unix. |
| **Symlink protection** | The `logs/` directory is rejected if it is a symlink. |
| **No shell injection** | Every subprocess call uses list arguments; `shell=True` is never used. |
| **Index hardening** | SQLite PRAGMAs `journal_mode=WAL`, `secure_delete=ON`, `foreign_keys=ON` applied on every connection. Deleted rows are overwritten on disk. |
| **Probe fail-closed** | Upstream probes only contact hosts listed in `~/.config/nostos/auth.toml`; unknown hosts are silently skipped unless `defaults.allow_unknown = true`. |
| **Per-repo quiet flag** | `nostos add --quiet-upstream` marks a repo as ineligible for upstream probes. The probe layer never queries or logs these repos. |
| **Offline kill switch** | `refresh --offline` hard-disables the network layer; no exception paths, no fail-open. |
| **Token hygiene** | Tokens are sourced from environment variables by default (`token_env`), passed as `Authorization: Bearer`, and redacted from every log and error path. |
| **Auth file perms** | `auth.toml` is rejected on load if its mode is not `0600` or the owner is not the invoking user (Unix). |

### At-rest confidentiality

The index reveals the operator's full toolchain. nostos deliberately ships **no** built-in DB encryption (adding a runtime dep would expand the supply-chain surface). Instead: place `$XDG_DATA_HOME/nostos/` on a disk-layer encrypted volume (LUKS on Linux, FileVault on macOS, BitLocker on Windows). That is the right layer for this threat model.

### Reporting Vulnerabilities

Please report security issues privately by opening a [GitHub security advisory](https://github.com/prodrom3/nostos/security/advisories/new) rather than filing a public issue. Public issue reports are acceptable only for **already-disclosed** CVEs or clearly non-sensitive hardening suggestions.

---

## Compatibility

| OS | Python 3.10 | 3.11 | 3.12 | 3.13 |
| --- | :---: | :---: | :---: | :---: |
| Ubuntu (latest) | ✓ | ✓ | ✓ | ✓ |
| macOS (latest)  | ✓ | ✓ | ✓ | ✓ |
| Windows (latest) | ✓ | ✓ | ✓ | ✓ |

CI exercises every cell of this matrix on every push and pull request. See the [CI workflow](.github/workflows/ci.yml) and the ["CI" badge](https://github.com/prodrom3/nostos/actions/workflows/ci.yml) at the top of this file for current build status.

---

## Architecture

### Module layout

```
nostos.py                 # thin entrypoint -> core.cli.run
core/
├── cli.py                  # argparse subparsers, legacy flag shim, default-verb injection
├── paths.py                # XDG-compliant paths ($XDG_CONFIG_HOME / $XDG_DATA_HOME)
├── index.py                # SQLite metadata index: schema, migrations, CRUD, PRAGMAs
├── config.py               # ~/.nostosrc loader + safety checks
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
    entry[nostos.py<br/>entrypoint]
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

### Run flow: `nostos pull`

```mermaid
flowchart TD
    start([nostos invoked]) --> rewrite[Rewrite legacy flags<br/>inject default verb]
    rewrite --> disp[Dispatch to<br/>core.commands.pull.run]
    disp --> mig[First-run watchlist<br/>migration into index]
    mig --> rc[Load ~/.nostosrc]
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

### Intake flow: `nostos add` -> `triage`

```mermaid
flowchart LR
    url[URL or path<br/>from intel feed]
    add[nostos add<br/>hardened clone]
    index[(metadata index)]
    triage[nostos triage<br/>interactive loop]
    list[nostos list<br/>filters]
    show[nostos show<br/>per-repo view]

    url --> add
    add -->|status=new| index
    index --> triage
    triage -->|status=in-use / flagged / dropped<br/>tags + notes| index
    index --> list
    index --> show
```

---

## Versioning & Support

nostos follows [Semantic Versioning](https://semver.org/) 2.0. Breaking changes are introduced only in a new **major** version and are called out in the release notes.

- **Stable:** CLI flags and exit codes.
- **Stable:** JSON output schema.
- **Internal:** the `core/` Python API is not a supported public API - import at your own risk.

Current version: see [`VERSION`](./VERSION) and `nostos --version`.

---

## Contributing

Contributions are welcome. Before opening a pull request:

1. Run the local gate:
   ```bash
   python -m unittest discover -s tests -v
   python -m mypy core/ nostos.py
   python -m ruff check core/ nostos.py tests/
   ```
2. Add or update tests for behavior changes.
3. Keep the change focused - one logical unit per PR.

For larger features, please open an issue first to align on scope.

---

## License

Released under the [MIT License](./LICENSE).

---

Authored by [prodrom3](https://github.com/prodrom3). Maintained by the **radamic** organization.
