"""`nostos add` - ingest a repo into the metadata index.

Accepts either a local path to an existing git repository or a remote
URL. When given a URL, the repo is cloned first (via the hardened
clone routine, with hooks disabled) and then the resulting local path
is registered.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

from .. import index as _index
from ..config import load_config
from ..watchlist import clone_repo, is_remote_url
from ._common import fail, maybe_migrate_watchlist


def add_parser(subparsers: Any) -> None:
    p = subparsers.add_parser(
        "add",
        help="Register a repository in the metadata index",
        description="Register a local git repository, or clone a remote URL and register it.",
    )
    p.add_argument(
        "target",
        metavar="PATH_OR_URL",
        help="Local path to a git repository, or a remote URL to clone",
    )
    p.add_argument(
        "--tag",
        action="append",
        default=[],
        metavar="TAG",
        help="Tag to attach (repeatable, or comma-separated)",
    )
    p.add_argument(
        "--source",
        default=None,
        help="Free-text provenance (e.g. 'blog:orange.tw, 2026-04-12')",
    )
    p.add_argument(
        "--note",
        default=None,
        help="Initial free-text note",
    )
    p.add_argument(
        "--status",
        default="new",
        choices=sorted(_index.VALID_STATUSES),
        help="Initial triage status (default: new)",
    )
    p.add_argument(
        "--quiet-upstream",
        action="store_true",
        help="Opsec flag: never query upstream metadata for this repo",
    )
    p.add_argument(
        "--clone-dir",
        default=None,
        metavar="DIR",
        help="Directory to clone into when target is a URL (default: cwd or config)",
    )
    p.set_defaults(func=run)


def _flatten_tags(raw: list[str]) -> list[str]:
    tags: list[str] = []
    for item in raw:
        for piece in item.split(","):
            piece = piece.strip()
            if piece:
                tags.append(piece)
    return tags


def run(args: argparse.Namespace) -> int:
    maybe_migrate_watchlist()

    target = args.target
    tags = _flatten_tags(args.tag)

    if is_remote_url(target):
        clone_dir = args.clone_dir
        if clone_dir is None:
            clone_dir = load_config()["clone_dir"] or os.getcwd()
        local_path = clone_repo(target, clone_dir)
        if local_path is None:
            return fail(f"clone failed: {target}")
        repo_path = local_path
        remote_url = target
    else:
        repo_path = target
        if not os.path.isdir(os.path.join(os.path.expanduser(repo_path), ".git")):
            return fail(f"not a git repository: {repo_path}")
        remote_url = None

    try:
        with _index.connect() as conn:
            repo_id = _index.add_repo(
                conn,
                repo_path,
                remote_url=remote_url,
                source=args.source,
                status=args.status,
                quiet=args.quiet_upstream,
                tags=tags,
                note=args.note,
            )
    except (OSError, ValueError) as e:
        return fail(str(e))

    print(f"Added to index (id={repo_id}): {os.path.realpath(os.path.expanduser(repo_path))}",
          file=sys.stderr, flush=True)
    return 0
