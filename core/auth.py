"""Auth config for gitpulse upstream probes.

Reads $XDG_CONFIG_HOME/gitpulse/auth.toml and exposes a per-host view:

    [hosts."github.com"]
    token_env = "GITHUB_TOKEN"       # preferred
    # token   = "ghp_..."            # inline (discouraged; use env var)
    # provider = "github"            # optional override; default derived from host

    [hosts."gitlab.internal.corp"]
    provider  = "gitlab"             # required for non-standard hosts
    token_env = "CORP_GITLAB_TOKEN"

    [defaults]
    allow_unknown = false            # fail-closed for hosts not listed above

Security
- The file must be owned by the current user and not world-readable
  on Unix. Failure of either check causes the loader to refuse to
  read it and return an empty / fail-closed config with a warning.
- A missing file is NOT an error; upstream probes will simply fail
  closed for every host.
- Inline tokens are supported but discouraged; token_env is always
  preferred and is the only form that is redacted from audit output.
"""

from __future__ import annotations

import logging
import os
import stat
import sys
from typing import Any

from .paths import auth_config_path

try:
    import tomllib as _toml  # type: ignore[import-not-found,unused-ignore]
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    import tomli as _toml  # type: ignore[import-not-found, no-redef]


_DEFAULT_PROVIDERS: dict[str, str] = {
    "github.com": "github",
    "gitlab.com": "gitlab",
}


class AuthConfig:
    """In-memory view of the auth.toml file.

    Hosts not present in the config produce (None, False) from
    resolve_host_token() unless defaults.allow_unknown is True.
    """

    def __init__(
        self,
        hosts: dict[str, dict[str, Any]] | None = None,
        allow_unknown: bool = False,
    ) -> None:
        self.hosts = hosts or {}
        self.allow_unknown = allow_unknown

    def provider_for(self, host: str) -> str | None:
        """Return the provider name for a host, or None if unknown."""
        cfg = self.hosts.get(host)
        if cfg and cfg.get("provider"):
            return str(cfg["provider"]).lower()
        return _DEFAULT_PROVIDERS.get(host)

    def resolve_token(self, host: str) -> str | None:
        """Return the token for a host, or None.

        token_env takes precedence over inline token. Unknown hosts
        always return None.
        """
        cfg = self.hosts.get(host)
        if not cfg:
            return None
        env_name = cfg.get("token_env")
        if env_name:
            return os.environ.get(str(env_name)) or None
        inline = cfg.get("token")
        return str(inline) if inline else None

    def is_allowed(self, host: str) -> bool:
        """Should a probe against this host be permitted?

        True when the host is explicitly configured OR when
        defaults.allow_unknown is True.
        """
        if host in self.hosts:
            return True
        return self.allow_unknown


def _is_auth_file_safe(path: str) -> bool:
    """Reject if not owned by current user or world-readable/writable (Unix)."""
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
    if st.st_mode & (stat.S_IWOTH | stat.S_IROTH | stat.S_IWGRP | stat.S_IRGRP):
        logging.warning(
            f"Ignoring {path}: permissions too loose "
            f"(fix with: chmod 600 {path})"
        )
        return False
    return True


def load_auth(path: str | None = None) -> AuthConfig:
    """Load the auth config. Returns an empty fail-closed config if
    the file is missing, unsafe, or malformed."""
    cfg_path = path or auth_config_path()
    if not os.path.isfile(cfg_path):
        return AuthConfig()
    if not _is_auth_file_safe(cfg_path):
        return AuthConfig()

    try:
        with open(cfg_path, "rb") as f:
            data = _toml.load(f)
    except (OSError, _toml.TOMLDecodeError) as e:
        logging.warning(f"Ignoring {cfg_path}: parse error ({e})")
        return AuthConfig()

    hosts_raw = data.get("hosts", {})
    hosts: dict[str, dict[str, Any]] = {}
    if isinstance(hosts_raw, dict):
        for name, cfg in hosts_raw.items():
            if isinstance(cfg, dict):
                hosts[str(name)] = {k: v for k, v in cfg.items()}

    defaults = data.get("defaults", {})
    allow_unknown = False
    if isinstance(defaults, dict):
        allow_unknown = bool(defaults.get("allow_unknown", False))

    return AuthConfig(hosts=hosts, allow_unknown=allow_unknown)
