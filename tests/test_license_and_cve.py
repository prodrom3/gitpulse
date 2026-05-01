"""Tests for the 1.6.0 DevSecOps batch:

- `nostos list --license / --license-not / --upstream-cve / --upstream-severity`
- `core.upstream.fetch_repo_advisories`
- index schema v3 migration / list_repos license + CVE filters
- thread-safety of `core.index.connect()` under concurrent workers
"""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import tempfile
import threading
import unittest
import urllib.error
from unittest import mock

from core import index
from core.commands import list_cmd as cmd_list
from core.upstream import (
    ProbeHTTPError,
    fetch_repo_advisories,
)

# ---------- list --license / --license-not ----------


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

    def _seed_repo(self, path: str, *, license: str | None = None, cves: tuple[int, str | None] | None = None):
        with index.connect(self.db) as conn:
            rid = index.add_repo(conn, path, remote_url=f"git@github.com:o/{os.path.basename(path)}.git")
            meta: dict = {
                "provider": "github", "host": "github.com", "owner": "o",
                "name": os.path.basename(path),
            }
            if license is not None:
                meta["license"] = license
            if cves is not None:
                meta["cve_count"] = cves[0]
                meta["cve_top_severity"] = cves[1]
            if license is not None or cves is not None:
                index.upsert_upstream_meta(conn, rid, meta)
        return rid


class TestLicenseFilter(_IndexCase):
    def test_includes_only_matching_licenses(self):
        self._seed_repo("/t/a", license="MIT")
        self._seed_repo("/t/b", license="Apache-2.0")
        self._seed_repo("/t/c", license="GPL-3.0")
        with index.connect(self.db) as conn:
            rows = index.list_repos(conn, licenses=["MIT", "Apache-2.0"])
        self.assertEqual(
            sorted(os.path.basename(r["path"]) for r in rows),
            ["a", "b"],
        )

    def test_case_insensitive(self):
        self._seed_repo("/t/a", license="MIT")
        with index.connect(self.db) as conn:
            rows = index.list_repos(conn, licenses=["mit"])
        self.assertEqual(len(rows), 1)

    def test_excludes_unrecorded_licenses(self):
        self._seed_repo("/t/no-meta")  # no upstream_meta at all
        self._seed_repo("/t/no-license", license=None)  # meta but license=None
        self._seed_repo("/t/has", license="MIT")
        with index.connect(self.db) as conn:
            rows = index.list_repos(conn, licenses=["MIT"])
        self.assertEqual(
            [os.path.basename(r["path"]) for r in rows],
            ["has"],
        )


class TestLicenseNotFilter(_IndexCase):
    def test_excludes_matching_licenses(self):
        self._seed_repo("/t/a", license="MIT")
        self._seed_repo("/t/b", license="GPL-3.0")
        with index.connect(self.db) as conn:
            rows = index.list_repos(conn, licenses_not=["GPL-3.0"])
        self.assertEqual(
            [os.path.basename(r["path"]) for r in rows],
            ["a"],
        )

    def test_keeps_unrecorded_licenses(self):
        # We don't know unrecorded ones are GPL, so they pass the filter.
        self._seed_repo("/t/a")  # no meta
        self._seed_repo("/t/b", license="GPL-3.0")
        with index.connect(self.db) as conn:
            rows = index.list_repos(conn, licenses_not=["GPL-3.0"])
        self.assertEqual(
            [os.path.basename(r["path"]) for r in rows],
            ["a"],
        )


# ---------- list --upstream-cve / --upstream-severity ----------


class TestCveFilter(_IndexCase):
    def test_upstream_cve_filters_to_advisory_repos(self):
        self._seed_repo("/t/clean", cves=(0, None))
        self._seed_repo("/t/has", cves=(2, "high"))
        self._seed_repo("/t/never-fetched")  # cve_count IS NULL
        with index.connect(self.db) as conn:
            rows = index.list_repos(conn, upstream_cve=True)
        self.assertEqual(
            [os.path.basename(r["path"]) for r in rows],
            ["has"],
        )

    def test_severity_threshold_includes_at_or_above(self):
        self._seed_repo("/t/low", cves=(1, "low"))
        self._seed_repo("/t/medium", cves=(1, "medium"))
        self._seed_repo("/t/high", cves=(1, "high"))
        self._seed_repo("/t/critical", cves=(1, "critical"))
        with index.connect(self.db) as conn:
            rows = index.list_repos(conn, upstream_severity="high")
        self.assertEqual(
            sorted(os.path.basename(r["path"]) for r in rows),
            ["critical", "high"],
        )

    def test_severity_invalid_raises(self):
        with self.assertRaises(ValueError):
            with index.connect(self.db) as conn:
                index.list_repos(conn, upstream_severity="nope")


# ---------- fetch_repo_advisories ----------


class _Resp:
    def __init__(self, body, headers=None):
        self._body = body if isinstance(body, bytes) else body.encode("utf-8")
        self.headers = headers or {}

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _ok(json_body, headers=None):
    import json as _j
    return _Resp(_j.dumps(json_body), headers=headers or {})


class TestFetchRepoAdvisories(unittest.TestCase):
    def test_open_advisories_counted(self):
        body = [
            {"state": "published", "severity": "high"},
            {"state": "published", "severity": "critical"},
            {"state": "closed", "severity": "high"},  # excluded
            {"state": "withdrawn", "severity": "high"},  # excluded
        ]

        def fake(req, timeout=None):
            return _ok(body if "page=1" in req.full_url else [])

        with mock.patch("urllib.request.urlopen", side_effect=fake):
            count, top = fetch_repo_advisories("github.com", "o", "r", token=None)
        self.assertEqual(count, 2)
        self.assertEqual(top, "critical")

    def test_no_open_returns_zero_none(self):
        body = [{"state": "closed", "severity": "high"}]

        def fake(req, timeout=None):
            return _ok(body if "page=1" in req.full_url else [])

        with mock.patch("urllib.request.urlopen", side_effect=fake):
            count, top = fetch_repo_advisories("github.com", "o", "r", token=None)
        self.assertEqual((count, top), (0, None))

    def test_404_raises(self):
        def fake(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, io.BytesIO(b""))

        with mock.patch("urllib.request.urlopen", side_effect=fake):
            with self.assertRaises(ProbeHTTPError):
                fetch_repo_advisories("github.com", "o", "missing", token=None)

    def test_403_degrades_gracefully(self):
        # Rate-limited / endpoint disabled - don't mark the repo "vulnerable".
        def fake(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, io.BytesIO(b""))

        with mock.patch("urllib.request.urlopen", side_effect=fake):
            count, top = fetch_repo_advisories("github.com", "o", "r", token=None)
        self.assertEqual((count, top), (0, None))


# ---------- list_cmd CLI integration ----------


class TestListCommandFlags(_IndexCase):
    def _args(self, **overrides):
        base = {
            "tag": None, "status": None, "untouched_over": None,
            "attack": None,
            "upstream_archived": False, "upstream_dormant": None,
            "upstream_stale": None,
            "license": [], "license_not": [],
            "upstream_cve": False, "upstream_severity": None,
            "json": True,
        }
        base.update(overrides)
        return argparse.Namespace(**base)

    def test_license_flag_csv_split(self):
        self._seed_repo("/t/a", license="MIT")
        self._seed_repo("/t/b", license="GPL-3.0")
        self._seed_repo("/t/c", license="Apache-2.0")
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            cmd_list.run(self._args(license=["MIT,Apache-2.0"]))
        data = json.loads(out.getvalue())
        names = sorted(os.path.basename(r["path"]) for r in data["repositories"])
        self.assertEqual(names, ["a", "c"])

    def test_upstream_cve_flag(self):
        self._seed_repo("/t/clean", cves=(0, None))
        self._seed_repo("/t/has", cves=(3, "medium"))
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            cmd_list.run(self._args(upstream_cve=True))
        data = json.loads(out.getvalue())
        self.assertEqual([os.path.basename(r["path"]) for r in data["repositories"]], ["has"])


# ---------- thread-safety ----------


class TestConcurrentConnect(_IndexCase):
    def test_many_concurrent_connections_against_fresh_db(self):
        # Regression for the WAL / schema race that broke the parallel
        # `nostos add --from-owner --workers N` path: many threads
        # opening connect() simultaneously against a brand-new DB.
        N = 16
        errors: list[Exception] = []

        def open_close():
            try:
                with index.connect(self.db) as conn:
                    conn.execute("SELECT 1").fetchone()
            except Exception as e:  # pragma: no cover - failure means regression
                errors.append(e)

        threads = [threading.Thread(target=open_close) for _ in range(N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
