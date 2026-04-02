import configparser
import logging
import os
import stat
import sys
from typing import Any

DEFAULT_DEPTH: int = 5
DEFAULT_TIMEOUT: int = 120
DEFAULT_WORKERS: int = 8
DEFAULT_MAX_LOG_FILES: int = 20
CONFIG_FILENAME: str = ".gitpulserc"


def get_config_path() -> str:
    return os.path.join(os.path.expanduser("~"), CONFIG_FILENAME)


def _is_config_safe(config_path: str) -> bool:
    """Verify the config file is owned by the current user and not world-writable."""
    if sys.platform == "win32":
        return True
    try:
        st = os.stat(config_path)
        if st.st_uid != os.getuid():
            logging.warning(
                f"Ignoring {config_path}: owned by uid {st.st_uid}, not current user"
            )
            return False
        if st.st_mode & stat.S_IWOTH:
            logging.warning(
                f"Ignoring {config_path}: world-writable (fix with: chmod o-w {config_path})"
            )
            return False
        return True
    except OSError:
        return False


def load_config() -> dict[str, Any]:
    """Load config from ~/.gitpulserc if it exists.

    Expected format (INI):
        [defaults]
        depth = 5
        workers = 8
        timeout = 120
        max_log_files = 20
        rebase = false

        [exclude]
        patterns = archived-*, .backup-*
    """
    config_path = get_config_path()
    result: dict[str, Any] = {
        "depth": DEFAULT_DEPTH,
        "workers": DEFAULT_WORKERS,
        "timeout": DEFAULT_TIMEOUT,
        "max_log_files": DEFAULT_MAX_LOG_FILES,
        "rebase": False,
        "exclude_patterns": [],
        "clone_dir": None,
    }

    if not os.path.isfile(config_path):
        return result

    if not _is_config_safe(config_path):
        return result

    parser = configparser.ConfigParser()
    parser.read(config_path, encoding="utf-8")

    if parser.has_section("defaults"):
        defaults = parser["defaults"]
        result["depth"] = defaults.getint("depth", DEFAULT_DEPTH)
        result["workers"] = defaults.getint("workers", DEFAULT_WORKERS)
        result["timeout"] = defaults.getint("timeout", DEFAULT_TIMEOUT)
        result["max_log_files"] = defaults.getint("max_log_files", DEFAULT_MAX_LOG_FILES)
        result["rebase"] = defaults.getboolean("rebase", False)
        clone_dir = defaults.get("clone_dir", "").strip()
        if clone_dir:
            result["clone_dir"] = clone_dir

    if parser.has_section("exclude"):
        raw = parser.get("exclude", "patterns", fallback="")
        patterns = [p.strip() for p in raw.split(",") if p.strip()]
        result["exclude_patterns"] = patterns

    return result
