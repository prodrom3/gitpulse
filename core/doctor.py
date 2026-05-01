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
- orphan_tags:     tag rows with zero repo_tags references (cosmetic).
- topic_rules:     topic_rules.toml syntax / load status.
- auth_perms:      auth.toml exists with safe permissions on Unix.
- quiet_no_remote: quiet=1 repos that lack remote_url (un-refreshable).
- unconfigured_hosts: hosts present in the fleet that aren't in
                   auth.toml (refresh / --auto-tags will silently skip).
- schema_version:  reports the current schema version.
- db_size:         file size of the index on disk.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import stat
import sys
from typing import Any

from . import index as _index
from . import vault as _vault
from .paths import auth_config_path, topic_rules_path


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
        "orphan_tags": [],
        "topic_rules": {},
        "auth_perms": {},
        "quiet_no_remote": [],
        "unconfigured_hosts": [],
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

        if repo.get("quiet") and not repo.get("remote_url"):
            report["quiet_no_remote"].append({"id": repo_id, "path": path})

        meta = _index.get_upstream_meta(conn, repo_id)
        if meta is None:
            report["missing_upstream"].append({"id": repo_id, "path": path})

    report["duplicate_tags"] = _check_duplicate_tags(conn)
    report["orphan_tags"] = _check_orphan_tags(conn)
    report["orphan_vault_files"] = _check_orphan_vault(
        conn, vault_path, vault_subdir
    )
    report["topic_rules"] = _check_topic_rules()
    report["auth_perms"] = _check_auth_perms()
    report["unconfigured_hosts"] = _check_unconfigured_hosts(repos)

    issue_count = (
        len(report["stale_paths"])
        + len(report["missing_remote"])
        + len(report["missing_upstream"])
        + len(report["orphan_vault_files"])
        + len(report["duplicate_tags"])
        + len(report["orphan_tags"])
        + len(report["quiet_no_remote"])
        + len(report["unconfigured_hosts"])
    )
    if not report["topic_rules"].get("ok", True):
        issue_count += 1
    if not report["auth_perms"].get("ok", True):
        issue_count += 1
    report["issues_total"] = issue_count

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


def _check_orphan_tags(conn: sqlite3.Connection) -> list[str]:
    """Tag rows with zero repo_tags references. Cosmetic-only:
    invisible to `nostos list --tag X` queries but visible in the raw
    `tags` table. Cleaned up by `nostos tags --prune-orphans`."""
    rows = conn.execute(
        "SELECT t.name FROM tags t "
        "LEFT JOIN repo_tags rt ON rt.tag_id = t.id "
        "WHERE rt.tag_id IS NULL "
        "ORDER BY t.name"
    ).fetchall()
    return [row["name"] for row in rows]


def _check_topic_rules() -> dict[str, Any]:
    """Verify topic_rules.toml parses and returns coherent counts.

    Reports:
      ok:    True iff the file is missing or parses cleanly.
      path:  Where we looked.
      deny:  Number of deny entries (0 if missing).
      alias: Number of alias entries (0 if missing).
      error: First parse / load error message, or None.
    """
    from .topic_rules import load_rules

    path = topic_rules_path()
    out: dict[str, Any] = {
        "ok": True, "path": path, "deny": 0, "alias": 0, "error": None,
    }
    if not os.path.isfile(path):
        # Missing is fine - rules are optional.
        return out
    # load_rules() never raises; it returns an empty rules object on
    # any failure and logs a warning. Capture the warning by routing
    # log records into a list so we can surface the actual error here.
    handler_records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            handler_records.append(record)

    capture = _Capture()
    root = logging.getLogger()
    root.addHandler(capture)
    try:
        rules = load_rules()
    finally:
        root.removeHandler(capture)

    out["deny"] = len(rules.deny)
    out["alias"] = len(rules.alias)
    if handler_records:
        # Any warning raised by load_rules means it failed and fell
        # back to empty. Surface the first one.
        first = handler_records[0]
        if "Ignoring" in first.getMessage() and path in first.getMessage():
            out["ok"] = False
            out["error"] = first.getMessage()
    return out


def _check_auth_perms() -> dict[str, Any]:
    """Verify auth.toml has tight permissions on Unix.

    Reports:
      ok:    True iff the file is missing OR (Unix) is owned by current
             user and not group/world readable or writable.
      path:  Where we looked.
      mode:  File mode (None if missing).
      error: Human-readable description if not ok.
    """
    path = auth_config_path()
    out: dict[str, Any] = {"ok": True, "path": path, "mode": None, "error": None}
    if not os.path.isfile(path):
        return out
    try:
        st = os.stat(path)
    except OSError as e:
        out["ok"] = False
        out["error"] = f"stat({path}) failed: {e}"
        return out
    out["mode"] = oct(stat.S_IMODE(st.st_mode))
    if sys.platform == "win32":
        return out
    if st.st_uid != os.getuid():
        out["ok"] = False
        out["error"] = (
            f"owned by uid {st.st_uid}, not current user; auth probe will be skipped"
        )
        return out
    if st.st_mode & (stat.S_IWOTH | stat.S_IROTH | stat.S_IWGRP | stat.S_IRGRP):
        out["ok"] = False
        out["error"] = (
            f"permissions {out['mode']} too loose; "
            f"fix with: chmod 600 {path}"
        )
    return out


def _check_unconfigured_hosts(repos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Find hosts that show up in fleet remotes but aren't allow-listed
    in auth.toml. Refresh / --auto-tags will silently fail-closed for
    these repos.

    Special case: when auth.toml does not exist at all, the operator
    is opting out of upstream entirely. Flagging every repo as
    "unconfigured host" would be noise. Skip the check in that case.
    """
    if not os.path.isfile(auth_config_path()):
        return []

    from .auth import load_auth
    from .upstream import parse_remote_url

    auth = load_auth()
    counts: dict[str, int] = {}
    for repo in repos:
        if repo.get("quiet"):
            continue
        url = repo.get("remote_url") or ""
        parsed = parse_remote_url(url)
        if parsed is None:
            continue
        host = parsed[0]
        if not auth.is_allowed(host):
            counts[host] = counts.get(host, 0) + 1
    return [{"host": h, "repos": n} for h, n in sorted(counts.items())]


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

    if report.get("orphan_tags"):
        out.append(f"\n  Orphan tag rows ({len(report['orphan_tags'])}):")
        for name in report["orphan_tags"][:20]:
            out.append(f"    {name}")
        out.append("    fix: nostos tags --prune-orphans")

    if report.get("quiet_no_remote"):
        out.append(
            f"\n  Quiet repos with no remote ({len(report['quiet_no_remote'])}):"
        )
        for e in report["quiet_no_remote"][:20]:
            out.append(f"    id={e['id']}  {e['path']}")
        out.append(
            "    note: these will never refresh - either set a remote_url or accept"
        )

    if report.get("unconfigured_hosts"):
        out.append(
            f"\n  Hosts not in auth.toml "
            f"({len(report['unconfigured_hosts'])}):"
        )
        for e in report["unconfigured_hosts"]:
            out.append(f"    {e['host']:<30}  {e['repos']} repo(s) affected")
        out.append(
            "    fix: add a [hosts.\"<host>\"] block per host you want refreshed"
        )

    rules = report.get("topic_rules") or {}
    if rules and not rules.get("ok", True):
        out.append("\n  Topic rules file unreadable:")
        out.append(f"    {rules.get('path')}")
        out.append(f"    {rules.get('error')}")

    auth = report.get("auth_perms") or {}
    if auth and not auth.get("ok", True):
        out.append("\n  auth.toml permission issue:")
        out.append(f"    {auth.get('path')}")
        out.append(f"    {auth.get('error')}")

    return "\n".join(out) + "\n"
