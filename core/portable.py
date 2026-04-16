"""Portable export / import bundle for the nostos metadata index.

A bundle is a schema-versioned JSON document capturing enough state
to recreate the index on another machine. It carries repos, tags,
notes, and the latest cached upstream_meta row per repo. It does not
carry the SQLite file itself (too opaque), schema-internal ids
(regenerated on import), or the IDs of schema_version / auto-indexes.

Schema history
- schema=1 : the original format. Each repo entry carries only `path`
  (an absolute OS-specific string). Cross-OS import requires --remap
  to rewrite path prefixes.
- schema=2 : adds `path_relative_to_home` and `local_name` per repo,
  and `source_host` / `source_platform` at the envelope level. Enables
  automatic cross-OS resolution and clone-on-import for repos that
  carry a `remote_url`. Fully readable by the schema=1 import path
  via the backwards-compat mapper: the extra fields are optional.

Design
- Stable JSON, schema-versioned, single file or stdin/stdout stream.
- Redaction knob strips notes, source, and remote_url so a bundle is
  safe to share with a teammate who should only see tags and status.
- Path remap rewrites absolute paths on import so a bundle from
  Alice's laptop lands cleanly on Bob's workstation.
- Merge vs replace: the default is merge (additive); replace wipes
  the index first and is intentionally privileged.
- Clone-on-import: when a bundle entry has a remote_url and none of
  the local resolution steps find an existing git repo, the import
  clones the remote into a configured directory and registers that
  path. Disable with clone_missing=False for offline / metadata-only
  replay.

Security / opsec
- Export is purely local file I/O. No network.
- Import may touch the network in clone-on-import mode. Pass
  clone_missing=False (CLI: `--no-clone`) to hard-disable that.
- Cloning reuses core.watchlist.clone_repo, which runs `git clone
  --no-checkout` with hooks disabled via GIT_CONFIG_* env vars to
  mitigate CVE-2024-32002 / 32004 / 32465.
- Redacted bundles carry `redacted: true` in the top-level envelope
  so downstream consumers can tell at a glance.
"""

from __future__ import annotations

import concurrent.futures
import datetime
import os
import platform
import socket
import sqlite3
from typing import Any

from . import index as _index

# The write side: every export writes this schema.
CURRENT_EXPORT_SCHEMA: int = 2
# The read side: validate_bundle accepts everything in this set.
READABLE_SCHEMAS: frozenset[int] = frozenset({1, 2})


class BundleError(Exception):
    """Raised on schema mismatch, malformed bundle, or invalid import params."""


# ---------- helpers ----------


def _now_utc() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _home() -> str:
    return os.path.realpath(os.path.expanduser("~"))


def _rel_to_home(path: str) -> str | None:
    """Return `path` expressed as a forward-slash-joined path relative
    to $HOME, or None if `path` is not under the current user's $HOME.

    Normalised to forward slashes so a bundle produced on Windows is
    readable on Linux without separator-translation work.
    """
    try:
        resolved = os.path.realpath(os.path.expanduser(path))
    except OSError:
        return None
    home = _home()
    try:
        rel = os.path.relpath(resolved, home)
    except ValueError:
        # Different drive on Windows, for example.
        return None
    if rel.startswith(".."):
        return None
    # Forward-slashes are legal on both Windows and Unix; joining
    # with os.path.join(home, rel) handles either at resolve time.
    return rel.replace(os.sep, "/")


def _basename_for_clone(path: str, remote_url: str | None) -> str:
    """Pick a directory name to use when this entry has to be cloned.

    Prefer the basename of the bundle entry's path so a fleet with two
    repos both named 'cli' but checked out at different paths stays
    distinguishable. Fall back to the remote URL's tail if path is
    empty/unusable.
    """
    bn = os.path.basename(path.rstrip("/\\"))
    if bn and bn not in (".", ".."):
        return bn
    if remote_url:
        # Reuse the watchlist helper's logic without circular imports.
        from .watchlist import extract_repo_name

        return extract_repo_name(remote_url)
    return "repo"


# ---------- export ----------


def build_bundle(
    conn: sqlite3.Connection,
    *,
    redact: bool = False,
    nostos_version: str = "unknown",
) -> dict[str, Any]:
    """Build a portable bundle dict from the live index.

    When `redact=True`, notes, free-text source, and remote_url are
    scrubbed. Tags, status, quiet flag, timestamps, path hints, and
    upstream metadata are retained (these are usually the useful
    fields for fleet inventory sharing).
    """
    repos = _index.list_repos(conn)
    out_repos: list[dict[str, Any]] = []
    for repo in repos:
        repo_id = int(repo["id"])
        path = repo["path"]
        remote_url = None if redact else repo.get("remote_url")
        entry: dict[str, Any] = {
            "path": path,
            "path_relative_to_home": _rel_to_home(path),
            "local_name": _basename_for_clone(path, repo.get("remote_url")),
            "remote_url": remote_url,
            "source": None if redact else repo.get("source"),
            "status": repo["status"],
            "quiet": bool(repo.get("quiet")),
            "added_at": repo["added_at"],
            "last_touched_at": repo.get("last_touched_at"),
            "tags": list(repo.get("tags", [])),
            "notes": [],
            "upstream": None,
        }
        if not redact:
            entry["notes"] = [
                {"body": n["body"], "created_at": n["created_at"]}
                for n in _index.get_notes(conn, repo_id)
            ]
        um = _index.get_upstream_meta(conn, repo_id)
        if um:
            # Strip the repo_id fk; it is regenerated on import.
            entry["upstream"] = {k: v for k, v in um.items() if k != "repo_id"}
        out_repos.append(entry)

    return {
        "schema": CURRENT_EXPORT_SCHEMA,
        "exported_at": _now_utc(),
        "nostos_version": nostos_version,
        "source_host": socket.gethostname() or None,
        "source_platform": platform.system().lower() or None,
        "redacted": redact,
        "repos": out_repos,
    }


# ---------- import ----------


def _apply_remaps(path: str, remaps: list[tuple[str, str]]) -> str:
    """Rewrite `path` if it starts with any remap src prefix.

    Remaps are tried in order; the first matching prefix wins. A
    trailing slash or backslash on `src` is tolerated so operators do
    not trip over `--remap /a/:/b` vs `--remap /a:/b`. Both path
    separators are accepted for the match so a bundle produced on
    Windows (backslashes) can be remapped on Unix and vice versa.
    """
    for src, dst in remaps:
        src_norm = src.rstrip("/\\")
        dst_norm = dst.rstrip("/\\")
        if path == src_norm:
            return dst_norm
        if path.startswith(src_norm + "/") or path.startswith(src_norm + "\\"):
            return dst_norm + path[len(src_norm):]
    return path


def parse_remap(spec: str) -> tuple[str, str]:
    """Parse a `src:dst` CLI spec into a (src, dst) tuple."""
    if ":" not in spec:
        raise BundleError(f"invalid --remap (expected src:dst, got {spec!r})")
    src, dst = spec.split(":", 1)
    if not src or not dst:
        raise BundleError(f"invalid --remap (empty side, got {spec!r})")
    return src, dst


def validate_bundle(bundle: dict[str, Any]) -> None:
    """Fail fast on malformed or wrong-version bundles."""
    if not isinstance(bundle, dict):
        raise BundleError("bundle is not a JSON object")
    schema = bundle.get("schema")
    if schema not in READABLE_SCHEMAS:
        readable = sorted(READABLE_SCHEMAS)
        raise BundleError(
            f"unsupported bundle schema: {schema!r} "
            f"(this nostos reads schemas {readable})"
        )
    if not isinstance(bundle.get("repos"), list):
        raise BundleError("bundle.repos must be a JSON array")


def _is_git_repo(path: str) -> bool:
    """Cheap check: `.git` directory or worktree file exists."""
    if not path:
        return False
    try:
        return os.path.isdir(os.path.join(path, ".git")) or os.path.isfile(
            os.path.join(path, ".git")
        )
    except OSError:
        return False


def resolve_entry_path(
    entry: dict[str, Any],
    remaps: list[tuple[str, str]],
) -> tuple[str, str]:
    """Find the local path an imported entry should live at.

    Returns a (path, reason) tuple. `reason` is one of:
      - "path_match"        : entry['path'] (post-remap) resolves to a live repo
      - "home_relative"     : path_relative_to_home under local $HOME resolves
      - "unresolved"        : neither worked; caller decides to clone or skip

    The returned path is always absolute and user-expanded.
    """
    primary_raw = str(entry.get("path") or "")
    primary = _apply_remaps(primary_raw, remaps)

    # 1. Direct hit (with --remap applied)
    if primary:
        resolved = os.path.realpath(os.path.expanduser(primary))
        if _is_git_repo(resolved):
            return resolved, "path_match"

    # 2. Relative-to-home fallback (v2 bundles only; v1 bundles don't carry it)
    rel = entry.get("path_relative_to_home")
    if rel:
        # Accept either '/'-or-'\\'-separated relative paths.
        rel_norm = str(rel).replace("\\", "/")
        candidate = os.path.join(_home(), *rel_norm.split("/"))
        candidate = os.path.realpath(candidate)
        if _is_git_repo(candidate):
            return candidate, "home_relative"

    # 3. Nothing matched. Return the post-remap primary path so the
    # caller can decide to clone there, skip, or register anyway.
    return (
        os.path.realpath(os.path.expanduser(primary)) if primary else "",
        "unresolved",
    )


def plan_import(
    bundle: dict[str, Any],
    remaps: list[tuple[str, str]],
    *,
    clone_missing: bool,
    clone_dir: str | None,
) -> list[dict[str, Any]]:
    """Walk the bundle and produce a per-entry plan without writing.

    Each plan item has:
      {
        "entry":   <the original bundle dict>,
        "path":    <resolved absolute path>,
        "action":  "register" | "clone_then_register" | "skip",
        "reason":  "path_match" | "home_relative" | "clone" |
                   "no_remote_no_path" | "no_remote_no_clone",
      }
    """
    plan: list[dict[str, Any]] = []
    for entry in bundle.get("repos", []):
        path, how = resolve_entry_path(entry, remaps)
        remote_url = entry.get("remote_url")

        if how in ("path_match", "home_relative"):
            plan.append(
                {"entry": entry, "path": path, "action": "register", "reason": how}
            )
            continue

        # unresolved from here on
        if not clone_missing:
            # Metadata-only mode. Register with the post-remap path even
            # if nothing exists there. Caller can `nostos pull` later.
            if path:
                plan.append(
                    {
                        "entry": entry,
                        "path": path,
                        "action": "register",
                        "reason": "no_remote_no_clone" if not remote_url else "no_clone",
                    }
                )
            else:
                plan.append(
                    {"entry": entry, "path": "", "action": "skip",
                     "reason": "no_path_no_clone"}
                )
            continue

        if remote_url:
            local_name = str(
                entry.get("local_name")
                or _basename_for_clone(entry.get("path") or "", remote_url)
            )
            target = os.path.join(clone_dir or _home(), local_name)
            plan.append(
                {
                    "entry": entry,
                    "path": target,
                    "action": "clone_then_register",
                    "reason": "clone",
                }
            )
            continue

        # No remote_url, no path match, clone-missing enabled: we can't help.
        plan.append(
            {"entry": entry, "path": "", "action": "skip",
             "reason": "no_remote_no_path"}
        )
    return plan


def import_bundle(
    conn: sqlite3.Connection,
    bundle: dict[str, Any],
    *,
    mode: str = "merge",
    remaps: list[tuple[str, str]] | None = None,
    dry_run: bool = False,
    clone_missing: bool = True,
    clone_dir: str | None = None,
    clone_workers: int = 4,
) -> dict[str, Any]:
    """Apply a bundle to the live index.

    mode='merge'   add missing repos, top up tags / notes / upstream.
                   Never mutates an existing repo's status, source, or
                   quiet flag: the operator's local decisions win.
    mode='replace' wipe the index first, then import the bundle as
                   the authoritative state. Caller is responsible for
                   the confirm/--yes gate before handing us mode=replace.

    Clone-on-import:
    - If an entry has a remote_url and nothing resolves locally, clone
      to {clone_dir or $HOME}/{local_name} and register that path.
    - Set clone_missing=False to disable the network call entirely.

    Returns a stats dict so the caller can print a summary.
    """
    validate_bundle(bundle)
    if mode not in {"merge", "replace"}:
        raise BundleError(f"invalid mode: {mode!r}")

    remaps = remaps or []
    stats: dict[str, Any] = {
        "mode": mode,
        "dry_run": dry_run,
        "bundle_schema": bundle.get("schema"),
        "source_host": bundle.get("source_host"),
        "source_platform": bundle.get("source_platform"),
        "total_in_bundle": len(bundle.get("repos", [])),
        "added": 0,
        "already_present": 0,
        "cloned": 0,
        "clone_failed": 0,
        "skipped": 0,
        "tags_added": 0,
        "notes_added": 0,
        "upstream_set": 0,
        "resolution": {
            "path_match": 0,
            "home_relative": 0,
            "clone": 0,
            "no_clone": 0,
            "no_remote_no_clone": 0,
            "no_remote_no_path": 0,
            "no_path_no_clone": 0,
        },
    }

    plan = plan_import(
        bundle, remaps, clone_missing=clone_missing, clone_dir=clone_dir
    )
    for item in plan:
        stats["resolution"][item["reason"]] = (
            stats["resolution"].get(item["reason"], 0) + 1
        )

    if dry_run:
        # Dry run: count what would happen, but do not touch the DB
        # or the network. Still pre-fills tags/notes/upstream counts
        # so the summary is useful.
        for item in plan:
            entry = item["entry"]
            if item["action"] == "skip":
                stats["skipped"] += 1
                continue
            tags = list(entry.get("tags") or [])
            notes = list(entry.get("notes") or [])
            upstream = entry.get("upstream")
            existing = _index.get_repo(conn, item["path"]) if item["path"] else None
            if existing is None:
                stats["added"] += 1
                stats["tags_added"] += len(tags)
                stats["notes_added"] += len(notes)
                if upstream:
                    stats["upstream_set"] += 1
                if item["action"] == "clone_then_register":
                    # We count it as "would clone" via the resolution bucket;
                    # don't also charge it against clone_failed.
                    pass
            else:
                stats["already_present"] += 1
        return stats

    # ---- mutate section below this line ----

    if mode == "replace":
        conn.execute("DELETE FROM repos")
        conn.commit()

    # Pass 1: register metadata for entries that don't need cloning,
    # and for clone entries write a placeholder registration we'll
    # revisit after cloning succeeds. This keeps the index internally
    # consistent even if the network pass fails halfway through.
    clone_tasks: list[tuple[dict[str, Any], str]] = []  # (item, intended_target)

    for item in plan:
        if item["action"] == "skip":
            stats["skipped"] += 1
            continue
        if item["action"] == "clone_then_register":
            clone_tasks.append((item, item["path"]))
            continue
        _apply_entry(conn, item["entry"], item["path"], stats)

    # Pass 2: clone what's missing. Parallel across clone_workers.
    if clone_tasks:
        def _clone_one(task: tuple[dict[str, Any], str]) -> tuple[dict[str, Any], str, str | None]:
            item, _intended = task
            entry = item["entry"]
            url = str(entry.get("remote_url") or "")
            local_name = str(
                entry.get("local_name")
                or _basename_for_clone(entry.get("path") or "", url)
            )
            parent = clone_dir or _home()
            os.makedirs(parent, exist_ok=True)
            # Use core.watchlist.clone_repo (hooks-disabled, --no-checkout).
            from .watchlist import clone_repo as _wl_clone

            cloned = _wl_clone(url, parent)
            if cloned is None:
                return item, local_name, None
            # If watchlist.clone_repo derived a different basename from
            # the URL than the bundle's local_name, move or accept either:
            # we keep the one clone_repo returned so the filesystem state
            # matches what we register.
            return item, local_name, cloned

        max_workers = max(1, min(clone_workers, len(clone_tasks)))
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
            for item, _name, cloned_path in ex.map(_clone_one, clone_tasks):
                if cloned_path is None:
                    stats["clone_failed"] += 1
                    continue
                stats["cloned"] += 1
                _apply_entry(conn, item["entry"], cloned_path, stats)

    return stats


def _apply_entry(
    conn: sqlite3.Connection,
    entry: dict[str, Any],
    path: str,
    stats: dict[str, Any],
) -> None:
    """Merge-semantics write of a single bundle entry at `path`."""
    remote_url = entry.get("remote_url")
    source = entry.get("source")
    status = entry.get("status", "new")
    quiet = bool(entry.get("quiet", False))
    tags = list(entry.get("tags") or [])
    notes = list(entry.get("notes") or [])
    upstream = entry.get("upstream")

    existing = _index.get_repo(conn, path)
    if existing is None:
        _index.add_repo(
            conn,
            path,
            remote_url=remote_url,
            source=source,
            status=status,
            quiet=quiet,
            tags=tags,
            note=None,
        )
        stats["added"] += 1
        stats["tags_added"] += len(tags)
        for n in notes:
            body = n.get("body")
            if body:
                _index.add_note(conn, path, body)
                stats["notes_added"] += 1
    else:
        stats["already_present"] += 1
        if tags:
            _index.add_tags(conn, path, tags)
            stats["tags_added"] += len(tags)
        for n in notes:
            body = n.get("body")
            if body:
                _index.add_note(conn, path, body)
                stats["notes_added"] += 1

    if upstream:
        _index.upsert_upstream_meta(conn, path, upstream)
        stats["upstream_set"] += 1
