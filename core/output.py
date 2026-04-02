import json
import os
import sys

from .models import RepoResult, RepoStatus


def _supports_color() -> bool:
    """Check if the terminal supports color output."""
    if os.environ.get("NO_COLOR"):
        return False
    if not hasattr(sys.stdout, "isatty") or not sys.stdout.isatty():
        return False
    if sys.platform == "win32":
        return bool(os.environ.get("ANSICON") or "WT_SESSION" in os.environ)
    return True


class Color:
    """ANSI color codes, disabled when output is not a terminal."""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled

    def _wrap(self, code: str, text: str) -> str:
        if self.enabled:
            return f"\033[{code}m{text}\033[0m"
        return text

    def green(self, text: str) -> str:
        return self._wrap("32", text)

    def yellow(self, text: str) -> str:
        return self._wrap("33", text)

    def red(self, text: str) -> str:
        return self._wrap("31", text)

    def cyan(self, text: str) -> str:
        return self._wrap("36", text)

    def bold(self, text: str) -> str:
        return self._wrap("1", text)

    def dim(self, text: str) -> str:
        return self._wrap("2", text)


def _make_color(json_mode: bool = False) -> Color:
    return Color(enabled=not json_mode and _supports_color())


def print_progress(
    completed: int,
    total: int | None,
    result: RepoResult,
    json_mode: bool = False,
    quiet: bool = False,
) -> None:
    """Print a progress line to stderr."""
    if json_mode or quiet:
        return

    c = _make_color()
    status_text = result.status.value
    if result.status == RepoStatus.UPDATED:
        status_text = c.green(status_text)
    elif result.status == RepoStatus.FETCHED:
        status_text = c.cyan(status_text)
    elif result.status == RepoStatus.UP_TO_DATE:
        status_text = c.dim(status_text)
    elif result.status == RepoStatus.SKIPPED:
        status_text = c.yellow(status_text)
    elif result.status == RepoStatus.FAILED:
        status_text = c.red(status_text)

    counter = f"[{completed}/{total}]" if total is not None else f"[{completed}/?]"
    print(f"  {counter} {status_text}: {result.path}", file=sys.stderr, flush=True)


def print_human_summary(
    results: list[RepoResult],
    total: int,
    json_mode: bool = False,
) -> None:
    """Print a categorized human-readable summary with color."""
    c = _make_color(json_mode)

    updated = [r for r in results if r.status == RepoStatus.UPDATED]
    fetched = [r for r in results if r.status == RepoStatus.FETCHED]
    up_to_date = [r for r in results if r.status == RepoStatus.UP_TO_DATE]
    skipped = [r for r in results if r.status == RepoStatus.SKIPPED]
    failed = [r for r in results if r.status == RepoStatus.FAILED]

    print(f"\n{c.bold('--- Summary ---')}")

    if updated:
        print(f"\n{c.green(f'Updated ({len(updated)})')}:")
        for r in updated:
            print(f"  {r.path}")

    if fetched:
        print(f"\n{c.cyan(f'Fetched ({len(fetched)})')}:")
        for r in fetched:
            print(f"  {r.path}")

    if up_to_date:
        print(f"\n{c.dim(f'Already up-to-date ({len(up_to_date)})')}:")
        for r in up_to_date:
            print(f"  {r.path}")

    if skipped:
        print(f"\n{c.yellow(f'Skipped ({len(skipped)})')}:")
        for r in skipped:
            print(f"  {r.path} - {r.reason}")

    if failed:
        print(f"\n{c.red(f'Failed ({len(failed)})')}:")
        for r in failed:
            print(f"  {r.path} - {r.reason}")

    parts = [
        f"Total: {total}",
        c.green(f"Updated: {len(updated)}"),
    ]
    if fetched:
        parts.append(c.cyan(f"Fetched: {len(fetched)}"))
    parts.extend([
        f"Up-to-date: {len(up_to_date)}",
        c.yellow(f"Skipped: {len(skipped)}"),
        c.red(f"Failed: {len(failed)}"),
    ])
    print(f"\n{' | '.join(parts)}")


def print_json_summary(results: list[RepoResult], total: int) -> None:
    """Print results as structured JSON to stdout."""
    updated = [r for r in results if r.status == RepoStatus.UPDATED]
    fetched = [r for r in results if r.status == RepoStatus.FETCHED]
    up_to_date = [r for r in results if r.status == RepoStatus.UP_TO_DATE]
    skipped = [r for r in results if r.status == RepoStatus.SKIPPED]
    failed = [r for r in results if r.status == RepoStatus.FAILED]

    output = {
        "total": total,
        "counts": {
            "updated": len(updated),
            "fetched": len(fetched),
            "up_to_date": len(up_to_date),
            "skipped": len(skipped),
            "failed": len(failed),
        },
        "repositories": [r.to_dict() for r in results],
    }
    print(json.dumps(output, indent=2))
