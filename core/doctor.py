"""Index health checks for `nostos doctor`.

Runs a battery of read-only checks against the metadata index and
(optionally) the vault directory, reporting issues the operator should
address. No network, no mutations unless --fix is given.

Checks performed
- stale_paths:     repos whose indexed path no longer exists on disk.
- missing_remote:  repos with no remote_url recorded.
- missing_upstream: repos with no upstream_meta row (never refreshed).
- orphan_vault:    vault .md files whose nostos_id has no matching
                   repo in the index.
- duplicate_tags:  tags that differ only by case (data-model quirk;
                   tags are lowercased on write but older imports may
                   have created case variants).
- schema_version:  reports the current schema version.
- db_size:         file size of the index on disk.
"""

from __future__ import annotations

import os
import sqlite3
from typing import Any

from . import index as _index
from . import vault as _vault


def run_checks(
    conn: sqlite3.Connection,
    *,
    vault_path: str | None = None,
    vault_subdir: str = "repos",
) -> dict[str, Any]:
    """Run every check and return a structured report."""
    report: dict[str, Any] = {
        "schema_version": _check_schema_version(conn),
        "db_size_bytes": _check_db_size(),
        "total_repos": 0,
        "stale_paths": [],
        "missing_remote": [],
        "missing_upstream": [],
        "orphan_vault_files": [],
        "duplicate_tags": [],
        "issues_total": 0,
    }

    repos = _index.list_repos(conn)
    report["total_repos"] = len(repos)

    for repo in repos:
        path = repo["path"]
        repo_id = int(repo["id"])

        if not os.path.isdir(path):
            report["stale_paths"].append({"id": repo_id, "path": path})

        if not repo.get("remote_url"):
            report["missing_remote"].append({"id": repo_id, "path": path})

        meta = _index.get_upstream_meta(conn, repo_id)
        if meta is None:
            report["missing_upstream"].append({"id": repo_id, "path": path})

    report["duplicate_tags"] = _check_duplicate_tags(conn)
    report["orphan_vault_files"] = _check_orphan_vault(
        conn, vault_path, vault_subdir
    )

    report["issues_total"] = (
        len(report["stale_paths"])
        + len(report["missing_remote"])
        + len(report["missing_upstream"])
        + len(report["orphan_vault_files"])
        + len(report["duplicate_tags"])
    )

    return report


def _check_schema_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def _check_db_size() -> int:
    from .paths import index_db_path

    path = index_db_path()
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _check_duplicate_tags(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Find tag names that differ only by case."""
    rows = conn.execute(
        "SELECT name, COUNT(*) AS n FROM tags "
        "GROUP BY LOWER(name) HAVING n > 1"
    ).fetchall()
    return [{"name": row["name"], "count": int(row["n"])} for row in rows]


def _check_orphan_vault(
    conn: sqlite3.Connection,
    vault_path: str | None,
    vault_subdir: str,
) -> list[str]:
    """Find vault .md files whose nostos_id does not match any repo."""
    if not vault_path:
        return []
    repos_dir = os.path.join(
        os.path.abspath(os.path.expanduser(vault_path)), vault_subdir
    )
    if not os.path.isdir(repos_dir):
        return []

    repo_ids: set[int] = set()
    for row in conn.execute("SELECT id FROM repos"):
        repo_ids.add(int(row["id"]))

    orphans: list[str] = []
    for name in sorted(os.listdir(repos_dir)):
        if not name.endswith(".md"):
            continue
        md_path = os.path.join(repos_dir, name)
        try:
            with open(md_path, encoding="utf-8") as f:
                text = f.read()
            front, _ = _vault.parse_frontmatter(text)
            gp_id = front.get("nostos_id")
            if not isinstance(gp_id, int) or gp_id not in repo_ids:
                orphans.append(md_path)
        except (OSError, _vault.FrontmatterError):
            orphans.append(md_path)

    return orphans


def fix_stale_paths(
    conn: sqlite3.Connection,
    stale: list[dict[str, Any]],
) -> int:
    """Mark stale repos as status='flagged' so the operator can triage them."""
    fixed = 0
    for entry in stale:
        _index.update_status(conn, entry["id"], "flagged")
        fixed += 1
    return fixed


def render_human(report: dict[str, Any]) -> str:
    """Render the doctor report as readable text."""
    out: list[str] = []
    out.append(
        f"nostos doctor - schema v{report['schema_version']}, "
        f"DB {report['db_size_bytes']:,} bytes, "
        f"{report['total_repos']} repo(s)"
    )

    if report["issues_total"] == 0:
        out.append("\nAll checks passed. No issues found.")
        return "\n".join(out) + "\n"

    out.append(f"\n{report['issues_total']} issue(s) found:\n")

    if report["stale_paths"]:
        out.append(f"  Stale paths ({len(report['stale_paths'])}):")
        for e in report["stale_paths"][:20]:
            out.append(f"    id={e['id']}  {e['path']}")
        out.append("    fix: nostos doctor --fix flags these as 'flagged'")

    if report["missing_remote"]:
        out.append(f"\n  Missing remote_url ({len(report['missing_remote'])}):")
        for e in report["missing_remote"][:20]:
            out.append(f"    id={e['id']}  {e['path']}")
        out.append("    fix: nostos show <id> and add the remote manually if needed")

    if report["missing_upstream"]:
        out.append(f"\n  Never refreshed ({len(report['missing_upstream'])}):")
        for e in report["missing_upstream"][:20]:
            out.append(f"    id={e['id']}  {e['path']}")
        out.append("    fix: nostos refresh")

    if report["orphan_vault_files"]:
        out.append(f"\n  Orphan vault files ({len(report['orphan_vault_files'])}):")
        for p in report["orphan_vault_files"][:20]:
            out.append(f"    {p}")
        out.append("    fix: nostos doctor --fix deletes these")

    if report["duplicate_tags"]:
        out.append(f"\n  Duplicate tags by case ({len(report['duplicate_tags'])}):")
        for e in report["duplicate_tags"]:
            out.append(f"    '{e['name']}' x{e['count']}")

    return "\n".join(out) + "\n"
