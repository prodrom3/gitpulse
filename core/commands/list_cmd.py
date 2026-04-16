"""`gitpulse list` - filter and print the repo fleet from the metadata index."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .. import index as _index
from ..output import Color, _supports_color
from ._common import maybe_migrate_watchlist


def add_parser(subparsers: Any) -> None:
    p = subparsers.add_parser(
        "list",
        help="List repositories in the metadata index",
        description="Filter and print the repo fleet.",
    )
    p.add_argument("--tag", default=None, help="Only repos carrying this tag")
    p.add_argument(
        "--status",
        default=None,
        choices=sorted(_index.VALID_STATUSES),
        help="Only repos in this triage status",
    )
    p.add_argument(
        "--untouched-over",
        type=int,
        default=None,
        metavar="DAYS",
        help="Only repos not pulled / shown in the last DAYS days",
    )
    p.add_argument(
        "--attack",
        default=None,
        metavar="TNNNN",
        help="Only repos tagged with this ATT&CK technique (e.g. T1059)",
    )
    p.add_argument(
        "--upstream-archived",
        action="store_true",
        help="Only repos whose upstream is archived (run `refresh` first)",
    )
    p.add_argument(
        "--upstream-dormant",
        type=int,
        default=None,
        metavar="DAYS",
        help="Only repos whose upstream had no push in the last DAYS days",
    )
    p.add_argument(
        "--upstream-stale",
        type=int,
        default=None,
        metavar="DAYS",
        help="Only repos whose upstream cache is older than DAYS (or missing)",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON (stable schema) instead of a table",
    )
    p.set_defaults(func=run)


_STATUS_COLOR = {
    "new": "cyan",
    "reviewed": "dim",
    "in-use": "green",
    "dropped": "dim",
    "flagged": "red",
}


def _print_table(repos: list[dict[str, Any]]) -> None:
    if not repos:
        print("(no matching repositories)", file=sys.stderr)
        return
    color = Color(enabled=_supports_color())
    rows: list[tuple[str, ...]] = []
    for repo in repos:
        status = repo["status"] or ""
        status_colored = getattr(color, _STATUS_COLOR.get(status, "dim"))(status)
        tags = ",".join(repo.get("tags", []))
        added = (repo["added_at"] or "")[:10]
        touched = (repo["last_touched_at"] or "")[:10] or "-"
        quiet = "Q" if repo.get("quiet") else " "
        rows.append(
            (str(repo["id"]), status_colored, quiet, added, touched, tags, repo["path"])
        )
    header: tuple[str, ...] = (
        color.bold("ID"),
        color.bold("STATUS"),
        " ",
        color.bold("ADDED"),
        color.bold("TOUCHED"),
        color.bold("TAGS"),
        color.bold("PATH"),
    )
    widths = [
        max(len(_strip_ansi(h)), *(len(_strip_ansi(row[i])) for row in rows))
        for i, h in enumerate(header)
    ]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*header))
    for row in rows:
        print(fmt.format(*row))


def _strip_ansi(s: str) -> str:
    # Cheap ANSI escape stripper for width math.
    import re as _re

    return _re.sub(r"\x1b\[[0-9;]*m", "", s)


def run(args: argparse.Namespace) -> int:
    maybe_migrate_watchlist()

    # --attack TNNNN is a convenience alias for --tag attack:tnnnn
    tag_filter = args.tag
    attack_filter = getattr(args, "attack", None)
    if attack_filter:
        from ..taxonomy import normalize_attack_tag

        tag_filter = normalize_attack_tag(attack_filter)

    try:
        with _index.connect() as conn:
            repos = _index.list_repos(
                conn,
                tag=tag_filter,
                status=args.status,
                untouched_days=args.untouched_over,
                upstream_archived=getattr(args, "upstream_archived", False),
                upstream_dormant_days=getattr(args, "upstream_dormant", None),
                upstream_stale_days=getattr(args, "upstream_stale", None),
            )
    except OSError as e:
        print(f"gitpulse: error: {e}", file=sys.stderr)
        return 1

    if args.json:
        output = {"total": len(repos), "repositories": repos}
        print(json.dumps(output, indent=2, default=str))
    else:
        _print_table(repos)

    return 0
