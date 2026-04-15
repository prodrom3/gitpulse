"""`gitpulse tag` - add / remove tags on a repository.

Tags prefixed with `+` are added; tags prefixed with `-` are removed.
A bare tag (no prefix) is treated as an add.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from .. import index as _index
from ._common import fail, maybe_migrate_watchlist


def add_parser(subparsers: Any) -> None:
    p = subparsers.add_parser(
        "tag",
        help="Add or remove tags on a repository",
        description="Edit tags: +tag adds, -tag removes, bare tag adds.",
    )
    p.add_argument("target", metavar="PATH_OR_ID")
    p.add_argument("tags", nargs="+", metavar="+TAG|-TAG|TAG")
    p.set_defaults(func=run)


def _split(tag_args: list[str]) -> tuple[list[str], list[str]]:
    to_add: list[str] = []
    to_remove: list[str] = []
    for raw in tag_args:
        t = raw.strip()
        if not t:
            continue
        if t.startswith("+"):
            to_add.append(t[1:])
        elif t.startswith("-"):
            to_remove.append(t[1:])
        else:
            to_add.append(t)
    return to_add, to_remove


def run(args: argparse.Namespace) -> int:
    maybe_migrate_watchlist()
    to_add, to_remove = _split(args.tags)
    try:
        with _index.connect() as conn:
            repo = _index.get_repo(conn, args.target)
            if repo is None:
                return fail(f"not in index: {args.target}")
            if to_add:
                _index.add_tags(conn, repo["id"], to_add)
            if to_remove:
                _index.remove_tags(conn, repo["id"], to_remove)
            final = _index.get_tags(conn, repo["id"])
    except OSError as e:
        return fail(str(e))

    print(f"tags: {', '.join(final) or '(none)'}", file=sys.stderr)
    return 0
