"""`nostos search` - free-text search across the indexed fleet.

Searches case-insensitively across:
- repo path on disk
- remote_url
- source (provenance text)
- attached tag names
- note bodies
- upstream description (populated by `nostos refresh`)

OR semantics across fields (any match qualifies). For tag-only or
status-only filtering, prefer `nostos list --tag <X>` / `--status <Y>` -
they're tighter. Use this when you don't remember the exact tag.
"""

from __future__ import annotations

import argparse
import json as _json
import sys
from typing import Any

from .. import index as _index
from ..output import Color, _supports_color
from ._common import maybe_migrate_watchlist


def add_parser(subparsers: Any) -> None:
    p = subparsers.add_parser(
        "search",
        help="Free-text search across paths, tags, notes, descriptions",
        description=(
            "Case-insensitive substring search across path, remote_url, "
            "source, tag names, note bodies, and upstream descriptions. "
            "Returns matching repos newest-first."
        ),
    )
    p.add_argument(
        "query",
        metavar="QUERY",
        help="Search query (substring; case-insensitive)",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Cap to the first N matches",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON (stable schema) instead of a table",
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    maybe_migrate_watchlist()

    try:
        with _index.connect() as conn:
            repos = _index.search_repos(conn, args.query, limit=args.limit)
    except OSError as e:
        print(f"nostos search: error: {e}", file=sys.stderr)
        return 1

    if args.json:
        print(_json.dumps(
            {"query": args.query, "total": len(repos), "repositories": repos},
            indent=2,
            default=str,
        ))
        return 0

    if not repos:
        print(f"nostos search: no matches for {args.query!r}", file=sys.stderr)
        return 0

    color = Color(enabled=_supports_color())
    print(color.bold(f"{len(repos)} match(es) for {args.query!r}:"))
    for repo in repos:
        tags = ",".join(repo.get("tags") or [])
        added = (repo.get("added_at") or "")[:10]
        print(f"  id={repo['id']:<4} {added}  {repo['path']}")
        if tags:
            print(f"    tags: {tags}")
    return 0
