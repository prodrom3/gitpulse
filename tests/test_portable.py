"""Tests for core.portable (export bundle + import applier) and the
export / import subcommands end-to-end.

Covers:
- schema 2 roundtrip and schema 1 forward-compat on import
- path resolution: absolute path, relative-to-home, --remap, clone
- --no-clone metadata-only mode
- plan_import as a pure dry-run builder
"""

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

    def test_schema_is_2(self):
        with index.connect(self.db) as conn:
            self._seed(conn)
            bundle = portable.build_bundle(conn, nostos_version="1.1.0")
        self.assertEqual(bundle["schema"], 2)
        self.assertEqual(bundle["nostos_version"], "1.1.0")
        self.assertFalse(bundle["redacted"])
        self.assertIsInstance(bundle["repos"], list)
        self.assertEqual(len(bundle["repos"]), 2)

    def test_envelope_has_source_host_and_platform(self):
        with index.connect(self.db) as conn:
            self._seed(conn)
            bundle = portable.build_bundle(conn)
        self.assertIn("source_host", bundle)
        self.assertIn("source_platform", bundle)
        self.assertIsInstance(bundle["source_platform"], str)

    def test_entry_has_new_fields(self):
        with index.connect(self.db) as conn:
            self._seed(conn)
            bundle = portable.build_bundle(conn)
        a = next(r for r in bundle["repos"] if r["path"] == _R("/tmp/a"))
        self.assertIn("path_relative_to_home", a)
        self.assertIn("local_name", a)
        self.assertEqual(a["local_name"], "a")

    def test_path_relative_to_home_is_none_when_not_under_home(self):
        with index.connect(self.db) as conn:
            self._seed(conn)
            bundle = portable.build_bundle(conn)
        a = next(r for r in bundle["repos"] if r["path"] == _R("/tmp/a"))
        # /tmp is not under $HOME on any platform we support.
        self.assertIsNone(a["path_relative_to_home"])

    def test_path_relative_to_home_populated_when_under_home(self):
        # Create a fake repo under the real $HOME, add it, check the field.
        home = os.path.realpath(os.path.expanduser("~"))
        sub = os.path.join(home, ".nostos-test-scratch-portable")
        os.makedirs(sub, exist_ok=True)
        try:
            with index.connect(self.db) as conn:
                index.add_repo(conn, sub)
                bundle = portable.build_bundle(conn)
            entry = next(r for r in bundle["repos"] if r["path"] == _R(sub))
            self.assertEqual(entry["path_relative_to_home"], ".nostos-test-scratch-portable")
        finally:
            shutil.rmtree(sub, ignore_errors=True)

    def test_bundle_carries_full_repo_detail(self):
        with index.connect(self.db) as conn:
            self._seed(conn)
            bundle = portable.build_bundle(conn)
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
        self.assertEqual(a["tags"], ["c2"])
        self.assertIsNotNone(a["upstream"])
        # local_name survives redaction because it's a clone hint, not secret
        self.assertEqual(a["local_name"], "a")


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
            portable._apply_remaps("/a/b", [("/a/", "/X")]),
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
            portable.validate_bundle({"schema": 2, "repos": "nope"})

    def test_accepts_schema_1(self):
        portable.validate_bundle({"schema": 1, "repos": []})

    def test_accepts_schema_2(self):
        portable.validate_bundle({"schema": 2, "repos": []})


class TestResolveEntryPath(_IndexTestCase):
    def test_path_match_when_git_exists(self):
        # Create a real repo on disk; resolver should prefer it
        repo = os.path.join(self.tmp, "r")
        os.makedirs(os.path.join(repo, ".git"), exist_ok=True)
        entry = {"path": repo}
        path, how = portable.resolve_entry_path(entry, remaps=[])
        self.assertEqual(how, "path_match")
        self.assertEqual(path, _R(repo))

    def test_remap_beats_original_path(self):
        repo = os.path.join(self.tmp, "new")
        os.makedirs(os.path.join(repo, ".git"), exist_ok=True)
        entry = {"path": os.path.join(self.tmp, "old")}
        path, how = portable.resolve_entry_path(
            entry,
            remaps=[(os.path.join(self.tmp, "old"), repo)],
        )
        self.assertEqual(how, "path_match")
        self.assertEqual(path, _R(repo))

    def test_home_relative_fallback(self):
        # Create a repo under the real $HOME so relative_to_home resolves
        home = os.path.realpath(os.path.expanduser("~"))
        sub = os.path.join(home, ".nostos-test-scratch-resolve")
        os.makedirs(os.path.join(sub, ".git"), exist_ok=True)
        try:
            entry = {
                "path": "/some/path/that/does/not/exist/anywhere",
                "path_relative_to_home": ".nostos-test-scratch-resolve",
            }
            path, how = portable.resolve_entry_path(entry, remaps=[])
            self.assertEqual(how, "home_relative")
            self.assertEqual(path, _R(sub))
        finally:
            shutil.rmtree(sub, ignore_errors=True)

    def test_unresolved_when_nothing_matches(self):
        entry = {"path": "/absolutely/not/there"}
        path, how = portable.resolve_entry_path(entry, remaps=[])
        self.assertEqual(how, "unresolved")


class TestPlanImport(_IndexTestCase):
    def _bundle_with(self, repos):
        return {"schema": 2, "repos": repos}

    def test_existing_repo_produces_register_action(self):
        repo = os.path.join(self.tmp, "r")
        os.makedirs(os.path.join(repo, ".git"), exist_ok=True)
        b = self._bundle_with([{"path": repo, "remote_url": "https://x"}])
        plan = portable.plan_import(b, remaps=[], clone_missing=True, clone_dir=None)
        self.assertEqual(len(plan), 1)
        self.assertEqual(plan[0]["action"], "register")
        self.assertEqual(plan[0]["reason"], "path_match")

    def test_missing_repo_with_url_produces_clone_action(self):
        b = self._bundle_with([
            {
                "path": "/gone",
                "remote_url": "https://github.com/user/thing.git",
                "local_name": "thing",
            }
        ])
        clone_dir = os.path.join(self.tmp, "clones")
        plan = portable.plan_import(
            b, remaps=[], clone_missing=True, clone_dir=clone_dir
        )
        self.assertEqual(plan[0]["action"], "clone_then_register")
        self.assertEqual(plan[0]["path"], os.path.join(clone_dir, "thing"))

    def test_no_clone_registers_with_placeholder_path(self):
        b = self._bundle_with([
            {"path": "/gone", "remote_url": "https://x"}
        ])
        plan = portable.plan_import(
            b, remaps=[], clone_missing=False, clone_dir=None
        )
        self.assertEqual(plan[0]["action"], "register")
        self.assertIn(plan[0]["reason"], {"no_clone", "no_remote_no_clone"})

    def test_no_remote_no_path_skips(self):
        b = self._bundle_with([{"path": "/gone", "remote_url": None}])
        plan = portable.plan_import(
            b, remaps=[], clone_missing=True, clone_dir=None
        )
        self.assertEqual(plan[0]["action"], "skip")


class TestImportBundle(_IndexTestCase):
    def test_merge_adds_missing_repos(self):
        with index.connect(self.db) as conn:
            index.add_repo(conn, "/tmp/src", tags=["c2"], note="hi")
            bundle = portable.build_bundle(conn)
        other_db = os.path.join(self.tmp, "other.db")
        with index.connect(other_db) as conn:
            stats = portable.import_bundle(
                conn, bundle, mode="merge", clone_missing=False
            )
            repos = index.list_repos(conn)
        self.assertEqual(stats["added"], 1)
        self.assertEqual(stats["already_present"], 0)
        self.assertEqual(len(repos), 1)
        self.assertEqual(sorted(repos[0]["tags"]), ["c2"])
        with index.connect(other_db) as conn:
            notes = index.get_notes(conn, repos[0]["id"])
        self.assertEqual(len(notes), 1)

    def test_merge_leaves_existing_status_alone(self):
        with index.connect(self.db) as conn:
            index.add_repo(conn, "/tmp/x", status="flagged")
            bundle = portable.build_bundle(conn)
        other_db = os.path.join(self.tmp, "other.db")
        with index.connect(other_db) as conn:
            index.add_repo(conn, "/tmp/x", status="in-use")
            portable.import_bundle(conn, bundle, mode="merge", clone_missing=False)
            repo = index.get_repo(conn, "/tmp/x")
        self.assertEqual(repo["status"], "in-use")

    def test_replace_wipes_existing(self):
        with index.connect(self.db) as conn:
            index.add_repo(conn, "/tmp/keep")
            bundle = portable.build_bundle(conn)
        other_db = os.path.join(self.tmp, "other.db")
        with index.connect(other_db) as conn:
            index.add_repo(conn, "/tmp/old1")
            index.add_repo(conn, "/tmp/old2")
            portable.import_bundle(
                conn, bundle, mode="replace", clone_missing=False
            )
            repos = index.list_repos(conn)
        paths = {r["path"] for r in repos}
        self.assertEqual(paths, {_R("/tmp/keep")})

    def test_remap_rewrites_paths(self):
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
                conn, bundle, mode="merge",
                remaps=[(alice_root, bob_root)],
                clone_missing=False,
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
            portable.import_bundle(
                conn, bundle, mode="merge",
                dry_run=True, clone_missing=False,
            )
            repos = index.list_repos(conn)
        # Either counted as "added" (if the path doesn't exist locally and
        # we fell through to no-clone registration) or "skipped". In either
        # case, no DB writes.
        self.assertEqual(repos, [])

    def test_invalid_mode_raises(self):
        with self.assertRaises(portable.BundleError):
            portable.import_bundle(
                mock.MagicMock(),
                {"schema": 2, "repos": []},
                mode="nuke",
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
            portable.import_bundle(
                conn, bundle, mode="merge", clone_missing=False
            )
            meta = index.get_upstream_meta(conn, "/tmp/x")
        self.assertIsNotNone(meta)
        self.assertEqual(meta["stars"], 42)
        self.assertEqual(meta["archived"], 1)

    def test_schema_1_bundle_still_imports(self):
        # Hand-craft a legacy schema-1 bundle (missing the v2 fields).
        legacy = {
            "schema": 1,
            "exported_at": "2026-04-15T00:00:00+00:00",
            "nostos_version": "1.0.0",
            "redacted": False,
            "repos": [
                {
                    "path": "/tmp/legacy",
                    "remote_url": None,
                    "source": None,
                    "status": "new",
                    "quiet": False,
                    "added_at": "2026-04-15T00:00:00+00:00",
                    "last_touched_at": None,
                    "tags": ["old"],
                    "notes": [],
                    "upstream": None,
                }
            ],
        }
        with index.connect(self.db) as conn:
            stats = portable.import_bundle(
                conn, legacy, mode="merge", clone_missing=False
            )
            repos = index.list_repos(conn)
        self.assertEqual(stats["added"], 1)
        self.assertEqual(len(repos), 1)
        self.assertEqual(sorted(repos[0]["tags"]), ["old"])

    def test_clone_on_import_calls_watchlist_clone(self):
        # Mock watchlist.clone_repo so we don't hit the network.
        target = os.path.join(self.tmp, "clones", "thing")

        def fake_clone(url, parent, timeout=120):
            os.makedirs(os.path.join(target, ".git"), exist_ok=True)
            return target

        with mock.patch("core.watchlist.clone_repo", side_effect=fake_clone):
            bundle = {
                "schema": 2,
                "repos": [
                    {
                        "path": "/does/not/exist",
                        "path_relative_to_home": None,
                        "local_name": "thing",
                        "remote_url": "https://github.com/user/thing.git",
                        "status": "new",
                    }
                ],
            }
            with index.connect(self.db) as conn:
                stats = portable.import_bundle(
                    conn, bundle, mode="merge",
                    clone_missing=True,
                    clone_dir=os.path.join(self.tmp, "clones"),
                )
                repos = index.list_repos(conn)
        self.assertEqual(stats["cloned"], 1)
        self.assertEqual(stats["clone_failed"], 0)
        self.assertEqual(len(repos), 1)
        self.assertEqual(repos[0]["path"], _R(target))

    def test_clone_failure_is_counted(self):
        with mock.patch("core.watchlist.clone_repo", return_value=None):
            bundle = {
                "schema": 2,
                "repos": [
                    {
                        "path": "/nowhere",
                        "remote_url": "https://example.invalid/nope.git",
                        "local_name": "nope",
                        "status": "new",
                    }
                ],
            }
            with index.connect(self.db) as conn:
                stats = portable.import_bundle(
                    conn, bundle, mode="merge",
                    clone_missing=True,
                    clone_dir=os.path.join(self.tmp, "clones"),
                )
                repos = index.list_repos(conn)
        self.assertEqual(stats["cloned"], 0)
        self.assertEqual(stats["clone_failed"], 1)
        self.assertEqual(repos, [])  # failed clone -> no DB write

    def test_no_clone_registers_metadata_only(self):
        bundle = {
            "schema": 2,
            "repos": [
                {
                    "path": "/not/there/yet",
                    "remote_url": "https://example.com/x.git",
                    "local_name": "x",
                    "status": "new",
                }
            ],
        }
        with index.connect(self.db) as conn:
            stats = portable.import_bundle(
                conn, bundle, mode="merge", clone_missing=False
            )
            repos = index.list_repos(conn)
        self.assertEqual(stats["added"], 1)
        self.assertEqual(stats["cloned"], 0)
        self.assertEqual(len(repos), 1)


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
        self.assertEqual(data["schema"], 2)
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
    def _make_bundle_file(self, repos=None, schema=2):
        bundle = {
            "schema": schema,
            "exported_at": "2026-04-15T00:00:00+00:00",
            "nostos_version": "1.1.0",
            "redacted": False,
            "repos": repos or [
                {
                    "path": "/tmp/i",
                    "path_relative_to_home": None,
                    "local_name": "i",
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
            "clone_dir": None,
            "no_clone": True,      # tests default to no-clone to stay offline
            "clone_workers": 4,
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
                    "path_relative_to_home": None,
                    "local_name": "r",
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
            "schema": 2,
            "exported_at": "2026-04-15T00:00:00+00:00",
            "nostos_version": "1.1.0",
            "redacted": False,
            "repos": [{
                "path": "/tmp/stdin",
                "path_relative_to_home": None,
                "local_name": "stdin",
                "remote_url": None,
                "source": None, "status": "new",
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
        self.assertIn("cloned", data)
        self.assertIn("clone_failed", data)

    def test_dry_run_prints_plan(self):
        path = self._make_bundle_file()
        with mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            rc = cmd_import.run(self._args(path, dry_run=True))
        self.assertEqual(rc, 0)
        out = err.getvalue()
        self.assertIn("Bundle: 1 repos", out)

    def test_schema_1_forward_compat_via_cli(self):
        # Older nostos (and any stashed gitpulse bundle) use schema 1.
        path = self._make_bundle_file(
            schema=1,
            repos=[
                {
                    "path": "/tmp/legacy",
                    "remote_url": None,
                    "source": None,
                    "status": "new",
                    "quiet": False,
                    "added_at": "2026-04-15T00:00:00+00:00",
                    "last_touched_at": None,
                    "tags": ["old"],
                    "notes": [],
                    "upstream": None,
                }
            ],
        )
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            rc = cmd_import.run(self._args(path))
        self.assertEqual(rc, 0)
        with index.connect(self.db) as conn:
            repos = index.list_repos(conn)
        self.assertEqual(len(repos), 1)
        self.assertEqual(sorted(repos[0]["tags"]), ["old"])


if __name__ == "__main__":
    unittest.main()
