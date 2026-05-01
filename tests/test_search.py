"""Tests for `nostos search` and core.index.search_repos."""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from core import index
from core.commands import search as cmd_search


def _R(path: str) -> str:
    """Match what core.index._normalize_path does to a path."""
    return os.path.realpath(os.path.expanduser(path))


class _IndexCase(unittest.TestCase):
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

    def _seed(
        self,
        path: str,
        *,
        remote_url: str | None = None,
        source: str | None = None,
        tags: list[str] | None = None,
        notes: list[str] | None = None,
        description: str | None = None,
    ) -> int:
        with index.connect(self.db) as conn:
            rid = index.add_repo(
                conn, path,
                remote_url=remote_url, source=source, tags=tags or [],
            )
            for body in notes or []:
                index.add_note(conn, rid, body)
            if description is not None:
                index.upsert_upstream_meta(conn, rid, {
                    "provider": "github", "host": "github.com", "owner": "o",
                    "name": os.path.basename(path),
                    "description": description,
                })
        return rid


class TestSearchRepos(_IndexCase):
    def test_matches_path(self):
        self._seed("/t/nuclei-scanner")
        self._seed("/t/something-else")
        with index.connect(self.db) as conn:
            rows = index.search_repos(conn, "nuclei")
        self.assertEqual([r["path"] for r in rows], [_R("/t/nuclei-scanner")])

    def test_matches_remote_url(self):
        self._seed("/t/a", remote_url="git@github.com:projectdiscovery/nuclei.git")
        self._seed("/t/b", remote_url="git@github.com:other/thing.git")
        with index.connect(self.db) as conn:
            rows = index.search_repos(conn, "projectdiscovery")
        self.assertEqual([r["path"] for r in rows], [_R("/t/a")])

    def test_matches_tag_name(self):
        self._seed("/t/a", tags=["xss", "csrf"])
        self._seed("/t/b", tags=["recon"])
        with index.connect(self.db) as conn:
            rows = index.search_repos(conn, "csrf")
        self.assertEqual([r["path"] for r in rows], [_R("/t/a")])

    def test_matches_note_body(self):
        self._seed("/t/a", notes=["found CSRF bypass on the staging endpoint"])
        self._seed("/t/b", notes=["just a recon tool"])
        with index.connect(self.db) as conn:
            rows = index.search_repos(conn, "bypass")
        self.assertEqual([r["path"] for r in rows], [_R("/t/a")])

    def test_matches_upstream_description(self):
        self._seed("/t/a", description="Fast XSS exploitation framework")
        self._seed("/t/b", description="Subdomain enumerator")
        with index.connect(self.db) as conn:
            rows = index.search_repos(conn, "xss")
        self.assertEqual([r["path"] for r in rows], [_R("/t/a")])

    def test_matches_source(self):
        self._seed("/t/a", source="blog:orange.tw 2026-04")
        self._seed("/t/b", source="colleague:alice")
        with index.connect(self.db) as conn:
            rows = index.search_repos(conn, "orange.tw")
        self.assertEqual([r["path"] for r in rows], [_R("/t/a")])

    def test_case_insensitive(self):
        self._seed("/t/MixedCase")
        with index.connect(self.db) as conn:
            self.assertEqual(len(index.search_repos(conn, "mixedcase")), 1)
            self.assertEqual(len(index.search_repos(conn, "MIXEDCASE")), 1)

    def test_no_match_returns_empty(self):
        self._seed("/t/a")
        with index.connect(self.db) as conn:
            self.assertEqual(index.search_repos(conn, "no-such-thing"), [])

    def test_empty_query_returns_empty(self):
        self._seed("/t/a")
        with index.connect(self.db) as conn:
            self.assertEqual(index.search_repos(conn, ""), [])
            self.assertEqual(index.search_repos(conn, "   "), [])

    def test_dedupes_repo_with_multiple_matches(self):
        # A repo whose path AND tag both match the query should still
        # come back once, not twice.
        self._seed("/t/csrf-tool", tags=["csrf"])
        with index.connect(self.db) as conn:
            rows = index.search_repos(conn, "csrf")
        self.assertEqual(len(rows), 1)

    def test_limit_caps_results(self):
        for i in range(5):
            self._seed(f"/t/recon-{i}", tags=["recon"])
        with index.connect(self.db) as conn:
            rows = index.search_repos(conn, "recon", limit=3)
        self.assertEqual(len(rows), 3)


class TestSearchCommand(_IndexCase):
    def _args(self, query, **overrides):
        base = {"query": query, "limit": None, "json": False}
        base.update(overrides)
        return argparse.Namespace(**base)

    def test_human_output(self):
        self._seed("/t/nuclei", tags=["scanner"])
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out, \
             mock.patch("sys.stderr", new_callable=io.StringIO):
            rc = cmd_search.run(self._args("nuclei"))
        self.assertEqual(rc, 0)
        text = out.getvalue()
        self.assertIn("nuclei", text)
        self.assertIn("scanner", text)

    def test_no_match_clean_message(self):
        with mock.patch("sys.stdout", new_callable=io.StringIO), \
             mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            rc = cmd_search.run(self._args("absent"))
        self.assertEqual(rc, 0)
        self.assertIn("no matches", err.getvalue())

    def test_json_shape(self):
        self._seed("/t/a", tags=["x"])
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out, \
             mock.patch("sys.stderr", new_callable=io.StringIO):
            cmd_search.run(self._args("a", json=True))
        data = json.loads(out.getvalue())
        self.assertEqual(data["query"], "a")
        self.assertEqual(data["total"], 1)
        self.assertEqual(len(data["repositories"]), 1)


if __name__ == "__main__":
    unittest.main()
