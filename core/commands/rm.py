"""`nostos rm` - remove a repo from the metadata index.

The clone on disk is left untouched unless --purge is given. When
--cleanup-vault is given (or implied by --purge), the corresponding
vault .md file is also deleted if the vault path is configured.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from typing import Any

from .. import index as _index
from .. import vault as _vault
from ..config import load_config
from ._common import fail, maybe_migrate_watchlist


def add_parser(subparsers: Any) -> None:
    p = subparsers.add_parser(
        "rm",
        help="Remove a repository from the metadata index",
        description=(
            "Drop a repository from the index. --purge also deletes "
            "the clone on disk. --cleanup-vault removes the corresponding "
            "vault markdown file."
        ),
    )
    p.add_argument("target", metavar="PATH_OR_ID")
    p.add_argument(
        "--purge",
        action="store_true",
        help="Also delete the clone directory and vault file after confirmation",
    )
    p.add_argument(
        "--cleanup-vault",
        action="store_true",
        help="Delete the corresponding vault .md file (implied by --purge)",
    )
    p.add_argument(
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt when --purge is given",
    )
    p.set_defaults(func=run)


def _find_vault_file(
    repo: dict[str, Any],
    upstream: dict[str, Any] | None,
    vault_path: str | None,
    vault_subdir: str,
) -> str | None:
    """Locate the vault .md file for a repo, if the vault is configured."""
    if not vault_path:
        return None
    slug = _vault.repo_slug(repo, upstream)
    candidate = os.path.join(
        os.path.abspath(os.path.expanduser(vault_path)),
        vault_subdir,
        slug + ".md",
    )
    return candidate if os.path.isfile(candidate) else None


def run(args: argparse.Namespace) -> int:
    maybe_migrate_watchlist()

    cleanup_vault = args.cleanup_vault or args.purge

    try:
        with _index.connect() as conn:
            repo = _index.get_repo(conn, args.target)
            if repo is None:
                return fail(f"not in index: {args.target}")
            path = repo["path"]
            upstream = _index.get_upstream_meta(conn, repo["id"])
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

    if cleanup_vault:
        cfg = load_config()
        vault_path = cfg.get("vault_path")
        vault_subdir = cfg.get("vault_subdir") or "repos"
        md = _find_vault_file(repo, upstream, vault_path, vault_subdir)
        if md:
            try:
                os.remove(md)
                print(f"removed vault file: {md}", file=sys.stderr)
            except OSError:
                pass
        elif vault_path:
            print("no vault file found for this repo", file=sys.stderr)

    return 0
