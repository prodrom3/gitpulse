"""`nostos refresh` - populate upstream metadata for registered repos.

Default behaviour is conservative:
- Only queries hosts listed in ~/.config/nostos/auth.toml (fail-closed).
- Skips repos with quiet=1 absolutely (no network, no log of repo path).
- Refreshes only stale cache entries (older than --since TTL).

Flags open this up:
- --all     refresh every registered repo regardless of cache freshness
- --force   same as --all (alias); refreshes even fresh entries
- --repo R  refresh exactly one repo (still subject to allow-list / quiet)
- --offline global kill switch: zero network traffic

No flag issues outbound calls to unconfigured hosts, ever. This is
the opsec guarantee documented in README > Security.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime
import logging
import sys
import threading
from typing import Any

from .. import index as _index
from ..auth import load_auth
from ..topic_rules import load_rules as load_topic_rules
from ..upstream import (
    HostNotAllowed,
    ProbeError,
    ProbeHTTPError,
    ProviderUnknown,
    fetch_repo_advisories,
    parse_remote_url,
    probe_upstream,
)
from ._common import fail, maybe_migrate_watchlist

_DEFAULT_TTL_DAYS: int = 7


def add_parser(subparsers: Any) -> None:
    p = subparsers.add_parser(
        "refresh",
        help="Fetch upstream metadata for registered repositories",
        description="Populate cached upstream metadata (stars, archived, "
        "last push, release, license) from the matching provider API. "
        "Fail-closed for unconfigured hosts; skip quiet repos.",
    )
    p.add_argument(
        "--repo",
        default=None,
        metavar="PATH_OR_ID",
        help="Refresh a single repository",
    )
    p.add_argument(
        "--since",
        type=int,
        default=_DEFAULT_TTL_DAYS,
        metavar="DAYS",
        help=f"Refresh entries whose cache is older than DAYS (default: {_DEFAULT_TTL_DAYS})",
    )
    p.add_argument(
        "--all",
        action="store_true",
        help="Refresh every registered repo, regardless of cache freshness",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Alias for --all; refresh even fresh entries",
    )
    p.add_argument(
        "--offline",
        action="store_true",
        help="Kill switch: make zero network calls (prints what would be refreshed)",
    )
    p.add_argument(
        "--auto-tags",
        action="store_true",
        help="After each successful probe, merge the upstream repo's "
        "topics into the repo's tag list (additive; never removes tags). "
        "Quiet repos and unconfigured hosts are still skipped.",
    )
    p.add_argument(
        "--cves",
        action="store_true",
        help="Also fetch GitHub Security Advisories per repo and store "
        "the open-advisory count + top severity in upstream_meta. "
        "Adds one extra paginated API call per repo on top of the "
        "main probe; gated by the same auth.toml allowlist.",
    )
    p.add_argument(
        "--workers",
        type=int,
        default=4,
        metavar="N",
        help="Concurrent probe workers (default: 4). Set to 1 to "
        "refresh serially. Each worker uses its own DB connection; "
        "GitHub rate limits are enforced via the existing "
        "Retry-After / X-RateLimit-Remaining handling.",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Emit a JSON summary instead of human-readable lines",
    )
    p.set_defaults(func=run)


def _collect_targets(
    conn: Any,
    *,
    repo_selector: str | None,
    refresh_all: bool,
    ttl_days: int,
) -> list[dict[str, Any]]:
    if repo_selector is not None:
        one = _index.get_repo(conn, repo_selector)
        return [one] if one else []
    if refresh_all:
        return _index.list_repos(conn)
    return _index.list_stale_upstream(conn, ttl_days=ttl_days)


def run(args: argparse.Namespace) -> int:
    maybe_migrate_watchlist()
    auth = load_auth()

    refresh_all = args.all or args.force

    try:
        with _index.connect() as conn:
            targets = _collect_targets(
                conn,
                repo_selector=args.repo,
                refresh_all=refresh_all,
                ttl_days=args.since,
            )
    except OSError as e:
        return fail(str(e))

    if not targets:
        print("nostos refresh: nothing to refresh", file=sys.stderr)
        return 0

    refreshed = 0
    skipped_quiet = 0
    skipped_unauthorised = 0
    failed = 0
    errors: list[dict[str, Any]] = []
    tagged_repos: list[dict[str, Any]] = []  # populated when --auto-tags is on
    counters_lock = threading.Lock()

    def _refresh_one(repo: dict[str, Any]) -> None:
        nonlocal refreshed, skipped_quiet, skipped_unauthorised, failed
        path = repo["path"]
        # Opsec: quiet repos are NEVER probed. Do not even log the path
        # at info level; debug only.
        if repo.get("quiet"):
            with counters_lock:
                skipped_quiet += 1
            logging.debug("nostos refresh: skipping quiet repo")
            return

        remote_url = repo.get("remote_url")
        if not remote_url:
            with counters_lock:
                failed += 1
                errors.append({"path": path, "error": "no remote_url recorded"})
            return

        parsed = parse_remote_url(remote_url)
        if parsed is None:
            with counters_lock:
                failed += 1
                errors.append({"path": path, "error": f"unparseable remote: {remote_url}"})
            return
        host, _, _ = parsed

        if not auth.is_allowed(host):
            with counters_lock:
                skipped_unauthorised += 1
            logging.debug(f"nostos refresh: host {host} not in auth.toml, skipping")
            return

        if args.offline:
            logging.info(f"nostos refresh: (offline) would refresh {path} from {host}")
            return

        try:
            meta = probe_upstream(remote_url, auth, offline=False)
        except HostNotAllowed:
            with counters_lock:
                skipped_unauthorised += 1
            return
        except ProviderUnknown as e:
            with counters_lock:
                failed += 1
                errors.append({"path": path, "error": f"provider unknown: {e}"})
            return
        except ProbeError as e:
            with counters_lock:
                failed += 1
                errors.append({"path": path, "error": str(e)})
            # Record the error so subsequent `show` can see why it failed.
            try:
                with _index.connect() as conn:
                    existing = _index.get_upstream_meta(conn, repo["id"]) or {}
                    existing["fetch_error"] = str(e)
                    existing.setdefault("provider", host)
                    existing.setdefault("host", host)
                    existing.setdefault("owner", "")
                    existing.setdefault("name", "")
                    _index.upsert_upstream_meta(conn, repo["id"], existing)
            except OSError:
                pass
            return

        if getattr(args, "cves", False):
            owner_for_cve = meta.get("owner") or ""
            name_for_cve = meta.get("name") or ""
            if owner_for_cve and name_for_cve and meta.get("provider") == "github":
                try:
                    cve_count, cve_top = fetch_repo_advisories(
                        host, owner_for_cve, name_for_cve, auth.resolve_token(host),
                    )
                    meta["cve_count"] = cve_count
                    meta["cve_top_severity"] = cve_top
                    meta["cve_fetched_at"] = datetime.datetime.now(
                        datetime.timezone.utc
                    ).isoformat(timespec="seconds")
                except ProbeHTTPError as e:
                    logging.debug(f"nostos refresh: cve fetch HTTP {e.status} for {path}")
                except ProbeError as e:
                    logging.debug(f"nostos refresh: cve fetch failed for {path}: {e}")

        try:
            with _index.connect() as conn:
                _index.upsert_upstream_meta(conn, repo["id"], meta)
                if args.auto_tags:
                    new_tags = _merge_topic_tags(
                        conn, repo["id"], meta.get("topics") or []
                    )
                else:
                    new_tags = []
            with counters_lock:
                refreshed += 1
                if new_tags:
                    tagged_repos.append({"path": path, "added": new_tags})
        except OSError as e:
            with counters_lock:
                failed += 1
                errors.append({"path": path, "error": f"index write failed: {e}"})

    workers = max(1, int(getattr(args, "workers", 4) or 1))
    if workers == 1 or len(targets) <= 1:
        for repo in targets:
            _refresh_one(repo)
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
            futures = [ex.submit(_refresh_one, repo) for repo in targets]
            for fut in concurrent.futures.as_completed(futures):
                fut.result()  # surface any unexpected exception

    summary = {
        "targets": len(targets),
        "refreshed": refreshed,
        "skipped_quiet": skipped_quiet,
        "skipped_unauthorised": skipped_unauthorised,
        "failed": failed,
        "errors": errors,
    }
    if args.auto_tags:
        summary["tagged_repos"] = tagged_repos
        summary["tags_added"] = sum(len(t["added"]) for t in tagged_repos)

    if args.json:
        import json as _json

        print(_json.dumps(summary, indent=2, default=str))
    else:
        print(
            f"refresh: {refreshed} refreshed, "
            f"{skipped_quiet} quiet-skipped, "
            f"{skipped_unauthorised} unconfigured-host-skipped, "
            f"{failed} failed "
            f"(targets: {len(targets)})",
            file=sys.stderr,
        )
        if args.auto_tags and tagged_repos:
            total = sum(len(t["added"]) for t in tagged_repos)
            print(
                f"  + auto-tags: added {total} new topic tag(s) "
                f"across {len(tagged_repos)} repo(s)",
                file=sys.stderr,
            )
            for t in tagged_repos[:10]:
                print(f"    {t['path']}: +{', '.join(t['added'])}", file=sys.stderr)
            if len(tagged_repos) > 10:
                print(f"    ...and {len(tagged_repos) - 10} more", file=sys.stderr)
        for err in errors[:10]:
            print(f"  ! {err['path']}: {err['error']}", file=sys.stderr)
        if len(errors) > 10:
            print(f"  ...and {len(errors) - 10} more", file=sys.stderr)

    return 1 if failed else 0


def _merge_topic_tags(
    conn: Any, repo_id: int, topics: list[str]
) -> list[str]:
    """Add upstream topics as tags on a repo. Returns the list of tags
    that were actually new (i.e. not already attached). Existing tags
    are never removed.

    Topic rules (deny / alias) are applied before the diff against the
    repo's current tags, so a freshly-aliased topic that already exists
    on the repo under its canonical form is correctly recognised as
    not-new.
    """
    if not topics:
        return []
    rules = load_topic_rules()
    curated = rules.apply([t for t in topics if isinstance(t, str)])
    if not curated:
        return []
    existing = {t.lower() for t in _index.get_tags(conn, repo_id)}
    new_tags = [t for t in curated if t.lower() not in existing]
    if new_tags:
        _index.add_tags(conn, repo_id, new_tags)
    return new_tags
