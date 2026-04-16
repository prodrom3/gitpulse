"""`nostos completion` - shell tab-completion setup.

Provides three verbs:
- `show`       : print the completion script for the target shell, so the
                 operator can review it, pipe it, or copy it by hand.
- `install`    : append a managed block to the user's shell rc file.
                 Idempotent: re-running replaces the existing block.
                 Detects the shell from $SHELL unless --shell overrides.
- `uninstall`  : remove the managed block if present.

The generated snippet uses argcomplete's native per-shell output
(`register-python-argcomplete --shell {bash,zsh,fish}`) so it does
not rely on the bash-shim bridge that trips up zsh users without a
careful `compinit` / `bashcompinit` setup.

Managed blocks are wrapped in stable BEGIN / END markers so the
install can detect, replace, and uninstall cleanly without parsing
the whole rc file.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from typing import Any

from ._common import fail

# Markers used to find and replace the block we own.
BEGIN_MARKER: str = "# BEGIN nostos completion (managed by `nostos completion install`)"
END_MARKER: str = "# END nostos completion"

SUPPORTED_SHELLS: frozenset[str] = frozenset({"bash", "zsh", "fish"})

# Where each shell sources at startup. For fish we use a conf.d drop-in so
# the user's main config.fish stays untouched.
_RC_FILES: dict[str, str] = {
    "bash": "~/.bashrc",
    "zsh": "~/.zshrc",
    "fish": "~/.config/fish/conf.d/nostos.fish",
}


def add_parser(subparsers: Any) -> None:
    p = subparsers.add_parser(
        "completion",
        help="Set up shell tab-completion",
        description=(
            "Generate or install shell tab-completion for nostos. "
            "Supported shells: bash, zsh, fish. "
            "PowerShell / cmd are not supported upstream by argcomplete; "
            "use Git Bash or WSL on Windows."
        ),
    )
    sub = p.add_subparsers(
        title="actions", dest="completion_command", metavar="ACTION"
    )

    show = sub.add_parser(
        "show", help="Print the completion script for SHELL"
    )
    show.add_argument(
        "--shell",
        choices=sorted(SUPPORTED_SHELLS),
        default=None,
        help="Target shell (default: auto-detect from $SHELL)",
    )
    show.set_defaults(func=_run_show)

    inst = sub.add_parser(
        "install", help="Append the completion block to the user's shell rc"
    )
    inst.add_argument(
        "--shell",
        choices=sorted(SUPPORTED_SHELLS),
        default=None,
        help="Target shell (default: auto-detect from $SHELL)",
    )
    inst.add_argument(
        "--rc-file",
        default=None,
        metavar="PATH",
        help="Override the rc file path (default: shell-appropriate)",
    )
    inst.add_argument(
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt before modifying the rc file",
    )
    inst.set_defaults(func=_run_install)

    uninst = sub.add_parser(
        "uninstall",
        help="Remove the nostos completion block from the user's shell rc",
    )
    uninst.add_argument(
        "--shell",
        choices=sorted(SUPPORTED_SHELLS),
        default=None,
        help="Target shell (default: auto-detect from $SHELL)",
    )
    uninst.add_argument(
        "--rc-file",
        default=None,
        metavar="PATH",
        help="Override the rc file path (default: shell-appropriate)",
    )
    uninst.set_defaults(func=_run_uninstall)

    # If the operator just types `nostos completion`, print help.
    p.set_defaults(func=_run_no_action)


# ---------- shell detection ----------


def detect_shell() -> str | None:
    """Best-effort detection of the operator's shell.

    Order:
      1. $NOSTOS_SHELL override, for tests and explicit opt-in.
      2. $SHELL basename (e.g. '/usr/bin/zsh' -> 'zsh').
      3. None if we can't tell.
    """
    override = os.environ.get("NOSTOS_SHELL")
    if override and override in SUPPORTED_SHELLS:
        return override
    sh = os.environ.get("SHELL", "")
    if not sh:
        return None
    base = os.path.basename(sh).strip().lower()
    # Sometimes $SHELL is like 'zsh-5.9'; strip any suffix.
    for candidate in SUPPORTED_SHELLS:
        if base == candidate or base.startswith(candidate + "-"):
            return candidate
    return None


def resolve_shell(args: argparse.Namespace) -> str | None:
    chosen = getattr(args, "shell", None)
    if chosen:
        return chosen
    return detect_shell()


def resolve_rc_file(shell: str, override: str | None) -> str:
    if override:
        return os.path.expanduser(override)
    return os.path.expanduser(_RC_FILES[shell])


# ---------- snippet generation ----------


def render_snippet(shell: str) -> str:
    """Call argcomplete's `register-python-argcomplete --shell SHELL nostos`
    and wrap the output in our BEGIN/END markers."""
    tool = shutil.which("register-python-argcomplete")
    if tool is None:
        # Fall back to running via the current interpreter, which always
        # works because argcomplete is now a required dependency.
        cmd = [
            sys.executable,
            "-m",
            "argcomplete.scripts.register_python_argcomplete",
            "--shell",
            shell,
            "nostos",
        ]
    else:
        cmd = [tool, "--shell", shell, "nostos"]
    try:
        result = subprocess.run(
            cmd, check=True, capture_output=True, text=True, timeout=15
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"timed out rendering completion: {e}") from None
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"register-python-argcomplete failed: {e.stderr or e.stdout}"
        ) from None
    body = result.stdout.rstrip()
    if not body:
        raise RuntimeError("register-python-argcomplete returned empty output")
    return f"{BEGIN_MARKER}\n{body}\n{END_MARKER}\n"


# ---------- idempotent file patching ----------


def strip_block(content: str) -> str:
    """Remove any existing nostos block (BEGIN...END, inclusive).

    If the markers appear multiple times (shouldn't), strip all. If the
    begin marker is present but end is missing, leave the file alone to
    avoid deleting the rest of the rc.
    """
    out_lines: list[str] = []
    skipping = False
    saw_end = False
    for line in content.splitlines(keepends=True):
        stripped = line.rstrip("\r\n")
        if not skipping and stripped == BEGIN_MARKER:
            skipping = True
            continue
        if skipping and stripped == END_MARKER:
            skipping = False
            saw_end = True
            continue
        if not skipping:
            out_lines.append(line)
    if skipping and not saw_end:
        # Malformed; bail out by not stripping anything.
        return content
    return "".join(out_lines)


def upsert_block(content: str, snippet: str) -> str:
    """Replace any existing block with `snippet`, or append if absent."""
    stripped = strip_block(content)
    if stripped and not stripped.endswith("\n"):
        stripped += "\n"
    if stripped and not stripped.endswith("\n\n"):
        stripped += "\n"
    return stripped + snippet


# ---------- subcommand runners ----------


def _run_no_action(args: argparse.Namespace) -> int:  # noqa: ARG001
    print(
        "nostos completion: specify an action (show, install, uninstall).",
        file=sys.stderr,
    )
    print(
        "Try `nostos completion install` to set up tab-completion for your shell.",
        file=sys.stderr,
    )
    return 2


def _run_show(args: argparse.Namespace) -> int:
    shell = resolve_shell(args)
    if shell is None:
        return fail(
            "could not detect your shell. Pass --shell bash|zsh|fish."
        )
    try:
        snippet = render_snippet(shell)
    except RuntimeError as e:
        return fail(str(e))
    sys.stdout.write(snippet)
    return 0


def _run_install(args: argparse.Namespace) -> int:
    shell = resolve_shell(args)
    if shell is None:
        return fail(
            "could not detect your shell. Pass --shell bash|zsh|fish."
        )
    rc_file = resolve_rc_file(shell, getattr(args, "rc_file", None))

    try:
        snippet = render_snippet(shell)
    except RuntimeError as e:
        return fail(str(e))

    # Read existing content (tolerate missing file / missing parent dir).
    try:
        os.makedirs(os.path.dirname(rc_file) or ".", exist_ok=True)
    except OSError as e:
        return fail(f"could not create parent dir for {rc_file}: {e}")
    try:
        with open(rc_file, encoding="utf-8") as f:
            existing = f.read()
    except FileNotFoundError:
        existing = ""
    except OSError as e:
        return fail(f"could not read {rc_file}: {e}")

    new_content = upsert_block(existing, snippet)
    if new_content == existing:
        print(
            f"nostos completion already up to date in {rc_file}",
            file=sys.stderr,
        )
        return 0

    already_present = BEGIN_MARKER in existing
    action = "Replace" if already_present else "Append"

    if not getattr(args, "yes", False):
        print(f"{action} nostos completion block in {rc_file}?", file=sys.stderr)
        try:
            confirm = input("  [y/N]: ").strip().lower()
        except EOFError:
            confirm = ""
        if confirm not in {"y", "yes"}:
            print("aborted", file=sys.stderr)
            return 1

    try:
        with open(rc_file, "w", encoding="utf-8") as f:
            f.write(new_content)
    except OSError as e:
        return fail(f"could not write {rc_file}: {e}")

    print(
        f"nostos completion installed in {rc_file} (shell={shell}).",
        file=sys.stderr,
    )
    print(
        "Reload your shell (`exec $SHELL`) or open a new terminal to pick it up.",
        file=sys.stderr,
    )
    return 0


def _run_uninstall(args: argparse.Namespace) -> int:
    shell = resolve_shell(args)
    if shell is None:
        return fail(
            "could not detect your shell. Pass --shell bash|zsh|fish."
        )
    rc_file = resolve_rc_file(shell, getattr(args, "rc_file", None))
    try:
        with open(rc_file, encoding="utf-8") as f:
            existing = f.read()
    except FileNotFoundError:
        print(f"nothing to do: {rc_file} does not exist", file=sys.stderr)
        return 0
    except OSError as e:
        return fail(f"could not read {rc_file}: {e}")

    if BEGIN_MARKER not in existing:
        print(
            f"nothing to do: no nostos completion block found in {rc_file}",
            file=sys.stderr,
        )
        return 0

    new_content = strip_block(existing)
    if new_content == existing:
        return fail(
            f"{rc_file} has a malformed nostos block (BEGIN without END). "
            "Not touching the file; fix it manually."
        )
    try:
        with open(rc_file, "w", encoding="utf-8") as f:
            f.write(new_content)
    except OSError as e:
        return fail(f"could not write {rc_file}: {e}")

    print(
        f"nostos completion removed from {rc_file}. Reload your shell to apply.",
        file=sys.stderr,
    )
    return 0
