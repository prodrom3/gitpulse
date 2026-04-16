"""`nostos import` - load a portable JSON bundle into the metadata index."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from .. import index as _index
from .. import portable
from ..config import load_config
from ._common import fail, maybe_migrate_watchlist


def add_parser(subparsers: Any) -> None:
    p = subparsers.add_parser(
        "import",
        help="Load a portable JSON bundle into the metadata index",
        description=(
            "Apply a nostos export bundle to the local index. Default "
            "behaviour is additive (merge): existing repos are not "
            "touched; missing repos are added; tags and notes are "
            "appended. For schema-2 bundles, entries that don't resolve "
            "locally (neither path nor relative-to-home match) are "
            "cloned from their remote_url into --clone-dir. Disable "
            "cloning with --no-clone for offline / metadata-only imports."
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
        "--clone-dir",
        default=None,
        metavar="DIR",
        help=(
            "Directory to clone repos into when no local path matches. "
            "Default: clone_dir from ~/.nostosrc, else $HOME."
        ),
    )
    p.add_argument(
        "--no-clone",
        action="store_true",
        help=(
            "Do not clone anything; register metadata only. Entries "
            "that don't resolve locally get a warning and a bare "
            "metadata row that `nostos pull` can populate later."
        ),
    )
    p.add_argument(
        "--clone-workers",
        type=int,
        default=4,
        metavar="N",
        help="Parallel clones when cloning is enabled (default: 4).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the import plan without writing or cloning.",
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


def _print_plan(plan: list[dict[str, Any]], *, bundle: dict[str, Any]) -> None:
    """Human-readable preview for --dry-run."""
    schema = bundle.get("schema")
    src_host = bundle.get("source_host") or "(unknown host)"
    src_plat = bundle.get("source_platform") or "(unknown platform)"
    total = len(plan)

    existing: list[dict[str, Any]] = []
    to_clone: list[dict[str, Any]] = []
    no_clone_register: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for item in plan:
        action = item["action"]
        reason = item["reason"]
        if action == "register" and reason in ("path_match", "home_relative"):
            existing.append(item)
        elif action == "register":
            no_clone_register.append(item)
        elif action == "clone_then_register":
            to_clone.append(item)
        else:
            skipped.append(item)

    print(
        f"Bundle: {total} repos (schema {schema}, "
        f"source: {src_host} {src_plat})",
        file=sys.stderr,
    )

    if existing:
        print(f"\nAlready present ({len(existing)}):", file=sys.stderr)
        for item in existing:
            reason_str = {
                "path_match": "absolute path match",
                "home_relative": "relative-to-home match",
            }.get(item["reason"], item["reason"])
            print(f"  {item['path']}   [{reason_str}]", file=sys.stderr)

    if to_clone:
        print(f"\nWill be cloned ({len(to_clone)}):", file=sys.stderr)
        for item in to_clone:
            url = item["entry"].get("remote_url") or "(no remote_url)"
            print(f"  {url}", file=sys.stderr)
            print(f"    -> {item['path']}", file=sys.stderr)

    if no_clone_register:
        print(
            f"\nWill be registered without a clone ({len(no_clone_register)}):",
            file=sys.stderr,
        )
        for item in no_clone_register:
            print(f"  {item['path']}   [{item['reason']}]", file=sys.stderr)

    if skipped:
        print(f"\nCannot resolve ({len(skipped)}):", file=sys.stderr)
        for item in skipped:
            entry_path = item["entry"].get("path") or "(no path)"
            url = item["entry"].get("remote_url")
            why = {
                "no_remote_no_path": "no remote_url and no local path",
                "no_remote_no_clone": "no remote_url, --no-clone set",
                "no_path_no_clone":  "no local path, --no-clone set",
            }.get(item["reason"], item["reason"])
            hint = f"url={url}" if url else f"path={entry_path}"
            print(f"  {hint}   [{why}]", file=sys.stderr)
            print(
                "    hint: pass --remap 'BUNDLED_PREFIX:LOCAL_PREFIX' "
                "or create the repo manually",
                file=sys.stderr,
            )

    print(
        f"\nSummary: {len(existing)} present, {len(to_clone)} to clone, "
        f"{len(no_clone_register)} bare register, {len(skipped)} skipped.",
        file=sys.stderr,
    )


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

    # Resolve clone_dir: explicit flag beats ~/.nostosrc beats $HOME.
    clone_dir = getattr(args, "clone_dir", None)
    if clone_dir is None:
        clone_dir = load_config().get("clone_dir") or None
    if clone_dir:
        clone_dir = os.path.realpath(os.path.expanduser(clone_dir))

    clone_missing = not getattr(args, "no_clone", False)
    clone_workers = max(1, int(getattr(args, "clone_workers", 4)))

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

    # For dry-run, show the human plan before (or instead of) JSON.
    if args.dry_run and not args.json:
        plan = portable.plan_import(
            bundle, remaps, clone_missing=clone_missing, clone_dir=clone_dir
        )
        _print_plan(plan, bundle=bundle)

    try:
        with _index.connect() as conn:
            stats = portable.import_bundle(
                conn,
                bundle,
                mode=args.mode,
                remaps=remaps,
                dry_run=args.dry_run,
                clone_missing=clone_missing,
                clone_dir=clone_dir,
                clone_workers=clone_workers,
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
            f"{stats['cloned']} cloned, "
            f"{stats['clone_failed']} clone failed, "
            f"{stats['skipped']} skipped, "
            f"{stats['tags_added']} tag links, "
            f"{stats['notes_added']} notes, "
            f"{stats['upstream_set']} upstream records",
            file=sys.stderr,
        )
    return 1 if stats.get("clone_failed", 0) > 0 else 0
