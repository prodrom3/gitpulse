import concurrent.futures
import logging
import os
import signal
import sys
import threading
import types

from core.cli import parse_args
from core.config import load_config
from core.discovery import discover_repositories, validate_path
from core.logging_config import setup_logging
from core.models import RepoResult, RepoStatus
from core.output import print_human_summary, print_json_summary, print_progress
from core.updater import SSHMultiplexer, check_git_version, update_repository
from core.watchlist import add_to_watchlist, list_watchlist, load_watchlist, remove_from_watchlist

_shutdown = threading.Event()


def _handle_signal(signum: int, frame: types.FrameType | None) -> None:
    """Set shutdown flag on Ctrl+C so we can cancel pending work gracefully."""
    _shutdown.set()
    print("\nInterrupted - cancelling pending tasks...", file=sys.stderr, flush=True)


def _collect_repos(args: object) -> list[str]:
    """Collect repos from watchlist and/or directory scan, deduplicating."""
    repos: list[str] = []
    seen: set[str] = set()

    # Watchlist repos
    if getattr(args, "watchlist", False):
        for repo in load_watchlist():
            resolved = os.path.realpath(repo)
            if resolved not in seen:
                repos.append(resolved)
                seen.add(resolved)

    # Directory scan repos
    path = getattr(args, "path", None)
    if path is not None:
        root_directory = validate_path(path)
        for repo in discover_repositories(
            root_directory,
            max_depth=getattr(args, "depth", 5),
            exclude_patterns=getattr(args, "exclude", None),
        ):
            resolved = os.path.realpath(repo)
            if resolved not in seen:
                repos.append(resolved)
                seen.add(resolved)

    return repos


def main() -> None:
    signal.signal(signal.SIGINT, _handle_signal)

    args = parse_args()

    # Handle watchlist management commands (no logging setup needed)
    if args.add:
        add_to_watchlist(args.add, clone_dir=args.clone_dir)
        sys.exit(0)
    if args.remove:
        remove_from_watchlist(args.remove)
        sys.exit(0)
    if args.list_watchlist:
        list_watchlist()
        sys.exit(0)

    config = load_config()
    setup_logging(max_log_files=config["max_log_files"])
    check_git_version()

    # Default to cwd scan if no path given and not using watchlist
    if args.path is None and not args.watchlist:
        args.path = os.getcwd()

    ssh = SSHMultiplexer()
    ssh.setup()
    env = ssh.get_env()

    try:
        repos = _collect_repos(args)

        if not repos:
            logging.info("No repositories found.")
            sys.exit(0)

        if args.dry_run:
            print(f"\nRepositories found ({len(repos)}):")
            for repo in repos:
                print(f"  {repo}")
            sys.exit(0)

        total = len(repos)
        if not args.quiet and not args.json:
            logging.info(f"Found {total} repositories. Starting updates...")

        results: list[RepoResult] = []
        completed = 0

        # Producer/consumer: submit pull jobs as repos are collected.
        futures: dict[concurrent.futures.Future[RepoResult], str] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
            for repo in repos:
                if _shutdown.is_set():
                    break
                future = executor.submit(
                    update_repository, repo, args.rebase, args.timeout, env,
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
                    completed, total, result,
                    json_mode=args.json, quiet=args.quiet,
                )

        if _shutdown.is_set() and not args.quiet:
            print(
                f"\nInterrupted after {completed}/{total} repositories.",
                file=sys.stderr, flush=True,
            )

        if args.json:
            print_json_summary(results, total)
        else:
            print_human_summary(results, total)

        has_failures = any(r.status == RepoStatus.FAILED for r in results)
        sys.exit(1 if has_failures else 0)

    finally:
        ssh.cleanup()


if __name__ == "__main__":
    main()
