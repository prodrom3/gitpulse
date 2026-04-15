"""Tests for core.digest aggregations and the digest subcommand."""

import argparse
import datetime
import io
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from core import digest as _digest
from core import index
from core.commands import digest as cmd_digest


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

    def _back_date(self, conn, path, column, days_ago):
        ts = (
            datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(days=days_ago)
        ).isoformat(timespec="seconds")
        conn.execute(
            f"UPDATE repos SET {column} = ? WHERE path = ?",
            (ts, os.path.realpath(path)),
        )
        conn.commit()

    def _back_date_upstream(self, conn, repo_id, column, days_ago):
        ts = (
            datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(days=days_ago)
        ).isoformat(timespec="seconds")
        conn.execute(
            f"UPDATE upstream_meta SET {column} = ? WHERE repo_id = ?",
            (ts, repo_id),
        )
        conn.commit()


class TestBuildDigest(_IndexTestCase):
    def test_counts_and_window(self):
        with index.connect(self.db) as conn:
            index.add_repo(conn, "/t/a", status="new")
            index.add_repo(conn, "/t/b", status="in-use")
            index.add_repo(conn, "/t/c", status="flagged")
            digest = _digest.build_digest(conn, since_days=7)
        self.assertEqual(digest["counts"]["total"], 3)
        self.assertEqual(digest["counts"]["by_status"]["new"], 1)
        self.assertEqual(digest["counts"]["by_status"]["in-use"], 1)
        self.assertEqual(digest["counts"]["by_status"]["flagged"], 1)
        self.assertEqual(digest["schema"], 1)
        self.assertEqual(digest["window_days"], 7)

    def test_added_section_only_within_window(self):
        with index.connect(self.db) as conn:
            index.add_repo(conn, "/t/new", tags=["recon"])
            index.add_repo(conn, "/t/old")
            self._back_date(conn, "/t/old", "added_at", 30)
            digest = _digest.build_digest(conn, since_days=7)
        paths = [r["path"] for r in digest["added"]]
        self.assertIn(os.path.realpath("/t/new"), paths)
        self.assertNotIn(os.path.realpath("/t/old"), paths)
        # Tags are preserved as a list
        new_row = next(r for r in digest["added"] if r["path"] == os.path.realpath("/t/new"))
        self.assertEqual(new_row["tags"], ["recon"])

    def test_refreshed_section_only_within_window(self):
        with index.connect(self.db) as conn:
            a = index.add_repo(conn, "/t/a")
            b = index.add_repo(conn, "/t/b")
            index.upsert_upstream_meta(
                conn, a,
                {"provider": "github", "host": "github.com", "owner": "o", "name": "a"},
            )
            index.upsert_upstream_meta(
                conn, b,
                {"provider": "github", "host": "github.com", "owner": "o", "name": "b"},
            )
            self._back_date_upstream(conn, b, "fetched_at", 30)
            digest = _digest.build_digest(conn, since_days=7)
        paths = [r["path"] for r in digest["refreshed"]]
        self.assertIn(os.path.realpath("/t/a"), paths)
        self.assertNotIn(os.path.realpath("/t/b"), paths)

    def test_archived_is_all_currently_archived(self):
        """Archived is surfaced every week regardless of when the flag
        was set; the operator should keep seeing the red flag."""
        with index.connect(self.db) as conn:
            a = index.add_repo(conn, "/t/a")
            index.upsert_upstream_meta(
                conn, a,
                {"provider": "github", "host": "github.com",
                 "owner": "o", "name": "a", "archived": True},
            )
            # push the probe into the distant past; still should surface
            self._back_date_upstream(conn, a, "fetched_at", 200)
            digest = _digest.build_digest(conn, since_days=7)
        self.assertEqual(len(digest["archived"]), 1)
        self.assertEqual(digest["archived"][0]["path"], os.path.realpath("/t/a"))

    def test_flagged(self):
        with index.connect(self.db) as conn:
            index.add_repo(conn, "/t/a", status="flagged")
            index.add_repo(conn, "/t/b", status="new")
            digest = _digest.build_digest(conn, since_days=7)
        paths = [r["path"] for r in digest["flagged"]]
        self.assertEqual(paths, [os.path.realpath("/t/a")])

    def test_stale_local(self):
        with index.connect(self.db) as conn:
            index.add_repo(conn, "/t/a")
            index.add_repo(conn, "/t/b")
            index.touch_repo(conn, "/t/a")
            self._back_date(conn, "/t/a", "last_touched_at", 200)
            # /t/b never touched -> NULL -> counts as stale
            digest = _digest.build_digest(conn, since_days=7, stale_days=90)
        paths = {r["path"] for r in digest["stale_local"]}
        self.assertEqual(
            paths,
            {os.path.realpath("/t/a"), os.path.realpath("/t/b")},
        )

    def test_dormant_upstream(self):
        with index.connect(self.db) as conn:
            a = index.add_repo(conn, "/t/a")
            index.upsert_upstream_meta(
                conn, a,
                {"provider": "github", "host": "github.com",
                 "owner": "o", "name": "a",
                 "last_push": (datetime.datetime.now(datetime.timezone.utc)
                               - datetime.timedelta(days=500)
                               ).isoformat(timespec="seconds")},
            )
            b = index.add_repo(conn, "/t/b")
            index.upsert_upstream_meta(
                conn, b,
                {"provider": "github", "host": "github.com",
                 "owner": "o", "name": "b",
                 "last_push": datetime.datetime.now(
                     datetime.timezone.utc
                 ).isoformat(timespec="seconds")},
            )
            digest = _digest.build_digest(conn, since_days=7, dormant_days=365)
        paths = {r["path"] for r in digest["dormant"]}
        self.assertEqual(paths, {os.path.realpath("/t/a")})


class TestRenderHuman(_IndexTestCase):
    def test_sections_appear(self):
        with index.connect(self.db) as conn:
            index.add_repo(conn, "/t/new", tags=["recon"])
            digest = _digest.build_digest(conn, since_days=7)
        text = _digest.render_human(digest)
        self.assertIn("gitpulse digest", text)
        self.assertIn("New intakes", text)
        self.assertIn("Refreshed upstream", text)
        self.assertIn("Currently archived upstream", text)
        self.assertIn("Operator-flagged", text)
        self.assertIn("Stale local", text)
        self.assertIn("Dormant upstream", text)
        self.assertIn(os.path.realpath("/t/new"), text)


class TestDigestCommand(_IndexTestCase):
    def _args(self, **overrides):
        base = {"since": 7, "stale": 90, "dormant": 365, "json": False}
        base.update(overrides)
        return argparse.Namespace(**base)

    def test_human_output(self):
        with index.connect(self.db) as conn:
            index.add_repo(conn, "/t/a", tags=["c2"])
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            rc = cmd_digest.run(self._args())
        self.assertEqual(rc, 0)
        self.assertIn("gitpulse digest", out.getvalue())

    def test_json_output_is_parseable(self):
        with index.connect(self.db) as conn:
            index.add_repo(conn, "/t/a")
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            rc = cmd_digest.run(self._args(json=True))
        self.assertEqual(rc, 0)
        data = json.loads(out.getvalue())
        self.assertIn("counts", data)
        self.assertIn("added", data)
        self.assertEqual(data["schema"], 1)

    def test_exit_code_is_always_zero(self):
        """The digest is informational; a non-empty archived list
        doesn't make the command 'fail'."""
        with index.connect(self.db) as conn:
            rid = index.add_repo(conn, "/t/a")
            index.upsert_upstream_meta(
                conn, rid,
                {"provider": "github", "host": "github.com",
                 "owner": "o", "name": "a", "archived": True},
            )
        with mock.patch("sys.stdout", new_callable=io.StringIO):
            rc = cmd_digest.run(self._args())
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
