"""End-to-end tests for the Phase 1 subcommands.

Each test constructs an argparse.Namespace with the fields the command
expects, patches the index location to a temp DB, and calls the
command's run() directly. File I/O, the SQLite index, and the pull
engine are exercised for real; network and git are mocked.
"""

import argparse
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from core import index
from core.commands import add as cmd_add
from core.commands import list_cmd as cmd_list
from core.commands import note as cmd_note
from core.commands import rm as cmd_rm
from core.commands import show as cmd_show
from core.commands import tag as cmd_tag
from core.commands import triage as cmd_triage


def _R(path: str) -> str:
    """Canonicalise a path exactly like core.index._normalize_path."""
    return os.path.realpath(os.path.expanduser(path))


class _IndexTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "index.db")
        self._patches = [
            mock.patch("core.index.index_db_path", return_value=self.db),
            mock.patch("core.index.ensure_data_dir", return_value=self.tmp),
            mock.patch("core.commands._common.maybe_migrate_watchlist"),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_repo(self, name="r"):
        repo = os.path.join(self.tmp, name)
        os.makedirs(os.path.join(repo, ".git"), exist_ok=True)
        return repo


class TestAdd(_IndexTestCase):
    def test_add_local_path(self):
        repo = self._make_repo("a")
        args = argparse.Namespace(
            target=repo,
            tag=["c2,post-ex"],
            source="colleague:x",
            note="initial",
            status="new",
            quiet_upstream=False,
            auto_tags=False,
            clone_dir=None,
        )
        rc = cmd_add.run(args)
        self.assertEqual(rc, 0)
        with index.connect(self.db) as conn:
            rows = index.list_repos(conn)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], "colleague:x")
        self.assertEqual(sorted(rows[0]["tags"]), ["c2", "post-ex"])

    def test_add_nonexistent_path_fails(self):
        args = argparse.Namespace(
            target="/nonexistent/repo",
            tag=[],
            source=None,
            note=None,
            status="new",
            quiet_upstream=False,
            auto_tags=False,
            clone_dir=None,
        )
        rc = cmd_add.run(args)
        self.assertEqual(rc, 1)

    def test_add_remote_url_uses_safe_clone(self):
        clone_dir = os.path.join(self.tmp, "clones")
        os.makedirs(clone_dir)
        cloned = os.path.join(clone_dir, "repo")
        os.makedirs(os.path.join(cloned, ".git"))

        with mock.patch(
            "core.commands.add.clone_repo", return_value=cloned
        ) as mock_clone:
            args = argparse.Namespace(
                target="https://github.com/u/repo.git",
                tag=[],
                source=None,
                note=None,
                status="new",
                quiet_upstream=False,
                auto_tags=False,
                clone_dir=clone_dir,
            )
            rc = cmd_add.run(args)

        self.assertEqual(rc, 0)
        mock_clone.assert_called_once()
        with index.connect(self.db) as conn:
            rows = index.list_repos(conn)
        self.assertEqual(rows[0]["remote_url"], "https://github.com/u/repo.git")

    def test_quiet_upstream_persists(self):
        repo = self._make_repo("q")
        args = argparse.Namespace(
            target=repo,
            tag=[],
            source=None,
            note=None,
            status="new",
            quiet_upstream=True,
            auto_tags=False,
            clone_dir=None,
        )
        cmd_add.run(args)
        with index.connect(self.db) as conn:
            rows = index.list_repos(conn)
        self.assertEqual(rows[0]["quiet"], 1)

    def test_auto_tags_merges_upstream_topics(self):
        clone_dir = os.path.join(self.tmp, "clones")
        os.makedirs(clone_dir)
        cloned = os.path.join(clone_dir, "repo")
        os.makedirs(os.path.join(cloned, ".git"))

        fake_meta = {"topics": ["c2", "redteam", "Mythic"]}

        with mock.patch("core.commands.add.clone_repo", return_value=cloned), \
             mock.patch("core.commands.add.probe_upstream", return_value=fake_meta), \
             mock.patch(
                 "core.commands.add.load_auth",
                 return_value=mock.Mock(is_allowed=lambda h: True),
             ):
            args = argparse.Namespace(
                target="https://github.com/u/repo.git",
                tag=["existing"],
                source=None,
                note=None,
                status="new",
                quiet_upstream=False,
                auto_tags=True,
                clone_dir=clone_dir,
            )
            rc = cmd_add.run(args)

        self.assertEqual(rc, 0)
        with index.connect(self.db) as conn:
            rows = index.list_repos(conn)
        # Topics merged, lowercased, deduplicated against existing tag.
        self.assertEqual(sorted(rows[0]["tags"]), ["c2", "existing", "mythic", "redteam"])

    def test_auto_tags_skipped_when_quiet_upstream(self):
        clone_dir = os.path.join(self.tmp, "clones")
        os.makedirs(clone_dir)
        cloned = os.path.join(clone_dir, "repo")
        os.makedirs(os.path.join(cloned, ".git"))

        with mock.patch("core.commands.add.clone_repo", return_value=cloned), \
             mock.patch("core.commands.add.probe_upstream") as mock_probe:
            args = argparse.Namespace(
                target="https://github.com/u/repo.git",
                tag=[],
                source=None,
                note=None,
                status="new",
                quiet_upstream=True,
                auto_tags=True,
                clone_dir=clone_dir,
            )
            rc = cmd_add.run(args)

        self.assertEqual(rc, 0)
        mock_probe.assert_not_called()

    def test_auto_tags_host_not_allowed_warns_and_continues(self):
        clone_dir = os.path.join(self.tmp, "clones")
        os.makedirs(clone_dir)
        cloned = os.path.join(clone_dir, "repo")
        os.makedirs(os.path.join(cloned, ".git"))

        with mock.patch("core.commands.add.clone_repo", return_value=cloned), \
             mock.patch("core.commands.add.probe_upstream") as mock_probe, \
             mock.patch(
                 "core.commands.add.load_auth",
                 return_value=mock.Mock(is_allowed=lambda h: False),
             ):
            args = argparse.Namespace(
                target="https://github.com/u/repo.git",
                tag=["manual"],
                source=None,
                note=None,
                status="new",
                quiet_upstream=False,
                auto_tags=True,
                clone_dir=clone_dir,
            )
            rc = cmd_add.run(args)

        self.assertEqual(rc, 0)
        # Fail-closed: probe never runs when host isn't in auth.toml.
        mock_probe.assert_not_called()
        with index.connect(self.db) as conn:
            rows = index.list_repos(conn)
        self.assertEqual(rows[0]["tags"], ["manual"])


class TestList(_IndexTestCase):
    def _seed(self):
        with index.connect(self.db) as conn:
            index.add_repo(conn, "/t/a", tags=["c2"], status="in-use")
            index.add_repo(conn, "/t/b", tags=["recon"], status="new")
            index.add_repo(conn, "/t/c", status="flagged")

    def test_list_all_as_json(self):
        self._seed()
        args = argparse.Namespace(
            tag=None, status=None, untouched_over=None, json=True
        )
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            rc = cmd_list.run(args)
        data = json.loads(out.getvalue())
        self.assertEqual(rc, 0)
        self.assertEqual(data["total"], 3)

    def test_list_filter_by_tag(self):
        self._seed()
        args = argparse.Namespace(
            tag="c2", status=None, untouched_over=None, json=True
        )
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            cmd_list.run(args)
        data = json.loads(out.getvalue())
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["repositories"][0]["path"], _R("/t/a"))

    def test_list_filter_by_status(self):
        self._seed()
        args = argparse.Namespace(
            tag=None, status="flagged", untouched_over=None, json=True
        )
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            cmd_list.run(args)
        data = json.loads(out.getvalue())
        self.assertEqual(data["total"], 1)

    def test_list_table_empty_repo_list(self):
        args = argparse.Namespace(
            tag=None, status=None, untouched_over=None, json=False
        )
        with mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            rc = cmd_list.run(args)
        self.assertEqual(rc, 0)
        self.assertIn("no matching", err.getvalue())


class TestShow(_IndexTestCase):
    def test_show_json(self):
        with index.connect(self.db) as conn:
            rid = index.add_repo(conn, "/t/a", tags=["c2"], note="hi")
        args = argparse.Namespace(target=str(rid), json=True)
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            rc = cmd_show.run(args)
        data = json.loads(out.getvalue())
        self.assertEqual(rc, 0)
        self.assertEqual(data["tags"], ["c2"])
        self.assertEqual(data["notes"][0]["body"], "hi")

    def test_show_human(self):
        with index.connect(self.db) as conn:
            index.add_repo(conn, "/t/a", source="blog:x")
        args = argparse.Namespace(target="/t/a", json=False)
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            cmd_show.run(args)
        text = out.getvalue()
        self.assertIn(_R("/t/a"), text)
        self.assertIn("blog:x", text)

    def test_show_updates_last_touched(self):
        with index.connect(self.db) as conn:
            index.add_repo(conn, "/t/a")
        args = argparse.Namespace(target="/t/a", json=True)
        with mock.patch("sys.stdout", new_callable=io.StringIO):
            cmd_show.run(args)
        with index.connect(self.db) as conn:
            repo = index.get_repo(conn, "/t/a")
        self.assertIsNotNone(repo["last_touched_at"])

    def test_show_missing(self):
        args = argparse.Namespace(target="/nope", json=False)
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            rc = cmd_show.run(args)
        self.assertEqual(rc, 1)


class TestTag(_IndexTestCase):
    def test_tag_add_and_remove(self):
        with index.connect(self.db) as conn:
            index.add_repo(conn, "/t/a", tags=["old"])
        args = argparse.Namespace(target="/t/a", tags=["+new", "-old"])
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            rc = cmd_tag.run(args)
        self.assertEqual(rc, 0)
        with index.connect(self.db) as conn:
            self.assertEqual(index.get_tags(conn, "/t/a"), ["new"])

    def test_tag_missing_repo(self):
        args = argparse.Namespace(target="/nope", tags=["x"])
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            rc = cmd_tag.run(args)
        self.assertEqual(rc, 1)


class TestNote(_IndexTestCase):
    def test_note_appends(self):
        with index.connect(self.db) as conn:
            index.add_repo(conn, "/t/a")
        args = argparse.Namespace(target="/t/a", body="second thought")
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            rc = cmd_note.run(args)
        self.assertEqual(rc, 0)
        with index.connect(self.db) as conn:
            notes = index.get_notes(conn, "/t/a")
        self.assertEqual(notes[-1]["body"], "second thought")

    def test_note_missing_repo(self):
        args = argparse.Namespace(target="/nope", body="x")
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            rc = cmd_note.run(args)
        self.assertEqual(rc, 1)


class TestRm(_IndexTestCase):
    def test_rm_drops_from_index(self):
        repo = self._make_repo("gone")
        with index.connect(self.db) as conn:
            index.add_repo(conn, repo)
        args = argparse.Namespace(
            target=repo, purge=False, cleanup_vault=False, yes=False
        )
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            rc = cmd_rm.run(args)
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.isdir(repo))  # clone preserved
        with index.connect(self.db) as conn:
            self.assertIsNone(index.get_repo(conn, repo))

    def test_rm_purge_with_yes_deletes_clone(self):
        repo = self._make_repo("gone2")
        with index.connect(self.db) as conn:
            index.add_repo(conn, repo)
        args = argparse.Namespace(
            target=repo, purge=True, cleanup_vault=False, yes=True
        )
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            cmd_rm.run(args)
        self.assertFalse(os.path.exists(repo))

    def test_rm_cleanup_vault_deletes_md(self):
        vault_dir = os.path.join(self.tmp, "vault")
        repos_dir = os.path.join(vault_dir, "repos")
        os.makedirs(repos_dir)
        repo = self._make_repo("vaulted")
        with index.connect(self.db) as conn:
            index.add_repo(conn, repo)
        # Create a matching vault file (slug = "vaulted")
        md_path = os.path.join(repos_dir, "vaulted.md")
        with open(md_path, "w") as f:
            f.write("---\nnostos_id: 1\n---\n")
        args = argparse.Namespace(
            target=repo, purge=False, cleanup_vault=True, yes=False
        )
        with mock.patch(
            "core.commands.rm.load_config",
            return_value={"vault_path": vault_dir, "vault_subdir": "repos"},
        ), mock.patch("sys.stderr", new_callable=io.StringIO):
            rc = cmd_rm.run(args)
        self.assertEqual(rc, 0)
        self.assertFalse(os.path.exists(md_path))  # vault file removed

    def test_rm_missing_repo(self):
        args = argparse.Namespace(
            target="/nope", purge=False, cleanup_vault=False, yes=False
        )
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            rc = cmd_rm.run(args)
        self.assertEqual(rc, 1)


class TestTriage(_IndexTestCase):
    def test_triage_processes_new_repos(self):
        with index.connect(self.db) as conn:
            index.add_repo(conn, "/t/a", status="new")
            index.add_repo(conn, "/t/b", status="new")
        args = argparse.Namespace(status="new")
        # Queue is newest-first: /t/b, then /t/a.
        # Per-repo inputs: tags, status, note.
        inputs = iter(["c2", "in-use", "ops-ready", "", "dropped", ""])
        with mock.patch("builtins.input", lambda prompt: next(inputs)), mock.patch(
            "sys.stderr", new_callable=io.StringIO
        ):
            rc = cmd_triage.run(args)
        self.assertEqual(rc, 0)
        with index.connect(self.db) as conn:
            a = index.get_repo(conn, "/t/a")
            b = index.get_repo(conn, "/t/b")
        self.assertEqual(b["status"], "in-use")
        self.assertEqual(b["tags"], ["c2"])
        self.assertEqual(b["notes"][0]["body"], "ops-ready")
        self.assertEqual(a["status"], "dropped")

    def test_triage_empty_queue(self):
        args = argparse.Namespace(status="new")
        with mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            rc = cmd_triage.run(args)
        self.assertEqual(rc, 0)
        self.assertIn("nothing to triage", err.getvalue())


class TestPullAutoRegister(_IndexTestCase):
    """Verify that a successful pull auto-registers discovered repos
    and updates last_touched_at."""

    def _git(self, *args, cwd=None):
        subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=True,
            capture_output=True,
            env={**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null"},
        )

    def _init_repo_with_upstream(self):
        """Create a local repo backed by a bare 'upstream' clone, both
        under self.tmp. Returns the worktree path."""
        upstream = os.path.join(self.tmp, "upstream.git")
        os.makedirs(upstream)
        self._git("init", "--bare", upstream)

        work = os.path.join(self.tmp, "work")
        os.makedirs(work)
        self._git("init", "-b", "main", work)
        self._git("config", "user.email", "t@t", cwd=work)
        self._git("config", "user.name", "t", cwd=work)
        self._git("commit", "--allow-empty", "-m", "init", cwd=work)
        self._git("remote", "add", "origin", upstream, cwd=work)
        self._git("push", "-u", "origin", "main", cwd=work)
        return work

    def test_pull_registers_repo_in_index(self):
        from core.commands import pull as cmd_pull

        work = self._init_repo_with_upstream()
        args = argparse.Namespace(
            command="pull",
            path=self.tmp,
            dry_run=False,
            fetch_only=False,
            rebase=False,
            depth=3,
            workers=2,
            timeout=30,
            exclude=[],
            json=True,
            quiet=True,
            from_index=False,
            watchlist=False,
        )

        # Prevent real logging file creation.
        with mock.patch("core.commands.pull.setup_logging"), mock.patch(
            "core.commands.pull.check_git_version"
        ), mock.patch("sys.stdout", new_callable=io.StringIO):
            rc = cmd_pull.run(args)

        self.assertEqual(rc, 0)
        with index.connect(self.db) as conn:
            rows = index.list_repos(conn)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["path"], os.path.realpath(work))
        self.assertEqual(rows[0]["source"], "auto-discovered")
        self.assertIsNotNone(rows[0]["last_touched_at"])


if __name__ == "__main__":
    unittest.main()
