"""Tests for nostos doctor."""

import argparse
import io
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from core import doctor as _doctor
from core import index
from core.commands import doctor as cmd_doctor


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


class TestDoctorChecks(_IndexTestCase):
    def test_clean_index_no_issues(self):
        repo_dir = os.path.join(self.tmp, "r")
        os.makedirs(os.path.join(repo_dir, ".git"))
        with index.connect(self.db) as conn:
            rid = index.add_repo(conn, repo_dir, remote_url="git@h:o/r.git")
            index.upsert_upstream_meta(
                conn, rid,
                {"provider": "github", "host": "github.com", "owner": "o", "name": "r"},
            )
            report = _doctor.run_checks(conn)
        self.assertEqual(report["issues_total"], 0)
        self.assertEqual(report["total_repos"], 1)

    def test_stale_path_detected(self):
        with index.connect(self.db) as conn:
            index.add_repo(conn, "/nonexistent/repo", remote_url="x")
            index.upsert_upstream_meta(
                conn, 1,
                {"provider": "github", "host": "github.com", "owner": "o", "name": "r"},
            )
            report = _doctor.run_checks(conn)
        self.assertEqual(len(report["stale_paths"]), 1)
        self.assertGreater(report["issues_total"], 0)

    def test_missing_remote_detected(self):
        repo_dir = os.path.join(self.tmp, "r")
        os.makedirs(os.path.join(repo_dir, ".git"))
        with index.connect(self.db) as conn:
            index.add_repo(conn, repo_dir)  # no remote_url
            index.upsert_upstream_meta(
                conn, 1,
                {"provider": "github", "host": "github.com", "owner": "o", "name": "r"},
            )
            report = _doctor.run_checks(conn)
        self.assertEqual(len(report["missing_remote"]), 1)

    def test_missing_upstream_detected(self):
        repo_dir = os.path.join(self.tmp, "r")
        os.makedirs(os.path.join(repo_dir, ".git"))
        with index.connect(self.db) as conn:
            index.add_repo(conn, repo_dir, remote_url="x")
            # No upstream_meta upserted
            report = _doctor.run_checks(conn)
        self.assertEqual(len(report["missing_upstream"]), 1)

    def test_orphan_vault_file_detected(self):
        vault_dir = os.path.join(self.tmp, "vault")
        repos_dir = os.path.join(vault_dir, "repos")
        os.makedirs(repos_dir)
        # Write a vault file with an id that doesn't exist in the DB
        with open(os.path.join(repos_dir, "orphan.md"), "w") as f:
            f.write("---\nnostos_id: 9999\nstatus: \"new\"\n---\n")
        with index.connect(self.db) as conn:
            report = _doctor.run_checks(
                conn, vault_path=vault_dir, vault_subdir="repos"
            )
        self.assertEqual(len(report["orphan_vault_files"]), 1)

    def test_schema_version_reported(self):
        with index.connect(self.db) as conn:
            report = _doctor.run_checks(conn)
        self.assertEqual(report["schema_version"], index.CURRENT_SCHEMA_VERSION)


class TestDoctorFix(_IndexTestCase):
    def test_fix_flags_stale_repos(self):
        with index.connect(self.db) as conn:
            index.add_repo(conn, "/nonexistent/a", status="new")
            report = _doctor.run_checks(conn)
            _doctor.fix_stale_paths(conn, report["stale_paths"])
            repo = index.get_repo(conn, "/nonexistent/a")
        self.assertEqual(repo["status"], "flagged")

    def test_fix_deletes_orphan_vault_files(self):
        vault_dir = os.path.join(self.tmp, "vault")
        repos_dir = os.path.join(vault_dir, "repos")
        os.makedirs(repos_dir)
        orphan = os.path.join(repos_dir, "orphan.md")
        with open(orphan, "w") as f:
            f.write("---\nnostos_id: 9999\nstatus: \"new\"\n---\n")
        with index.connect(self.db) as conn:
            report = _doctor.run_checks(
                conn, vault_path=vault_dir, vault_subdir="repos"
            )
        for p in report["orphan_vault_files"]:
            os.remove(p)
        self.assertFalse(os.path.exists(orphan))


class TestDoctorCommand(_IndexTestCase):
    def _args(self, **overrides):
        base = {"fix": False, "json": False}
        base.update(overrides)
        return argparse.Namespace(**base)

    def test_human_output(self):
        with index.connect(self.db) as conn:
            index.add_repo(conn, "/nonexistent/a")
        with mock.patch(
            "core.commands.doctor.load_config",
            return_value={"vault_path": None, "vault_subdir": "repos"},
        ), mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            rc = cmd_doctor.run(self._args())
        self.assertEqual(rc, 1)  # issues found
        self.assertIn("Stale paths", out.getvalue())

    def test_json_output(self):
        with index.connect(self.db) as conn:
            index.add_repo(conn, "/nonexistent/a")
        with mock.patch(
            "core.commands.doctor.load_config",
            return_value={"vault_path": None, "vault_subdir": "repos"},
        ), mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            cmd_doctor.run(self._args(json=True))
        data = json.loads(out.getvalue())
        self.assertIn("stale_paths", data)
        self.assertIn("issues_total", data)

    def test_fix_returns_zero(self):
        with index.connect(self.db) as conn:
            index.add_repo(conn, "/nonexistent/a")
        with mock.patch(
            "core.commands.doctor.load_config",
            return_value={"vault_path": None, "vault_subdir": "repos"},
        ), mock.patch("sys.stdout", new_callable=io.StringIO), mock.patch(
            "sys.stderr", new_callable=io.StringIO
        ):
            rc = cmd_doctor.run(self._args(fix=True))
        self.assertEqual(rc, 0)  # fixed -> clean exit
        with index.connect(self.db) as conn:
            repo = index.get_repo(conn, "/nonexistent/a")
        self.assertEqual(repo["status"], "flagged")

    def test_clean_index_passes(self):
        repo_dir = os.path.join(self.tmp, "r")
        os.makedirs(os.path.join(repo_dir, ".git"))
        with index.connect(self.db) as conn:
            rid = index.add_repo(conn, repo_dir, remote_url="x")
            index.upsert_upstream_meta(
                conn, rid,
                {"provider": "github", "host": "github.com", "owner": "o", "name": "r"},
            )
        with mock.patch(
            "core.commands.doctor.load_config",
            return_value={"vault_path": None, "vault_subdir": "repos"},
        ), mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            rc = cmd_doctor.run(self._args())
        self.assertEqual(rc, 0)
        self.assertIn("All checks passed", out.getvalue())


if __name__ == "__main__":
    unittest.main()
