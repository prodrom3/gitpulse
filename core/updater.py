import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Optional

from .config import DEFAULT_TIMEOUT
from .models import RepoResult, RepoStatus

MIN_GIT_VERSION: tuple[int, ...] = (2, 45, 1)


def check_git_version() -> None:
    """Warn if the installed git version is below the minimum safe version.

    Git < 2.45.1 is vulnerable to:
    - CVE-2024-32002: RCE via symlinks in submodules during clone
    - CVE-2024-32004: Arbitrary code execution from local clones
    - CVE-2024-32465: Hook execution from untrusted repos
    """
    try:
        result = subprocess.run(
            ["git", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        # Output: "git version 2.45.1" or "git version 2.45.1.windows.1"
        version_str = result.stdout.strip().replace("git version ", "")
        parts = version_str.split(".")
        version = tuple(int(p) for p in parts[:3] if p.isdigit())
        if version < MIN_GIT_VERSION:
            min_str = ".".join(str(v) for v in MIN_GIT_VERSION)
            logging.warning(
                f"Git {version_str} detected. Version >= {min_str} is recommended "
                f"to mitigate CVE-2024-32002, CVE-2024-32004, CVE-2024-32465."
            )
    except (subprocess.TimeoutExpired, OSError, ValueError):
        logging.warning("Could not determine git version.")


def sanitize_log_output(text: str) -> str:
    """Strip potential credentials from git output (e.g. https://user:token@host URLs)."""
    return re.sub(r"(https?://)([^@]+)@", r"\1***@", text)


def get_branch(repo_path: str) -> str | None:
    """Get the current branch name, or None on failure."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except (subprocess.TimeoutExpired, OSError):
        return None


def get_remote_url(repo_path: str) -> str | None:
    """Get the remote origin URL, or None on failure."""
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        url = result.stdout.strip() if result.returncode == 0 else None
        return sanitize_log_output(url) if url else None
    except (subprocess.TimeoutExpired, OSError):
        return None


def check_repo_state(repo_path: str) -> tuple[bool, str | None, str | None]:
    """Check if a repo is in a pullable state. Returns (ok, reason, branch)."""
    try:
        head_check = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        branch = head_check.stdout.strip()
        if branch == "HEAD":
            return False, "detached HEAD", None

        tracking_check = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "@{upstream}"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if tracking_check.returncode != 0:
            return False, f"branch '{branch}' has no upstream tracking branch", branch

        dirty_check = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if dirty_check.stdout.strip():
            return False, "dirty working tree (uncommitted changes)", branch

        return True, None, branch
    except subprocess.TimeoutExpired:
        return False, "timed out checking repo state", None
    except OSError as e:
        return False, str(e), None


def fetch_repo(
    repo_path: str,
    timeout: int,
    env: dict[str, str] | None = None,
) -> tuple[int, str | None]:
    """Fetch from remote. Returns (behind_count, error_message)."""
    try:
        subprocess.run(
            ["git", "fetch"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        result = subprocess.run(
            ["git", "rev-list", "HEAD..@{upstream}", "--count"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        count = result.stdout.strip()
        if count.isdigit():
            return int(count), None
        return 0, None
    except subprocess.TimeoutExpired:
        return -1, f"timed out after {timeout}s"
    except OSError as e:
        return -1, str(e)


def update_repository(
    repo_path: str,
    rebase: bool = False,
    timeout: int = DEFAULT_TIMEOUT,
    env: dict[str, str] | None = None,
    fetch_only: bool = False,
) -> RepoResult:
    """Pull (or fetch) a single repository. Returns a RepoResult."""
    logging.info(f"Checking: {repo_path}")

    ok, reason, branch = check_repo_state(repo_path)
    remote_url = get_remote_url(repo_path)

    if not ok:
        logging.warning(f"Skipping {repo_path}: {reason}")
        return RepoResult(repo_path, RepoStatus.SKIPPED, reason, branch, remote_url)

    behind_count, fetch_error = fetch_repo(repo_path, timeout, env=env)

    if fetch_error:
        logging.error(f"Failed to fetch {repo_path}: {fetch_error}")
        return RepoResult(repo_path, RepoStatus.FAILED, fetch_error, branch, remote_url)

    if behind_count == 0:
        logging.info(f"Already up-to-date: {repo_path}")
        return RepoResult(repo_path, RepoStatus.UP_TO_DATE, None, branch, remote_url)

    if fetch_only:
        logging.info(f"Fetched {repo_path} ({behind_count} commits behind)")
        return RepoResult(
            repo_path, RepoStatus.FETCHED,
            f"{behind_count} commits behind", branch, remote_url,
        )

    cmd = ["git", "pull"]
    if rebase:
        cmd.append("--rebase")

    try:
        result = subprocess.run(
            cmd,
            cwd=repo_path,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        logging.info(f"Successfully updated: {repo_path}")
        if result.stdout.strip():
            logging.info(result.stdout.strip())
        return RepoResult(repo_path, RepoStatus.UPDATED, None, branch, remote_url)
    except subprocess.TimeoutExpired:
        msg = f"timed out after {timeout}s"
        logging.error(f"Timed out updating {repo_path} after {timeout}s")
        return RepoResult(repo_path, RepoStatus.FAILED, msg, branch, remote_url)
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.strip() if e.stderr else str(e)
        sanitized = sanitize_log_output(stderr)
        logging.error(f"Failed to update {repo_path}: {sanitized}")
        return RepoResult(repo_path, RepoStatus.FAILED, sanitized, branch, remote_url)


class SSHMultiplexer:
    """Manages SSH connection multiplexing for faster fetches on Unix.

    Sets up SSH ControlMaster so multiple git operations to the same host
    reuse a single SSH connection. Automatically disabled on Windows.
    """

    def __init__(self) -> None:
        self.enabled: bool = sys.platform != "win32"
        self.control_dir: str | None = None
        self._env: dict[str, str] | None = None

    def setup(self) -> None:
        if not self.enabled:
            return
        if not shutil.which("ssh"):
            self.enabled = False
            return
        self.control_dir = tempfile.mkdtemp(prefix="gitpulse-ssh-")
        control_path = os.path.join(self.control_dir, "%h_%p_%r")
        ssh_cmd = (
            f'ssh -o ControlMaster=auto'
            f' -o "ControlPath={control_path}"'
            f' -o ControlPersist=60'
        )
        self._env = os.environ.copy()
        self._env["GIT_SSH_COMMAND"] = ssh_cmd

    def get_env(self) -> dict[str, str] | None:
        if self.enabled and self._env:
            return self._env
        return None

    def cleanup(self) -> None:
        if self.control_dir and os.path.isdir(self.control_dir):
            shutil.rmtree(self.control_dir, ignore_errors=True)
            self.control_dir = None
            self._env = None
