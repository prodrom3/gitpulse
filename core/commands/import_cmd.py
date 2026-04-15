"""`gitpulse import` - load a portable JSON bundle into the metadata index."""

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
        "import",
        help="Load a portable JSON bundle into the metadata index",
        description=(
            "Apply a gitpulse export bundle to the local index. Default "
            "behaviour is additive (merge): existing repos are not "
            "touched; missing repos are added; tags and notes are appended."
        ),
    )
    p.add_argument(
        "bundle",
        metavar="FILE",
        help="Path to the bundle, or '-' for stdin",
    )
    group = p.add_mutually_exclusive_group()
    group.add_argument(
        "--merge",
        action="store_const",
        dest="mode",
        const="merge",
        help="Add missing repos, top up tags/notes/upstream. Default.",
    )
    group.add_argument(
        "--replace",
        action="store_const",
        dest="mode",
        const="replace",
        help=(
            "WIPE the local index first, then import the bundle. "
            "Requires --yes to proceed non-interactively."
        ),
    )
    p.set_defaults(mode="merge")
    p.add_argument(
        "--remap",
        action="append",
        default=[],
        metavar="SRC:DST",
        help=(
            "Rewrite repo paths on import: paths starting with SRC "
            "have that prefix replaced with DST. Repeatable."
        ),
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without writing to the index.",
    )
    p.add_argument(
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt when --replace is used.",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Print the result summary as JSON",
    )
    p.set_defaults(func=run)


def _load(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise portable.BundleError(f"invalid JSON: {e}") from None
    if not isinstance(data, dict):
        raise portable.BundleError("bundle is not a JSON object")
    return data


def run(args: argparse.Namespace) -> int:
    maybe_migrate_watchlist()

    # Read bundle from file or stdin
    try:
        if args.bundle == "-":
            text = sys.stdin.read()
        else:
            with open(args.bundle, encoding="utf-8") as f:
                text = f.read()
    except OSError as e:
        return fail(f"could not read {args.bundle}: {e}")

    try:
        bundle = _load(text)
        portable.validate_bundle(bundle)
    except portable.BundleError as e:
        return fail(str(e))

    # Parse remaps
    remaps: list[tuple[str, str]] = []
    try:
        for spec in args.remap or []:
            remaps.append(portable.parse_remap(spec))
    except portable.BundleError as e:
        return fail(str(e))

    # Replace-mode gate
    if args.mode == "replace" and not args.dry_run and not args.yes:
        try:
            confirm = input(
                "This will WIPE the local index before importing. Continue? [y/N]: "
            ).strip().lower()
        except EOFError:
            confirm = ""
        if confirm not in {"y", "yes"}:
            print("aborted", file=sys.stderr)
            return 1

    try:
        with _index.connect() as conn:
            stats = portable.import_bundle(
                conn,
                bundle,
                mode=args.mode,
                remaps=remaps,
                dry_run=args.dry_run,
            )
    except (OSError, portable.BundleError) as e:
        return fail(str(e))

    if args.json:
        print(json.dumps(stats, indent=2, default=str))
    else:
        prefix = "[dry-run] " if args.dry_run else ""
        print(
            f"{prefix}import ({stats['mode']}): "
            f"{stats['added']} added, "
            f"{stats['already_present']} already present, "
            f"{stats['tags_added']} tag links, "
            f"{stats['notes_added']} notes, "
            f"{stats['upstream_set']} upstream records",
            file=sys.stderr,
        )
    return 0
