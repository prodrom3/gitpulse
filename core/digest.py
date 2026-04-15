"""Weekly digest aggregations over the metadata index.

Purely local, zero network. Answers the operator's Monday-morning
question: "what moved in my fleet since last week?" Grouping:

- added          newly ingested repos since the cutoff
- refreshed      repos whose upstream_meta was re-fetched since the cutoff
- archived       ALL repos where upstream is currently archived (supply-chain
                 red flag; surfaced every week until the operator deals with it)
- flagged        ALL repos the operator marked status='flagged'
- stale_local    untouched (no pull / show) for > stale_days
- dormant        upstream last_push older than dormant_days
- counts         totals by status
"""

from __future__ import annotations

import datetime
import sqlite3
from typing import Any

_DEFAULT_SINCE_DAYS: int = 7
_DEFAULT_STALE_DAYS: int = 90
_DEFAULT_DORMANT_DAYS: int = 365


def _iso_cutoff(days: int) -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(days=days)
    ).isoformat(timespec="seconds")


def build_digest(
    conn: sqlite3.Connection,
    *,
    since_days: int = _DEFAULT_SINCE_DAYS,
    stale_days: int = _DEFAULT_STALE_DAYS,
    dormant_days: int = _DEFAULT_DORMANT_DAYS,
) -> dict[str, Any]:
    """Produce a digest dict. The shape is stable and versioned below
    so downstream consumers (dashboards, Slack notifiers) can rely on it.
    """
    cutoff = _iso_cutoff(since_days)

    added_rows = conn.execute(
        "SELECT r.*, (SELECT GROUP_CONCAT(t.name) FROM tags t "
        "JOIN repo_tags rt ON rt.tag_id = t.id WHERE rt.repo_id = r.id) AS tag_csv "
        "FROM repos r WHERE r.added_at >= ? ORDER BY r.added_at DESC",
        (cutoff,),
    ).fetchall()

    refreshed_rows = conn.execute(
        "SELECT r.*, u.fetched_at, u.archived, u.last_push, u.latest_release "
        "FROM repos r JOIN upstream_meta u ON u.repo_id = r.id "
        "WHERE u.fetched_at >= ? ORDER BY u.fetched_at DESC",
        (cutoff,),
    ).fetchall()

    archived_rows = conn.execute(
        "SELECT r.*, u.host, u.owner, u.name FROM repos r "
        "JOIN upstream_meta u ON u.repo_id = r.id WHERE u.archived = 1 "
        "ORDER BY r.path"
    ).fetchall()

    flagged_rows = conn.execute(
        "SELECT * FROM repos WHERE status = 'flagged' ORDER BY added_at DESC"
    ).fetchall()

    stale_cutoff = _iso_cutoff(stale_days)
    # SQLite ORDER BY ASC puts NULLs first by default, which is the
    # "never touched" case we want surfaced at the top of this section.
    stale_rows = conn.execute(
        "SELECT * FROM repos "
        "WHERE last_touched_at IS NULL OR last_touched_at < ? "
        "ORDER BY last_touched_at ASC, path",
        (stale_cutoff,),
    ).fetchall()

    dormant_cutoff = _iso_cutoff(dormant_days)
    dormant_rows = conn.execute(
        "SELECT r.*, u.last_push FROM repos r "
        "JOIN upstream_meta u ON u.repo_id = r.id "
        "WHERE u.last_push IS NOT NULL AND u.last_push < ? "
        "ORDER BY u.last_push ASC",
        (dormant_cutoff,),
    ).fetchall()

    counts_by_status = {
        row["status"]: int(row["n"])
        for row in conn.execute(
            "SELECT status, COUNT(*) AS n FROM repos GROUP BY status"
        )
    }
    total = int(conn.execute("SELECT COUNT(*) AS n FROM repos").fetchone()["n"])

    return {
        "schema": 1,
        "generated_at": datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat(timespec="seconds"),
        "window_days": since_days,
        "stale_days": stale_days,
        "dormant_days": dormant_days,
        "counts": {"total": total, "by_status": counts_by_status},
        "added": [_row(r) for r in added_rows],
        "refreshed": [_row(r) for r in refreshed_rows],
        "archived": [_row(r) for r in archived_rows],
        "flagged": [_row(r) for r in flagged_rows],
        "stale_local": [_row(r) for r in stale_rows],
        "dormant": [_row(r) for r in dormant_rows],
    }


def _row(row: sqlite3.Row) -> dict[str, Any]:
    d: dict[str, Any] = dict(row)
    # Normalise tag_csv to a list when the added-section query populated it.
    if "tag_csv" in d:
        raw = d.pop("tag_csv")
        d["tags"] = sorted(raw.split(",")) if raw else []
    return d


def render_human(digest: dict[str, Any]) -> str:
    """Render a digest dict as a readable text report."""
    out: list[str] = []

    def section(title: str, rows: list[dict[str, Any]], fmt: Any) -> None:
        out.append(f"\n== {title} ({len(rows)}) ==")
        if not rows:
            out.append("  (none)")
            return
        for r in rows:
            out.append("  " + fmt(r))

    out.append(
        f"gitpulse digest ({digest['generated_at']}) - "
        f"window {digest['window_days']}d"
    )
    counts = digest["counts"]
    by_status = counts["by_status"]
    status_summary = ", ".join(f"{k}={v}" for k, v in sorted(by_status.items())) or "(none)"
    out.append(f"Total repos: {counts['total']} | {status_summary}")

    section(
        "New intakes",
        digest["added"],
        lambda r: f"{r['path']}  [{','.join(r.get('tags', []))}]  (source: {r.get('source') or '-'})",
    )
    section(
        "Refreshed upstream",
        digest["refreshed"],
        lambda r: f"{r['path']}  archived={bool(r.get('archived'))}  "
        f"last_push={r.get('last_push') or '-'}  release={r.get('latest_release') or '-'}",
    )
    section(
        "Currently archived upstream (supply-chain flag)",
        digest["archived"],
        lambda r: f"{r['path']}  ({r.get('host') or '-'}:{r.get('owner') or ''}/{r.get('name') or ''})",
    )
    section(
        "Operator-flagged",
        digest["flagged"],
        lambda r: f"{r['path']}  (added {r.get('added_at')})",
    )
    section(
        f"Stale local (untouched > {digest['stale_days']}d)",
        digest["stale_local"],
        lambda r: f"{r['path']}  last_touched={r.get('last_touched_at') or 'never'}",
    )
    section(
        f"Dormant upstream (no push > {digest['dormant_days']}d)",
        digest["dormant"],
        lambda r: f"{r['path']}  last_push={r.get('last_push')}",
    )

    return "\n".join(out) + "\n"
