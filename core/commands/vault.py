"""`gitpulse vault export` - render the index into an Obsidian vault.

The vault is a one-way view today: each `gitpulse vault export` run
rewrites every `<vault>/<subdir>/<slug>.md` from the current DB state.
Any edits to those files in Obsidian are **overwritten** on the next
export. Two-way sync is deliberately deferred to a later release; see
README > Upstream probes and the vault section for details.
"""

from __future__ import annotations

import argparse
from typing import Any

from .. import index as _index
from .. import vault as _vault
from ..config import load_config
from ._common import fail, maybe_migrate_watchlist


def add_parser(subparsers: Any) -> None:
    p = subparsers.add_parser(
        "vault",
        help="Render the metadata index into an Obsidian vault",
        description="Manage a one-way Obsidian-friendly view of the repo fleet.",
    )
    sub = p.add_subparsers(dest="vault_command", metavar="SUBCOMMAND", required=True)

    exp = sub.add_parser(
        "export",
        help="Write / refresh one markdown file per repo into the vault",
        description="Write one markdown file per repo into the configured vault.",
    )
    exp.add_argument(
        "--path",
        default=None,
        metavar="DIR",
        help="Vault path; overrides [vault] path in ~/.gitpulserc",
    )
    exp.add_argument(
        "--subdir",
        default=None,
        metavar="NAME",
        help="Subdirectory inside the vault (default: 'repos' or config value)",
    )
    exp.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress the per-file progress output",
    )
    exp.set_defaults(func=run_export)


class _IndexLoader:
    """Adapter that lets core.vault.export_all iterate the live DB."""

    def __init__(self, conn: Any) -> None:
        self.conn = conn

    def iter_repos(self) -> list[dict[str, Any]]:
        repos = _index.list_repos(self.conn)
        out = []
        for r in repos:
            repo_id = int(r["id"])
            r["upstream"] = _index.get_upstream_meta(self.conn, repo_id)
            r["notes"] = _index.get_notes(self.conn, repo_id)
            out.append(r)
        return out


def run_export(args: argparse.Namespace) -> int:
    maybe_migrate_watchlist()

    cfg = load_config()
    vault_path = args.path or cfg.get("vault_path")
    subdir = args.subdir or cfg.get("vault_subdir") or "repos"

    if not vault_path:
        return fail(
            "vault path not set. Pass --path DIR or add [vault] path to ~/.gitpulserc."
        )

    # Imported lazily to avoid a circular import with core.cli.
    from ..cli import get_version as _get_version

    target = _vault.VaultTarget(vault_path, subdir=subdir)
    try:
        with _index.connect() as conn:
            loader = _IndexLoader(conn)
            written = _vault.export_all(
                target, loader, gitpulse_version=_get_version()
            )
    except OSError as e:
        return fail(str(e))

    if not args.quiet:
        for path in written:
            print(f"wrote: {path}")
    print(
        f"vault export: {len(written)} file(s) written to {target.repos_dir}"
    )
    return 0
