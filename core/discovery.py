import fnmatch
import logging
import os
import sys
from typing import Generator

from .config import DEFAULT_DEPTH


def is_owned_by_current_user(path: str) -> bool:
    """Check if the path is owned by the current user (Unix) or skip check on Windows."""
    if sys.platform == "win32":
        return True
    try:
        return os.stat(path).st_uid == os.getuid()
    except OSError:
        return False


def is_excluded(path: str, patterns: list[str]) -> bool:
    """Check if a repo path matches any exclusion glob pattern."""
    name = os.path.basename(path)
    return any(fnmatch.fnmatch(name, p) for p in patterns)


def validate_path(path: str) -> str:
    """Resolve and validate the input path."""
    resolved = os.path.realpath(path)
    if not os.path.isdir(resolved):
        logging.error(f"Path does not exist or is not a directory: {resolved}")
        sys.exit(1)
    return resolved


def discover_repositories(
    root_directory: str,
    max_depth: int = DEFAULT_DEPTH,
    exclude_patterns: list[str] | None = None,
) -> Generator[str, None, None]:
    """Generator that yields repo paths as they are discovered.

    Walks the directory tree with a depth limit. Skips hidden directories,
    repos not owned by the current user, and repos matching exclude patterns.
    Stops descending into discovered repos to avoid nested repo traversal.
    """
    if exclude_patterns is None:
        exclude_patterns = []

    root_depth = root_directory.rstrip(os.sep).count(os.sep)

    for root, dirs, files in os.walk(root_directory):
        current_depth = root.rstrip(os.sep).count(os.sep) - root_depth
        if current_depth >= max_depth:
            dirs.clear()
            continue

        if ".git" in dirs:
            git_dir = os.path.join(root, ".git")

            if not is_owned_by_current_user(git_dir):
                logging.warning(f"Skipping repo not owned by current user: {root}")
                dirs.clear()
                continue

            if is_excluded(root, exclude_patterns):
                logging.info(f"Excluding: {root}")
                dirs.clear()
                continue

            yield root
            dirs.clear()
        else:
            dirs[:] = [d for d in dirs if not d.startswith(".")]
