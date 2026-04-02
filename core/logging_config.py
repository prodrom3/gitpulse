import datetime
import glob
import logging
import os
import stat

from .config import DEFAULT_MAX_LOG_FILES

_SCRIPT_DIR: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _get_logs_directory() -> str:
    """Return the logs directory path, anchored to the script's location."""
    return os.path.join(_SCRIPT_DIR, "logs")


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
    if not os.path.exists(logs_directory):
        os.makedirs(logs_directory)

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
