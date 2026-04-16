# Portable bundle schema

`nostos export` writes a schema-versioned JSON document of the metadata index; `nostos import` re-applies one. This doc pins the **bundle format** and the **import resolution algorithm** so consumers (other nostos installs, external tooling, audit pipelines) can rely on stable shape.

## Export

```bash
# Stdout (default) - pipes cleanly into ssh / scp / archivers
nostos export > nostos-$(date +%Y%m%d).json

# To a file (chmod 0600 on Unix)
nostos export --out /backup/nostos.json

# Redact notes, source, and remote_url - safe to share
nostos export --out share.json --redact --pretty
```

The writer always emits the **current** schema (see below). The reader accepts every schema in the `READABLE_SCHEMAS` set so older bundles keep working.

## Import

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

### Resolution algorithm (per entry)

1. Apply `--remap` rules to the bundle's absolute `path`.
2. If that path exists locally and is a git repo, register it.
3. Otherwise, if the entry carries `path_relative_to_home` (schema 2 only), try `$HOME/<that>`; register if present.
4. Otherwise, if `--no-clone` is set, register the entry with its post-remap path as a placeholder (no file mirror).
5. Otherwise, if `remote_url` is set, clone to `<clone-dir>/<local_name>` using the same hardened clone routine as `nostos add` (`--no-checkout`, git hooks disabled).
6. Otherwise, skip the entry and print a hint.

The resolution reason for each entry is visible in `--dry-run` output and in the `resolution` breakdown of the JSON summary.

### Merge semantics (default)

- Repos in the bundle that are not in the local index are **added**.
- Repos that already exist locally keep their **status, source, and quiet flag** unchanged. Local operator decisions always win.
- Tags are **unioned** (duplicates dropped).
- Notes are **appended** (we cannot tell which are "new" without content hashing; append is the right default).
- `upstream` metadata from the bundle is written as the current cached value. Run `nostos refresh` afterwards to rebuild it from live providers.

### Replace semantics (`--replace`)

- Local index is **wiped** first, then the bundle is applied fresh.
- Without `--yes` the command prompts interactively; empty / `n` aborts with exit code 1.
- Typical use: disaster recovery, migrating to a new host, rotating workstations.

### Clone-on-import

- Cloning happens in a second pass after all resolvable entries are registered, parallelised across `--clone-workers`. A clone failure leaves the entry out of the index on that pass (count in `clone_failed`); re-running the import retries only the missing ones.
- `clone_dir` defaults to `clone_dir` in `~/.nostosrc`, falling back to `$HOME`.
- Hooks are disabled via `GIT_CONFIG_*` env vars to mitigate CVE-2024-32002 / 32004 / 32465.

## Current schema (v2)

Written by nostos 1.1.0+:

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

## Field semantics

| Field | Added in | Purpose |
|---|---|---|
| `schema` | 1 | Integer, selects read/write rules. Current writer emits `2`. |
| `exported_at` | 1 | ISO-8601 UTC timestamp of when the bundle was produced. |
| `nostos_version` | 1 | Informational - the nostos version that wrote the bundle. |
| `source_host` | 2 | Hostname of the exporting machine. For debugging import mismatches. |
| `source_platform` | 2 | Platform name (linux / darwin / windows). Informational. |
| `redacted` | 1 | `true` when notes / source / remote_url were stripped at export time. |
| `repos[].path` | 1 | Original absolute path on the exporting host. Primary key. |
| `repos[].path_relative_to_home` | 2 | Same path expressed relative to `$HOME` (forward slashes), or `null` if the path was not under `$HOME`. The cross-OS resolution fallback. |
| `repos[].local_name` | 2 | Basename hint used when cloning into `--clone-dir` on import. |
| `repos[].remote_url` | 1 | The `origin` URL. Used as the clone source when no local path resolves. |
| `repos[].source` through `repos[].upstream` | 1 | Unchanged from schema 1. |

## Backwards compatibility

- Schema-1 bundles (from earlier nostos and from gitpulse) import on nostos 1.1.0+ via the resolution algorithm's fallbacks. The three new schema-2 fields are simply absent; the algorithm skips step 3 (home-relative) and falls through to step 5 (clone) if a `remote_url` is set.
- Validator accepts `READABLE_SCHEMAS = frozenset({1, 2})`. A bundle whose `schema` field is not in that set fails fast with `BundleError`.

## Stats summary

`nostos import` returns (or prints, with `--json`) a stats dict with this shape:

```json
{
  "mode": "merge",
  "dry_run": false,
  "bundle_schema": 2,
  "source_host": "alice-workstation",
  "source_platform": "linux",
  "total_in_bundle": 42,
  "added": 10,
  "already_present": 28,
  "cloned": 3,
  "clone_failed": 1,
  "skipped": 0,
  "tags_added": 85,
  "notes_added": 12,
  "upstream_set": 35,
  "resolution": {
    "path_match": 28,
    "home_relative": 10,
    "clone": 4,
    "no_clone": 0,
    "no_remote_no_clone": 0,
    "no_remote_no_path": 0,
    "no_path_no_clone": 0
  }
}
```

Exit code is `1` if `clone_failed > 0`, else `0`.
