"""`nostos export` - write a portable JSON bundle of the metadata index."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .. import index as _index
from .. import portable
from ._common import fail, maybe_migrate_watchlist


def add_parser(subparsers: Any) -> None:
    p = subparsers.add_parser(
        "export",
        help="Write a portable JSON bundle of the metadata index",
        description=(
            "Write a schema-versioned JSON bundle that can be imported "
            "on another machine. Default output is stdout; pass --out "
            "to write to a file."
        ),
    )
    p.add_argument(
        "--out",
        default="-",
        metavar="FILE",
        help="Output path, or '-' for stdout (default: stdout)",
    )
    p.add_argument(
        "--redact",
        action="store_true",
        help=(
            "Strip notes, source, and remote_url from the bundle. "
            "Tags, status, quiet flag, and upstream metadata are retained."
        ),
    )
    p.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print the JSON (default: compact)",
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    maybe_migrate_watchlist()
    from ..cli import get_version as _get_version

    try:
        with _index.connect() as conn:
            bundle = portable.build_bundle(
                conn,
                redact=args.redact,
                nostos_version=_get_version(),
            )
    except OSError as e:
        return fail(str(e))

    indent = 2 if args.pretty else None
    text = json.dumps(bundle, indent=indent, default=str)

    if args.out == "-":
        sys.stdout.write(text)
        sys.stdout.write("\n")
    else:
        try:
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(text)
        except OSError as e:
            return fail(f"could not write {args.out}: {e}")
        # Best-effort 0600 on the bundle file; it carries the same
        # sensitivity as the index itself.
        import os
        import stat as _stat

        if sys.platform != "win32":
            try:
                os.chmod(args.out, _stat.S_IRUSR | _stat.S_IWUSR)
            except OSError:
                pass
        print(
            f"export: {len(bundle['repos'])} repo(s) written to {args.out} "
            f"(redacted={bundle['redacted']})",
            file=sys.stderr,
        )

    return 0
