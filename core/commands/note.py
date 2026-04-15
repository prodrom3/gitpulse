"""`gitpulse note` - append a timestamped note to a repository."""

from __future__ import annotations

import argparse
import sys
from typing import Any

from .. import index as _index
from ._common import fail, maybe_migrate_watchlist


def add_parser(subparsers: Any) -> None:
    p = subparsers.add_parser(
        "note",
        help="Append a note to a repository",
        description="Append a timestamped free-text note.",
    )
    p.add_argument("target", metavar="PATH_OR_ID")
    p.add_argument("body", help="Note body (quote multi-word notes)")
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    maybe_migrate_watchlist()
    try:
        with _index.connect() as conn:
            if not _index.add_note(conn, args.target, args.body):
                return fail(f"not in index: {args.target}")
    except OSError as e:
        return fail(str(e))
    print("note saved", file=sys.stderr)
    return 0
