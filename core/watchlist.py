import logging
import os
import re
import stat
import subprocess
import sys

WATCHLIST_FILENAME: str = ".gitpulse_repos"

_URL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^https?://"),
    re.compile(r"^git@[\w.\-]+:"),
    re.compile(r"^ssh://"),
    re.compile(r"^git://"),
]


def get_watchlist_path() -> str:
    return os.path.join(os.path.expanduser("~"), WATCHLIST_FILENAME)


def is_remote_url(value: str) -> bool:
    """Check if a string looks like a git remote URL."""
    return any(p.match(value) for p in _URL_PATTERNS)


def extract_repo_name(url: str) -> str:
    """Extract the repository name from a remote URL.

    Examples:
        https://github.com/user/repo.git -> repo
        git@github.com:user/repo.git -> repo
        https://gitlab.com/group/subgroup/repo -> repo
    """
    # Strip trailing slash and .git suffix
    cleaned = url.rstrip("/")
    if cleaned.endswith(".git"):
        cleaned = cleaned[:-4]

    # Get the last path segment
    if ":" in cleaned and not cleaned.startswith("http"):
        # SSH format: git@host:user/repo
        path_part = cleaned.split(":")[-1]
    else:
        # HTTPS format: https://host/user/repo
        path_part = cleaned

    name = path_part.rstrip("/").rsplit("/", 1)[-1]
    return name or "repo"


def _safe_clone_env() -> dict[str, str]:
    """Build an environment that disables git hooks during clone.

    Mitigates CVE-2024-32002, CVE-2024-32004, CVE-2024-32465 where
    malicious repos can execute arbitrary code via hooks during clone.
    """
    env = os.environ.copy()
    env["GIT_CONFIG_COUNT"] = "2"
    env["GIT_CONFIG_KEY_0"] = "core.hooksPath"
    env["GIT_CONFIG_VALUE_0"] = "/dev/null"
    env["GIT_CONFIG_KEY_1"] = "protocol.file.allow"
    env["GIT_CONFIG_VALUE_1"] = "user"
    return env


def clone_repo(url: str, clone_dir: str, timeout: int = 120) -> str | None:
    """Clone a remote repo into clone_dir. Returns the local path, or None on failure.

    Uses --no-checkout to prevent hook execution during clone, then
    checks out in a second step. Hooks are disabled via environment
    variables as defense-in-depth against CVE-2024-32002/32004/32465.
    """
    repo_name = extract_repo_name(url)
    target = os.path.join(clone_dir, repo_name)

    # Already cloned
    if os.path.isdir(os.path.join(target, ".git")):
        print(f"Already cloned: {target}")
        return target

    if os.path.exists(target):
        print(f"Error: {target} exists but is not a git repository", file=sys.stderr)
        return None

    if not os.path.isdir(clone_dir):
        os.makedirs(clone_dir, exist_ok=True)

    safe_env = _safe_clone_env()

    print(f"Cloning {url} into {target}...")
    try:
        # Phase 1: clone without checkout (no hooks fire)
        subprocess.run(
            ["git", "clone", "--no-checkout", url, target],
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=safe_env,
        )
        # Phase 2: checkout in the cloned repo (hooks still disabled via env)
        subprocess.run(
            ["git", "checkout"],
            cwd=target,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=safe_env,
        )
        print(f"Cloned: {target}")
        return target
    except subprocess.TimeoutExpired:
        print(f"Error: clone timed out after {timeout}s", file=sys.stderr)
        return None
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.strip() if e.stderr else str(e)
        print(f"Error cloning {url}: {stderr}", file=sys.stderr)
        return None


def _is_watchlist_safe(path: str) -> bool:
    """Verify the watchlist file exists and (on Unix) is owned by the current user
    and not world-writable. A nonexistent path is never considered safe."""
    try:
        st = os.stat(path)
    except OSError:
        return False
    if sys.platform == "win32":
        return True
    if st.st_uid != os.getuid():
        logging.warning(
            f"Ignoring {path}: owned by uid {st.st_uid}, not current user"
        )
        return False
    if st.st_mode & stat.S_IWOTH:
        logging.warning(
            f"Ignoring {path}: world-writable (fix with: chmod o-w {path})"
        )
        return False
    return True


def load_watchlist() -> list[str]:
    """Load repo paths from the watchlist file. Returns resolved, validated paths."""
    path = get_watchlist_path()
    if not os.path.isfile(path):
        return []
    if not _is_watchlist_safe(path):
        return []

    repos: list[str] = []
    stale: list[str] = []

    with open(path, encoding="utf-8") as f:
        for line in f:
            entry = line.strip()
            if not entry or entry.startswith("#"):
                continue
            resolved = os.path.realpath(entry)
            git_dir = os.path.join(resolved, ".git")
            if os.path.isdir(git_dir):
                repos.append(resolved)
            else:
                stale.append(entry)

    if stale:
        logging.warning(
            f"Watchlist: {len(stale)} stale entries (missing or not git repos):"
        )
        for s in stale:
            logging.warning(f"  {s}")

    return repos


def _read_raw_entries() -> list[str]:
    """Read all non-comment, non-blank lines from the watchlist file."""
    path = get_watchlist_path()
    if not os.path.isfile(path):
        return []
    entries: list[str] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            entry = line.strip()
            if entry and not entry.startswith("#"):
                entries.append(os.path.realpath(entry))
    return entries


def add_to_watchlist(repo_path: str, clone_dir: str | None = None) -> bool:
    """Add a repo to the watchlist. Accepts local paths or remote URLs.

    If repo_path is a remote URL, clones to clone_dir first.
    Returns True if added, False on error or duplicate.
    """
    if is_remote_url(repo_path):
        if clone_dir is None:
            clone_dir = os.getcwd()
        local_path = clone_repo(repo_path, clone_dir)
        if local_path is None:
            return False
        repo_path = local_path

    resolved = os.path.realpath(repo_path)
    git_dir = os.path.join(resolved, ".git")
    if not os.path.isdir(git_dir):
        print(f"Error: {resolved} is not a git repository", file=sys.stderr)
        return False

    existing = _read_raw_entries()
    if resolved in existing:
        print(f"Already in watchlist: {resolved}")
        return False

    path = get_watchlist_path()
    with open(path, "a", encoding="utf-8") as f:
        f.write(resolved + "\n")

    print(f"Added to watchlist: {resolved}")
    return True


def remove_from_watchlist(repo_path: str) -> bool:
    """Remove a repo path from the watchlist. Returns True if removed, False if not found."""
    resolved = os.path.realpath(repo_path)
    path = get_watchlist_path()

    if not os.path.isfile(path):
        print(f"Not in watchlist: {resolved}", file=sys.stderr)
        return False

    lines: list[str] = []
    found = False
    with open(path, encoding="utf-8") as f:
        for line in f:
            entry = line.strip()
            if entry and not entry.startswith("#"):
                if os.path.realpath(entry) == resolved:
                    found = True
                    continue
            lines.append(line)

    if not found:
        print(f"Not in watchlist: {resolved}", file=sys.stderr)
        return False

    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)

    print(f"Removed from watchlist: {resolved}")
    return True


def list_watchlist() -> list[str]:
    """List all entries in the watchlist, marking stale ones."""
    path = get_watchlist_path()
    if not os.path.isfile(path):
        print(f"Watchlist is empty (no file at {path})")
        return []

    entries: list[str] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            entry = line.strip()
            if not entry or entry.startswith("#"):
                continue
            resolved = os.path.realpath(entry)
            git_dir = os.path.join(resolved, ".git")
            if os.path.isdir(git_dir):
                print(f"  {resolved}")
            else:
                print(f"  {resolved}  [stale - not found]")
            entries.append(resolved)

    if not entries:
        print("Watchlist is empty.")

    return entries
