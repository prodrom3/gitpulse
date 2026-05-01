"""`nostos topics` - manage topic curation rules for upstream auto-tag imports.

Sub-verbs:
- `topics list`                show current rules
- `topics deny TOPIC...`       add one or more topics to the deny list
- `topics allow TOPIC...`      remove topics from the deny list
- `topics alias SRC DST`       rewrite SRC to DST during import
- `topics unalias SRC...`      drop alias entries
- `topics export [PATH]`       write rules as TOML to PATH or stdout
- `topics import FILE [...]`   load a rules TOML; merge or replace
- `topics apply [...]`         retroactively curate existing repo tags

Rules persist in $XDG_CONFIG_HOME/nostos/topic_rules.toml. They take
effect on the next `nostos add --auto-tags` / `nostos refresh
--auto-tags`. Use `nostos topics apply` to retroactively curate tag
state on already-indexed repos when the rules change.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from .. import index as _index
from ..topic_rules import (
    TopicRules,
    dump_rules,
    load_rules,
    merge_rules,
    parse_rules_from_text,
    save_rules,
)
from ._common import fail, maybe_migrate_watchlist


def add_parser(subparsers: Any) -> None:
    p = subparsers.add_parser(
        "topics",
        help="Manage topic curation rules (deny / alias)",
        description=(
            "Edit the topic curation file applied when --auto-tags imports "
            "upstream repo topics. Sub-verbs: list, deny, allow, alias, "
            "unalias, export, import, apply."
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

    exp = sub.add_parser(
        "export",
        help="Write rules as TOML to a file or stdout",
        description=(
            "Serialize the current rules to TOML. With no PATH, or "
            "PATH set to '-', writes to stdout (handy for piping or "
            "redirecting). Otherwise writes to PATH atomically."
        ),
    )
    exp.add_argument(
        "path",
        nargs="?",
        default="-",
        metavar="PATH",
        help="Output file. '-' or omitted = stdout.",
    )
    exp.set_defaults(func=run_export)

    imp = sub.add_parser(
        "import",
        help="Load a rules TOML; merge with or replace the current rules",
        description=(
            "Read a TOML rules document from FILE (or stdin via '-') "
            "and apply it. Default is --merge: deny lists are unioned "
            "and alias maps are overlaid (incoming wins on conflict). "
            "--replace overwrites the local rules entirely."
        ),
    )
    imp.add_argument(
        "source",
        metavar="FILE",
        help="Path to a rules TOML, or '-' for stdin",
    )
    grp = imp.add_mutually_exclusive_group()
    grp.add_argument(
        "--merge",
        action="store_const",
        dest="mode",
        const="merge",
        help="Union deny lists, overlay alias maps (default)",
    )
    grp.add_argument(
        "--replace",
        action="store_const",
        dest="mode",
        const="replace",
        help="Replace the local rules with the imported set",
    )
    imp.set_defaults(mode="merge", func=run_import)

    apl = sub.add_parser(
        "apply",
        help="Retroactively curate existing repo tags using current rules",
        description=(
            "Walk the metadata index and rewrite tags so they match the "
            "current rule set: drop denied tags, rewrite alias-source tags "
            "to their target. Tags not mentioned by any rule are left "
            "alone. Idempotent: running twice produces the same result."
        ),
    )
    apl.add_argument(
        "--repo",
        default=None,
        metavar="PATH_OR_ID",
        help="Apply to a single repo only (default: every indexed repo)",
    )
    apl.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would change but do not modify the index",
    )
    apl.add_argument(
        "--json",
        action="store_true",
        help="Emit a JSON summary instead of human-readable lines",
    )
    apl.set_defaults(func=run_apply)


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


def run_export(args: argparse.Namespace) -> int:
    rules = load_rules()
    body = dump_rules(rules)
    target = args.path
    if target == "-" or not target:
        sys.stdout.write(body)
        sys.stdout.flush()
        return 0
    try:
        save_rules(rules, path=target)
    except OSError as e:
        return fail(f"could not write {target}: {e}")
    print(f"topics export: wrote {target}", file=sys.stderr)
    return 0


def run_import(args: argparse.Namespace) -> int:
    src = args.source
    try:
        if src == "-":
            text = sys.stdin.read()
        else:
            with open(src, encoding="utf-8") as f:
                text = f.read()
    except OSError as e:
        return fail(f"could not read {src}: {e}")

    try:
        incoming = parse_rules_from_text(text)
    except ValueError as e:
        return fail(f"invalid rules TOML in {src}: {e}")

    if args.mode == "replace":
        final = incoming
    else:
        final = merge_rules(load_rules(), incoming)

    try:
        path = save_rules(final)
    except OSError as e:
        return fail(f"could not write rules: {e}")

    label = "replaced" if args.mode == "replace" else "merged"
    print(
        f"topics import: {label} from {src} "
        f"({len(final.deny)} deny, {len(final.alias)} alias) -> {path}",
        file=sys.stderr,
    )
    return 0


def _diff_tags(
    current: list[str], rules: TopicRules
) -> tuple[list[str], list[str]]:
    """Return (to_remove, to_add) for a single repo.

    Reuses the same rules.apply() pass that runs at merge time, so
    apply-mode behaviour is identical to import-mode behaviour. The
    diff is computed against `current` so already-correct repos are
    no-ops (idempotent).
    """
    curated = set(rules.apply(current))
    cur_set = {t.lower() for t in current}
    to_remove = sorted(cur_set - curated)
    to_add = sorted(curated - cur_set)
    return to_remove, to_add


def run_apply(args: argparse.Namespace) -> int:
    maybe_migrate_watchlist()
    rules = load_rules()
    if not rules.deny and not rules.alias:
        msg = "topics apply: no rules loaded; nothing to do"
        if args.json:
            import json as _json
            print(_json.dumps({"changed": 0, "repos": []}))
        else:
            print(msg, file=sys.stderr)
        return 0

    try:
        with _index.connect() as conn:
            if args.repo is not None:
                one = _index.get_repo(conn, args.repo)
                targets = [one] if one else []
            else:
                targets = _index.list_repos(conn)
    except OSError as e:
        return fail(str(e))

    if args.repo is not None and not targets:
        return fail(f"not in index: {args.repo}")

    changed: list[dict[str, Any]] = []
    total_removed = 0
    total_added = 0

    for repo in targets:
        current = repo.get("tags") or []
        to_remove, to_add = _diff_tags(current, rules)
        if not to_remove and not to_add:
            continue
        changed.append({
            "path": repo["path"],
            "removed": to_remove,
            "added": to_add,
        })
        total_removed += len(to_remove)
        total_added += len(to_add)
        if args.dry_run:
            continue
        try:
            with _index.connect() as conn:
                if to_remove:
                    _index.remove_tags(conn, repo["id"], to_remove)
                if to_add:
                    _index.add_tags(conn, repo["id"], to_add)
        except OSError as e:
            return fail(f"index write failed for {repo['path']}: {e}")

    if args.json:
        import json as _json
        print(_json.dumps({
            "dry_run": bool(args.dry_run),
            "repos_changed": len(changed),
            "tags_removed": total_removed,
            "tags_added": total_added,
            "changes": changed,
        }, indent=2))
    else:
        prefix = "topics apply (dry-run): " if args.dry_run else "topics apply: "
        print(
            f"{prefix}{len(changed)} repo(s) changed, "
            f"{total_removed} tag(s) removed, "
            f"{total_added} tag(s) added.",
            file=sys.stderr,
        )
        for entry in changed[:20]:
            bits: list[str] = []
            if entry["removed"]:
                bits.append("-" + ", -".join(entry["removed"]))
            if entry["added"]:
                bits.append("+" + ", +".join(entry["added"]))
            print(f"  {entry['path']}: {' '.join(bits)}", file=sys.stderr)
        if len(changed) > 20:
            print(f"  ...and {len(changed) - 20} more", file=sys.stderr)
    return 0
