"""`gitpulse attack` - ATT&CK technique helpers.

Sub-verbs:
- `attack list`       print the built-in technique lookup table.
- `attack tag <repo> T1059 [T1071 ...]`  shorthand for
  `gitpulse tag <repo> +attack:t1059 +attack:t1071`.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from .. import index as _index
from .. import taxonomy as _tax
from ._common import fail, maybe_migrate_watchlist


def add_parser(subparsers: Any) -> None:
    p = subparsers.add_parser(
        "attack",
        help="ATT&CK technique helpers (list taxonomy, tag repos)",
        description="Work with MITRE ATT&CK technique tags.",
    )
    sub = p.add_subparsers(dest="attack_command", metavar="SUBCOMMAND", required=True)

    # attack list
    lst = sub.add_parser(
        "list",
        help="Print the built-in ATT&CK technique lookup table",
    )
    lst.set_defaults(func=run_list)

    # attack tag <repo> T1059 [T1071 ...]
    tg = sub.add_parser(
        "tag",
        help="Tag a repo with one or more ATT&CK technique IDs",
        description=(
            "Shorthand for `gitpulse tag <repo> +attack:TNNNN`. "
            "Each ID is validated against the built-in lookup table."
        ),
    )
    tg.add_argument("target", metavar="PATH_OR_ID")
    tg.add_argument("techniques", nargs="+", metavar="TNNNN")
    tg.set_defaults(func=run_tag)


def run_list(args: argparse.Namespace) -> int:
    print(f"MITRE ATT&CK techniques ({len(_tax.TECHNIQUES)} in the built-in table):\n")
    sys.stdout.write(_tax.render_table())
    return 0


def run_tag(args: argparse.Namespace) -> int:
    maybe_migrate_watchlist()

    tags_to_add: list[str] = []
    for raw in args.techniques:
        tag = _tax.normalize_attack_tag(raw)
        info = _tax.lookup(tag)
        if info is None:
            print(
                f"warning: {raw} is not in the built-in lookup table; "
                f"adding as {tag} anyway",
                file=sys.stderr,
            )
        tags_to_add.append(tag)

    try:
        with _index.connect() as conn:
            if not _index.add_tags(conn, args.target, tags_to_add):
                return fail(f"not in index: {args.target}")
            final = _index.get_tags(conn, args.target)
    except OSError as e:
        return fail(str(e))

    attack_tags = [t for t in final if t.startswith("attack:")]
    other_tags = [t for t in final if not t.startswith("attack:")]
    print(f"attack tags: {', '.join(attack_tags) or '(none)'}", file=sys.stderr)
    if other_tags:
        print(f"other tags:  {', '.join(other_tags)}", file=sys.stderr)
    return 0
