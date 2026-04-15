"""Tests for core.portable (export bundle + import applier) and the
export / import subcommands end-to-end."""

import argparse
import io
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from core import index, portable
from core.commands import export_cmd as cmd_export
from core.commands import import_cmd as cmd_import


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


class TestBuildBundle(_IndexTestCase):
    def _seed(self, conn):
        a = index.add_repo(
            conn,
            "/tmp/a",
            remote_url="git@github.com:o/a.git",
            source="colleague",
            status="in-use",
            tags=["c2"],
            note="first note",
        )
        index.upsert_upstream_meta(
            conn, a,
            {"provider": "github", "host": "github.com", "owner": "o",
             "name": "a", "stars": 10, "archived": False},
        )
        index.add_repo(conn, "/tmp/b", status="flagged")
        return a

    def test_schema_and_envelope(self):
        with index.connect(self.db) as conn:
            self._seed(conn)
            bundle = portable.build_bundle(conn, gitpulse_version="2.4.0")
        self.assertEqual(bundle["schema"], portable.CURRENT_EXPORT_SCHEMA)
        self.assertEqual(bundle["gitpulse_version"], "2.4.0")
        self.assertFalse(bundle["redacted"])
        self.assertIsInstance(bundle["repos"], list)
        self.assertEqual(len(bundle["repos"]), 2)

    def test_bundle_carries_full_repo_detail(self):
        with index.connect(self.db) as conn:
            self._seed(conn)
            bundle = portable.build_bundle(conn)
        paths = [r["path"] for r in bundle["repos"]]
        self.assertIn(_R("/tmp/a"), paths)
        a = next(r for r in bundle["repos"] if r["path"] == _R("/tmp/a"))
        self.assertEqual(a["remote_url"], "git@github.com:o/a.git")
        self.assertEqual(a["status"], "in-use")
        self.assertEqual(a["tags"], ["c2"])
        self.assertEqual(len(a["notes"]), 1)
        self.assertEqual(a["notes"][0]["body"], "first note")
        self.assertIsNotNone(a["upstream"])
        self.assertEqual(a["upstream"]["stars"], 10)
        self.assertNotIn("repo_id", a["upstream"])

    def test_redact_strips_sensitive_fields(self):
        with index.connect(self.db) as conn:
            self._seed(conn)
            bundle = portable.build_bundle(conn, redact=True)
        self.assertTrue(bundle["redacted"])
        a = next(r for r in bundle["repos"] if r["path"] == _R("/tmp/a"))
        self.assertIsNone(a["remote_url"])
        self.assertIsNone(a["source"])
        self.assertEqual(a["notes"], [])
        # Tags, status, upstream are retained
        self.assertEqual(a["tags"], ["c2"])
        self.assertIsNotNone(a["upstream"])


class TestRemap(unittest.TestCase):
    def test_exact_prefix_swap(self):
        self.assertEqual(
            portable._apply_remaps("/home/alice/tools/r", [("/home/alice", "/home/bob")]),
            "/home/bob/tools/r",
        )

    def test_unrelated_path_unchanged(self):
        self.assertEqual(
            portable._apply_remaps("/opt/x", [("/home/alice", "/home/bob")]),
            "/opt/x",
        )

    def test_first_matching_wins(self):
        remaps = [("/a", "/A"), ("/a/b", "/X")]
        self.assertEqual(portable._apply_remaps("/a/b/c", remaps), "/A/b/c")

    def test_trailing_slash_tolerated(self):
        self.assertEqual(
            portable._apply_remaps(
                "/a/b",
                [("/a/", "/X")],
            ),
            "/X/b",
        )

    def test_exact_match(self):
        self.assertEqual(
            portable._apply_remaps("/a", [("/a", "/b")]),
            "/b",
        )

    def test_accepts_backslash_separator(self):
        # A bundle made on Windows carries backslashed paths; the remap
        # match must still work if the operator passes the src as the
        # Windows-style path.
        self.assertEqual(
            portable._apply_remaps(
                r"C:\Users\alice\tools\r",
                [(r"C:\Users\alice", r"D:\bob")],
            ),
            r"D:\bob\tools\r",
        )


class TestParseRemap(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(portable.parse_remap("/a:/b"), ("/a", "/b"))

    def test_empty_side_rejected(self):
        with self.assertRaises(portable.BundleError):
            portable.parse_remap("/a:")
        with self.assertRaises(portable.BundleError):
            portable.parse_remap(":/b")

    def test_missing_colon_rejected(self):
        with self.assertRaises(portable.BundleError):
            portable.parse_remap("/a")


class TestValidateBundle(unittest.TestCase):
    def test_rejects_non_object(self):
        with self.assertRaises(portable.BundleError):
            portable.validate_bundle([])  # type: ignore[arg-type]

    def test_rejects_wrong_schema(self):
        with self.assertRaises(portable.BundleError):
            portable.validate_bundle({"schema": 99, "repos": []})

    def test_rejects_missing_schema(self):
        with self.assertRaises(portable.BundleError):
            portable.validate_bundle({"repos": []})

    def test_rejects_repos_not_list(self):
        with self.assertRaises(portable.BundleError):
            portable.validate_bundle({"schema": 1, "repos": "nope"})

    def test_accepts_minimal_valid(self):
        portable.validate_bundle({"schema": 1, "repos": []})


class TestImportBundle(_IndexTestCase):
    def _round_trip(self, conn_exp, **build_kwargs):
        return portable.build_bundle(conn_exp, **build_kwargs)

    def test_merge_adds_missing_repos(self):
        # Source DB: one repo
        with index.connect(self.db) as conn:
            index.add_repo(conn, "/tmp/src", tags=["c2"], note="hi")
            bundle = portable.build_bundle(conn)
        # Fresh DB
        other_db = os.path.join(self.tmp, "other.db")
        with index.connect(other_db) as conn:
            stats = portable.import_bundle(conn, bundle, mode="merge")
            repos = index.list_repos(conn)
        self.assertEqual(stats["added"], 1)
        self.assertEqual(stats["already_present"], 0)
        self.assertEqual(len(repos), 1)
        self.assertEqual(sorted(repos[0]["tags"]), ["c2"])
        with index.connect(other_db) as conn:
            notes = index.get_notes(conn, repos[0]["id"])
        self.assertEqual(len(notes), 1)

    def test_merge_leaves_existing_status_alone(self):
        # Build a bundle with status=flagged, then import into a DB
        # that already has the same path with status=in-use.
        with index.connect(self.db) as conn:
            index.add_repo(conn, "/tmp/x", status="flagged")
            bundle = portable.build_bundle(conn)
        other_db = os.path.join(self.tmp, "other.db")
        with index.connect(other_db) as conn:
            index.add_repo(conn, "/tmp/x", status="in-use")
            portable.import_bundle(conn, bundle, mode="merge")
            repo = index.get_repo(conn, "/tmp/x")
        self.assertEqual(repo["status"], "in-use")  # local wins

    def test_replace_wipes_existing(self):
        # Source: one repo; Local: two repos; replace should end with one.
        with index.connect(self.db) as conn:
            index.add_repo(conn, "/tmp/keep")
            bundle = portable.build_bundle(conn)
        other_db = os.path.join(self.tmp, "other.db")
        with index.connect(other_db) as conn:
            index.add_repo(conn, "/tmp/old1")
            index.add_repo(conn, "/tmp/old2")
            portable.import_bundle(conn, bundle, mode="replace")
            repos = index.list_repos(conn)
        paths = {r["path"] for r in repos}
        self.assertEqual(paths, {_R("/tmp/keep")})

    def test_remap_rewrites_paths(self):
        # Use canonical (realpath'd) tmp roots so the remap source prefix
        # matches what add_repo actually stores. Using '/home/...' breaks
        # on macOS (/home -> /System/Volumes/Data/home) and on Windows
        # (POSIX-style paths get resolved to a drive root).
        alice_root = os.path.realpath(os.path.join(self.tmp, "alice-root"))
        bob_root = os.path.realpath(os.path.join(self.tmp, "bob-root"))
        alice_path = os.path.join(alice_root, "tools", "r")
        expected = os.path.join(bob_root, "tools", "r")

        with index.connect(self.db) as conn:
            index.add_repo(conn, alice_path)
            bundle = portable.build_bundle(conn)
        other_db = os.path.join(self.tmp, "other.db")
        with index.connect(other_db) as conn:
            portable.import_bundle(
                conn,
                bundle,
                mode="merge",
                remaps=[(alice_root, bob_root)],
            )
            repos = index.list_repos(conn)
        self.assertEqual(len(repos), 1)
        self.assertEqual(repos[0]["path"], expected)

    def test_dry_run_does_not_write(self):
        with index.connect(self.db) as conn:
            index.add_repo(conn, "/tmp/a")
            bundle = portable.build_bundle(conn)
        other_db = os.path.join(self.tmp, "other.db")
        with index.connect(other_db) as conn:
            stats = portable.import_bundle(conn, bundle, mode="merge", dry_run=True)
            repos = index.list_repos(conn)
        self.assertEqual(stats["added"], 1)
        self.assertEqual(repos, [])

    def test_invalid_mode_raises(self):
        with self.assertRaises(portable.BundleError):
            portable.import_bundle(
                mock.MagicMock(), {"schema": 1, "repos": []}, mode="nuke"
            )

    def test_upstream_meta_round_trips(self):
        with index.connect(self.db) as conn:
            rid = index.add_repo(conn, "/tmp/x")
            index.upsert_upstream_meta(
                conn, rid,
                {"provider": "github", "host": "github.com", "owner": "o",
                 "name": "x", "stars": 42, "archived": True},
            )
            bundle = portable.build_bundle(conn)
        other_db = os.path.join(self.tmp, "other.db")
        with index.connect(other_db) as conn:
            portable.import_bundle(conn, bundle, mode="merge")
            meta = index.get_upstream_meta(conn, "/tmp/x")
        self.assertIsNotNone(meta)
        self.assertEqual(meta["stars"], 42)
        self.assertEqual(meta["archived"], 1)


class TestExportCommand(_IndexTestCase):
    def _args(self, **overrides):
        base = {"out": "-", "redact": False, "pretty": False}
        base.update(overrides)
        return argparse.Namespace(**base)

    def test_stdout_emits_valid_json(self):
        with index.connect(self.db) as conn:
            index.add_repo(conn, "/tmp/a", tags=["c2"])
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            rc = cmd_export.run(self._args())
        self.assertEqual(rc, 0)
        data = json.loads(out.getvalue())
        self.assertEqual(data["schema"], 1)
        self.assertEqual(len(data["repos"]), 1)

    def test_out_file_writes(self):
        out_path = os.path.join(self.tmp, "bundle.json")
        with index.connect(self.db) as conn:
            index.add_repo(conn, "/tmp/a")
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            rc = cmd_export.run(self._args(out=out_path))
        self.assertEqual(rc, 0)
        with open(out_path) as f:
            data = json.load(f)
        self.assertEqual(len(data["repos"]), 1)

    def test_redact_flag_honoured(self):
        with index.connect(self.db) as conn:
            index.add_repo(conn, "/tmp/a", remote_url="x", note="secret")
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            cmd_export.run(self._args(redact=True))
        data = json.loads(out.getvalue())
        self.assertTrue(data["redacted"])
        self.assertIsNone(data["repos"][0]["remote_url"])
        self.assertEqual(data["repos"][0]["notes"], [])


class TestImportCommand(_IndexTestCase):
    def _make_bundle_file(self, repos=None):
        bundle = {
            "schema": 1,
            "exported_at": "2026-04-15T00:00:00+00:00",
            "gitpulse_version": "2.4.0",
            "redacted": False,
            "repos": repos or [
                {
                    "path": "/tmp/i",
                    "remote_url": None,
                    "source": None,
                    "status": "new",
                    "quiet": False,
                    "added_at": "2026-04-15T00:00:00+00:00",
                    "last_touched_at": None,
                    "tags": ["foo"],
                    "notes": [],
                    "upstream": None,
                }
            ],
        }
        path = os.path.join(self.tmp, "bundle.json")
        with open(path, "w") as f:
            json.dump(bundle, f)
        return path

    def _args(self, bundle_path, **overrides):
        base = {
            "bundle": bundle_path,
            "mode": "merge",
            "remap": [],
            "dry_run": False,
            "yes": False,
            "json": False,
        }
        base.update(overrides)
        return argparse.Namespace(**base)

    def test_merge_happy_path(self):
        path = self._make_bundle_file()
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            rc = cmd_import.run(self._args(path))
        self.assertEqual(rc, 0)
        with index.connect(self.db) as conn:
            repos = index.list_repos(conn)
        self.assertEqual(len(repos), 1)

    def test_invalid_json_errors(self):
        bad = os.path.join(self.tmp, "bad.json")
        with open(bad, "w") as f:
            f.write("not json")
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            rc = cmd_import.run(self._args(bad))
        self.assertEqual(rc, 1)

    def test_wrong_schema_errors(self):
        path = os.path.join(self.tmp, "bad.json")
        with open(path, "w") as f:
            json.dump({"schema": 999, "repos": []}, f)
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            rc = cmd_import.run(self._args(path))
        self.assertEqual(rc, 1)

    def test_replace_without_yes_aborts(self):
        path = self._make_bundle_file()
        with mock.patch("builtins.input", return_value=""), mock.patch(
            "sys.stderr", new_callable=io.StringIO
        ):
            rc = cmd_import.run(self._args(path, mode="replace"))
        # Aborted; empty stdin means "n"
        self.assertEqual(rc, 1)

    def test_replace_with_yes_proceeds(self):
        path = self._make_bundle_file()
        with index.connect(self.db) as conn:
            index.add_repo(conn, "/tmp/existing")
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            rc = cmd_import.run(self._args(path, mode="replace", yes=True))
        self.assertEqual(rc, 0)
        with index.connect(self.db) as conn:
            repos = index.list_repos(conn)
        paths = {r["path"] for r in repos}
        self.assertNotIn(_R("/tmp/existing"), paths)
        self.assertIn(_R("/tmp/i"), paths)

    def test_remap_through_cli(self):
        path = self._make_bundle_file(
            repos=[
                {
                    "path": "/alice/tools/r",
                    "remote_url": None,
                    "source": None,
                    "status": "new",
                    "quiet": False,
                    "added_at": "2026-04-15T00:00:00+00:00",
                    "last_touched_at": None,
                    "tags": [],
                    "notes": [],
                    "upstream": None,
                }
            ]
        )
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            rc = cmd_import.run(
                self._args(path, remap=["/alice:/bob"]),
            )
        self.assertEqual(rc, 0)
        with index.connect(self.db) as conn:
            repos = index.list_repos(conn)
        self.assertEqual(repos[0]["path"], _R("/bob/tools/r"))

    def test_stdin_bundle(self):
        bundle = {
            "schema": 1,
            "exported_at": "2026-04-15T00:00:00+00:00",
            "gitpulse_version": "2.4.0",
            "redacted": False,
            "repos": [{
                "path": "/tmp/stdin",
                "remote_url": None, "source": None, "status": "new",
                "quiet": False, "added_at": "2026-04-15T00:00:00+00:00",
                "last_touched_at": None, "tags": [], "notes": [], "upstream": None,
            }],
        }
        with mock.patch("sys.stdin", io.StringIO(json.dumps(bundle))), mock.patch(
            "sys.stderr", new_callable=io.StringIO
        ):
            rc = cmd_import.run(self._args("-"))
        self.assertEqual(rc, 0)

    def test_json_summary_output(self):
        path = self._make_bundle_file()
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out, mock.patch(
            "sys.stderr", new_callable=io.StringIO
        ):
            cmd_import.run(self._args(path, json=True))
        data = json.loads(out.getvalue())
        self.assertEqual(data["mode"], "merge")
        self.assertIn("added", data)


if __name__ == "__main__":
    unittest.main()
