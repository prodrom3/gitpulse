"""Tests for the `refresh` subcommand and its upstream-aware list/show changes."""

import argparse
import io
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from core import index
from core.auth import AuthConfig
from core.commands import list_cmd as cmd_list
from core.commands import refresh as cmd_refresh
from core.commands import show as cmd_show


def _R(path: str) -> str:
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


def _refresh_args(**overrides):
    base = {
        "repo": None,
        "since": 7,
        "all": False,
        "force": False,
        "offline": False,
        "auto_tags": False,
        "json": False,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


class TestRefreshHappyPath(_IndexTestCase):
    def test_refreshes_stale_repos_with_configured_host(self):
        with index.connect(self.db) as conn:
            rid = index.add_repo(
                conn,
                "/t/r",
                remote_url="git@github.com:o/r.git",
                source="test",
            )
        fake_meta = {
            "provider": "github",
            "host": "github.com",
            "owner": "o",
            "name": "r",
            "stars": 7,
            "archived": False,
            "default_branch": "main",
            "last_push": "2026-04-10T00:00:00Z",
            "fetched_at": "2026-04-15T00:00:00+00:00",
        }
        with mock.patch(
            "core.commands.refresh.load_auth",
            return_value=AuthConfig(hosts={"github.com": {}}),
        ), mock.patch(
            "core.commands.refresh.probe_upstream", return_value=fake_meta
        ), mock.patch(
            "sys.stderr", new_callable=io.StringIO
        ):
            rc = cmd_refresh.run(_refresh_args())
        self.assertEqual(rc, 0)
        with index.connect(self.db) as conn:
            meta = index.get_upstream_meta(conn, rid)
        self.assertEqual(meta["stars"], 7)
        self.assertEqual(meta["provider"], "github")


class TestRefreshQuietAndFailClosed(_IndexTestCase):
    def test_skips_quiet_repos_entirely(self):
        with index.connect(self.db) as conn:
            index.add_repo(
                conn,
                "/t/q",
                remote_url="git@github.com:o/q.git",
                quiet=True,
            )
        with mock.patch(
            "core.commands.refresh.load_auth",
            return_value=AuthConfig(hosts={"github.com": {}}),
        ), mock.patch("core.commands.refresh.probe_upstream") as mock_probe, mock.patch(
            "sys.stderr", new_callable=io.StringIO
        ):
            rc = cmd_refresh.run(_refresh_args())
        self.assertEqual(rc, 0)
        mock_probe.assert_not_called()

    def test_skips_unconfigured_host(self):
        with index.connect(self.db) as conn:
            index.add_repo(
                conn,
                "/t/x",
                remote_url="git@random.example:o/x.git",
            )
        with mock.patch(
            "core.commands.refresh.load_auth",
            return_value=AuthConfig(),  # empty, allow_unknown=False
        ), mock.patch("core.commands.refresh.probe_upstream") as mock_probe, mock.patch(
            "sys.stderr", new_callable=io.StringIO
        ):
            rc = cmd_refresh.run(_refresh_args())
        self.assertEqual(rc, 0)
        mock_probe.assert_not_called()

    def test_offline_never_calls_probe(self):
        with index.connect(self.db) as conn:
            index.add_repo(
                conn,
                "/t/o",
                remote_url="git@github.com:o/o.git",
            )
        with mock.patch(
            "core.commands.refresh.load_auth",
            return_value=AuthConfig(hosts={"github.com": {}}),
        ), mock.patch("core.commands.refresh.probe_upstream") as mock_probe, mock.patch(
            "sys.stderr", new_callable=io.StringIO
        ):
            rc = cmd_refresh.run(_refresh_args(offline=True))
        self.assertEqual(rc, 0)
        mock_probe.assert_not_called()


class TestRefreshErrorHandling(_IndexTestCase):
    def test_probe_error_is_recorded(self):
        from core.upstream import ProbeError

        with index.connect(self.db) as conn:
            rid = index.add_repo(
                conn,
                "/t/e",
                remote_url="git@github.com:o/e.git",
            )
        with mock.patch(
            "core.commands.refresh.load_auth",
            return_value=AuthConfig(hosts={"github.com": {}}),
        ), mock.patch(
            "core.commands.refresh.probe_upstream",
            side_effect=ProbeError("timeout"),
        ), mock.patch("sys.stderr", new_callable=io.StringIO):
            rc = cmd_refresh.run(_refresh_args())
        self.assertEqual(rc, 1)
        with index.connect(self.db) as conn:
            meta = index.get_upstream_meta(conn, rid)
        self.assertIsNotNone(meta)
        self.assertEqual(meta["fetch_error"], "timeout")

    def test_json_summary_shape(self):
        with index.connect(self.db) as conn:
            index.add_repo(conn, "/t/q", remote_url="git@github.com:o/q.git", quiet=True)
        with mock.patch(
            "core.commands.refresh.load_auth",
            return_value=AuthConfig(hosts={"github.com": {}}),
        ), mock.patch("sys.stdout", new_callable=io.StringIO) as out, mock.patch(
            "sys.stderr", new_callable=io.StringIO
        ):
            cmd_refresh.run(_refresh_args(json=True))
        data = json.loads(out.getvalue())
        self.assertEqual(
            set(data.keys()),
            {"targets", "refreshed", "skipped_quiet", "skipped_unauthorised", "failed", "errors"},
        )
        self.assertEqual(data["skipped_quiet"], 1)


class TestRefreshAutoTags(_IndexTestCase):
    def _seed_repo(self, *, tags=None):
        with index.connect(self.db) as conn:
            rid = index.add_repo(
                conn,
                "/t/r",
                remote_url="git@github.com:o/r.git",
                source="test",
                tags=tags or [],
            )
        return rid

    def _meta(self, **overrides):
        base = {
            "provider": "github",
            "host": "github.com",
            "owner": "o",
            "name": "r",
            "stars": 1,
            "archived": False,
            "default_branch": "main",
            "last_push": "2026-04-10T00:00:00Z",
            "fetched_at": "2026-04-15T00:00:00+00:00",
            "topics": ["c2", "redteam", "Mythic"],
        }
        base.update(overrides)
        return base

    def test_auto_tags_off_does_not_touch_tags(self):
        rid = self._seed_repo(tags=["manual"])
        with mock.patch(
            "core.commands.refresh.load_auth",
            return_value=AuthConfig(hosts={"github.com": {}}),
        ), mock.patch(
            "core.commands.refresh.probe_upstream", return_value=self._meta()
        ), mock.patch("sys.stderr", new_callable=io.StringIO):
            rc = cmd_refresh.run(_refresh_args())
        self.assertEqual(rc, 0)
        with index.connect(self.db) as conn:
            self.assertEqual(index.get_tags(conn, rid), ["manual"])

    def test_auto_tags_on_merges_topics(self):
        rid = self._seed_repo(tags=["manual"])
        with mock.patch(
            "core.commands.refresh.load_auth",
            return_value=AuthConfig(hosts={"github.com": {}}),
        ), mock.patch(
            "core.commands.refresh.probe_upstream", return_value=self._meta()
        ), mock.patch("sys.stderr", new_callable=io.StringIO):
            rc = cmd_refresh.run(_refresh_args(auto_tags=True))
        self.assertEqual(rc, 0)
        with index.connect(self.db) as conn:
            tags = index.get_tags(conn, rid)
        # Existing tag preserved; topics merged in lowercase.
        self.assertEqual(sorted(tags), ["c2", "manual", "mythic", "redteam"])

    def test_auto_tags_idempotent_on_repeat_refresh(self):
        rid = self._seed_repo()
        with mock.patch(
            "core.commands.refresh.load_auth",
            return_value=AuthConfig(hosts={"github.com": {}}),
        ), mock.patch(
            "core.commands.refresh.probe_upstream", return_value=self._meta()
        ), mock.patch("sys.stderr", new_callable=io.StringIO):
            cmd_refresh.run(_refresh_args(auto_tags=True, all=True))
            cmd_refresh.run(_refresh_args(auto_tags=True, all=True))
        with index.connect(self.db) as conn:
            tags = index.get_tags(conn, rid)
        self.assertEqual(sorted(tags), ["c2", "mythic", "redteam"])

    def test_auto_tags_json_summary_includes_breakdown(self):
        self._seed_repo()
        with mock.patch(
            "core.commands.refresh.load_auth",
            return_value=AuthConfig(hosts={"github.com": {}}),
        ), mock.patch(
            "core.commands.refresh.probe_upstream", return_value=self._meta()
        ), mock.patch("sys.stdout", new_callable=io.StringIO) as out, mock.patch(
            "sys.stderr", new_callable=io.StringIO
        ):
            cmd_refresh.run(_refresh_args(auto_tags=True, json=True))
        data = json.loads(out.getvalue())
        self.assertEqual(data["tags_added"], 3)
        self.assertEqual(len(data["tagged_repos"]), 1)
        self.assertEqual(
            sorted(data["tagged_repos"][0]["added"]),
            ["Mythic", "c2", "redteam"],
        )

    def test_auto_tags_skipped_for_quiet_repo(self):
        with index.connect(self.db) as conn:
            rid = index.add_repo(
                conn,
                "/t/q",
                remote_url="git@github.com:o/q.git",
                quiet=True,
            )
        with mock.patch(
            "core.commands.refresh.load_auth",
            return_value=AuthConfig(hosts={"github.com": {}}),
        ), mock.patch(
            "core.commands.refresh.probe_upstream", return_value=self._meta()
        ) as mock_probe, mock.patch("sys.stderr", new_callable=io.StringIO):
            cmd_refresh.run(_refresh_args(auto_tags=True, all=True))
        mock_probe.assert_not_called()
        with index.connect(self.db) as conn:
            self.assertEqual(index.get_tags(conn, rid), [])


class TestListUpstreamFilters(_IndexTestCase):
    def test_list_upstream_archived(self):
        with index.connect(self.db) as conn:
            a = index.add_repo(conn, "/t/a", remote_url="git@github.com:o/a.git")
            index.upsert_upstream_meta(
                conn,
                a,
                {"provider": "github", "host": "github.com", "owner": "o", "name": "a", "archived": True},
            )
            index.add_repo(conn, "/t/b", remote_url="git@github.com:o/b.git")
        args = argparse.Namespace(
            tag=None,
            status=None,
            untouched_over=None,
            upstream_archived=True,
            upstream_dormant=None,
            upstream_stale=None,
            json=True,
        )
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            cmd_list.run(args)
        data = json.loads(out.getvalue())
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["repositories"][0]["path"], _R("/t/a"))


class TestShowUpstreamBlock(_IndexTestCase):
    def test_show_prints_upstream(self):
        with index.connect(self.db) as conn:
            rid = index.add_repo(conn, "/t/a", remote_url="git@github.com:o/a.git")
            index.upsert_upstream_meta(
                conn,
                rid,
                {
                    "provider": "github",
                    "host": "github.com",
                    "owner": "o",
                    "name": "a",
                    "stars": 42,
                    "archived": False,
                    "default_branch": "main",
                    "last_push": "2026-04-10T00:00:00Z",
                },
            )
        args = argparse.Namespace(target="/t/a", json=False)
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            cmd_show.run(args)
        text = out.getvalue()
        self.assertIn("Upstream:", text)
        self.assertIn("Stars:         42", text)
        self.assertIn("Default branch: main", text)

    def test_show_prints_hint_when_no_upstream(self):
        with index.connect(self.db) as conn:
            index.add_repo(conn, "/t/a")
        args = argparse.Namespace(target="/t/a", json=False)
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            cmd_show.run(args)
        text = out.getvalue()
        self.assertIn("run `nostos refresh`", text)

    def test_show_json_includes_upstream(self):
        with index.connect(self.db) as conn:
            rid = index.add_repo(conn, "/t/a", remote_url="git@github.com:o/a.git")
            index.upsert_upstream_meta(
                conn,
                rid,
                {"provider": "github", "host": "github.com", "owner": "o", "name": "a", "stars": 1},
            )
        args = argparse.Namespace(target="/t/a", json=True)
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            cmd_show.run(args)
        data = json.loads(out.getvalue())
        self.assertIn("upstream", data)
        self.assertEqual(data["upstream"]["stars"], 1)


if __name__ == "__main__":
    unittest.main()
