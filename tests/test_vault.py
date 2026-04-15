"""Tests for core.vault (markdown rendering + one-way export)."""

import argparse
import io
import os
import shutil
import stat
import sys
import tempfile
import unittest
from unittest import mock

from core import index, vault
from core.commands import vault as cmd_vault


class TestSlug(unittest.TestCase):
    def test_slug_from_upstream(self):
        slug = vault.repo_slug(
            {"path": "/tmp/x"},
            {"owner": "Prodrom3", "name": "GitPulse"},
        )
        self.assertEqual(slug, "prodrom3-gitpulse")

    def test_slug_without_upstream_uses_basename(self):
        slug = vault.repo_slug({"path": "/home/user/tools/My-Repo"}, None)
        self.assertEqual(slug, "my-repo")

    def test_slug_strips_punctuation(self):
        slug = vault.repo_slug(
            {"path": "/tmp/weird~name!"},
            None,
        )
        # Non-portable chars collapse to '-', trailing '-' stripped.
        self.assertTrue(slug.startswith("weird"))
        self.assertNotIn("~", slug)
        self.assertNotIn("!", slug)


class TestRenderMarkdown(unittest.TestCase):
    def _repo(self, **overrides):
        base = {
            "id": 42,
            "path": "/home/user/tools/repo",
            "remote_url": "git@github.com:o/r.git",
            "source": "blog:orange.tw",
            "status": "in-use",
            "quiet": 0,
            "added_at": "2026-04-15T10:00:00+00:00",
            "last_touched_at": "2026-04-15T11:00:00+00:00",
            "tags": ["recon", "passive"],
        }
        base.update(overrides)
        return base

    def _upstream(self, **overrides):
        base = {
            "provider": "github",
            "host": "github.com",
            "owner": "o",
            "name": "r",
            "stars": 100,
            "forks": 10,
            "open_issues": 2,
            "archived": False,
            "default_branch": "main",
            "license": "MIT",
            "last_push": "2026-04-10T00:00:00Z",
            "latest_release": "v1.0",
            "description": "A useful tool",
            "fetched_at": "2026-04-15T12:00:00+00:00",
        }
        base.update(overrides)
        return base

    def test_frontmatter_has_required_keys(self):
        md = vault.render_markdown(
            self._repo(),
            self._upstream(),
            [],
            gitpulse_version="2.3.0",
        )
        self.assertTrue(md.startswith("---\n"))
        # Closing --- on its own line followed by body
        self.assertIn("\n---\n", md[4:])
        self.assertIn('gitpulse_id: 42', md)
        self.assertIn('status: "in-use"', md)
        self.assertIn("tags: [", md)
        self.assertIn("upstream:", md)
        self.assertIn('provider: "github"', md)
        self.assertIn("stars: 100", md)
        self.assertIn("archived: false", md)

    def test_tags_flow_list_format(self):
        md = vault.render_markdown(
            self._repo(tags=["c2", "post-ex", "priority/high"]),
            None,
            [],
        )
        self.assertIn(
            'tags: ["c2", "post-ex", "priority/high"]',
            md,
        )

    def test_empty_tags_renders_empty_list(self):
        md = vault.render_markdown(self._repo(tags=[]), None, [])
        self.assertIn("tags: []", md)

    def test_notes_rendered_chronologically(self):
        notes = [
            {"created_at": "2026-04-14T10:00:00+00:00", "body": "first"},
            {"created_at": "2026-04-15T09:00:00+00:00", "body": "second"},
        ]
        md = vault.render_markdown(self._repo(), None, notes)
        self.assertIn("- **2026-04-14T10:00:00+00:00** - first", md)
        self.assertIn("- **2026-04-15T09:00:00+00:00** - second", md)

    def test_no_notes_renders_placeholder(self):
        md = vault.render_markdown(self._repo(), None, [])
        self.assertIn("_No notes yet._", md)

    def test_upstream_absent_hides_block(self):
        md = vault.render_markdown(self._repo(), None, [])
        self.assertNotIn("upstream:", md)

    def test_remote_url_is_redacted(self):
        md = vault.render_markdown(
            self._repo(remote_url="https://user:token@github.com/o/r.git"),
            None,
            [],
        )
        self.assertNotIn("token", md)
        self.assertIn("https://***@github.com/o/r.git", md)

    def test_header_uses_owner_name_when_upstream_present(self):
        md = vault.render_markdown(self._repo(), self._upstream(), [])
        self.assertIn("# o/r", md)

    def test_header_falls_back_to_path_basename(self):
        md = vault.render_markdown(self._repo(), None, [])
        self.assertIn("# repo", md)


class TestExportRepo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _target(self):
        return vault.VaultTarget(self.tmp, subdir="repos")

    def test_writes_file_with_slug(self):
        target = self._target()
        repo = {
            "id": 1,
            "path": "/tmp/foo",
            "remote_url": None,
            "source": None,
            "status": "new",
            "quiet": 0,
            "added_at": "2026-04-15T00:00:00+00:00",
            "last_touched_at": None,
            "tags": [],
        }
        path = vault.export_repo(target, repo, None, [])
        self.assertTrue(os.path.isfile(path))
        self.assertEqual(os.path.basename(path), "foo.md")
        with open(path) as f:
            self.assertIn("gitpulse_id: 1", f.read())

    def test_creates_repos_dir_with_0700(self):
        target = self._target()
        repo = {
            "id": 2, "path": "/tmp/bar", "remote_url": None, "source": None,
            "status": "new", "quiet": 0, "added_at": "2026-04-15T00:00:00+00:00",
            "last_touched_at": None, "tags": [],
        }
        vault.export_repo(target, repo, None, [])
        self.assertTrue(os.path.isdir(target.repos_dir))
        if sys.platform != "win32":
            mode = stat.S_IMODE(os.stat(target.repos_dir).st_mode)
            self.assertEqual(mode, 0o700)

    def test_file_is_0600(self):
        if sys.platform == "win32":
            self.skipTest("Unix perm check")
        target = self._target()
        repo = {
            "id": 3, "path": "/tmp/baz", "remote_url": None, "source": None,
            "status": "new", "quiet": 0, "added_at": "2026-04-15T00:00:00+00:00",
            "last_touched_at": None, "tags": [],
        }
        path = vault.export_repo(target, repo, None, [])
        mode = stat.S_IMODE(os.stat(path).st_mode)
        self.assertEqual(mode, 0o600)

    def test_overwrite_is_idempotent(self):
        target = self._target()
        repo = {
            "id": 4, "path": "/tmp/quux", "remote_url": None, "source": None,
            "status": "new", "quiet": 0, "added_at": "2026-04-15T00:00:00+00:00",
            "last_touched_at": None, "tags": [],
        }
        path1 = vault.export_repo(target, repo, None, [])
        path2 = vault.export_repo(target, repo, None, [])
        self.assertEqual(path1, path2)
        self.assertTrue(os.path.isfile(path1))


class TestExportCommand(unittest.TestCase):
    """End-to-end for `gitpulse vault export` against a real DB."""

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

    def _args(self, **overrides):
        base = {"vault_command": "export", "path": None, "subdir": None, "quiet": True}
        base.update(overrides)
        return argparse.Namespace(**base)

    def test_exports_every_repo(self):
        with index.connect(self.db) as conn:
            index.add_repo(conn, "/t/a", tags=["c2"])
            index.add_repo(conn, "/t/b", tags=["recon"])
        with mock.patch("sys.stdout", new_callable=io.StringIO):
            rc = cmd_vault.run_export(self._args())
        self.assertEqual(rc, 0)
        files = os.listdir(os.path.join(self.vault_dir, "repos"))
        # two .md files, each with a slug name
        md_files = [f for f in files if f.endswith(".md")]
        self.assertEqual(len(md_files), 2)

    def test_errors_without_vault_path(self):
        self._patches[-1].stop()
        with mock.patch(
            "core.commands.vault.load_config",
            return_value={"vault_path": None, "vault_subdir": "repos"},
        ):
            with mock.patch("sys.stderr", new_callable=io.StringIO):
                rc = cmd_vault.run_export(self._args())
        self.assertEqual(rc, 1)
        # Re-start the last patch to satisfy tearDown
        self._patches[-1].start()

    def test_cli_path_overrides_config(self):
        override = os.path.join(self.tmp, "other")
        with index.connect(self.db) as conn:
            index.add_repo(conn, "/t/a")
        with mock.patch("sys.stdout", new_callable=io.StringIO):
            rc = cmd_vault.run_export(self._args(path=override))
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.isdir(os.path.join(override, "repos")))


if __name__ == "__main__":
    unittest.main()
