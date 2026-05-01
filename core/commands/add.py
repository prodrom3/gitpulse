"""`nostos add` - ingest a repo into the metadata index.

Accepts either a local path to an existing git repository or a remote
URL. When given a URL, the repo is cloned first (via the hardened
clone routine, with hooks disabled) and then the resulting local path
is registered.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

from .. import index as _index
from ..auth import load_auth
from ..config import load_config
from ..topic_rules import load_rules as load_topic_rules
from ..upstream import (
    HostNotAllowed,
    ProbeError,
    ProviderUnknown,
    parse_remote_url,
    probe_upstream,
)
from ..watchlist import clone_repo, is_remote_url
from ._common import fail, maybe_migrate_watchlist


def add_parser(subparsers: Any) -> None:
    p = subparsers.add_parser(
        "add",
        help="Register a repository in the metadata index",
        description="Register a local git repository, or clone a remote URL and register it.",
    )
    p.add_argument(
        "target",
        metavar="PATH_OR_URL",
        help="Local path to a git repository, or a remote URL to clone",
    )
    p.add_argument(
        "--tag",
        action="append",
        default=[],
        metavar="TAG",
        help="Tag to attach (repeatable, or comma-separated)",
    )
    p.add_argument(
        "--source",
        default=None,
        help="Free-text provenance (e.g. 'blog:orange.tw, 2026-04-12')",
    )
    p.add_argument(
        "--note",
        default=None,
        help="Initial free-text note",
    )
    p.add_argument(
        "--status",
        default="new",
        choices=sorted(_index.VALID_STATUSES),
        help="Initial triage status (default: new)",
    )
    p.add_argument(
        "--quiet-upstream",
        action="store_true",
        help="Opsec flag: never query upstream metadata for this repo",
    )
    p.add_argument(
        "--auto-tags",
        action="store_true",
        default=None,
        help="Fetch repo topics from the upstream host and merge them into "
        "--tag values. Requires the host to be configured in auth.toml. "
        "Skipped silently if --quiet-upstream is also set. "
        "Default in config: [add] auto_tags = false.",
    )
    p.add_argument(
        "--clone-dir",
        default=None,
        metavar="DIR",
        help="Directory to clone into when target is a URL (default: cwd or config)",
    )
    p.set_defaults(func=run)


def _flatten_tags(raw: list[str]) -> list[str]:
    tags: list[str] = []
    for item in raw:
        for piece in item.split(","):
            piece = piece.strip()
            if piece:
                tags.append(piece)
    return tags


def _fetch_upstream_topics(remote_url: str) -> list[str]:
    """Probe the remote host for repo topics. Returns [] on any failure.

    Caller is responsible for the --quiet-upstream short-circuit; this
    helper assumes the user has opted in. Failures are reported on
    stderr but never raise: --auto-tags is best-effort.
    """
    parsed = parse_remote_url(remote_url)
    if parsed is None:
        print(
            f"nostos add: --auto-tags: cannot parse remote URL ({remote_url}); "
            "skipping topic fetch.",
            file=sys.stderr,
        )
        return []
    host, _, _ = parsed

    auth = load_auth()
    if not auth.is_allowed(host):
        print(
            f"nostos add: --auto-tags: host {host} is not configured in "
            "auth.toml; skipping topic fetch. See "
            "docs/upstream-probes.md to configure a token.",
            file=sys.stderr,
        )
        return []

    try:
        meta = probe_upstream(remote_url, auth, offline=False)
    except HostNotAllowed:
        return []
    except ProviderUnknown as e:
        print(f"nostos add: --auto-tags: {e}; skipping topic fetch.", file=sys.stderr)
        return []
    except ProbeError as e:
        print(
            f"nostos add: --auto-tags: upstream probe failed ({e}); "
            "skipping topic fetch.",
            file=sys.stderr,
        )
        return []

    topics = meta.get("topics") or []
    raw = [str(t) for t in topics if isinstance(t, str)]
    rules = load_topic_rules()
    return rules.apply(raw)


def _resolve_auto_tags(cli_value: bool | None, cfg: dict[str, Any]) -> bool:
    """CLI flag overrides config; config defaults to False."""
    if cli_value is not None:
        return cli_value
    return bool(cfg.get("add_auto_tags", False))


def run(args: argparse.Namespace) -> int:
    maybe_migrate_watchlist()

    cfg = load_config()
    target = args.target
    tags = _flatten_tags(args.tag)
    auto_tags = _resolve_auto_tags(getattr(args, "auto_tags", None), cfg)

    if is_remote_url(target):
        clone_dir = args.clone_dir
        if clone_dir is None:
            clone_dir = cfg["clone_dir"] or os.getcwd()
        local_path = clone_repo(target, clone_dir)
        if local_path is None:
            return fail(f"clone failed: {target}")
        repo_path = local_path
        remote_url = target
    else:
        repo_path = target
        if not os.path.isdir(os.path.join(os.path.expanduser(repo_path), ".git")):
            return fail(f"not a git repository: {repo_path}")
        remote_url = None

    if auto_tags and remote_url and not args.quiet_upstream:
        fetched = _fetch_upstream_topics(remote_url)
        if fetched:
            existing = {t.lower() for t in tags}
            new_topics = [t for t in fetched if t.lower() not in existing]
            tags.extend(new_topics)
            if new_topics:
                print(
                    f"nostos add: --auto-tags: fetched {len(new_topics)} topic(s) "
                    f"from upstream: {', '.join(new_topics)}",
                    file=sys.stderr,
                )
    elif auto_tags and args.quiet_upstream:
        # Opsec: --quiet-upstream wins. Do not log the URL or warn loudly.
        pass

    try:
        with _index.connect() as conn:
            repo_id = _index.add_repo(
                conn,
                repo_path,
                remote_url=remote_url,
                source=args.source,
                status=args.status,
                quiet=args.quiet_upstream,
                tags=tags,
                note=args.note,
            )
    except (OSError, ValueError) as e:
        return fail(str(e))

    print(f"Added to index (id={repo_id}): {os.path.realpath(os.path.expanduser(repo_path))}",
          file=sys.stderr, flush=True)
    return 0
