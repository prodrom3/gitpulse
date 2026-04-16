"""Upstream metadata probes for nostos.

Parses a git remote URL into (provider, host, owner, name), then calls
the matching provider probe to fetch a small metadata record (stars,
archived, default branch, last push, latest release, license) which
is cached in the metadata index.

Design principles
- Zero new runtime dependencies: everything uses urllib.request.
- Fail-closed on unknown hosts: a host not present in
  ~/.config/nostos/auth.toml is skipped entirely (no network call).
  This is the critical opsec guarantee; see README > Security.
- Per-repo `quiet=1` repos are always skipped: the upstream layer
  never queries them, never logs them.
- Tokens are redacted from every log path; inline tokens are passed
  via Authorization header only.
- Errors are surfaced, not swallowed: the caller decides whether to
  record the error in upstream_meta.fetch_error or just report.
"""

from __future__ import annotations

import datetime
import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Protocol

from .auth import AuthConfig


class _Probe(Protocol):
    kind: str

    def fetch(
        self,
        host: str,
        owner: str,
        name: str,
        token: str | None,
    ) -> dict[str, Any]: ...

# ---------- result / error types ----------


class ProbeError(Exception):
    """Base class for upstream probe failures surfaced to callers."""


class HostNotAllowed(ProbeError):
    """Host is not configured in auth.toml and allow_unknown is False."""


class ProviderUnknown(ProbeError):
    """Host is configured but no probe is registered for its provider."""


class ProbeHTTPError(ProbeError):
    """The upstream API returned an error (401, 403, 404, 429, 5xx, etc.)."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


# ---------- remote URL parsing ----------


_SCP_RE = re.compile(r"^(?:[\w.\-]+@)?(?P<host>[\w.\-]+):(?P<path>[\w./\-]+?)(?:\.git)?$")
_URL_RE = re.compile(
    r"^(?:https?|ssh|git)://(?:[\w.\-]+@)?(?P<host>[\w.\-]+)"
    r"(?::\d+)?/(?P<path>[\w./\-]+?)(?:\.git)?/?$"
)


def parse_remote_url(url: str) -> tuple[str, str, str] | None:
    """Return (host, owner, name) or None if the URL is unrecognisable.

    Handles the common git remote forms:
    - git@github.com:owner/repo.git            (SCP-style SSH)
    - ssh://git@github.com/owner/repo.git      (ssh:// URL)
    - https://github.com/owner/repo(.git)      (HTTPS)
    - git://host/owner/repo.git                (git://)
    and gracefully handles subgroup paths on GitLab by taking the
    *last* path component as the repo name and everything-before
    as the owner (so 'group/subgroup/repo' becomes owner='group/subgroup').
    """
    if not url:
        return None
    url = url.strip()

    m = _URL_RE.match(url)
    if m is None:
        m = _SCP_RE.match(url)
    if m is None:
        return None

    host = m.group("host")
    path = m.group("path").rstrip("/").removesuffix(".git")
    parts = path.split("/")
    if len(parts) < 2:
        return None
    name = parts[-1]
    owner = "/".join(parts[:-1])
    return host, owner, name


# ---------- provider probes ----------


def _http_get_json(
    url: str,
    *,
    token: str | None = None,
    accept: str | None = None,
    timeout: float = 15.0,
) -> tuple[dict[str, Any], dict[str, str]]:
    """GET a URL and parse JSON. Returns (body, headers).

    Raises ProbeHTTPError on HTTP 4xx/5xx, ProbeError on parse/timeout
    failures. Never logs Authorization headers.
    """
    req = urllib.request.Request(url, method="GET")
    req.add_header("User-Agent", "nostos")
    if accept:
        req.add_header("Accept", accept)
    if token:
        # GitHub uses 'Bearer <token>'; GitLab/Gitea use 'token <token>' on
        # /api/v4 and /api/v1 respectively, but both also accept
        # 'Authorization: Bearer' since late 2023.
        req.add_header("Authorization", f"Bearer {token}")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            headers = {k: v for k, v in resp.headers.items()}
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        # Drain to get a message if possible; still don't leak auth.
        try:
            body = e.read().decode("utf-8", errors="replace")
        except OSError:
            body = ""
        msg = _short_http_message(body) or e.reason or ""
        raise ProbeHTTPError(e.code, f"{e.code} {msg}") from None
    except urllib.error.URLError as e:
        raise ProbeError(f"network error: {e.reason}") from None
    except TimeoutError:
        raise ProbeError("timeout") from None
    except OSError as e:
        raise ProbeError(f"os error: {e}") from None

    try:
        data = json.loads(body)
    except json.JSONDecodeError as e:
        raise ProbeError(f"invalid JSON from upstream: {e}") from None
    if not isinstance(data, dict):
        raise ProbeError("unexpected JSON shape from upstream")
    return data, headers


def _short_http_message(body: str) -> str:
    """Extract a short human message from a JSON error body, never a token."""
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        return body[:80].replace("\n", " ")
    if isinstance(data, dict):
        for key in ("message", "error", "description"):
            val = data.get(key)
            if isinstance(val, str):
                return val[:120]
    return ""


def _respect_rate_limit(headers: dict[str, str]) -> None:
    """Sleep briefly when a provider reports we are near zero remaining."""
    remaining = headers.get("X-RateLimit-Remaining") or headers.get(
        "RateLimit-Remaining"
    )
    try:
        if remaining is not None and int(remaining) <= 1:
            logging.warning(
                "nostos: upstream rate-limit nearly exhausted "
                f"(remaining={remaining}); sleeping 2s"
            )
            time.sleep(2)
    except ValueError:
        pass


# ---- GitHub (github.com + GHE) ----


class GitHubProbe:
    kind = "github"

    @staticmethod
    def api_base(host: str) -> str:
        if host == "github.com":
            return "https://api.github.com"
        # GitHub Enterprise: <host>/api/v3
        return f"https://{host}/api/v3"

    def fetch(
        self,
        host: str,
        owner: str,
        name: str,
        token: str | None,
    ) -> dict[str, Any]:
        base = self.api_base(host)
        repo_url = f"{base}/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(name)}"
        data, headers = _http_get_json(
            repo_url,
            token=token,
            accept="application/vnd.github+json",
        )
        _respect_rate_limit(headers)

        license_info = data.get("license") or {}
        license_name = license_info.get("spdx_id") if isinstance(license_info, dict) else None

        result: dict[str, Any] = {
            "provider": self.kind,
            "host": host,
            "owner": owner,
            "name": name,
            "description": data.get("description"),
            "stars": data.get("stargazers_count"),
            "forks": data.get("forks_count"),
            "open_issues": data.get("open_issues_count"),
            "archived": bool(data.get("archived")),
            "default_branch": data.get("default_branch"),
            "license": license_name,
            "last_push": data.get("pushed_at"),
            "latest_release": None,
        }

        # Latest release (optional; a repo with no releases returns 404).
        try:
            rel, _ = _http_get_json(
                f"{base}/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(name)}/releases/latest",
                token=token,
                accept="application/vnd.github+json",
            )
            result["latest_release"] = rel.get("tag_name")
        except ProbeHTTPError as e:
            if e.status != 404:
                # Non-404 is unusual but not fatal; leave latest_release as None.
                logging.debug(f"nostos: release fetch failed: {e}")
        except ProbeError:
            pass

        return result


# ---- GitLab (gitlab.com + self-hosted) ----


class GitLabProbe:
    kind = "gitlab"

    @staticmethod
    def api_base(host: str) -> str:
        return f"https://{host}/api/v4"

    def fetch(
        self,
        host: str,
        owner: str,
        name: str,
        token: str | None,
    ) -> dict[str, Any]:
        base = self.api_base(host)
        project = urllib.parse.quote(f"{owner}/{name}", safe="")
        data, headers = _http_get_json(f"{base}/projects/{project}", token=token)
        _respect_rate_limit(headers)

        last_push = data.get("last_activity_at") or data.get("pushed_at")

        result: dict[str, Any] = {
            "provider": self.kind,
            "host": host,
            "owner": owner,
            "name": name,
            "description": data.get("description"),
            "stars": data.get("star_count"),
            "forks": data.get("forks_count"),
            "open_issues": data.get("open_issues_count"),
            "archived": bool(data.get("archived")),
            "default_branch": data.get("default_branch"),
            "license": (data.get("license") or {}).get("nickname")
            or (data.get("license") or {}).get("key"),
            "last_push": last_push,
            "latest_release": None,
        }

        try:
            rel, _ = _http_get_json(
                f"{base}/projects/{project}/releases?per_page=1", token=token
            )
            # GitLab returns a list; but our _http_get_json demands a dict.
            # Use a list-accepting fallback here.
        except ProbeError:
            pass

        try:
            req = urllib.request.Request(
                f"{base}/projects/{project}/releases?per_page=1", method="GET"
            )
            req.add_header("User-Agent", "nostos")
            if token:
                req.add_header("Authorization", f"Bearer {token}")
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = resp.read().decode("utf-8", errors="replace")
            items = json.loads(body)
            if isinstance(items, list) and items:
                tag = items[0].get("tag_name")
                if tag:
                    result["latest_release"] = tag
        except (urllib.error.URLError, OSError, ValueError, TimeoutError):
            pass

        return result


# ---- Gitea (self-hosted) ----


class GiteaProbe:
    kind = "gitea"

    @staticmethod
    def api_base(host: str) -> str:
        return f"https://{host}/api/v1"

    def fetch(
        self,
        host: str,
        owner: str,
        name: str,
        token: str | None,
    ) -> dict[str, Any]:
        base = self.api_base(host)
        data, headers = _http_get_json(
            f"{base}/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(name)}",
            token=token,
        )
        _respect_rate_limit(headers)

        result: dict[str, Any] = {
            "provider": self.kind,
            "host": host,
            "owner": owner,
            "name": name,
            "description": data.get("description"),
            "stars": data.get("stars_count"),
            "forks": data.get("forks_count"),
            "open_issues": data.get("open_issues_count"),
            "archived": bool(data.get("archived")),
            "default_branch": data.get("default_branch"),
            "license": None,
            "last_push": data.get("updated_at"),
            "latest_release": None,
        }
        return result


_PROBES: dict[str, _Probe] = {
    "github": GitHubProbe(),
    "gitlab": GitLabProbe(),
    "gitea": GiteaProbe(),
}


# ---------- dispatcher ----------


def probe_upstream(
    remote_url: str,
    auth: AuthConfig,
    *,
    offline: bool = False,
) -> dict[str, Any]:
    """Probe the upstream for a repo. Returns a dict matching the
    upstream_meta schema, with `fetched_at` set.

    Raises:
    - ProbeError if offline, if parsing fails, or if the network call fails.
    - HostNotAllowed if the host is not configured and allow_unknown is False.
    - ProviderUnknown if the host is configured but has no known provider.
    """
    if offline:
        raise ProbeError("offline mode: no network calls permitted")

    parsed = parse_remote_url(remote_url)
    if parsed is None:
        raise ProbeError(f"cannot parse remote URL: {remote_url!r}")
    host, owner, name = parsed

    if not auth.is_allowed(host):
        raise HostNotAllowed(f"host not configured: {host}")

    provider = auth.provider_for(host)
    if provider is None:
        raise ProviderUnknown(f"no provider registered for host: {host}")

    probe = _PROBES.get(provider)
    if probe is None:
        raise ProviderUnknown(f"unknown provider: {provider}")

    token = auth.resolve_token(host)
    result = probe.fetch(host, owner, name, token)
    result["fetched_at"] = datetime.datetime.now(
        datetime.timezone.utc
    ).isoformat(timespec="seconds")
    return result
