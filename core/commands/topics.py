"""`nostos topics` - manage topic curation rules for upstream auto-tag imports.

Sub-verbs:
- `topics list`              show current rules
- `topics deny TOPIC...`     add one or more topics to the deny list
- `topics allow TOPIC...`    remove topics from the deny list
- `topics alias SRC DST`     rewrite SRC to DST during import
- `topics unalias SRC...`    drop alias entries

Rules persist in $XDG_CONFIG_HOME/nostos/topic_rules.toml. They take
effect on the next `nostos add --auto-tags` or `nostos refresh
--auto-tags`. Existing tag state on already-indexed repos is not
rewritten retroactively - run `nostos refresh --all --auto-tags`
after editing rules to re-curate the fleet.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from ..topic_rules import TopicRules, load_rules, save_rules
from ._common import fail


def add_parser(subparsers: Any) -> None:
    p = subparsers.add_parser(
        "topics",
        help="Manage topic curation rules (deny / alias)",
        description=(
            "Edit the topic curation file applied when --auto-tags imports "
            "upstream repo topics. Sub-verbs: list, deny, allow, alias, "
            "unalias."
        ),
    )
    sub = p.add_subparsers(dest="topics_command", metavar="SUBCOMMAND", required=True)

    lst = sub.add_parser("list", help="Show current rules")
    lst.add_argument("--json", action="store_true", help="JSON output")
    lst.set_defaults(func=run_list)

    deny = sub.add_parser("deny", help="Add topics to the deny list")
    deny.add_argument("topics", nargs="+", metavar="TOPIC")
    deny.set_defaults(func=run_deny)

    allow = sub.add_parser("allow", help="Remove topics from the deny list")
    allow.add_argument("topics", nargs="+", metavar="TOPIC")
    allow.set_defaults(func=run_allow)

    al = sub.add_parser(
        "alias",
        help="Rewrite SRC to DST during topic import",
        description="Add an alias mapping SRC -> DST. Both names are lowercased.",
    )
    al.add_argument("src", metavar="SRC")
    al.add_argument("dst", metavar="DST")
    al.set_defaults(func=run_alias)

    unal = sub.add_parser("unalias", help="Remove alias entries by source name")
    unal.add_argument("sources", nargs="+", metavar="SRC")
    unal.set_defaults(func=run_unalias)


def _print_rules(rules: TopicRules) -> None:
    if rules.deny:
        print("deny:")
        for n in sorted(rules.deny):
            print(f"  {n}")
    else:
        print("deny: (empty)")

    if rules.alias:
        print("alias:")
        width = max(len(s) for s in rules.alias)
        for src in sorted(rules.alias):
            print(f"  {src:<{width}}  ->  {rules.alias[src]}")
    else:
        print("alias: (empty)")


def run_list(args: argparse.Namespace) -> int:
    rules = load_rules()
    if getattr(args, "json", False):
        import json as _json
        print(_json.dumps(
            {"deny": sorted(rules.deny), "alias": rules.alias},
            indent=2,
        ))
    else:
        _print_rules(rules)
    return 0


def run_deny(args: argparse.Namespace) -> int:
    rules = load_rules()
    added = 0
    for raw in args.topics:
        name = raw.strip().lower()
        if not name:
            continue
        if name not in rules.deny:
            rules.deny.add(name)
            added += 1
    try:
        path = save_rules(rules)
    except OSError as e:
        return fail(f"could not write rules: {e}")
    print(f"topics deny: +{added} (file: {path})", file=sys.stderr)
    return 0


def run_allow(args: argparse.Namespace) -> int:
    rules = load_rules()
    removed = 0
    for raw in args.topics:
        name = raw.strip().lower()
        if name and name in rules.deny:
            rules.deny.discard(name)
            removed += 1
    try:
        path = save_rules(rules)
    except OSError as e:
        return fail(f"could not write rules: {e}")
    print(f"topics allow: -{removed} (file: {path})", file=sys.stderr)
    return 0


def run_alias(args: argparse.Namespace) -> int:
    src = args.src.strip().lower()
    dst = args.dst.strip().lower()
    if not src or not dst:
        return fail("alias: SRC and DST must be non-empty")
    rules = load_rules()
    rules.alias[src] = dst
    try:
        path = save_rules(rules)
    except OSError as e:
        return fail(f"could not write rules: {e}")
    print(f"topics alias: {src} -> {dst} (file: {path})", file=sys.stderr)
    return 0


def run_unalias(args: argparse.Namespace) -> int:
    rules = load_rules()
    removed = 0
    for raw in args.sources:
        name = raw.strip().lower()
        if name and name in rules.alias:
            rules.alias.pop(name)
            removed += 1
    try:
        path = save_rules(rules)
    except OSError as e:
        return fail(f"could not write rules: {e}")
    print(f"topics unalias: -{removed} (file: {path})", file=sys.stderr)
    return 0
