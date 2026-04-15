"""`gitpulse show` - per-repo dashboard."""

from __future__ import annotations

import argparse
import json
from typing import Any

from .. import index as _index
from ._common import fail, maybe_migrate_watchlist


def add_parser(subparsers: Any) -> None:
    p = subparsers.add_parser(
        "show",
        help="Show full metadata for a single repository",
        description="Print identity, tags, status, notes for a single repo.",
    )
    p.add_argument("target", metavar="PATH_OR_ID", help="Repo path or index id")
    p.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON instead of human-readable text",
    )
    p.set_defaults(func=run)


def _print_human(repo: dict[str, Any]) -> None:
    print(f"ID:         {repo['id']}")
    print(f"Path:       {repo['path']}")
    print(f"Remote:     {repo['remote_url'] or '-'}")
    print(f"Source:     {repo['source'] or '-'}")
    print(f"Status:     {repo['status']}")
    print(f"Quiet:      {'yes (no upstream probe)' if repo['quiet'] else 'no'}")
    print(f"Added:      {repo['added_at']}")
    print(f"Touched:    {repo['last_touched_at'] or '-'}")
    print(f"Tags:       {', '.join(repo.get('tags', [])) or '-'}")
    notes = repo.get("notes", [])
    if notes:
        print("\nNotes:")
        for n in notes:
            print(f"  [{n['created_at']}] {n['body']}")
    else:
        print("\nNotes:      -")


def run(args: argparse.Namespace) -> int:
    maybe_migrate_watchlist()

    try:
        with _index.connect() as conn:
            repo = _index.get_repo(conn, args.target)
            if repo is None:
                return fail(f"not in index: {args.target}")
            _index.touch_repo(conn, repo["path"])
    except OSError as e:
        return fail(str(e))

    if args.json:
        print(json.dumps(repo, indent=2, default=str))
    else:
        _print_human(repo)
    return 0
