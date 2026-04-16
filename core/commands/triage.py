"""`nostos triage` - walk the inbox of newly-added repos.

Iterates over repos with status='new', prompting the operator for
tags, a status transition, and an optional note. Keyboard-driven,
no external TUI dependency. Ctrl+C aborts cleanly.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from .. import index as _index
from ._common import maybe_migrate_watchlist

_VALID_STATUS_CHOICES: list[str] = sorted(_index.VALID_STATUSES)


def add_parser(subparsers: Any) -> None:
    p = subparsers.add_parser(
        "triage",
        help="Walk newly-added repositories and classify them",
        description="Iterate repositories with status='new' and classify them interactively.",
    )
    p.add_argument(
        "--status",
        default="new",
        choices=_VALID_STATUS_CHOICES,
        help="Status of the queue to walk (default: new)",
    )
    p.set_defaults(func=run)


def _prompt(text: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    try:
        raw = input(f"{text}{suffix}: ").strip()
    except EOFError:
        return ""
    return raw or (default or "")


def _prompt_status(current: str) -> str:
    while True:
        choices = "/".join(_VALID_STATUS_CHOICES)
        value = _prompt(f"  status ({choices})", current)
        if value in _index.VALID_STATUSES:
            return value
        print("    invalid status; try again", file=sys.stderr)


def run(args: argparse.Namespace) -> int:
    maybe_migrate_watchlist()

    try:
        with _index.connect() as conn:
            queue = _index.list_repos(conn, status=args.status)
    except OSError as e:
        print(f"nostos: error: {e}", file=sys.stderr)
        return 1

    if not queue:
        print(f"nothing to triage (status={args.status})", file=sys.stderr)
        return 0

    print(
        f"triaging {len(queue)} repo(s) with status={args.status}. "
        f"Empty input keeps the current value. Ctrl+C aborts.\n",
        file=sys.stderr,
    )

    try:
        for i, repo in enumerate(queue, start=1):
            print(
                f"[{i}/{len(queue)}] {repo['path']}  (source={repo['source'] or '-'})",
                file=sys.stderr,
            )
            new_tags = _prompt("  tags (comma-separated, leading + adds)", "")
            new_status = _prompt_status(repo["status"])
            new_note = _prompt("  note (blank = skip)", "")

            try:
                with _index.connect() as conn:
                    if new_tags:
                        adds = [t.strip().lstrip("+") for t in new_tags.split(",") if t.strip()]
                        if adds:
                            _index.add_tags(conn, repo["id"], adds)
                    if new_status != repo["status"]:
                        _index.update_status(conn, repo["id"], new_status)
                    if new_note:
                        _index.add_note(conn, repo["id"], new_note)
            except OSError as e:
                print(f"  skipped (index error: {e})", file=sys.stderr)

    except KeyboardInterrupt:
        print("\naborted", file=sys.stderr)
        return 130

    print("\ndone.", file=sys.stderr)
    return 0
