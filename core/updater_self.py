"""Self-update helpers for `gitpulse update`.

This module is intentionally separate from `core.updater` (which does
`git pull` for tracked repositories) to keep the two mental models
apart: `updater` updates the fleet, `updater_self` updates gitpulse
itself.

No code here executes a self-update without the caller's explicit
consent. We only detect, recommend, and (on request) run a
well-known command for the detected install method.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from typing import Any

_RELEASES_URL: str = "https://api.github.com/repos/prodrom3/gitpulse/releases/latest"


class UpdateError(Exception):
    """Raised for any hard failure in the self-update flow."""


# ---------- release check ----------


def fetch_latest_release(
    *,
    token: str | None = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """Fetch the latest release from the GitHub API. Returns the raw dict.

    Issues a single authenticated-or-unauthenticated GET. Unauth is
    fine for occasional checks (60 req/hour is plenty for humans).
    """
    req = urllib.request.Request(_RELEASES_URL, method="GET")
    req.add_header("User-Agent", "gitpulse-self-update")
    req.add_header("Accept", "application/vnd.github+json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raise UpdateError(f"GitHub API returned {e.code}") from None
    except urllib.error.URLError as e:
        raise UpdateError(f"network error: {e.reason}") from None
    except TimeoutError:
        raise UpdateError("timeout contacting GitHub") from None
    except OSError as e:
        raise UpdateError(f"os error: {e}") from None
    try:
        data = json.loads(body)
    except json.JSONDecodeError as e:
        raise UpdateError(f"invalid JSON from GitHub: {e}") from None
    if not isinstance(data, dict):
        raise UpdateError("unexpected response shape from GitHub")
    return data


def normalize_tag(raw: str) -> str:
    """Turn v2.4.0 / 2.4.0 / release-2.4.0 into 2.4.0, else raise."""
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", raw or "")
    if not m:
        raise UpdateError(f"cannot parse release tag: {raw!r}")
    return f"{m.group(1)}.{m.group(2)}.{m.group(3)}"


def version_tuple(ver: str) -> tuple[int, int, int]:
    """(2, 4, 0) from a normalised '2.4.0'. Raises on malformed input."""
    parts = ver.split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise UpdateError(f"cannot parse version: {ver!r}")
    return (int(parts[0]), int(parts[1]), int(parts[2]))


def is_newer(remote: str, local: str) -> bool:
    try:
        return version_tuple(remote) > version_tuple(local)
    except UpdateError:
        return False


# ---------- install-method detection ----------


def _repo_root() -> str:
    """Repo root of the currently running gitpulse, if any."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return here


def _looks_like_gitpulse_repo(path: str) -> bool:
    """Does `path` look like a git checkout of prodrom3/gitpulse?"""
    git_dir = os.path.join(path, ".git")
    if not os.path.isdir(git_dir):
        return False
    # Cheapest check: is there a VERSION file at the root?
    if not os.path.isfile(os.path.join(path, "VERSION")):
        return False
    # Check the remote URL via git; if git is unavailable, fall back
    # to a positive signal if the VERSION file exists.
    try:
        result = subprocess.run(
            ["git", "-C", path, "config", "--get", "remote.origin.url"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        url = (result.stdout or "").strip().lower()
        return "prodrom3/gitpulse" in url or "gitpulse" in url
    except (OSError, subprocess.TimeoutExpired):
        return True


def _pipx_has_gitpulse() -> bool:
    """Best-effort check: `pipx list --json` mentions gitpulse."""
    if shutil.which("pipx") is None:
        return False
    try:
        result = subprocess.run(
            ["pipx", "list", "--json"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            return False
        data = json.loads(result.stdout or "{}")
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return False
    venvs = data.get("venvs") if isinstance(data, dict) else None
    return isinstance(venvs, dict) and "gitpulse" in venvs


def detect_install_method() -> dict[str, Any]:
    """Return a dict describing how the running gitpulse was installed.

    Keys:
        method: 'source' | 'pipx' | 'pip' | 'unknown'
        source_dir: path (method='source' only)
        upgrade_cmd: shell command string, or None if we cannot determine one
        notes: human hint for the caller to print
    """
    root = _repo_root()
    if _looks_like_gitpulse_repo(root):
        return {
            "method": "source",
            "source_dir": root,
            "upgrade_cmd": f"git -C {root} pull --ff-only",
            "notes": "Updating will fast-forward your local checkout.",
        }
    if _pipx_has_gitpulse():
        return {
            "method": "pipx",
            "source_dir": None,
            "upgrade_cmd": "pipx upgrade gitpulse",
            "notes": "Updating will reinstall gitpulse into its pipx venv.",
        }
    return {
        "method": "pip",
        "source_dir": None,
        "upgrade_cmd": (
            "pip install --upgrade git+https://github.com/prodrom3/gitpulse.git"
        ),
        "notes": (
            "Could not auto-detect a source clone or pipx install. If you "
            "installed via pip, the suggested command above may need sudo "
            "or --user depending on your environment; apply manually."
        ),
    }


# ---------- run update ----------


def run_upgrade(detection: dict[str, Any], *, timeout: float = 300.0) -> str:
    """Execute the suggested upgrade command for the detected method.

    Only safe methods are run automatically:
    - 'source': a `git -C <root> pull --ff-only` in the known repo.
    - 'pipx':   `pipx upgrade gitpulse`.

    For method='pip' we deliberately return the recommended command as
    text; we never invoke pip ourselves because the right invocation
    depends on whether the install is --user, system-wide, or virtualenv.
    Returns the combined stdout+stderr for the caller to surface.
    """
    method = detection.get("method")
    if method == "source":
        root = detection["source_dir"]
        return _run(["git", "-C", root, "pull", "--ff-only"], timeout)
    if method == "pipx":
        return _run(["pipx", "upgrade", "gitpulse"], timeout)
    raise UpdateError(
        "automatic upgrade is not supported for this install method; "
        f"run manually: {detection.get('upgrade_cmd')}"
    )


def _run(cmd: list[str], timeout: float) -> str:
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as e:
        raise UpdateError(f"binary not found: {e}") from None
    except subprocess.TimeoutExpired:
        raise UpdateError(f"upgrade timed out after {timeout}s") from None
    out = (result.stdout or "") + (result.stderr or "")
    if result.returncode != 0:
        raise UpdateError(f"{' '.join(cmd)} failed (rc={result.returncode}): {out.strip()}")
    return out.strip()
