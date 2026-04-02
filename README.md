# gitpulse

[![CI](https://github.com/prodrom3/gitpulse/actions/workflows/ci.yml/badge.svg)](https://github.com/prodrom3/gitpulse/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![Version](https://img.shields.io/badge/version-2.0.0-orange.svg)](https://github.com/prodrom3/gitpulse/releases)

`gitpulse` is a Python CLI tool that batch-updates multiple git repositories in parallel. It scans a directory tree, discovers all git repositories, and pulls updates concurrently - keeping dozens of cloned repos in sync with a single command.

**Author:** [prodrom3](https://github.com/prodrom3) / [radamic](https://github.com/radamic) | **Last updated:** 2026-04-02

<p align="center">
  <img width="460" height="460" src="https://github.com/prodrom3/gitpulse/assets/7604466/91c585dc-ef92-48f1-8461-60b4fcbcfb6d">
</p>

## Features

- **Parallel updates** - Uses multi-threading to pull repositories concurrently, with configurable worker count
- **Smart detection** - Skips repos that are already up-to-date, have uncommitted changes, detached HEAD, or no upstream branch
- **Watchlist** - Maintain a persistent list of repos to track, even across different directories
- **Fetch-only mode** - Check what's new across all repos without merging anything
- **Producer/consumer** - Starts pulling repos while still discovering more, so the first results come back faster
- **SSH multiplexing** - Reuses SSH connections across repos sharing the same remote host (Unix)
- **Dry-run mode** - Preview which repositories will be updated before pulling
- **Rebase support** - Optionally use `git pull --rebase` instead of merge
- **Exclude patterns** - Skip specific repos by glob pattern (e.g. `--exclude 'archived-*'`)
- **Configurable depth** - Control how deep the directory scan goes
- **Timeout protection** - Kills hung git operations after a configurable timeout
- **Config file** - Set persistent defaults in `~/.gitpulserc` so you don't repeat flags every run
- **JSON output** - Machine-readable output for scripting, piping to `jq`, or dashboards
- **Color output** - Green/yellow/red status in terminal, automatically disabled when piped
- **Progress indicator** - See real-time status as each repo completes (suppress with `--quiet`)
- **Graceful interruption** - Ctrl+C cancels pending tasks and prints a partial summary
- **Logging** - Generates timestamped log files with automatic rotation (keeps last 20 runs)
- **Security** - Strips credentials from log output, restricts log file permissions, verifies repo ownership
- **Exit codes** - Returns 0 on success, 1 if any repo failed - suitable for scripting and CI

## Requirements

- Python >= 3.10
- Git >= 2.45.1 (recommended - gitpulse warns at startup if your version is vulnerable to CVE-2024-32002/32004/32465)

## Installation

**Option 1 - Run directly (no install):**

```bash
git clone https://github.com/prodrom3/gitpulse.git
cd gitpulse
python gitpulse.py --help
```

**Option 2 - Install as a command:**

```bash
git clone https://github.com/prodrom3/gitpulse.git
cd gitpulse
pip install .
gitpulse --help    # now available anywhere
```

No third-party dependencies - only Python 3.10+ and git.

## Usage

```bash
python gitpulse.py [path] [options]
```

### Arguments

| Argument | Description | Default |
|---|---|---|
| `path` | Root directory to scan for repositories | Current directory |
| `-v, --version` | Show version and exit | |
| `--dry-run` | List discovered repos without pulling | Off |
| `--fetch-only` | Only fetch from remotes, do not merge or rebase | Off |
| `--rebase` | Use `git pull --rebase` | Off |
| `--depth N` | Maximum directory scan depth | 5 |
| `--workers N` | Number of concurrent worker threads | 8 |
| `--timeout N` | Seconds before a git operation is killed | 120 |
| `--exclude PATTERN` | Glob patterns to skip repos by name | None |
| `--json` | Output results as JSON | Off |
| `-q, --quiet` | Suppress progress, only show summary | Off |
| `--add PATH_OR_URL` | Add a repository to the watchlist (local path or remote URL) | |
| `--remove PATH` | Remove a repository from the watchlist | |
| `--list` | Show all repositories in the watchlist | |
| `--watchlist` | Pull only watchlist repos (combine with path to also scan a directory) | Off |
| `--clone-dir DIR` | Directory to clone remote repos into | Current directory |

### Examples

```bash
# Update all repos under the current directory
python gitpulse.py

# Update all repos under a specific path
python gitpulse.py /home/user/projects

# Preview which repos would be updated
python gitpulse.py --dry-run

# Fetch only - see what's new without merging
python gitpulse.py --fetch-only

# Pull with rebase, 16 workers, and a 60-second timeout
python gitpulse.py --rebase --workers 16 --timeout 60

# Only scan 2 levels deep
python gitpulse.py --depth 2

# Skip archived and temporary repos
python gitpulse.py --exclude 'archived-*' 'temp-*'

# Get JSON output for scripting
python gitpulse.py --json | jq '.counts'

# Quiet mode for CI - only summary, no progress
python gitpulse.py --quiet

# Check version
python gitpulse.py --version

# Add local repos to a persistent watchlist
python gitpulse.py --add /home/user/projects/repo-a
python gitpulse.py --add /home/user/work/repo-b

# Add remote repos by URL (clones first, then adds to watchlist)
python gitpulse.py --add https://github.com/user/repo.git
python gitpulse.py --add git@gitlab.com:team/project.git

# Clone into a specific directory instead of cwd
python gitpulse.py --add https://github.com/user/repo.git --clone-dir /home/user/repos

# See what's in the watchlist
python gitpulse.py --list

# Pull only watchlist repos
python gitpulse.py --watchlist

# Pull watchlist repos AND scan a directory
python gitpulse.py --watchlist /home/user/other-projects

# Remove a repo from the watchlist
python gitpulse.py --remove /home/user/projects/repo-a
```

### Output

gitpulse shows color-coded real-time progress as repos complete:

```
  [1/9] updated: /home/user/projects/repo-a
  [2/9] up-to-date: /home/user/projects/repo-d
  [3/9] skipped: /home/user/projects/repo-e
  ...
```

Followed by a categorized summary:

```
--- Summary ---

Updated (3):
  /home/user/projects/repo-a
  /home/user/projects/repo-b
  /home/user/projects/tools/repo-c

Already up-to-date (5):
  /home/user/projects/repo-d
  ...

Skipped (1):
  /home/user/projects/repo-e - dirty working tree (uncommitted changes)

Failed (0):

Total: 9 | Updated: 3 | Up-to-date: 5 | Skipped: 1 | Failed: 0
```

With `--fetch-only`, repos that have new commits show as "Fetched" with the commit count:

```
Fetched (2):
  /home/user/projects/repo-a
  /home/user/projects/repo-b
```

### JSON Output

With `--json`, output is structured for machine consumption:

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
      "remote_url": "git@github.com:user/repo-a.git"
    }
  ]
}
```

## Config File

Create `~/.gitpulserc` to set persistent defaults:

```ini
[defaults]
depth = 5
workers = 8
timeout = 120
max_log_files = 20
rebase = false
clone_dir = /home/user/repos

[exclude]
patterns = archived-*, .backup-*, vendor-*
```

CLI flags always override config file values.

## Watchlist

For repos scattered across different directories, use the watchlist instead of (or alongside) directory scanning. The watchlist is stored at `~/.gitpulse_repos` - one path per line, supports comments (`#`) and blank lines.

```bash
# Add local repos
python gitpulse.py --add /home/user/projects/important-api
python gitpulse.py --add /home/user/work/frontend

# Add remote repos by URL (GitHub, GitLab, any git host)
python gitpulse.py --add https://github.com/user/repo.git
python gitpulse.py --add git@gitlab.com:team/project.git

# Clone into a specific directory
python gitpulse.py --add https://github.com/user/repo.git --clone-dir /home/user/repos

# See what's tracked
python gitpulse.py --list

# Pull everything in the watchlist
python gitpulse.py --watchlist

# Pull watchlist + scan another directory
python gitpulse.py --watchlist /home/user/other-repos

# Clean up
python gitpulse.py --remove /opt/tools/deployment-scripts
```

When you `--add` a remote URL, gitpulse clones it locally (to `--clone-dir` or the current directory), then adds the local path to the watchlist. Supported URL formats: HTTPS, SSH (`git@host:user/repo`), `ssh://`, and `git://`.

You can set a default clone directory in `~/.gitpulserc`:

```ini
[defaults]
clone_dir = /home/user/repos
```

Stale entries (deleted or moved repos) are flagged with a warning but don't block the rest of the run. The watchlist file has the same security checks as the config file (ownership and permissions on Unix).

## Logging

Each run creates a timestamped log file in the `logs/` directory (e.g. `2026-04-02_14-30-00.log`). Log files are automatically rotated - only the 20 most recent are kept (configurable via config file). Log files are created with restricted permissions (owner read/write only) and credentials are stripped from any logged output.

## Caution

- Repos with uncommitted changes are automatically skipped to avoid merge conflicts. Commit or stash your work if you want them to be updated.
- Ensure your repositories have the correct credentials (SSH keys or credential helpers) configured, as the script will use your existing git configuration.
- On shared filesystems, repositories not owned by the current user are skipped.

## Security

gitpulse includes several hardening measures:

- **Git version check** - Warns at startup if git < 2.45.1 (affected by CVE-2024-32002, CVE-2024-32004, CVE-2024-32465)
- **Safe clone** - Remote repos are cloned with `--no-checkout` and git hooks disabled via `GIT_CONFIG` environment variables, preventing malicious hook execution
- **Credential stripping** - HTTPS credentials are stripped from all log output
- **File permissions** - Log files are created with 0600 (owner-only) permissions
- **Config/watchlist validation** - `~/.gitpulserc` and `~/.gitpulse_repos` are rejected if not owned by the current user or if world-writable (Unix)
- **Repo ownership check** - Repositories not owned by the current user are skipped on Unix
- **Symlink protection** - The `logs/` directory is verified to not be a symlink
- **No shell injection** - All subprocess calls use list arguments, never `shell=True`

## Contribution

If you find any bugs or have ideas for improvements, feel free to open an issue or create a pull request on this repository. Your contributions are highly appreciated!
