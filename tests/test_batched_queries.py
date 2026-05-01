"""Tests for the 1.6.3 batched-query refactor.

The hot loops (`list_repos`, `search_repos`, `doctor.run_checks`,
`portable._serialize_index`) used to do one SQL call per repo for
tags / notes / upstream_meta lookups. This module:

1. Verifies the new batched helpers in core.index produce the same
   per-repo data as the old per-repo helpers (output equivalence).
2. Verifies the helpers chunk correctly above the 500-id boundary.
3. Counts SQL queries during list / search / export to prove they
   are now O(1) per call rather than O(N).
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
import unittest
from unittest import mock

from core import index


class _IndexCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "index.db")
        self._patches = [
            mock.patch("core.index.index_db_path", return_value=self.db),
            mock.patch("core.index.ensure_data_dir", return_value=self.tmp),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestBatchedHelpersEquivalence(_IndexCase):
    """The batched helpers must produce identical per-repo data to
    the per-repo helpers they replace."""

    def _seed(self, n: int, *, tags_per_repo: int = 3, notes_per_repo: int = 2):
        with index.connect(self.db) as conn:
            ids = []
            for i in range(n):
                rid = index.add_repo(
                    conn, f"/t/r{i}",
                    remote_url=f"git@github.com:o/r{i}.git",
                    tags=[f"tag{j}" for j in range(tags_per_repo)] + [f"only-r{i}"],
                )
                ids.append(rid)
                for j in range(notes_per_repo):
                    index.add_note(conn, rid, f"note {j} for r{i}")
                index.upsert_upstream_meta(conn, rid, {
                    "provider": "github", "host": "github.com",
                    "owner": "o", "name": f"r{i}",
                    "stars": i * 10, "archived": False,
                })
        return ids

    def test_get_tags_for_repos_matches_per_repo(self):
        ids = self._seed(5)
        with index.connect(self.db) as conn:
            batched = index._get_tags_for_repos(conn, ids)
            for rid in ids:
                self.assertEqual(
                    batched[rid],
                    index._get_tags_for_repo(conn, rid),
                    f"mismatch for repo {rid}",
                )

    def test_get_tags_for_empty_input(self):
        with index.connect(self.db) as conn:
            self.assertEqual(index._get_tags_for_repos(conn, []), {})

    def test_get_tags_for_unknown_id_returns_empty_list(self):
        ids = self._seed(2)
        with index.connect(self.db) as conn:
            out = index._get_tags_for_repos(conn, ids + [99999])
        self.assertEqual(out[99999], [])

    def test_get_upstream_meta_batch_matches_per_repo(self):
        ids = self._seed(5)
        with index.connect(self.db) as conn:
            batched = index.get_upstream_meta_batch(conn, ids)
            for rid in ids:
                expected = index.get_upstream_meta(conn, rid)
                # Compare as dicts; sqlite3.Row -> dict conversion in
                # both paths produces equivalent content.
                self.assertEqual(batched[rid], expected, f"mismatch for repo {rid}")

    def test_get_upstream_meta_batch_returns_none_for_unfetched(self):
        with index.connect(self.db) as conn:
            rid = index.add_repo(conn, "/t/r")
            self.assertIsNone(index.get_upstream_meta_batch(conn, [rid])[rid])

    def test_get_notes_batch_matches_per_repo(self):
        ids = self._seed(4, notes_per_repo=3)
        with index.connect(self.db) as conn:
            batched = index.get_notes_batch(conn, ids)
            for rid in ids:
                expected = index.get_notes(conn, rid)
                self.assertEqual(
                    [n["body"] for n in batched[rid]],
                    [n["body"] for n in expected],
                    f"mismatch for repo {rid}",
                )


class TestBatchedHelpersChunking(_IndexCase):
    """SQLite default SQLITE_LIMIT_VARIABLE_NUMBER is 999. The batched
    helpers chunk at 500 to stay well under that even on older
    builds."""

    def test_chunked_yields_correct_partitions(self):
        items = list(range(1234))
        chunks = list(index._chunked(items, size=500))
        self.assertEqual(len(chunks), 3)
        self.assertEqual(len(chunks[0]), 500)
        self.assertEqual(len(chunks[1]), 500)
        self.assertEqual(len(chunks[2]), 234)
        # No item lost or duplicated
        flat = [x for c in chunks for x in c]
        self.assertEqual(flat, items)

    def test_get_tags_for_repos_handles_above_chunk_boundary(self):
        # Seed enough repos to require chunking.
        with index.connect(self.db) as conn:
            ids = []
            for i in range(750):
                rid = index.add_repo(conn, f"/t/r{i}", tags=[f"t{i % 7}"])
                ids.append(rid)
            batched = index._get_tags_for_repos(conn, ids)
        self.assertEqual(len(batched), 750)
        # Every repo got exactly one tag.
        self.assertTrue(all(len(v) == 1 for v in batched.values()))


class _CountingConnection:
    """Wraps a sqlite3.Connection and counts SQL executions matching a
    substring. Used to assert query counts in regression tests."""

    def __init__(self, conn: sqlite3.Connection, match: str):
        self._conn = conn
        self._match = match.lower()
        self.count = 0

    def execute(self, sql, params=()):
        if self._match in sql.lower():
            self.count += 1
        return self._conn.execute(sql, params)

    def __getattr__(self, name):
        return getattr(self._conn, name)


class TestQueryCountsAreO1(_IndexCase):
    """Regression tests: the 1.6.3 refactor cuts list_repos /
    search_repos / portable.export_index from O(N) tag/notes/upstream
    queries down to O(1). These tests fail if a future change
    accidentally reintroduces an N+1 loop."""

    def _seed_n(self, n: int):
        with index.connect(self.db) as conn:
            ids = []
            for i in range(n):
                rid = index.add_repo(conn, f"/t/r{i}", tags=[f"t{i}", "shared"])
                ids.append(rid)
                index.upsert_upstream_meta(conn, rid, {
                    "provider": "github", "host": "github.com",
                    "owner": "o", "name": f"r{i}",
                })
        return ids

    def test_list_repos_uses_one_tag_query(self):
        self._seed_n(20)
        with index.connect(self.db) as conn:
            wrapper = _CountingConnection(conn, "from tags")
            index.list_repos(wrapper)
        # One batched tag query (not 20 per-repo queries).
        self.assertEqual(wrapper.count, 1)

    def test_search_repos_uses_one_tag_query(self):
        self._seed_n(20)
        with index.connect(self.db) as conn:
            wrapper = _CountingConnection(conn, "from tags")
            index.search_repos(wrapper, "shared")
        self.assertEqual(wrapper.count, 1)


class TestExportBatchedQueries(_IndexCase):
    """The portable export path used to call get_notes() and
    get_upstream_meta() once per repo - 2N queries on top of the
    list_repos call. Now it does 2 batched queries total."""

    def test_export_uses_one_notes_query_and_one_upstream_query(self):
        from core import portable

        with index.connect(self.db) as conn:
            for i in range(15):
                rid = index.add_repo(
                    conn, f"/t/r{i}",
                    remote_url=f"git@github.com:o/r{i}.git",
                )
                index.add_note(conn, rid, f"note for r{i}")
                index.upsert_upstream_meta(conn, rid, {
                    "provider": "github", "host": "github.com",
                    "owner": "o", "name": f"r{i}",
                })

        with index.connect(self.db) as conn:
            wrapper = _CountingConnection(conn, "from notes")
            portable.build_bundle(wrapper, nostos_version="test", redact=False)
        self.assertEqual(wrapper.count, 1)

        with index.connect(self.db) as conn:
            wrapper = _CountingConnection(conn, "from upstream_meta")
            portable.build_bundle(wrapper, nostos_version="test", redact=False)
        self.assertEqual(wrapper.count, 1)


if __name__ == "__main__":
    unittest.main()
