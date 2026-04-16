"""`nostos doctor` - index health check and optional auto-fix."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from .. import doctor as _doctor
from .. import index as _index
from ..config import load_config
from ._common import fail, maybe_migrate_watchlist


def add_parser(subparsers: Any) -> None:
    p = subparsers.add_parser(
        "doctor",
        help="Check index integrity and report issues",
        description=(
            "Run read-only health checks against the metadata index: "
            "stale paths, missing remotes, never-refreshed repos, "
            "orphan vault files, duplicate tags. --fix applies safe "
            "auto-remediations."
        ),
    )
    p.add_argument(
        "--fix",
        action="store_true",
        help=(
            "Apply safe auto-fixes: flag stale paths as 'flagged', "
            "delete orphan vault files."
        ),
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Emit a JSON report instead of human-readable text.",
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    maybe_migrate_watchlist()
    cfg = load_config()
    vault_path = cfg.get("vault_path")
    vault_subdir = cfg.get("vault_subdir") or "repos"

    try:
        with _index.connect() as conn:
            report = _doctor.run_checks(
                conn,
                vault_path=vault_path,
                vault_subdir=vault_subdir,
            )

            if args.fix:
                fixed_stale = 0
                fixed_orphans = 0
                if report["stale_paths"]:
                    fixed_stale = _doctor.fix_stale_paths(
                        conn, report["stale_paths"]
                    )
                if report["orphan_vault_files"]:
                    for orphan in report["orphan_vault_files"]:
                        try:
                            os.remove(orphan)
                            fixed_orphans += 1
                        except OSError:
                            pass
                report["fixed_stale"] = fixed_stale
                report["fixed_orphans"] = fixed_orphans
    except OSError as e:
        return fail(str(e))

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        sys.stdout.write(_doctor.render_human(report))
        if args.fix:
            fixed_stale = report.get("fixed_stale", 0)
            fixed_orphans = report.get("fixed_orphans", 0)
            if fixed_stale or fixed_orphans:
                print(
                    f"\nauto-fix: {fixed_stale} stale repo(s) flagged, "
                    f"{fixed_orphans} orphan vault file(s) deleted",
                    file=sys.stderr,
                )

    return 1 if report["issues_total"] > 0 and not args.fix else 0
