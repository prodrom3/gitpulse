"""`gitpulse digest` - weekly changeset report over the local index."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .. import digest as _digest
from .. import index as _index
from ._common import fail, maybe_migrate_watchlist


def add_parser(subparsers: Any) -> None:
    p = subparsers.add_parser(
        "digest",
        help="Print a weekly changeset report (local-only, zero network)",
        description=(
            "Summarise what moved in the fleet: new intakes, upstream "
            "refreshes, archived upstreams, flagged repos, stale locals, "
            "dormant upstreams. All values come from the local index; "
            "no network calls are made."
        ),
    )
    p.add_argument(
        "--since",
        type=int,
        default=7,
        metavar="DAYS",
        help="Window for 'added' and 'refreshed' sections (default: 7)",
    )
    p.add_argument(
        "--stale",
        type=int,
        default=90,
        metavar="DAYS",
        help="Threshold for the stale-local section (default: 90)",
    )
    p.add_argument(
        "--dormant",
        type=int,
        default=365,
        metavar="DAYS",
        help="Threshold for the dormant-upstream section (default: 365)",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Emit a JSON document instead of the human report",
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    maybe_migrate_watchlist()

    try:
        with _index.connect() as conn:
            report = _digest.build_digest(
                conn,
                since_days=args.since,
                stale_days=args.stale,
                dormant_days=args.dormant,
            )
    except OSError as e:
        return fail(str(e))

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        sys.stdout.write(_digest.render_human(report))

    # Operational signal: exit 0 always. A non-empty "archived" or
    # "flagged" section is a flag for the operator to act on, but the
    # digest itself is always informational, not a pass/fail check.
    return 0
