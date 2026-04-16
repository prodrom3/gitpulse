"""`gitpulse vault` - bridge the metadata index with an Obsidian vault.

Two sub-verbs:
- `vault export`  rewrite every markdown file from the DB (one-way).
- `vault sync`    read operator-curated frontmatter edits (status,
                  tags) back into the DB, then re-render every file.

The read-back surface is deliberately narrow and partitioned from
the DB-authoritative fields (upstream.*, last_touched, remote_url,
path, added, gitpulse_id). This avoids having to resolve conflicts:
the two sides never write to the same field. Body content (notes)
remains DB-authoritative; use `gitpulse note` to add notes.
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
        help="Bridge the metadata index with an Obsidian vault",
        description="Manage the Obsidian-friendly view of the repo fleet.",
    )
    sub = p.add_subparsers(dest="vault_command", metavar="SUBCOMMAND", required=True)

    exp = sub.add_parser(
        "export",
        help="Write / refresh one markdown file per repo into the vault",
        description=(
            "Write one markdown file per repo into the configured vault. "
            "Overwrites any vault-side edits; use `vault sync` if you "
            "want operator edits to status / tags applied back to the DB first."
        ),
    )
    exp.add_argument("--path", default=None, metavar="DIR",
                     help="Vault path; overrides [vault] path in ~/.gitpulserc")
    exp.add_argument("--subdir", default=None, metavar="NAME",
                     help="Subdirectory inside the vault (default: 'repos' or config value)")
    exp.add_argument("--quiet", action="store_true",
                     help="Suppress the per-file progress output")
    exp.set_defaults(func=run_export)

    syn = sub.add_parser(
        "sync",
        help="Reconcile operator edits (status, tags) back into the DB",
        description=(
            "Read the vault's markdown frontmatter, apply status and "
            "tags edits to the DB, then rewrite every markdown file "
            "from the reconciled DB state. DB-authoritative fields "
            "(upstream metadata, timestamps, path, remote_url, "
            "gitpulse_id) are ignored on read and regenerated on write; "
            "note body edits are ignored (use `gitpulse note`)."
        ),
    )
    syn.add_argument("--path", default=None, metavar="DIR",
                     help="Vault path; overrides [vault] path in ~/.gitpulserc")
    syn.add_argument("--subdir", default=None, metavar="NAME",
                     help="Subdirectory inside the vault (default: 'repos' or config value)")
    syn.add_argument("--json", action="store_true",
                     help="Emit a JSON summary instead of human output")
    syn.set_defaults(func=run_sync)


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


class _IndexSyncWriter:
    """Adapter that applies vault-side edits to the live index.

    apply_edits() is called once per vault file with (repo_id, status,
    tags, new_notes). Returns a dict describing what changed, or a dict
    with repo_missing=True when the id no longer exists in the DB.
    """

    def __init__(self, conn: Any) -> None:
        self.conn = conn

    def apply_edits(
        self,
        *,
        repo_id: int,
        status: str | None,
        tags: list[str] | None,
        new_notes: list[dict[str, str]] | None = None,
    ) -> dict[str, Any] | None:
        repo = _index.get_repo(self.conn, repo_id)
        if repo is None:
            return {"repo_missing": True}

        result: dict[str, Any] = {
            "repo_missing": False,
            "status_changed": False,
            "tags_changed": False,
            "notes_added": 0,
        }

        if status is not None and status != repo["status"]:
            _index.update_status(self.conn, repo_id, status)
            result["status_changed"] = True

        if tags is not None:
            current = set(repo.get("tags", []) or [])
            desired = set(tags)
            if current != desired:
                to_add = list(desired - current)
                to_remove = list(current - desired)
                if to_add:
                    _index.add_tags(self.conn, repo_id, to_add)
                if to_remove:
                    _index.remove_tags(self.conn, repo_id, to_remove)
                result["tags_changed"] = True

        if new_notes:
            existing_bodies = {
                n["body"] for n in (repo.get("notes") or [])
            }
            for note in new_notes:
                body = note.get("body", "").strip()
                if body and body not in existing_bodies:
                    _index.add_note(self.conn, repo_id, body)
                    existing_bodies.add(body)
                    result["notes_added"] += 1

        return result


def run_sync(args: argparse.Namespace) -> int:
    maybe_migrate_watchlist()

    cfg = load_config()
    vault_path = args.path or cfg.get("vault_path")
    subdir = args.subdir or cfg.get("vault_subdir") or "repos"

    if not vault_path:
        return fail(
            "vault path not set. Pass --path DIR or add [vault] path to ~/.gitpulserc."
        )

    from ..cli import get_version as _get_version

    target = _vault.VaultTarget(vault_path, subdir=subdir)
    try:
        with _index.connect() as conn:
            writer = _IndexSyncWriter(conn)
            reader = _IndexLoader(conn)
            stats = _vault.sync_vault(
                target, reader, writer, gitpulse_version=_get_version()
            )
    except OSError as e:
        return fail(str(e))

    if args.json:
        import json as _json

        print(_json.dumps(stats, indent=2, default=str))
    else:
        print(
            f"vault sync: {stats['files_scanned']} file(s) scanned, "
            f"{stats['edits_applied']} edit(s) applied "
            f"({stats['status_changed']} status, {stats['tags_changed']} tags, "
            f"{stats['notes_added']} notes), "
            f"{stats['files_rewritten']} file(s) rewritten"
        )
        if stats["orphans"]:
            print(f"  orphans (no matching repo in index): {len(stats['orphans'])}")
            for p in stats["orphans"][:10]:
                print(f"    {p}")
            if len(stats["orphans"]) > 10:
                print(f"    ... and {len(stats['orphans']) - 10} more")
        if stats["parse_errors"]:
            print(f"  parse errors: {len(stats['parse_errors'])}")
            for err in stats["parse_errors"][:10]:
                print(f"    {err['path']}: {err['error']}")
    return 0
