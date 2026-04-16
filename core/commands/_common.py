"""Shared helpers for subcommand modules."""

from __future__ import annotations

import os
import sys


def fail(msg: str, *, code: int = 1) -> int:
    """Print an error to stderr and return an exit code."""
    print(f"nostos: error: {msg}", file=sys.stderr, flush=True)
    return code


def maybe_migrate_watchlist() -> None:
    """One-shot migration from ~/.nostos_repos into the index.

    If the legacy watchlist file still exists (and has not already been
    renamed to .migrated), its entries are imported into the index with
    source='legacy-watchlist' and status='reviewed'. The file is then
    renamed to ~/.nostos_repos.migrated and a one-line notice is
    printed to stderr.
    """
    legacy = os.path.join(os.path.expanduser("~"), ".nostos_repos")
    if not os.path.isfile(legacy):
        return
    from .. import index as _index

    try:
        with _index.connect() as conn:
            n = _index.migrate_watchlist(conn, legacy)
    except OSError:
        return

    try:
        os.rename(legacy, legacy + ".migrated")
    except OSError:
        # Rename failed - leave the file but don't re-migrate next run
        # by rewriting it with a header comment. Best-effort.
        try:
            with open(legacy, "w", encoding="utf-8") as f:
                f.write("# migrated into nostos index; safe to delete\n")
        except OSError:
            pass

    print(
        f"nostos: migrated {n} watchlist entries into the metadata index "
        f"({legacy} -> {legacy}.migrated)",
        file=sys.stderr,
        flush=True,
    )
