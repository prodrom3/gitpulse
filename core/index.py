"""Metadata index for the nostos repo fleet.

A single SQLite file at $XDG_DATA_HOME/nostos/index.db stores per-repo
identity, triage state, tags, and free-text notes. The file is created
0600 and opened with hardened PRAGMAs (WAL, secure_delete, foreign_keys).

The index is treated as an intelligence artifact: it reveals the
operator's full toolchain. Place the data directory on an encrypted
volume (LUKS / FileVault / BitLocker) for at-rest protection.
"""

from __future__ import annotations

import datetime
import os
import sqlite3
import stat
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from .paths import ensure_data_dir, index_db_path

VALID_STATUSES: frozenset[str] = frozenset(
    {"new", "reviewed", "in-use", "dropped", "flagged"}
)

CURRENT_SCHEMA_VERSION: int = 2

_SCHEMA_V1: str = """
CREATE TABLE schema_version (version INTEGER PRIMARY KEY);
INSERT INTO schema_version VALUES (1);

CREATE TABLE repos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    path            TEXT NOT NULL UNIQUE,
    remote_url      TEXT,
    source          TEXT,
    added_at        TEXT NOT NULL,
    last_touched_at TEXT,
    status          TEXT NOT NULL DEFAULT 'new'
                    CHECK (status IN ('new','reviewed','in-use','dropped','flagged')),
    quiet           INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_repos_status    ON repos(status);
CREATE INDEX idx_repos_added_at  ON repos(added_at);
CREATE INDEX idx_repos_last_t_at ON repos(last_touched_at);

CREATE TABLE tags (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE repo_tags (
    repo_id INTEGER NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
    tag_id  INTEGER NOT NULL REFERENCES tags(id)  ON DELETE CASCADE,
    PRIMARY KEY (repo_id, tag_id)
);

CREATE TABLE notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id    INTEGER NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
    body       TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX idx_notes_repo_id ON notes(repo_id);
"""

# v2 adds the upstream_meta table. Each row is 1:1 with a repo row and
# caches the most recent successful probe of the upstream host. fetched_at
# is the TTL anchor. fetch_error holds a short message when the probe
# failed, so operators can see why a refresh did not populate fields.
_MIGRATION_V1_TO_V2: str = """
CREATE TABLE upstream_meta (
    repo_id          INTEGER PRIMARY KEY REFERENCES repos(id) ON DELETE CASCADE,
    provider         TEXT NOT NULL,
    host             TEXT NOT NULL,
    owner            TEXT NOT NULL,
    name             TEXT NOT NULL,
    description      TEXT,
    stars            INTEGER,
    forks            INTEGER,
    open_issues      INTEGER,
    archived         INTEGER NOT NULL DEFAULT 0,
    default_branch   TEXT,
    license          TEXT,
    last_push        TEXT,
    latest_release   TEXT,
    fetched_at       TEXT NOT NULL,
    fetch_error      TEXT
);
CREATE INDEX idx_upstream_archived ON upstream_meta(archived);
CREATE INDEX idx_upstream_fetched  ON upstream_meta(fetched_at);
CREATE INDEX idx_upstream_last_push ON upstream_meta(last_push);

INSERT INTO schema_version VALUES (2);
"""


# ---------- connection / schema ----------


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA secure_delete = ON")
    conn.execute("PRAGMA foreign_keys = ON")


def _chmod_0600(path: str) -> None:
    if sys.platform == "win32":
        return
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def _current_schema_version(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
    ).fetchone()
    if row is None:
        return 0
    result = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    return int(result[0]) if result and result[0] is not None else 0


def _ensure_schema(conn: sqlite3.Connection) -> None:
    version = _current_schema_version(conn)
    if version == CURRENT_SCHEMA_VERSION:
        return
    if version > CURRENT_SCHEMA_VERSION:
        raise RuntimeError(
            f"index.db schema version {version} is newer than this nostos "
            f"release supports ({CURRENT_SCHEMA_VERSION}). Upgrade nostos."
        )
    if version == 0:
        conn.executescript(_SCHEMA_V1)
        version = 1
    if version == 1:
        conn.executescript(_MIGRATION_V1_TO_V2)
        version = 2
    conn.commit()


@contextmanager
def connect(path: str | None = None) -> Iterator[sqlite3.Connection]:
    """Open (and create if needed) the metadata index.

    The database file is created with 0600 permissions on Unix. The
    PRAGMAs journal_mode=WAL, secure_delete=ON, and foreign_keys=ON
    are applied on every connection.
    """
    if path is None:
        ensure_data_dir()
        path = index_db_path()
    is_new = not os.path.exists(path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        if is_new:
            _chmod_0600(path)
        _apply_pragmas(conn)
        _ensure_schema(conn)
        yield conn
    finally:
        conn.close()


# ---------- helpers ----------


def _now_utc() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _normalize_path(path: str) -> str:
    return os.path.realpath(os.path.expanduser(path))


def _resolve_repo_id(conn: sqlite3.Connection, selector: str | int) -> int | None:
    """Accept a repo id (int or all-digit str) or a path, return the id."""
    if isinstance(selector, int):
        row = conn.execute("SELECT id FROM repos WHERE id = ?", (selector,)).fetchone()
        return int(row["id"]) if row else None
    selector_str = str(selector)
    if selector_str.isdigit():
        row = conn.execute(
            "SELECT id FROM repos WHERE id = ?", (int(selector_str),)
        ).fetchone()
        if row:
            return int(row["id"])
    normalized = _normalize_path(selector_str)
    row = conn.execute("SELECT id FROM repos WHERE path = ?", (normalized,)).fetchone()
    return int(row["id"]) if row else None


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


# ---------- repos ----------


def add_repo(
    conn: sqlite3.Connection,
    path: str,
    *,
    remote_url: str | None = None,
    source: str | None = None,
    status: str = "new",
    quiet: bool = False,
    tags: list[str] | None = None,
    note: str | None = None,
) -> int:
    """Insert a repo or return the existing id if path already registered.

    When the path exists already, only missing fields are filled in;
    existing metadata (status, source, quiet) is left untouched. Tags
    and notes passed here are additive.
    """
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid status: {status!r}")
    normalized = _normalize_path(path)
    now = _now_utc()

    existing = conn.execute(
        "SELECT id, remote_url, source FROM repos WHERE path = ?", (normalized,)
    ).fetchone()
    if existing:
        repo_id = int(existing["id"])
        updates = []
        params: list[Any] = []
        if remote_url and not existing["remote_url"]:
            updates.append("remote_url = ?")
            params.append(remote_url)
        if source and not existing["source"]:
            updates.append("source = ?")
            params.append(source)
        if updates:
            params.append(repo_id)
            conn.execute(
                f"UPDATE repos SET {', '.join(updates)} WHERE id = ?", params
            )
    else:
        cur = conn.execute(
            """
            INSERT INTO repos (path, remote_url, source, added_at, status, quiet)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (normalized, remote_url, source, now, status, 1 if quiet else 0),
        )
        repo_id = int(cur.lastrowid or 0)

    if tags:
        _add_tags(conn, repo_id, tags)
    if note:
        _add_note(conn, repo_id, note, now)

    conn.commit()
    return repo_id


def list_repos(
    conn: sqlite3.Connection,
    *,
    tag: str | None = None,
    status: str | None = None,
    untouched_days: int | None = None,
    upstream_archived: bool = False,
    upstream_dormant_days: int | None = None,
    upstream_stale_days: int | None = None,
) -> list[dict[str, Any]]:
    """Return repos matching the given filters, newest-added first.

    Upstream filters implicitly LEFT JOIN upstream_meta:
    - upstream_archived: only repos whose upstream row has archived=1.
    - upstream_dormant_days: upstream last_push older than N days
      (NULL last_push is excluded; we can't call a repo with no known
      push date "dormant" without guessing).
    - upstream_stale_days: upstream cache older than N days OR missing
      (never fetched).
    """
    where: list[str] = []
    params: list[Any] = []

    if tag:
        where.append(
            "r.id IN (SELECT rt.repo_id FROM repo_tags rt "
            "JOIN tags t ON t.id = rt.tag_id WHERE t.name = ?)"
        )
        params.append(tag)

    if status:
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid status: {status!r}")
        where.append("r.status = ?")
        params.append(status)

    if untouched_days is not None:
        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
            days=untouched_days
        )
        cutoff_iso = cutoff.isoformat(timespec="seconds")
        # "untouched" means last_touched_at is NULL or older than cutoff
        where.append("(r.last_touched_at IS NULL OR r.last_touched_at < ?)")
        params.append(cutoff_iso)

    if upstream_archived:
        where.append("u.archived = 1")

    if upstream_dormant_days is not None:
        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
            days=upstream_dormant_days
        )
        where.append("u.last_push IS NOT NULL AND u.last_push < ?")
        params.append(cutoff.isoformat(timespec="seconds"))

    if upstream_stale_days is not None:
        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
            days=upstream_stale_days
        )
        where.append("(u.fetched_at IS NULL OR u.fetched_at < ?)")
        params.append(cutoff.isoformat(timespec="seconds"))

    sql = "SELECT r.* FROM repos r LEFT JOIN upstream_meta u ON u.repo_id = r.id"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY r.added_at DESC, r.id DESC"

    rows = conn.execute(sql, params).fetchall()
    result = []
    for row in rows:
        repo = _row_to_dict(row)
        repo["tags"] = _get_tags_for_repo(conn, int(row["id"]))
        result.append(repo)
    return result


def get_repo(
    conn: sqlite3.Connection, selector: str | int
) -> dict[str, Any] | None:
    repo_id = _resolve_repo_id(conn, selector)
    if repo_id is None:
        return None
    row = conn.execute("SELECT * FROM repos WHERE id = ?", (repo_id,)).fetchone()
    if row is None:
        return None
    repo = _row_to_dict(row)
    repo["tags"] = _get_tags_for_repo(conn, repo_id)
    repo["notes"] = get_notes(conn, repo_id)
    return repo


def remove_repo(conn: sqlite3.Connection, selector: str | int) -> bool:
    repo_id = _resolve_repo_id(conn, selector)
    if repo_id is None:
        return False
    conn.execute("DELETE FROM repos WHERE id = ?", (repo_id,))
    conn.commit()
    return True


def update_status(
    conn: sqlite3.Connection, selector: str | int, status: str
) -> bool:
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid status: {status!r}")
    repo_id = _resolve_repo_id(conn, selector)
    if repo_id is None:
        return False
    conn.execute("UPDATE repos SET status = ? WHERE id = ?", (status, repo_id))
    conn.commit()
    return True


def set_quiet(
    conn: sqlite3.Connection, selector: str | int, quiet: bool
) -> bool:
    repo_id = _resolve_repo_id(conn, selector)
    if repo_id is None:
        return False
    conn.execute(
        "UPDATE repos SET quiet = ? WHERE id = ?", (1 if quiet else 0, repo_id)
    )
    conn.commit()
    return True


def touch_repo(conn: sqlite3.Connection, path: str) -> bool:
    """Mark a repo as touched now. Used after pull or show."""
    normalized = _normalize_path(path)
    cur = conn.execute(
        "UPDATE repos SET last_touched_at = ? WHERE path = ?",
        (_now_utc(), normalized),
    )
    conn.commit()
    return cur.rowcount > 0


# ---------- tags ----------


def _add_tags(conn: sqlite3.Connection, repo_id: int, tags: list[str]) -> None:
    for raw in tags:
        name = raw.strip().lower()
        if not name:
            continue
        conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (name,))
        tag_row = conn.execute(
            "SELECT id FROM tags WHERE name = ?", (name,)
        ).fetchone()
        if tag_row:
            conn.execute(
                "INSERT OR IGNORE INTO repo_tags (repo_id, tag_id) VALUES (?, ?)",
                (repo_id, int(tag_row["id"])),
            )


def add_tags(
    conn: sqlite3.Connection, selector: str | int, tags: list[str]
) -> bool:
    repo_id = _resolve_repo_id(conn, selector)
    if repo_id is None:
        return False
    _add_tags(conn, repo_id, tags)
    conn.commit()
    return True


def remove_tags(
    conn: sqlite3.Connection, selector: str | int, tags: list[str]
) -> bool:
    repo_id = _resolve_repo_id(conn, selector)
    if repo_id is None:
        return False
    for raw in tags:
        name = raw.strip().lower()
        if not name:
            continue
        conn.execute(
            """
            DELETE FROM repo_tags WHERE repo_id = ?
            AND tag_id IN (SELECT id FROM tags WHERE name = ?)
            """,
            (repo_id, name),
        )
    conn.commit()
    return True


def _get_tags_for_repo(conn: sqlite3.Connection, repo_id: int) -> list[str]:
    rows = conn.execute(
        """
        SELECT t.name FROM tags t
        JOIN repo_tags rt ON rt.tag_id = t.id
        WHERE rt.repo_id = ?
        ORDER BY t.name
        """,
        (repo_id,),
    ).fetchall()
    return [row["name"] for row in rows]


def get_tags(conn: sqlite3.Connection, selector: str | int) -> list[str]:
    repo_id = _resolve_repo_id(conn, selector)
    if repo_id is None:
        return []
    return _get_tags_for_repo(conn, repo_id)


# ---------- notes ----------


def _add_note(
    conn: sqlite3.Connection, repo_id: int, body: str, created_at: str
) -> None:
    conn.execute(
        "INSERT INTO notes (repo_id, body, created_at) VALUES (?, ?, ?)",
        (repo_id, body, created_at),
    )


def add_note(
    conn: sqlite3.Connection, selector: str | int, body: str
) -> bool:
    repo_id = _resolve_repo_id(conn, selector)
    if repo_id is None:
        return False
    _add_note(conn, repo_id, body, _now_utc())
    conn.commit()
    return True


def get_notes(
    conn: sqlite3.Connection, selector: str | int
) -> list[dict[str, Any]]:
    repo_id = _resolve_repo_id(conn, selector)
    if repo_id is None:
        return []
    rows = conn.execute(
        """
        SELECT id, body, created_at FROM notes
        WHERE repo_id = ?
        ORDER BY created_at ASC, id ASC
        """,
        (repo_id,),
    ).fetchall()
    return [_row_to_dict(row) for row in rows]


# ---------- upstream metadata ----------

_UPSTREAM_COLUMNS = (
    "repo_id",
    "provider",
    "host",
    "owner",
    "name",
    "description",
    "stars",
    "forks",
    "open_issues",
    "archived",
    "default_branch",
    "license",
    "last_push",
    "latest_release",
    "fetched_at",
    "fetch_error",
)


def upsert_upstream_meta(
    conn: sqlite3.Connection,
    selector: str | int,
    meta: dict[str, Any],
) -> bool:
    """Insert or replace the upstream metadata row for the given repo.

    `meta` keys beyond the schema are silently ignored. `fetched_at`
    is set to now() if missing. `archived` is coerced to 0/1. When
    `fetch_error` is set, the caller should either omit the other
    fields or pass partial data captured before the failure.
    """
    repo_id = _resolve_repo_id(conn, selector)
    if repo_id is None:
        return False

    row: dict[str, Any] = {col: meta.get(col) for col in _UPSTREAM_COLUMNS}
    row["repo_id"] = repo_id
    row["fetched_at"] = meta.get("fetched_at") or _now_utc()
    row["archived"] = 1 if meta.get("archived") else 0

    cols = ", ".join(_UPSTREAM_COLUMNS)
    placeholders = ", ".join(["?"] * len(_UPSTREAM_COLUMNS))
    conn.execute(
        f"INSERT OR REPLACE INTO upstream_meta ({cols}) VALUES ({placeholders})",
        tuple(row[col] for col in _UPSTREAM_COLUMNS),
    )
    conn.commit()
    return True


def get_upstream_meta(
    conn: sqlite3.Connection, selector: str | int
) -> dict[str, Any] | None:
    repo_id = _resolve_repo_id(conn, selector)
    if repo_id is None:
        return None
    row = conn.execute(
        "SELECT * FROM upstream_meta WHERE repo_id = ?", (repo_id,)
    ).fetchone()
    return _row_to_dict(row) if row else None


def list_stale_upstream(
    conn: sqlite3.Connection,
    ttl_days: int = 7,
    *,
    include_never_fetched: bool = True,
) -> list[dict[str, Any]]:
    """Return repos whose upstream_meta is missing or older than ttl_days.

    `include_never_fetched` defaults to True so a fresh index produces
    a useful first-run refresh batch. Set to False when you only want
    cache-expired entries.
    """
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        days=ttl_days
    )
    cutoff_iso = cutoff.isoformat(timespec="seconds")

    if include_never_fetched:
        sql = """
            SELECT r.* FROM repos r
            LEFT JOIN upstream_meta u ON u.repo_id = r.id
            WHERE u.fetched_at IS NULL OR u.fetched_at < ?
            ORDER BY r.added_at DESC, r.id DESC
        """
    else:
        sql = """
            SELECT r.* FROM repos r
            JOIN upstream_meta u ON u.repo_id = r.id
            WHERE u.fetched_at < ?
            ORDER BY r.added_at DESC, r.id DESC
        """
    rows = conn.execute(sql, (cutoff_iso,)).fetchall()
    result = []
    for row in rows:
        repo = _row_to_dict(row)
        repo["tags"] = _get_tags_for_repo(conn, int(row["id"]))
        result.append(repo)
    return result


# ---------- migration from legacy watchlist ----------


def migrate_watchlist(conn: sqlite3.Connection, watchlist_path: str) -> int:
    """Import entries from ~/.nostos_repos into the index.

    Returns the number of rows inserted. Existing entries are left alone.
    Caller is responsible for renaming the source file after this runs.
    """
    if not os.path.isfile(watchlist_path):
        return 0
    inserted = 0
    with open(watchlist_path, encoding="utf-8") as f:
        for line in f:
            entry = line.strip()
            if not entry or entry.startswith("#"):
                continue
            try:
                add_repo(
                    conn,
                    entry,
                    source="legacy-watchlist",
                    status="reviewed",
                )
                inserted += 1
            except sqlite3.Error:
                continue
    return inserted
