"""`nostos show` - per-repo dashboard."""

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


def _print_human(repo: dict[str, Any], upstream: dict[str, Any] | None) -> None:
    print(f"ID:         {repo['id']}")
    print(f"Path:       {repo['path']}")
    print(f"Remote:     {repo['remote_url'] or '-'}")
    print(f"Source:     {repo['source'] or '-'}")
    print(f"Status:     {repo['status']}")
    print(f"Quiet:      {'yes (no upstream probe)' if repo['quiet'] else 'no'}")
    print(f"Added:      {repo['added_at']}")
    print(f"Touched:    {repo['last_touched_at'] or '-'}")
    print(f"Tags:       {', '.join(repo.get('tags', [])) or '-'}")

    if upstream:
        print("\nUpstream:")
        print(f"  Provider:      {upstream.get('provider') or '-'}")
        print(f"  Host:          {upstream.get('host') or '-'}")
        print(
            f"  Repo:          "
            f"{upstream.get('owner') or ''}/{upstream.get('name') or ''}"
        )
        print(f"  Stars:         {upstream.get('stars') if upstream.get('stars') is not None else '-'}")
        print(f"  Forks:         {upstream.get('forks') if upstream.get('forks') is not None else '-'}")
        print(f"  Open issues:   {upstream.get('open_issues') if upstream.get('open_issues') is not None else '-'}")
        print(f"  Archived:      {'yes' if upstream.get('archived') else 'no'}")
        default_branch = upstream.get("default_branch") or "-"
        print(f"  Default branch: {default_branch}")
        print(f"  License:       {upstream.get('license') or '-'}")
        print(f"  Last push:     {upstream.get('last_push') or '-'}")
        latest_release = upstream.get("latest_release") or "-"
        print(f"  Latest release: {latest_release}")
        print(f"  Cached:        {upstream.get('fetched_at') or '-'}")
        if upstream.get("fetch_error"):
            print(f"  Fetch error:   {upstream['fetch_error']}")
    else:
        print("\nUpstream:   - (run `nostos refresh` to populate)")

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
            upstream = _index.get_upstream_meta(conn, repo["id"])
            _index.touch_repo(conn, repo["path"])
    except OSError as e:
        return fail(str(e))

    if args.json:
        payload = dict(repo)
        payload["upstream"] = upstream
        print(json.dumps(payload, indent=2, default=str))
    else:
        _print_human(repo, upstream)
    return 0
