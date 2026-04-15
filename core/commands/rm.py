"""`gitpulse rm` - remove a repo from the metadata index.

The clone on disk is left untouched. Pass --purge to also delete the
working tree after confirmation.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from typing import Any

from .. import index as _index
from ._common import fail, maybe_migrate_watchlist


def add_parser(subparsers: Any) -> None:
    p = subparsers.add_parser(
        "rm",
        help="Remove a repository from the metadata index",
        description="Drop a repository from the index. --purge also deletes the clone on disk.",
    )
    p.add_argument("target", metavar="PATH_OR_ID")
    p.add_argument(
        "--purge",
        action="store_true",
        help="Also delete the clone directory after explicit confirmation",
    )
    p.add_argument(
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt when --purge is given",
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    maybe_migrate_watchlist()

    try:
        with _index.connect() as conn:
            repo = _index.get_repo(conn, args.target)
            if repo is None:
                return fail(f"not in index: {args.target}")
            path = repo["path"]
            _index.remove_repo(conn, repo["id"])
    except OSError as e:
        return fail(str(e))

    print(f"removed from index: {path}", file=sys.stderr)

    if args.purge:
        if not args.yes:
            try:
                confirm = input(f"purge {path} from disk? [y/N]: ").strip().lower()
            except EOFError:
                confirm = ""
            if confirm not in {"y", "yes"}:
                print("purge cancelled", file=sys.stderr)
                return 0
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
            print(f"purged: {path}", file=sys.stderr)
        else:
            print(f"nothing on disk at: {path}", file=sys.stderr)

    return 0
