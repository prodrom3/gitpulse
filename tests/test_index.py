import os
import sqlite3
import stat
import sys
import tempfile
import unittest

from core import index


def _R(path: str) -> str:
    """Canonicalise a path the same way core.index does (realpath + expanduser).

    Needed because tests use abstract paths like /tmp/a or /t/a as test IDs,
    but the index normalises them: on macOS /tmp is a symlink to /private/tmp,
    and on Windows a POSIX-style path resolves to a drive-rooted path.
    """
    return os.path.realpath(os.path.expanduser(path))


class TestConnectAndSchema(unittest.TestCase):
    def test_creates_schema_on_first_open(self):
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "a.db")
            with index.connect(db) as conn:
                tables = {
                    r["name"]
                    for r in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
            # sqlite_sequence is auto-created by AUTOINCREMENT; assert
            # our tables are a subset.
            expected = {"schema_version", "repos", "tags", "repo_tags", "notes"}
            self.assertTrue(expected.issubset(tables))

    def test_schema_version_is_current(self):
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "a.db")
            with index.connect(db) as conn:
                row = conn.execute(
                    "SELECT MAX(version) FROM schema_version"
                ).fetchone()
            self.assertEqual(row[0], index.CURRENT_SCHEMA_VERSION)

    def test_reopen_is_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "a.db")
            with index.connect(db) as conn:
                index.add_repo(conn, "/tmp/repo-a")
            with index.connect(db) as conn:
                count = conn.execute("SELECT COUNT(*) FROM repos").fetchone()[0]
            self.assertEqual(count, 1)

    def test_rejects_newer_schema_version(self):
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "a.db")
            conn = sqlite3.connect(db)
            conn.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY)")
            conn.execute("INSERT INTO schema_version VALUES (999)")
            conn.commit()
            conn.close()
            with self.assertRaises(RuntimeError):
                with index.connect(db):
                    pass

    def test_pragmas_applied(self):
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "a.db")
            with index.connect(db) as conn:
                journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
                secure = conn.execute("PRAGMA secure_delete").fetchone()[0]
                fks = conn.execute("PRAGMA foreign_keys").fetchone()[0]
            self.assertEqual(journal.lower(), "wal")
            self.assertEqual(secure, 1)
            self.assertEqual(fks, 1)

    @unittest.skipIf(sys.platform == "win32", "Unix-only perm check")
    def test_new_db_file_is_0600(self):
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "a.db")
            with index.connect(db):
                pass
            mode = stat.S_IMODE(os.stat(db).st_mode)
            self.assertEqual(mode, 0o600)


class TestRepoCrud(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "index.db")

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_add_and_get(self):
        with index.connect(self.db) as conn:
            repo_id = index.add_repo(
                conn,
                "/tmp/a",
                remote_url="git@host:u/a.git",
                source="colleague",
                tags=["c2", "post-ex"],
                note="hello",
            )
            repo = index.get_repo(conn, repo_id)
        self.assertEqual(repo["remote_url"], "git@host:u/a.git")
        self.assertEqual(sorted(repo["tags"]), ["c2", "post-ex"])
        self.assertEqual(len(repo["notes"]), 1)
        self.assertEqual(repo["status"], "new")
        self.assertEqual(repo["quiet"], 0)

    def test_add_rejects_invalid_status(self):
        with index.connect(self.db) as conn:
            with self.assertRaises(ValueError):
                index.add_repo(conn, "/tmp/a", status="bogus")

    def test_add_path_realpath_normalized(self):
        with index.connect(self.db) as conn:
            index.add_repo(conn, "/tmp/./a/../a")
            repo = index.get_repo(conn, "/tmp/a")
        self.assertIsNotNone(repo)
        self.assertEqual(repo["path"], _R("/tmp/a"))

    def test_add_existing_path_is_idempotent(self):
        with index.connect(self.db) as conn:
            first = index.add_repo(conn, "/tmp/a")
            second = index.add_repo(conn, "/tmp/a")
        self.assertEqual(first, second)

    def test_add_existing_path_fills_missing_fields(self):
        with index.connect(self.db) as conn:
            index.add_repo(conn, "/tmp/a")
            index.add_repo(conn, "/tmp/a", remote_url="git@host:u/a.git")
            repo = index.get_repo(conn, "/tmp/a")
        self.assertEqual(repo["remote_url"], "git@host:u/a.git")

    def test_list_filters_by_tag(self):
        with index.connect(self.db) as conn:
            index.add_repo(conn, "/tmp/a", tags=["c2"])
            index.add_repo(conn, "/tmp/b", tags=["recon"])
            both = index.list_repos(conn)
            c2 = index.list_repos(conn, tag="c2")
        self.assertEqual(len(both), 2)
        self.assertEqual(len(c2), 1)
        self.assertEqual(c2[0]["path"], _R("/tmp/a"))

    def test_list_filters_by_status(self):
        with index.connect(self.db) as conn:
            index.add_repo(conn, "/tmp/a", status="new")
            index.add_repo(conn, "/tmp/b", status="in-use")
            flagged = index.list_repos(conn, status="in-use")
        self.assertEqual(len(flagged), 1)

    def test_list_filters_by_untouched_days(self):
        import datetime

        with index.connect(self.db) as conn:
            index.add_repo(conn, "/tmp/a")
            index.add_repo(conn, "/tmp/b")
            # Mark b as touched now; a remains NULL
            index.touch_repo(conn, "/tmp/b")
            # Manually push b's last_touched_at into the past
            old = (
                datetime.datetime.now(datetime.timezone.utc)
                - datetime.timedelta(days=400)
            ).isoformat(timespec="seconds")
            conn.execute(
                "UPDATE repos SET last_touched_at = ? WHERE path = ?",
                (old, _R("/tmp/b")),
            )
            conn.commit()
            stale = index.list_repos(conn, untouched_days=90)
        paths = {r["path"] for r in stale}
        self.assertEqual(paths, {_R("/tmp/a"), _R("/tmp/b")})

    def test_update_status_valid_and_invalid(self):
        with index.connect(self.db) as conn:
            rid = index.add_repo(conn, "/tmp/a")
            self.assertTrue(index.update_status(conn, rid, "in-use"))
            repo = index.get_repo(conn, rid)
            self.assertEqual(repo["status"], "in-use")
            with self.assertRaises(ValueError):
                index.update_status(conn, rid, "not-a-status")

    def test_update_status_missing_repo(self):
        with index.connect(self.db) as conn:
            self.assertFalse(index.update_status(conn, 999, "in-use"))

    def test_set_quiet(self):
        with index.connect(self.db) as conn:
            rid = index.add_repo(conn, "/tmp/a")
            self.assertTrue(index.set_quiet(conn, rid, True))
            repo = index.get_repo(conn, rid)
            self.assertEqual(repo["quiet"], 1)
            index.set_quiet(conn, rid, False)
            repo = index.get_repo(conn, rid)
            self.assertEqual(repo["quiet"], 0)

    def test_touch_repo_missing(self):
        with index.connect(self.db) as conn:
            self.assertFalse(index.touch_repo(conn, "/nonexistent/repo"))

    def test_remove_repo_cascades(self):
        with index.connect(self.db) as conn:
            rid = index.add_repo(
                conn, "/tmp/a", tags=["c2"], note="gone soon"
            )
            self.assertTrue(index.remove_repo(conn, rid))
            self.assertIsNone(index.get_repo(conn, rid))
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM repo_tags").fetchone()[0], 0
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0], 0
            )


class TestTagsAndNotes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "index.db")

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_tags_are_lowercased_and_deduplicated(self):
        with index.connect(self.db) as conn:
            rid = index.add_repo(conn, "/tmp/a", tags=["C2", "c2", "Recon"])
            tags = index.get_tags(conn, rid)
        self.assertEqual(sorted(tags), ["c2", "recon"])

    def test_add_tags_on_existing_repo(self):
        with index.connect(self.db) as conn:
            index.add_repo(conn, "/tmp/a")
            index.add_tags(conn, "/tmp/a", ["new-tag"])
            self.assertEqual(index.get_tags(conn, "/tmp/a"), ["new-tag"])

    def test_remove_tag(self):
        with index.connect(self.db) as conn:
            index.add_repo(conn, "/tmp/a", tags=["a", "b"])
            index.remove_tags(conn, "/tmp/a", ["a"])
            self.assertEqual(index.get_tags(conn, "/tmp/a"), ["b"])

    def test_tags_on_missing_repo(self):
        with index.connect(self.db) as conn:
            self.assertFalse(index.add_tags(conn, 999, ["x"]))
            self.assertEqual(index.get_tags(conn, 999), [])

    def test_notes_append_and_retrieve(self):
        with index.connect(self.db) as conn:
            index.add_repo(conn, "/tmp/a")
            index.add_note(conn, "/tmp/a", "first")
            index.add_note(conn, "/tmp/a", "second")
            notes = index.get_notes(conn, "/tmp/a")
        self.assertEqual([n["body"] for n in notes], ["first", "second"])

    def test_note_on_missing_repo(self):
        with index.connect(self.db) as conn:
            self.assertFalse(index.add_note(conn, "/nope", "hi"))


class TestWatchlistMigration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "index.db")

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, content: str) -> str:
        p = os.path.join(self.tmp, ".gitpulse_repos")
        with open(p, "w") as f:
            f.write(content)
        return p

    def test_migration_imports_entries(self):
        wl = self._write("/tmp/a\n/tmp/b\n")
        with index.connect(self.db) as conn:
            n = index.migrate_watchlist(conn, wl)
            repos = index.list_repos(conn)
        self.assertEqual(n, 2)
        self.assertEqual({r["path"] for r in repos}, {_R("/tmp/a"), _R("/tmp/b")})
        self.assertTrue(all(r["source"] == "legacy-watchlist" for r in repos))
        self.assertTrue(all(r["status"] == "reviewed" for r in repos))

    def test_migration_skips_comments_and_blanks(self):
        wl = self._write("# comment\n\n/tmp/a\n# another\n")
        with index.connect(self.db) as conn:
            n = index.migrate_watchlist(conn, wl)
        self.assertEqual(n, 1)

    def test_migration_is_idempotent(self):
        wl = self._write("/tmp/a\n")
        with index.connect(self.db) as conn:
            first = index.migrate_watchlist(conn, wl)
            second = index.migrate_watchlist(conn, wl)
            count = conn.execute("SELECT COUNT(*) FROM repos").fetchone()[0]
        self.assertEqual(first, 1)
        self.assertEqual(second, 1)  # add_repo is idempotent; re-imports but no-op
        self.assertEqual(count, 1)

    def test_migration_missing_file_returns_zero(self):
        with index.connect(self.db) as conn:
            self.assertEqual(
                index.migrate_watchlist(conn, "/nonexistent/file"), 0
            )


if __name__ == "__main__":
    unittest.main()
