"""Tests for the dashboard HTML generator and command."""

import argparse
import io
import os
import shutil
import tempfile
import unittest
from unittest import mock

from core import dashboard as _dashboard
from core import index
from core.commands import dashboard as cmd_dashboard


def _R(path: str) -> str:
    return os.path.realpath(os.path.expanduser(path))


class TestRenderHtml(unittest.TestCase):
    def test_minimal_digest_renders(self):
        digest = {
            "generated_at": "2026-04-16T10:00:00+00:00",
            "window_days": 7,
            "stale_days": 90,
            "dormant_days": 365,
            "counts": {"total": 0, "by_status": {}},
            "added": [],
            "refreshed": [],
            "archived": [],
            "flagged": [],
            "stale_local": [],
            "dormant": [],
        }
        html = _dashboard.render_html(digest)
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("gitpulse fleet health", html)
        self.assertIn("Total: 0", html)

    def test_populated_digest_renders_rows(self):
        digest = {
            "generated_at": "2026-04-16T10:00:00+00:00",
            "window_days": 7,
            "stale_days": 90,
            "dormant_days": 365,
            "counts": {"total": 2, "by_status": {"new": 1, "in-use": 1}},
            "added": [
                {"id": 1, "path": "/t/a", "tags": ["c2"], "source": "blog"},
            ],
            "refreshed": [],
            "archived": [
                {"id": 2, "path": "/t/b", "host": "github.com", "owner": "o", "name": "b"},
            ],
            "flagged": [],
            "stale_local": [],
            "dormant": [],
        }
        html = _dashboard.render_html(digest, title="Test Report")
        self.assertIn("Test Report", html)
        self.assertIn("/t/a", html)
        self.assertIn("/t/b", html)
        self.assertIn("c2", html)
        self.assertIn("supply-chain", html.lower())

    def test_html_escaping(self):
        digest = {
            "generated_at": "now",
            "window_days": 7,
            "stale_days": 90,
            "dormant_days": 365,
            "counts": {"total": 1, "by_status": {"new": 1}},
            "added": [
                {"id": 1, "path": "/t/<script>alert(1)</script>", "tags": [], "source": None},
            ],
            "refreshed": [],
            "archived": [],
            "flagged": [],
            "stale_local": [],
            "dormant": [],
        }
        html = _dashboard.render_html(digest)
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)


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


class TestDashboardCommand(_IndexTestCase):
    def _args(self, **overrides):
        base = {
            "out": "-",
            "title": "gitpulse fleet health",
            "since": 7,
            "stale": 90,
            "dormant": 365,
        }
        base.update(overrides)
        return argparse.Namespace(**base)

    def test_stdout_emits_html(self):
        with index.connect(self.db) as conn:
            index.add_repo(conn, "/t/a", tags=["c2"])
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            rc = cmd_dashboard.run(self._args())
        self.assertEqual(rc, 0)
        self.assertIn("<!DOCTYPE html>", out.getvalue())
        self.assertIn(_R("/t/a"), out.getvalue())

    def test_out_file_writes(self):
        out_path = os.path.join(self.tmp, "report.html")
        with index.connect(self.db) as conn:
            index.add_repo(conn, "/t/a")
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            rc = cmd_dashboard.run(self._args(out=out_path))
        self.assertEqual(rc, 0)
        with open(out_path) as f:
            self.assertIn("<!DOCTYPE html>", f.read())

    def test_custom_title(self):
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            cmd_dashboard.run(self._args(title="My Report"))
        self.assertIn("My Report", out.getvalue())


if __name__ == "__main__":
    unittest.main()
