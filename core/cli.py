"""Argparse / subcommand dispatch for gitpulse.

The top-level command is a verb-first subparser tree: `gitpulse pull`,
`gitpulse add`, `gitpulse list`, etc. Invocations without a verb are
treated as an implicit `pull` for backward compatibility. The legacy
top-level flags (--add, --remove, --list) are rewritten to their
subcommand equivalents and emit a deprecation notice.
"""

# PYTHON_ARGCOMPLETE_OK

from __future__ import annotations

import argparse
import os
import sys
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

from .commands import add as _cmd_add
from .commands import attack as _cmd_attack
from .commands import dashboard as _cmd_dashboard
from .commands import digest as _cmd_digest
from .commands import doctor as _cmd_doctor
from .commands import export_cmd as _cmd_export
from .commands import import_cmd as _cmd_import
from .commands import list_cmd as _cmd_list
from .commands import note as _cmd_note
from .commands import pull as _cmd_pull
from .commands import refresh as _cmd_refresh
from .commands import rm as _cmd_rm
from .commands import show as _cmd_show
from .commands import tag as _cmd_tag
from .commands import triage as _cmd_triage
from .commands import update as _cmd_update
from .commands import vault as _cmd_vault

_KNOWN_VERBS: frozenset[str] = frozenset(
    {
        "pull", "add", "list", "show", "tag", "note", "triage",
        "rm", "refresh", "digest", "vault", "export", "import",
        "update", "doctor", "attack", "dashboard",
    }
)


def get_version() -> str:
    """Return the gitpulse version.

    Reads the VERSION file at the repo root first so source-tree edits
    are reflected immediately. Falls back to installed package metadata
    for pip-installed runs.
    """
    version_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "VERSION")
    try:
        with open(version_file) as f:
            value = f.read().strip()
            if value:
                return value
    except OSError:
        pass
    try:
        return _pkg_version("gitpulse")
    except PackageNotFoundError:
        return "unknown"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gitpulse",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "gitpulse - manage a fleet of git repositories.\n"
            "\n"
            "Pull updates in parallel, maintain a curated index with tags, "
            "status, and notes, probe upstream metadata (stars, archived, "
            "last push), generate weekly digests and HTML dashboards, "
            "bridge to an Obsidian vault, and export portable bundles "
            "that move cleanly between machines."
        ),
        epilog=(
            "Examples:\n"
            "  gitpulse pull ~/code               Pull every repo under ~/code\n"
            "  gitpulse pull --from-index --tags  Pull indexed repos + all their git tags\n"
            "  gitpulse add URL --tag python      Clone a remote repo and register it\n"
            "  gitpulse list --tag security       Show indexed repos carrying a tag\n"
            "  gitpulse refresh                   Fetch upstream metadata for the index\n"
            "  gitpulse export --out fleet.json   Export the full index for portability\n"
            "\n"
            "Run `gitpulse <command> --help` for flags on a specific command.\n"
            "Docs: https://github.com/prodrom3/gitpulse"
        ),
    )
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"%(prog)s {get_version()}",
    )
    subparsers = parser.add_subparsers(
        title="commands",
        dest="command",
        metavar="COMMAND",
    )
    # Group the verbs in a logical order so `--help` reads top to bottom.
    # Core pull / index intake:
    _cmd_pull.add_parser(subparsers)
    _cmd_add.add_parser(subparsers)
    # Index inspection & editing:
    _cmd_list.add_parser(subparsers)
    _cmd_show.add_parser(subparsers)
    _cmd_tag.add_parser(subparsers)
    _cmd_note.add_parser(subparsers)
    _cmd_triage.add_parser(subparsers)
    _cmd_rm.add_parser(subparsers)
    # Upstream intelligence & reporting:
    _cmd_refresh.add_parser(subparsers)
    _cmd_digest.add_parser(subparsers)
    _cmd_dashboard.add_parser(subparsers)
    _cmd_attack.add_parser(subparsers)
    # External bridges & portability:
    _cmd_vault.add_parser(subparsers)
    _cmd_export.add_parser(subparsers)
    _cmd_import.add_parser(subparsers)
    # Operational / housekeeping:
    _cmd_update.add_parser(subparsers)
    _cmd_doctor.add_parser(subparsers)
    return parser


def _rewrite_legacy_argv(argv: list[str]) -> list[str]:
    """Translate legacy top-level flags to subcommand form.

    Keeps `gitpulse --add X`, `gitpulse --remove X`, `gitpulse --list`,
    and `gitpulse --watchlist` working for one release. Users get a
    one-line deprecation notice to stderr when a legacy flag fires.
    """
    if not argv:
        return argv

    # --list with no other verb -> `list`
    if argv and argv[0] == "--list":
        _deprecate("--list", "list")
        return ["list"] + argv[1:]

    # --add PATH ... -> `add PATH ...`
    if "--add" in argv:
        idx = argv.index("--add")
        if idx + 1 < len(argv):
            target = argv[idx + 1]
            _deprecate("--add", "add")
            rest = argv[:idx] + argv[idx + 2 :]
            return ["add", target] + rest

    # --remove PATH ... -> `rm PATH ...`
    if "--remove" in argv:
        idx = argv.index("--remove")
        if idx + 1 < len(argv):
            target = argv[idx + 1]
            _deprecate("--remove", "rm")
            rest = argv[:idx] + argv[idx + 2 :]
            return ["rm", target] + rest

    return argv


def _deprecate(old: str, new_verb: str) -> None:
    print(
        f"gitpulse: warning: {old} is deprecated; use `gitpulse {new_verb}` instead",
        file=sys.stderr,
        flush=True,
    )


def _inject_default_verb(argv: list[str]) -> list[str]:
    """If the first positional arg is not a known verb, prepend `pull`."""
    for a in argv:
        if a in {"-h", "--help", "-v", "--version"}:
            return argv
        if not a.startswith("-"):
            if a in _KNOWN_VERBS:
                return argv
            return ["pull"] + argv
    # All flags, no positional -> implicit pull
    return ["pull"] + argv


def run(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    argv = _rewrite_legacy_argv(list(argv))
    argv = _inject_default_verb(argv)

    parser = build_parser()

    # Optional shell tab-completion. Only active if argcomplete is installed
    # and the shell invoked us in completion mode. Silently no-ops otherwise,
    # so we don't make argcomplete a hard dependency.
    try:
        import argcomplete  # type: ignore[import-not-found]

        argcomplete.autocomplete(parser)
    except ImportError:
        pass

    args = parser.parse_args(argv)

    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 2
    return int(func(args))


# Back-compat: keep the old parse_args() symbol for anyone importing it.
def parse_args() -> argparse.Namespace:
    """Legacy entry used by older tests. Returns a Namespace for the
    rewritten argv, without executing the command."""
    argv = _rewrite_legacy_argv(list(sys.argv[1:]))
    argv = _inject_default_verb(argv)
    return build_parser().parse_args(argv)


def main_entry() -> None:
    """Entry point for the pip-installed `gitpulse` console script."""
    sys.exit(run(sys.argv[1:]))
