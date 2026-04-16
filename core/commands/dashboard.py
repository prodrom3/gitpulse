"""`nostos dashboard` - generate a static HTML fleet health report."""

from __future__ import annotations

import argparse
import sys
from typing import Any

from .. import dashboard as _dashboard
from .. import digest as _digest
from .. import index as _index
from ._common import fail, maybe_migrate_watchlist


def add_parser(subparsers: Any) -> None:
    p = subparsers.add_parser(
        "dashboard",
        help="Generate a static HTML fleet health report",
        description=(
            "Render a self-contained HTML file from the current digest "
            "data. No JavaScript framework, no CDN, no external assets. "
            "Open in any browser, email, or serve from a static host."
        ),
    )
    p.add_argument(
        "--out",
        default="-",
        metavar="FILE",
        help="Output path, or '-' for stdout (default: stdout)",
    )
    p.add_argument(
        "--title",
        default="nostos fleet health",
        help="Page title",
    )
    p.add_argument(
        "--since",
        type=int,
        default=7,
        metavar="DAYS",
        help="Window for added / refreshed sections (default: 7)",
    )
    p.add_argument(
        "--stale",
        type=int,
        default=90,
        metavar="DAYS",
        help="Stale-local threshold (default: 90)",
    )
    p.add_argument(
        "--dormant",
        type=int,
        default=365,
        metavar="DAYS",
        help="Dormant-upstream threshold (default: 365)",
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    maybe_migrate_watchlist()

    try:
        with _index.connect() as conn:
            digest = _digest.build_digest(
                conn,
                since_days=args.since,
                stale_days=args.stale,
                dormant_days=args.dormant,
            )
    except OSError as e:
        return fail(str(e))

    html = _dashboard.render_html(digest, title=args.title)

    if args.out == "-":
        sys.stdout.write(html)
    else:
        try:
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(html)
        except OSError as e:
            return fail(f"could not write {args.out}: {e}")
        print(f"dashboard: written to {args.out}", file=sys.stderr)

    return 0
