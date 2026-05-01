"""`nostos tags` - list every tag in the index with attachment counts.

Distinct from `nostos tag` (singular), which adds / removes tags on
one repo. `nostos tags` (plural) operates on the tag space across
the whole fleet:

- print every tag with the number of repos carrying it
- optionally prune orphan rows in the `tags` table that no longer
  link to any repo (cosmetic; `nostos list --tag X` ignores them
  regardless)
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from .. import index as _index
from ._common import fail, maybe_migrate_watchlist


def add_parser(subparsers: Any) -> None:
    p = subparsers.add_parser(
        "tags",
        help="List every tag in the index with attachment counts",
        description=(
            "Print all tags currently attached to one or more repos, "
            "sorted by attachment count (descending) then name. "
            "Use --prune-orphans to also delete tag rows that are no "
            "longer attached to any repo (cosmetic cleanup)."
        ),
    )
    p.add_argument(
        "--include-orphans",
        action="store_true",
        help="Also list tags with zero attached repos (count=0 rows)",
    )
    p.add_argument(
        "--prune-orphans",
        action="store_true",
        help="Delete orphan tag rows after listing (no-op when none exist)",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Emit a JSON array instead of human-readable lines",
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    maybe_migrate_watchlist()
    try:
        with _index.connect() as conn:
            entries = _index.list_tags_with_counts(
                conn, include_orphans=args.include_orphans
            )
            pruned = 0
            if args.prune_orphans:
                pruned = _index.prune_orphan_tags(conn)
    except OSError as e:
        return fail(str(e))

    if args.json:
        import json as _json
        print(_json.dumps({
            "tags": [{"name": n, "repos": c} for n, c in entries],
            "total_tags": len(entries),
            "orphans_pruned": pruned,
        }, indent=2))
    else:
        if not entries:
            print("nostos tags: no tags in the index", file=sys.stderr)
        else:
            width = max(len(n) for n, _ in entries)
            for name, n in entries:
                print(f"  {name:<{width}}  {n}")
            print(
                f"\n{len(entries)} tag(s).",
                file=sys.stderr,
            )
        if args.prune_orphans:
            msg = (
                f"pruned {pruned} orphan tag row(s)."
                if pruned
                else "no orphan tags to prune."
            )
            print(msg, file=sys.stderr)

    return 0
