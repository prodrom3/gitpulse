"""XDG Base Directory resolution for nostos.

The metadata index and auth/config files live outside the repo tree so an
accidental `git add .` cannot pick them up. Paths follow the XDG Base
Directory Specification: config in $XDG_CONFIG_HOME/nostos, data in
$XDG_DATA_HOME/nostos. Windows has no XDG convention, so we fall back
to the user profile directory.
"""

import os
import sys

APP_NAME: str = "nostos"


def _home() -> str:
    return os.path.expanduser("~")


def xdg_config_home() -> str:
    """Return $XDG_CONFIG_HOME or the platform-appropriate default."""
    env = os.environ.get("XDG_CONFIG_HOME")
    if env:
        return env
    if sys.platform == "win32":
        return os.environ.get("APPDATA") or os.path.join(_home(), "AppData", "Roaming")
    return os.path.join(_home(), ".config")


def xdg_data_home() -> str:
    """Return $XDG_DATA_HOME or the platform-appropriate default."""
    env = os.environ.get("XDG_DATA_HOME")
    if env:
        return env
    if sys.platform == "win32":
        return os.environ.get("LOCALAPPDATA") or os.path.join(_home(), "AppData", "Local")
    return os.path.join(_home(), ".local", "share")


def config_dir() -> str:
    return os.path.join(xdg_config_home(), APP_NAME)


def data_dir() -> str:
    return os.path.join(xdg_data_home(), APP_NAME)


def index_db_path() -> str:
    """Path to the SQLite metadata index."""
    return os.path.join(data_dir(), "index.db")


def auth_config_path() -> str:
    """Path to the optional per-host auth config (TOML)."""
    return os.path.join(config_dir(), "auth.toml")


def topic_rules_path() -> str:
    """Path to the optional topic curation file (TOML).

    Drives the deny / alias rules applied when --auto-tags imports
    upstream repo topics into the local tag list.
    """
    return os.path.join(config_dir(), "topic_rules.toml")


def _ensure_dir(path: str, mode: int = 0o700) -> str:
    """Create a directory with restrictive perms if missing.

    Also tightens perms to the requested mode on Unix even if the directory
    already existed with looser bits. Windows silently no-ops the chmod.
    """
    os.makedirs(path, exist_ok=True)
    if sys.platform != "win32":
        try:
            os.chmod(path, mode)
        except OSError:
            pass
    return path


def ensure_config_dir() -> str:
    return _ensure_dir(config_dir(), 0o700)


def ensure_data_dir() -> str:
    return _ensure_dir(data_dir(), 0o700)
