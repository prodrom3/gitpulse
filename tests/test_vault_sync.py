"""Tests for the frontmatter parser and the vault-sync reconciliation."""

import argparse
import io
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from core import index, vault
from core.commands import vault as cmd_vault


def _R(path: str) -> str:
    return os.path.realpath(os.path.expanduser(path))


# ---------- frontmatter parser ----------


class TestParseFrontmatter(unittest.TestCase):
    def test_rejects_no_frontmatter(self):
        with self.assertRaises(vault.FrontmatterError):
            vault.parse_frontmatter("no frontmatter here\n")

    def test_parses_scalars(self):
        text = '---\ngitpulse_id: 7\nstatus: "in-use"\nquiet: false\n---\nbody\n'
        front, body = vault.parse_frontmatter(text)
        self.assertEqual(front["gitpulse_id"], 7)
        self.assertEqual(front["status"], "in-use")
        self.assertEqual(front["quiet"], False)
        self.assertEqual(body, "body\n")

    def test_parses_flow_tag_list(self):
        text = '---\ntags: ["c2", "post-ex", "priority/high"]\n---\n'
        front, _ = vault.parse_frontmatter(text)
        self.assertEqual(front["tags"], ["c2", "post-ex", "priority/high"])

    def test_parses_empty_flow_list(self):
        text = '---\ntags: []\n---\n'
        front, _ = vault.parse_frontmatter(text)
        self.assertEqual(front["tags"], [])

    def test_parses_block_tag_list(self):
        text = (
            "---\n"
            "gitpulse_id: 1\n"
            "tags:\n"
            "  - c2\n"
            "  - recon\n"
            "status: \"new\"\n"
            "---\nbody\n"
        )
        front, _ = vault.parse_frontmatter(text)
        self.assertEqual(front["tags"], ["c2", "recon"])
        self.assertEqual(front["status"], "new")

    def test_skips_nested_upstream_block(self):
        text = (
            "---\n"
            "gitpulse_id: 42\n"
            "status: \"in-use\"\n"
            "upstream:\n"
            '  provider: "github"\n'
            "  stars: 123\n"
            'tags: ["x"]\n'
            "---\n"
        )
        front, _ = vault.parse_frontmatter(text)
        self.assertEqual(front["gitpulse_id"], 42)
        self.assertEqual(front["tags"], ["x"])
        # upstream sub-keys are deliberately NOT surfaced; DB wins there.
        self.assertNotIn("upstream", front)

    def test_null_and_booleans(self):
        text = '---\na: null\nb: true\nc: false\nd: ~\n---\n'
        front, _ = vault.parse_frontmatter(text)
        self.assertIsNone(front["a"])
        self.assertTrue(front["b"])
        self.assertFalse(front["c"])
        self.assertIsNone(front["d"])

    def test_escaped_quotes_in_string(self):
        text = '---\nnote: "a \\"quoted\\" word"\n---\n'
        front, _ = vault.parse_frontmatter(text)
        self.assertEqual(front["note"], 'a "quoted" word')

    def test_parse_notes_from_body(self):
        body = (
            "\n# org/repo\n\n"
            "## Description\n\nA tool\n\n"
            "## Notes\n\n"
            "- **2026-04-14T10:00:00+00:00** - first note\n"
            "- **2026-04-15T09:00:00+00:00** - second note\n"
            "\n"
        )
        notes = vault.parse_notes_from_body(body)
        self.assertEqual(len(notes), 2)
        self.assertEqual(notes[0]["body"], "first note")
        self.assertEqual(notes[0]["created_at"], "2026-04-14T10:00:00+00:00")
        self.assertEqual(notes[1]["body"], "second note")

    def test_parse_notes_empty_section(self):
        body = "\n## Notes\n\n_No notes yet._\n"
        notes = vault.parse_notes_from_body(body)
        self.assertEqual(notes, [])

    def test_parse_notes_no_section(self):
        body = "\n# Just a title\n\nSome text.\n"
        notes = vault.parse_notes_from_body(body)
        self.assertEqual(notes, [])

    def test_parse_notes_stops_at_next_section(self):
        body = (
            "\n## Notes\n\n"
            "- **2026-04-14T10:00:00+00:00** - a note\n"
            "\n## Other\n\nNot a note bullet.\n"
        )
        notes = vault.parse_notes_from_body(body)
        self.assertEqual(len(notes), 1)

    def test_round_trip_with_writer(self):
        """Anything our writer emits must parse back to equivalent data."""
        written = vault._render_frontmatter(
            {
                "gitpulse_id": 9,
                "path": "/tmp/foo",
                "status": "in-use",
                "quiet": False,
                "tags": ["c2", "post-ex"],
                "upstream": {"provider": "github", "stars": 100},
            }
        )
        front, body = vault.parse_frontmatter(written + "\nbody\n")
        self.assertEqual(front["gitpulse_id"], 9)
        self.assertEqual(front["status"], "in-use")
        self.assertEqual(front["quiet"], False)
        self.assertEqual(front["tags"], ["c2", "post-ex"])
        self.assertEqual(body, "body\n")


# ---------- sync_vault() ----------


class _FakeReader:
    def __init__(self, repos):
        self.repos = repos

    def iter_repos(self):
        return [dict(r) for r in self.repos]


class _FakeWriter:
    def __init__(self, known_ids):
        self.known_ids = set(known_ids)
        self.calls: list[dict] = []

    def apply_edits(self, *, repo_id, status, tags, new_notes=None):
        self.calls.append({
            "repo_id": repo_id, "status": status, "tags": tags,
            "new_notes": new_notes,
        })
        if repo_id not in self.known_ids:
            return {"repo_missing": True}
        return {
            "repo_missing": False,
            "status_changed": status is not None,
            "tags_changed": tags is not None,
            "notes_added": len(new_notes) if new_notes else 0,
        }


class TestSyncVault(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.target = vault.VaultTarget(self.tmp, subdir="repos")
        self.target.ensure()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_md(self, name: str, front: dict, body: str = "body\n"):
        path = os.path.join(self.target.repos_dir, name + ".md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(vault._render_frontmatter(front) + "\n" + body)
        return path

    def _stub_repo(self, repo_id: int, path: str, **overrides):
        base = {
            "id": repo_id,
            "path": path,
            "remote_url": None,
            "source": None,
            "status": "reviewed",
            "quiet": 0,
            "added_at": "2026-04-15T00:00:00+00:00",
            "last_touched_at": None,
            "tags": [],
            "notes": [],
            "upstream": None,
        }
        base.update(overrides)
        return base

    def test_empty_vault_returns_zero_stats(self):
        stats = vault.sync_vault(
            self.target, _FakeReader([]), _FakeWriter(known_ids=[])
        )
        self.assertEqual(stats["files_scanned"], 0)
        self.assertEqual(stats["edits_applied"], 0)
        self.assertEqual(stats["files_rewritten"], 0)

    def test_applies_tag_edits(self):
        self._write_md(
            "a",
            {
                "gitpulse_id": 1,
                "status": "in-use",
                "tags": ["c2", "post-ex"],
            },
        )
        writer = _FakeWriter(known_ids=[1])
        reader = _FakeReader(
            [self._stub_repo(1, "/tmp/a", tags=["c2", "post-ex"], status="in-use")]
        )
        stats = vault.sync_vault(self.target, reader, writer)
        self.assertEqual(stats["files_scanned"], 1)
        self.assertEqual(stats["edits_applied"], 1)
        self.assertEqual(len(writer.calls), 1)
        self.assertEqual(writer.calls[0]["repo_id"], 1)
        self.assertEqual(writer.calls[0]["status"], "in-use")
        self.assertEqual(writer.calls[0]["tags"], ["c2", "post-ex"])

    def test_invalid_status_reported_as_parse_error(self):
        self._write_md("a", {"gitpulse_id": 1, "status": "not-a-status"})
        writer = _FakeWriter(known_ids=[1])
        reader = _FakeReader([self._stub_repo(1, "/tmp/a")])
        stats = vault.sync_vault(self.target, reader, writer)
        self.assertEqual(len(stats["parse_errors"]), 1)
        self.assertIn("invalid status", stats["parse_errors"][0]["error"])

    def test_orphan_file_collected(self):
        self._write_md("a", {"gitpulse_id": 9999, "status": "in-use"})
        writer = _FakeWriter(known_ids=[])  # id 9999 not in DB
        reader = _FakeReader([])
        stats = vault.sync_vault(self.target, reader, writer)
        self.assertEqual(len(stats["orphans"]), 1)
        self.assertTrue(stats["orphans"][0].endswith("a.md"))

    def test_malformed_frontmatter_collected(self):
        path = os.path.join(self.target.repos_dir, "broken.md")
        with open(path, "w") as f:
            f.write("no frontmatter here at all\n")
        writer = _FakeWriter(known_ids=[])
        reader = _FakeReader([])
        stats = vault.sync_vault(self.target, reader, writer)
        self.assertEqual(len(stats["parse_errors"]), 1)

    def test_rewrites_from_reconciled_reader(self):
        self._write_md("a", {"gitpulse_id": 1, "status": "in-use", "tags": ["c2"]})
        # Reader returns the reconciled state (simulated)
        reader = _FakeReader([
            self._stub_repo(1, "/tmp/a", tags=["c2"], status="in-use"),
            self._stub_repo(2, "/tmp/b", tags=["recon"]),
        ])
        writer = _FakeWriter(known_ids=[1])
        stats = vault.sync_vault(self.target, reader, writer)
        self.assertEqual(stats["files_rewritten"], 2)
        # Both files should exist on disk now.
        files = sorted(os.listdir(self.target.repos_dir))
        self.assertEqual(len(files), 2)


# ---------- end-to-end against a real index ----------


class _IndexBackedTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.vault_dir = os.path.join(self.tmp, "vault")
        self.db = os.path.join(self.tmp, "index.db")
        self._patches = [
            mock.patch("core.index.index_db_path", return_value=self.db),
            mock.patch("core.index.ensure_data_dir", return_value=self.tmp),
            mock.patch("core.commands._common.maybe_migrate_watchlist"),
            mock.patch(
                "core.commands.vault.load_config",
                return_value={
                    "vault_path": self.vault_dir,
                    "vault_subdir": "repos",
                },
            ),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _sync_args(self, **overrides):
        base = {
            "vault_command": "sync",
            "path": None,
            "subdir": None,
            "json": False,
        }
        base.update(overrides)
        return argparse.Namespace(**base)


class TestVaultSyncCommand(_IndexBackedTestCase):
    def test_round_trip_tag_edit_in_obsidian(self):
        # 1. Seed the DB and export the vault once.
        with index.connect(self.db) as conn:
            rid = index.add_repo(conn, "/t/a", tags=["old"], status="new")
        with mock.patch("sys.stdout", new_callable=io.StringIO), mock.patch(
            "sys.stderr", new_callable=io.StringIO
        ):
            cmd_vault.run_export(
                argparse.Namespace(
                    vault_command="export", path=None, subdir=None, quiet=True
                )
            )

        # 2. Simulate the operator editing the vault file: swap tags
        #    and change the status. Replace the frontmatter in place.
        files = sorted(os.listdir(os.path.join(self.vault_dir, "repos")))
        self.assertEqual(len(files), 1)
        md_path = os.path.join(self.vault_dir, "repos", files[0])
        with open(md_path) as f:
            original = f.read()
        # Write back a version with edited status + tags.
        edited_front = {
            "gitpulse_id": rid,
            "path": "/t/a",
            "status": "in-use",
            "tags": ["new-tag", "second"],
        }
        body_start = original.find("\n---", 3)
        body = original[body_start + len("\n---") :]
        with open(md_path, "w") as f:
            f.write(vault._render_frontmatter(edited_front) + body)

        # 3. Run sync. Expect: DB reflects edited status + tags; file
        #    is regenerated.
        with mock.patch("sys.stdout", new_callable=io.StringIO), mock.patch(
            "sys.stderr", new_callable=io.StringIO
        ):
            rc = cmd_vault.run_sync(self._sync_args())
        self.assertEqual(rc, 0)

        with index.connect(self.db) as conn:
            repo = index.get_repo(conn, rid)
        self.assertEqual(repo["status"], "in-use")
        self.assertEqual(sorted(repo["tags"]), ["new-tag", "second"])

    def test_json_summary_emits_stats(self):
        with index.connect(self.db) as conn:
            index.add_repo(conn, "/t/a", tags=["x"])
        # Export, then sync with --json output
        with mock.patch("sys.stdout", new_callable=io.StringIO), mock.patch(
            "sys.stderr", new_callable=io.StringIO
        ):
            cmd_vault.run_export(
                argparse.Namespace(
                    vault_command="export", path=None, subdir=None, quiet=True
                )
            )
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            cmd_vault.run_sync(self._sync_args(json=True))
        data = json.loads(out.getvalue())
        self.assertIn("files_scanned", data)
        self.assertIn("edits_applied", data)
        self.assertIn("orphans", data)

    def test_note_added_in_obsidian_round_trips(self):
        # 1. Seed DB with one repo and one existing note, then export.
        with index.connect(self.db) as conn:
            rid = index.add_repo(conn, "/t/a", status="new")
            index.add_note(conn, rid, "existing note")
        with mock.patch("sys.stdout", new_callable=io.StringIO), mock.patch(
            "sys.stderr", new_callable=io.StringIO
        ):
            cmd_vault.run_export(
                argparse.Namespace(
                    vault_command="export", path=None, subdir=None, quiet=True
                )
            )

        # 2. Simulate the operator adding a note bullet in the vault.
        files = sorted(os.listdir(os.path.join(self.vault_dir, "repos")))
        md_path = os.path.join(self.vault_dir, "repos", files[0])
        with open(md_path) as f:
            original = f.read()
        # Append a new note bullet at the end of the file
        with open(md_path, "w") as f:
            f.write(
                original.rstrip()
                + "\n- **2026-04-16T08:00:00+00:00** - added in Obsidian\n"
            )

        # 3. Sync and verify the new note appears in the DB.
        with mock.patch("sys.stdout", new_callable=io.StringIO), mock.patch(
            "sys.stderr", new_callable=io.StringIO
        ):
            rc = cmd_vault.run_sync(self._sync_args())
        self.assertEqual(rc, 0)

        with index.connect(self.db) as conn:
            notes = index.get_notes(conn, rid)
        bodies = [n["body"] for n in notes]
        self.assertIn("existing note", bodies)
        self.assertIn("added in Obsidian", bodies)
        self.assertEqual(len(bodies), 2)

    def test_duplicate_note_not_re_added(self):
        # Syncing twice should not duplicate notes.
        with index.connect(self.db) as conn:
            rid = index.add_repo(conn, "/t/a", status="new")
            index.add_note(conn, rid, "existing")
        with mock.patch("sys.stdout", new_callable=io.StringIO), mock.patch(
            "sys.stderr", new_callable=io.StringIO
        ):
            cmd_vault.run_export(
                argparse.Namespace(
                    vault_command="export", path=None, subdir=None, quiet=True
                )
            )
            cmd_vault.run_sync(self._sync_args())
            cmd_vault.run_sync(self._sync_args())
        with index.connect(self.db) as conn:
            notes = index.get_notes(conn, rid)
        self.assertEqual(len(notes), 1)

    def test_missing_vault_path_errors(self):
        # Override the config patch for this one test
        with mock.patch(
            "core.commands.vault.load_config",
            return_value={"vault_path": None, "vault_subdir": "repos"},
        ), mock.patch("sys.stderr", new_callable=io.StringIO):
            rc = cmd_vault.run_sync(self._sync_args())
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
