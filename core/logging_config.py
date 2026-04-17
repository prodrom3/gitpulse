import datetime
import glob
import logging
import os
import stat
import sys

from .config import DEFAULT_MAX_LOG_FILES
from .paths import data_dir, ensure_data_dir


def _get_logs_directory() -> str:
    """Return the logs directory path under the XDG data dir.

    Logs live alongside the metadata index so a pipx install doesn't
    bury them inside the venv: the operator always finds them at a
    predictable, cross-OS location.

    Linux:   $XDG_DATA_HOME/nostos/logs          (default ~/.local/share/nostos/logs)
    macOS:   $XDG_DATA_HOME/nostos/logs          (same XDG conventions)
    Windows: $LOCALAPPDATA/nostos/logs           (paths.data_dir falls back here)
    """
    return os.path.join(data_dir(), "logs")


def rotate_logs(logs_directory: str, max_files: int = DEFAULT_MAX_LOG_FILES) -> None:
    """Remove oldest log files if count exceeds max_files."""
    log_files = sorted(
        glob.glob(os.path.join(logs_directory, "*.log")),
        key=os.path.getmtime,
    )
    while len(log_files) > max_files:
        oldest = log_files.pop(0)
        try:
            os.remove(oldest)
        except OSError:
            pass


def setup_logging(max_log_files: int = DEFAULT_MAX_LOG_FILES) -> None:
    logs_directory = _get_logs_directory()
    resolved = os.path.realpath(logs_directory)
    if os.path.exists(logs_directory) and resolved != os.path.abspath(logs_directory):
        raise SystemExit(
            f"Refusing to write logs: '{logs_directory}' is a symlink to '{resolved}'"
        )
    # Ensure the parent (data dir) exists with 0700 perms, then the logs
    # subdir itself. Re-creating the data dir is cheap and idempotent.
    ensure_data_dir()
    if not os.path.exists(logs_directory):
        os.makedirs(logs_directory)
        if sys.platform != "win32":
            try:
                os.chmod(logs_directory, 0o700)
            except OSError:
                pass

    rotate_logs(logs_directory, max_log_files)

    log_file_name = (
        datetime.datetime.now(datetime.timezone.utc)
        .astimezone()
        .strftime("%Y-%m-%d_%H-%M-%S")
        + ".log"
    )
    log_file_path = os.path.join(logs_directory, log_file_name)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s]: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_file_path, mode="w"),
        ],
    )

    try:
        os.chmod(log_file_path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
