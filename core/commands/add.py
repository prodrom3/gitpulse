"""`nostos add` - ingest a repo into the metadata index.

Accepts:
- a local path to an existing git repository, OR
- a remote URL (HTTPS or SSH), OR
- `--from-owner OWNER` to bulk-ingest every public repo of a GitHub
  user / org with optional filters (--include-forks,
  --include-archived, --limit, --match, --lang).

For URL targets the repo is cloned first via the hardened clone
routine (hooks disabled, CVE-2024-32002/32004/32465 mitigated) and
then the resulting local path is registered.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import os
import re
import sys
from typing import Any

from .. import index as _index
from ..auth import load_auth
from ..config import load_config
from ..topic_rules import load_rules as load_topic_rules
from ..upstream import (
    HostNotAllowed,
    ProbeError,
    ProbeHTTPError,
    ProviderUnknown,
    list_owner_repos,
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
        nargs="?",
        default=None,
        help="Local path to a git repository, or a remote URL to clone. "
        "Optional when --from-owner is set.",
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

    # --- Bulk owner ingest (GitHub only for now) ---
    p.add_argument(
        "--from-owner",
        default=None,
        metavar="OWNER",
        help="Bulk-add every public repo of a GitHub user or org. "
        "Replaces the positional PATH_OR_URL. Skips forks and "
        "archived repos by default (override with --include-forks / "
        "--include-archived). Tags / source / note flags apply to "
        "every imported repo.",
    )
    p.add_argument(
        "--include-forks",
        action="store_true",
        help="With --from-owner: also include forked repositories",
    )
    p.add_argument(
        "--include-archived",
        action="store_true",
        help="With --from-owner: also include archived repositories",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="With --from-owner: cap to the top N repos by stargazers",
    )
    p.add_argument(
        "--match",
        default=None,
        metavar="REGEX",
        help="With --from-owner: only repos whose name matches this regex",
    )
    p.add_argument(
        "--lang",
        default=None,
        metavar="LANG",
        help="With --from-owner: only repos whose primary language is LANG "
        "(case-insensitive)",
    )
    p.add_argument(
        "--workers",
        type=int,
        default=4,
        metavar="N",
        help="With --from-owner: number of concurrent clones (default: 4). "
        "Set to 1 to clone serially.",
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


def _add_one(
    target: str,
    *,
    base_tags: list[str],
    args: argparse.Namespace,
    cfg: dict[str, Any],
    auto_tags: bool,
) -> int:
    """Add a single repo (URL or local path). Returns 0 on success, 1 on
    failure. Mirrors the original `run()` body so it can be called from
    the single-target path and the bulk `--from-owner` path."""
    tags = list(base_tags)

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

    print(
        f"Added to index (id={repo_id}): "
        f"{os.path.realpath(os.path.expanduser(repo_path))}",
        file=sys.stderr,
        flush=True,
    )
    return 0


def _filter_owner_repos(
    repos: list[dict[str, Any]],
    *,
    match: str | None,
    lang: str | None,
    limit: int | None,
) -> list[dict[str, Any]]:
    """Apply --match / --lang / --limit to the result of list_owner_repos."""
    out = list(repos)
    if match:
        try:
            pattern = re.compile(match)
        except re.error as e:
            raise ValueError(f"--match: invalid regex {match!r}: {e}") from None
        out = [r for r in out if pattern.search(r.get("name") or "")]
    if lang:
        target = lang.strip().lower()
        out = [
            r for r in out
            if isinstance(r.get("language"), str)
            and r["language"].lower() == target
        ]
    if limit is not None and limit > 0:
        out = sorted(out, key=lambda r: r.get("stargazers_count", 0), reverse=True)
        out = out[:limit]
    return out


def _run_from_owner(args: argparse.Namespace, cfg: dict[str, Any]) -> int:
    """Bulk-add every public repo of a GitHub user / org."""
    owner = args.from_owner.strip()
    if not owner:
        return fail("--from-owner: OWNER must be non-empty")

    # GitHub-only for now. Hardcode the host; future GitLab/Gitea support
    # would route through a small dispatcher off the host argument.
    host = "github.com"

    auth = load_auth()
    if not auth.is_allowed(host):
        return fail(
            f"--from-owner: host {host} is not configured in auth.toml. "
            "Add a [hosts.\"github.com\"] block with token_env to enable."
        )
    token = auth.resolve_token(host)

    print(
        f"nostos add --from-owner {owner}: querying {host} ...",
        file=sys.stderr,
    )
    try:
        repos = list_owner_repos(
            host,
            owner,
            token,
            include_forks=args.include_forks,
            include_archived=args.include_archived,
        )
    except ProbeHTTPError as e:
        if e.status == 404:
            return fail(
                f"--from-owner: owner {owner!r} not found on {host} "
                "(neither user nor org)."
            )
        return fail(f"--from-owner: upstream error: {e}")
    except ProbeError as e:
        return fail(f"--from-owner: upstream error: {e}")

    try:
        repos = _filter_owner_repos(
            repos, match=args.match, lang=args.lang, limit=args.limit,
        )
    except ValueError as e:
        return fail(str(e))

    if not repos:
        print(
            "nostos add --from-owner: no repos matched the filters.",
            file=sys.stderr,
        )
        return 0

    base_tags = _flatten_tags(args.tag)
    auto_tags = _resolve_auto_tags(getattr(args, "auto_tags", None), cfg)

    print(
        f"nostos add --from-owner {owner}: {len(repos)} repo(s) to ingest:",
        file=sys.stderr,
    )
    for r in repos:
        print(f"  {r['full_name']}  ({r.get('language') or '-'}, "
              f"stars={r['stargazers_count']})", file=sys.stderr)

    workers = max(1, int(getattr(args, "workers", 4) or 1))

    def _clone_and_register(r: dict[str, Any]) -> tuple[str, int]:
        url = r.get("clone_url") or r.get("html_url") or ""
        if not url:
            print(
                f"  ! {r['full_name']}: no clone URL in upstream metadata",
                file=sys.stderr,
            )
            return r["full_name"], 1
        rc = _add_one(
            url, base_tags=base_tags, args=args, cfg=cfg, auto_tags=auto_tags,
        )
        return r["full_name"], rc

    succeeded = 0
    failed = 0
    if workers == 1:
        for r in repos:
            _, rc = _clone_and_register(r)
            if rc == 0:
                succeeded += 1
            else:
                failed += 1
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
            futures = [ex.submit(_clone_and_register, r) for r in repos]
            for fut in concurrent.futures.as_completed(futures):
                _, rc = fut.result()
                if rc == 0:
                    succeeded += 1
                else:
                    failed += 1

    print(
        f"nostos add --from-owner {owner}: "
        f"{succeeded} added, {failed} failed (of {len(repos)} matched).",
        file=sys.stderr,
    )
    return 1 if failed and not succeeded else 0


def run(args: argparse.Namespace) -> int:
    maybe_migrate_watchlist()
    cfg = load_config()

    from_owner = getattr(args, "from_owner", None)
    if from_owner:
        if args.target:
            return fail(
                "--from-owner and a positional PATH_OR_URL are mutually "
                "exclusive."
            )
        return _run_from_owner(args, cfg)

    if not args.target:
        return fail(
            "missing PATH_OR_URL. Pass a local path / URL, or use "
            "--from-owner OWNER for bulk ingest."
        )

    base_tags = _flatten_tags(args.tag)
    auto_tags = _resolve_auto_tags(getattr(args, "auto_tags", None), cfg)
    return _add_one(
        args.target,
        base_tags=base_tags,
        args=args,
        cfg=cfg,
        auto_tags=auto_tags,
    )
