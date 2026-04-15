"""`gitpulse pull` - batch-update the repo fleet.

This is the historical behavior of gitpulse. It discovers repositories
(via directory scan and/or the index), pulls them concurrently with
hardening, prints a summary, and exits 0/1. Each touched repo is
also recorded in / updated against the metadata index so future
`list`, `show`, and `triage` reflect the real state.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import logging
import os
import signal
import sys
import threading
import types
from typing import Any

from .. import index as _index
from ..config import load_config
from ..discovery import discover_repositories, validate_path
from ..logging_config import setup_logging
from ..models import RepoResult, RepoStatus
from ..output import print_human_summary, print_json_summary, print_progress
from ..updater import SSHMultiplexer, check_git_version, update_repository
from ._common import maybe_migrate_watchlist

_shutdown = threading.Event()


def _handle_signal(signum: int, frame: types.FrameType | None) -> None:
    _shutdown.set()
    print("\nInterrupted - cancelling pending tasks...", file=sys.stderr, flush=True)


def add_parser(subparsers: Any) -> None:
    config = load_config()
    p = subparsers.add_parser(
        "pull",
        help="Batch-update repositories (directory scan and/or index)",
        description="Batch-update git repositories in parallel.",
    )
    p.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Root directory to scan for repositories (default: current directory)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="List discovered repositories without pulling",
    )
    p.add_argument(
        "--fetch-only",
        action="store_true",
        help="Only fetch from remotes; do not merge or rebase",
    )
    p.add_argument(
        "--rebase",
        action="store_true",
        default=config["rebase"],
        help="Use --rebase when pulling",
    )
    p.add_argument(
        "--depth",
        type=int,
        default=config["depth"],
        help=f"Maximum directory depth to scan (default: {config['depth']})",
    )
    p.add_argument(
        "--workers",
        type=int,
        default=config["workers"],
        help=f"Number of concurrent workers (default: {config['workers']})",
    )
    p.add_argument(
        "--timeout",
        type=int,
        default=config["timeout"],
        help=f"Timeout in seconds per git pull (default: {config['timeout']})",
    )
    p.add_argument(
        "--exclude",
        nargs="*",
        default=config["exclude_patterns"],
        metavar="PATTERN",
        help="Glob patterns to exclude repos by directory name",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON instead of human-readable text",
    )
    p.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress progress output; only show the final summary",
    )
    p.add_argument(
        "--from-index",
        action="store_true",
        help="Pull every repository registered in the metadata index",
    )
    p.add_argument(
        "--watchlist",
        action="store_true",
        help="Alias for --from-index (deprecated; will be removed in a future release)",
    )
    p.set_defaults(func=run)


def _collect_repos(args: argparse.Namespace) -> list[str]:
    """Collect repos from the index and/or directory scan, deduplicated."""
    repos: list[str] = []
    seen: set[str] = set()

    from_index = getattr(args, "from_index", False) or getattr(args, "watchlist", False)
    if from_index:
        try:
            with _index.connect() as conn:
                for indexed in _index.list_repos(conn):
                    resolved = os.path.realpath(indexed["path"])
                    if resolved not in seen:
                        repos.append(resolved)
                        seen.add(resolved)
        except OSError as e:
            logging.warning(f"Could not read metadata index: {e}")

    path = getattr(args, "path", None)
    if path is not None:
        root_directory = validate_path(path)
        for discovered in discover_repositories(
            root_directory,
            max_depth=getattr(args, "depth", 5),
            exclude_patterns=getattr(args, "exclude", None),
        ):
            resolved = os.path.realpath(discovered)
            if resolved not in seen:
                repos.append(resolved)
                seen.add(resolved)

    return repos


def _record_in_index(results: list[RepoResult]) -> None:
    """Auto-register every touched repo and update last_touched_at."""
    if not results:
        return
    try:
        with _index.connect() as conn:
            for r in results:
                _index.add_repo(
                    conn,
                    r.path,
                    remote_url=r.remote_url,
                    source="auto-discovered",
                )
                _index.touch_repo(conn, r.path)
    except OSError as e:
        logging.warning(f"Could not update metadata index: {e}")


def run(args: argparse.Namespace) -> int:
    signal.signal(signal.SIGINT, _handle_signal)

    maybe_migrate_watchlist()

    if getattr(args, "watchlist", False) and not getattr(args, "from_index", False):
        print(
            "gitpulse: warning: --watchlist is deprecated; use --from-index instead",
            file=sys.stderr,
            flush=True,
        )

    config = load_config()
    setup_logging(max_log_files=config["max_log_files"])
    check_git_version()

    from_index = getattr(args, "from_index", False) or getattr(args, "watchlist", False)
    if args.path is None and not from_index:
        args.path = os.getcwd()

    ssh = SSHMultiplexer()
    ssh.setup()
    env = ssh.get_env()

    try:
        repos = _collect_repos(args)

        if not repos:
            logging.info("No repositories found.")
            return 0

        if args.dry_run:
            print(f"\nRepositories found ({len(repos)}):")
            for repo in repos:
                print(f"  {repo}")
            return 0

        total = len(repos)
        if not args.quiet and not args.json:
            logging.info(f"Found {total} repositories. Starting updates...")

        results: list[RepoResult] = []
        completed = 0

        futures: dict[concurrent.futures.Future[RepoResult], str] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
            for repo in repos:
                if _shutdown.is_set():
                    break
                future = executor.submit(
                    update_repository,
                    repo,
                    args.rebase,
                    args.timeout,
                    env,
                    args.fetch_only,
                )
                futures[future] = repo

            for future in concurrent.futures.as_completed(futures):
                if _shutdown.is_set():
                    for f in futures:
                        f.cancel()
                    break
                result = future.result()
                results.append(result)
                completed += 1
                print_progress(
                    completed,
                    total,
                    result,
                    json_mode=args.json,
                    quiet=args.quiet,
                )

        if _shutdown.is_set() and not args.quiet:
            print(
                f"\nInterrupted after {completed}/{total} repositories.",
                file=sys.stderr,
                flush=True,
            )

        _record_in_index(results)

        if args.json:
            print_json_summary(results, total)
        else:
            print_human_summary(results, total)

        has_failures = any(r.status == RepoStatus.FAILED for r in results)
        return 1 if has_failures else 0

    finally:
        ssh.cleanup()
