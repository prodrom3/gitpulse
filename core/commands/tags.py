"""`nostos tags` - list every tag in the index with attachment counts.

Distinct from `nostos tag` (singular), which adds / removes tags on
one repo. `nostos tags` (plural) operates on the tag space across
the whole fleet:

- print every tag with the number of repos carrying it
- optionally prune orphan rows in the `tags` table that no longer
  link to any repo (cosmetic; `nostos list --tag X` ignores them
  regardless)
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from .. import index as _index
from ..tag_buckets import (
    DISPLAY_ORDER,
    SUB_BUCKET_DISPLAY_ORDER,
    SUB_BUCKETS,
    bucket_for,
    sub_bucket_for,
)
from ._common import fail, maybe_migrate_watchlist


def add_parser(subparsers: Any) -> None:
    p = subparsers.add_parser(
        "tags",
        help="List every tag in the index with attachment counts",
        description=(
            "Print all tags currently attached to one or more repos, "
            "sorted by attachment count (descending) then name. "
            "Output is grouped by inferred bucket (discipline / "
            "attack-class / recon-technique / tool-kind / language / "
            "os / ...) when stdout is a TTY; pipe or pass --flat for "
            "the legacy un-grouped form. --prune-orphans deletes tag "
            "rows that no longer link to any repo (cosmetic cleanup)."
        ),
    )
    p.add_argument(
        "--include-orphans",
        action="store_true",
        help="Also list tags with zero attached repos (count=0 rows)",
    )
    p.add_argument(
        "--prune-orphans",
        action="store_true",
        help="Delete orphan tag rows after listing (no-op when none exist)",
    )
    grouping = p.add_mutually_exclusive_group()
    grouping.add_argument(
        "--grouped",
        dest="grouping",
        action="store_const",
        const="grouped",
        help="Force grouped output (the default on a TTY)",
    )
    grouping.add_argument(
        "--flat",
        dest="grouping",
        action="store_const",
        const="flat",
        help="Force flat (un-grouped) output, even on a TTY",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Emit a JSON array instead of human-readable lines",
    )
    p.set_defaults(func=run, grouping=None)


def run(args: argparse.Namespace) -> int:
    maybe_migrate_watchlist()
    try:
        with _index.connect() as conn:
            entries = _index.list_tags_with_counts(
                conn, include_orphans=args.include_orphans
            )
            pruned = 0
            if args.prune_orphans:
                pruned = _index.prune_orphan_tags(conn)
    except OSError as e:
        return fail(str(e))

    if args.json:
        import json as _json
        tag_entries = []
        for n, c in entries:
            b = bucket_for(n)
            tag_entries.append({
                "name": n,
                "repos": c,
                "bucket": b,
                "sub_bucket": sub_bucket_for(n, b),
            })
        print(_json.dumps({
            "tags": tag_entries,
            "total_tags": len(entries),
            "orphans_pruned": pruned,
        }, indent=2))
    else:
        if not entries:
            print("nostos tags: no tags in the index", file=sys.stderr)
        else:
            grouped = _resolve_grouping(args.grouping)
            if grouped:
                _print_grouped(entries)
            else:
                _print_flat(entries)
            print(
                f"\n{len(entries)} tag(s).",
                file=sys.stderr,
            )
        if args.prune_orphans:
            msg = (
                f"pruned {pruned} orphan tag row(s)."
                if pruned
                else "no orphan tags to prune."
            )
            print(msg, file=sys.stderr)

    return 0


def _resolve_grouping(explicit: str | None) -> bool:
    """Decide grouped vs flat. Explicit flag wins; default is TTY-aware."""
    if explicit == "grouped":
        return True
    if explicit == "flat":
        return False
    try:
        return bool(sys.stdout.isatty())
    except (AttributeError, ValueError):
        return False


def _print_flat(entries: list[tuple[str, int]]) -> None:
    width = max(len(n) for n, _ in entries)
    for name, n in entries:
        print(f"  {name:<{width}}  {n}")


def _print_grouped(entries: list[tuple[str, int]]) -> None:
    """Print entries grouped by inferred bucket. Buckets that define
    sub-buckets are further grouped one level deeper. Empty buckets
    and empty sub-buckets are skipped."""
    by_bucket: dict[str, list[tuple[str, int]]] = {}
    for name, n in entries:
        by_bucket.setdefault(bucket_for(name), []).append((name, n))

    width = max(len(n) for n, _ in entries)
    first = True
    for bucket in DISPLAY_ORDER:
        items = by_bucket.get(bucket)
        if not items:
            continue
        if not first:
            print()
        first = False
        print(f"[{bucket}]")
        if bucket in SUB_BUCKETS:
            _print_sub_grouped(bucket, items, width)
        else:
            for name, n in items:
                print(f"  {name:<{width}}  {n}")


def _print_sub_grouped(
    bucket: str, items: list[tuple[str, int]], width: int
) -> None:
    """Print one bucket's items, sub-grouped where the bucket defines
    sub-buckets. Sub-buckets in `SUB_BUCKET_DISPLAY_ORDER` come first
    in their listed order; any sub-bucket not pre-ordered comes after
    in alphabetical order; the synthetic 'other' is always last."""
    by_sub: dict[str, list[tuple[str, int]]] = {}
    for name, n in items:
        sub = sub_bucket_for(name, bucket) or "other"
        by_sub.setdefault(sub, []).append((name, n))

    ordered = SUB_BUCKET_DISPLAY_ORDER.get(bucket)
    if ordered is None:
        # Fall back to declaration order from SUB_BUCKETS, with 'other' last.
        ordered = tuple(s for s, _ in SUB_BUCKETS.get(bucket, ())) + ("other",)

    seen: set[str] = set()
    for sub in ordered:
        sub_items = by_sub.get(sub)
        seen.add(sub)
        if not sub_items:
            continue
        print(f"  ({sub})")
        for name, n in sub_items:
            print(f"    {name:<{width}}  {n}")
    # Pick up any straggler sub-buckets not in the display order.
    for sub in sorted(set(by_sub) - seen):
        print(f"  ({sub})")
        for name, n in by_sub[sub]:
            print(f"    {name:<{width}}  {n}")
