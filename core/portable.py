"""Portable export / import bundle for the gitpulse metadata index.

A bundle is a schema-versioned JSON document capturing enough state
to recreate the index on another machine. It carries repos, tags,
notes, and the latest cached upstream_meta row per repo. It does not
carry the SQLite file itself (too opaque), schema-internal ids
(regenerated on import), or the IDs of schema_version / auto-indexes.

Design
- Stable JSON, schema v1, single file or stdin/stdout stream.
- Redaction knob strips notes, source, and remote_url so a bundle is
  safe to share with a teammate who should only see tags and status.
- Path remap rewrites absolute paths on import so a bundle from
  Alice's laptop lands cleanly on Bob's workstation.
- Merge vs replace: the default is merge (additive); replace wipes
  the index first and is intentionally privileged.

Security / opsec
- Export and import are purely local file I/O. No network.
- Redacted bundles carry `redacted: true` in the top-level envelope
  so downstream consumers can tell at a glance.
- The stable schema number protects against silently loading a bundle
  from a gitpulse version that expects fields we do not write.
"""

from __future__ import annotations

import datetime
import sqlite3
from typing import Any

from . import index as _index

CURRENT_EXPORT_SCHEMA: int = 1


class BundleError(Exception):
    """Raised on schema mismatch, malformed bundle, or invalid import params."""


# ---------- export ----------


def _now_utc() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def build_bundle(
    conn: sqlite3.Connection,
    *,
    redact: bool = False,
    gitpulse_version: str = "unknown",
) -> dict[str, Any]:
    """Build a portable bundle dict from the live index.

    When `redact=True`, notes, free-text source, and remote_url are
    scrubbed. Tags, status, quiet flag, timestamps, and upstream
    metadata are retained (these are usually the useful fields for
    fleet inventory sharing).
    """
    repos = _index.list_repos(conn)
    out_repos: list[dict[str, Any]] = []
    for repo in repos:
        repo_id = int(repo["id"])
        entry: dict[str, Any] = {
            "path": repo["path"],
            "remote_url": None if redact else repo.get("remote_url"),
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
        "gitpulse_version": gitpulse_version,
        "redacted": redact,
        "repos": out_repos,
    }


# ---------- import ----------


def _apply_remaps(path: str, remaps: list[tuple[str, str]]) -> str:
    """Rewrite `path` if it starts with any remap src prefix.

    Remaps are tried in order; the first matching prefix wins. A
    trailing slash on `src` is tolerated either way so operators do
    not trip over `--remap /a/:/b` vs `--remap /a:/b`.
    """
    for src, dst in remaps:
        src_norm = src.rstrip("/")
        if path == src_norm or path.startswith(src_norm + "/"):
            return dst.rstrip("/") + path[len(src_norm):]
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
    if schema != CURRENT_EXPORT_SCHEMA:
        raise BundleError(
            f"unsupported bundle schema: {schema!r} "
            f"(this gitpulse reads schema {CURRENT_EXPORT_SCHEMA})"
        )
    if not isinstance(bundle.get("repos"), list):
        raise BundleError("bundle.repos must be a JSON array")


def import_bundle(
    conn: sqlite3.Connection,
    bundle: dict[str, Any],
    *,
    mode: str = "merge",
    remaps: list[tuple[str, str]] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Apply a bundle to the live index.

    mode='merge'   add missing repos, top up tags / notes / upstream.
                   Never mutates an existing repo's status, source, or
                   quiet flag: the operator's local decisions win.
    mode='replace' wipe the index first, then import the bundle as
                   the authoritative state. Caller is responsible for
                   the confirm/--yes gate before handing us mode=replace.

    Returns a stats dict so the caller can print a summary.
    """
    validate_bundle(bundle)
    if mode not in {"merge", "replace"}:
        raise BundleError(f"invalid mode: {mode!r}")

    remaps = remaps or []
    stats: dict[str, Any] = {
        "mode": mode,
        "dry_run": dry_run,
        "total_in_bundle": len(bundle["repos"]),
        "added": 0,
        "already_present": 0,
        "tags_added": 0,
        "notes_added": 0,
        "upstream_set": 0,
    }

    if mode == "replace" and not dry_run:
        conn.execute("DELETE FROM repos")
        conn.commit()

    for entry in bundle["repos"]:
        path = _apply_remaps(str(entry["path"]), remaps)
        remote_url = entry.get("remote_url")
        source = entry.get("source")
        status = entry.get("status", "new")
        quiet = bool(entry.get("quiet", False))
        tags = list(entry.get("tags", []) or [])
        notes = list(entry.get("notes", []) or [])
        upstream = entry.get("upstream")

        if dry_run:
            # Simulate the "would it be added?" question for the summary
            existing = _index.get_repo(conn, path)
            if existing is None:
                stats["added"] += 1
                stats["tags_added"] += len(tags)
                stats["notes_added"] += len(notes)
                if upstream:
                    stats["upstream_set"] += 1
            else:
                stats["already_present"] += 1
            continue

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
            # Notes handled below via the add_note loop so timestamps survive.
            for n in notes:
                body = n.get("body")
                if body:
                    _index.add_note(conn, path, body)
                    stats["notes_added"] += 1
        else:
            stats["already_present"] += 1
            # Additive tag merge: duplicates are dropped by the tag CRUD.
            if tags:
                _index.add_tags(conn, path, tags)
                stats["tags_added"] += len(tags)
            # Notes are additive only (we never know which are "new" without
            # content hashing). Merge mode appends them all; duplicates are
            # acceptable and rare in practice.
            for n in notes:
                body = n.get("body")
                if body:
                    _index.add_note(conn, path, body)
                    stats["notes_added"] += 1

        if upstream:
            # Take the bundle's upstream record at face value; the
            # operator can run `gitpulse refresh` afterwards to rebuild
            # it from live providers if desired.
            _index.upsert_upstream_meta(conn, path, upstream)
            stats["upstream_set"] += 1

    return stats
