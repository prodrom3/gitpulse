import argparse
import os
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

from .config import load_config


def get_version() -> str:
    """Return the gitpulse version.

    Prefers installed package metadata (PEP 566) so a pip-installed command
    reports the right version; falls back to the source VERSION file for
    direct-source runs.
    """
    try:
        return _pkg_version("gitpulse")
    except PackageNotFoundError:
        pass
    version_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "VERSION")
    try:
        with open(version_file) as f:
            return f.read().strip()
    except OSError:
        return "unknown"


def parse_args() -> argparse.Namespace:
    config = load_config()

    parser = argparse.ArgumentParser(
        prog="gitpulse",
        description="Batch-update multiple git repositories in parallel.",
    )
    parser.add_argument(
        "-v", "--version",
        action="version",
        version=f"%(prog)s {get_version()}",
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Root directory to scan for repositories (default: current directory)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List discovered repositories without pulling",
    )
    parser.add_argument(
        "--fetch-only",
        action="store_true",
        help="Only fetch from remotes, do not merge or rebase",
    )
    parser.add_argument(
        "--rebase",
        action="store_true",
        default=config["rebase"],
        help="Use --rebase when pulling",
    )
    parser.add_argument(
        "--depth",
        type=int,
        default=config["depth"],
        help=f"Maximum directory depth to scan (default: {config['depth']})",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=config["workers"],
        help=f"Number of concurrent workers (default: {config['workers']})",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=config["timeout"],
        help=f"Timeout in seconds per git pull (default: {config['timeout']})",
    )
    parser.add_argument(
        "--exclude",
        nargs="*",
        default=config["exclude_patterns"],
        metavar="PATTERN",
        help="Glob patterns to exclude repos by directory name (e.g. 'archived-*' 'temp-*')",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON instead of human-readable text",
    )
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Suppress progress output, only show the final summary",
    )

    # Watchlist management
    watchlist_group = parser.add_argument_group("watchlist")
    watchlist_group.add_argument(
        "--add",
        metavar="PATH_OR_URL",
        help="Add a repository to the watchlist (local path or remote URL)",
    )
    watchlist_group.add_argument(
        "--remove",
        metavar="PATH",
        help="Remove a repository from the watchlist",
    )
    watchlist_group.add_argument(
        "--list",
        action="store_true",
        dest="list_watchlist",
        help="Show all repositories in the watchlist",
    )
    watchlist_group.add_argument(
        "--watchlist",
        action="store_true",
        help="Pull only watchlist repos (combine with path to also scan a directory)",
    )
    watchlist_group.add_argument(
        "--clone-dir",
        default=config["clone_dir"],
        metavar="DIR",
        help="Directory to clone remote repos into (default: current directory)",
    )

    return parser.parse_args()


def main_entry() -> None:
    """Entry point for pip-installed 'gitpulse' command."""
    from gitpulse import main
    main()
