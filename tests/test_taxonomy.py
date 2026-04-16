"""Tests for core.taxonomy and the attack subcommand."""

import argparse
import io
import os
import shutil
import tempfile
import unittest
from unittest import mock

from core import index, taxonomy
from core.commands import attack as cmd_attack


class TestTaxonomyLookup(unittest.TestCase):
    def test_known_technique(self):
        result = taxonomy.lookup("T1059")
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "T1059")
        self.assertIn("Command", result[1])

    def test_lowercase_lookup(self):
        result = taxonomy.lookup("t1059")
        self.assertIsNotNone(result)

    def test_with_attack_prefix(self):
        result = taxonomy.lookup("attack:t1059")
        self.assertIsNotNone(result)

    def test_unknown_technique(self):
        self.assertIsNone(taxonomy.lookup("T9999"))

    def test_normalize_bare_id(self):
        self.assertEqual(taxonomy.normalize_attack_tag("T1059"), "attack:t1059")

    def test_normalize_already_prefixed(self):
        self.assertEqual(taxonomy.normalize_attack_tag("attack:T1059"), "attack:t1059")

    def test_normalize_non_technique(self):
        self.assertEqual(taxonomy.normalize_attack_tag("recon"), "recon")

    def test_render_table_not_empty(self):
        text = taxonomy.render_table()
        self.assertIn("T1059", text)
        self.assertIn("Reconnaissance", text)
        self.assertIn("Command and Control", text)


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


class TestAttackListCommand(unittest.TestCase):
    def test_prints_table(self):
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            rc = cmd_attack.run_list(argparse.Namespace())
        self.assertEqual(rc, 0)
        text = out.getvalue()
        self.assertIn("T1059", text)


class TestAttackTagCommand(_IndexTestCase):
    def test_tags_repo_with_technique(self):
        repo = os.path.join(self.tmp, "r")
        os.makedirs(os.path.join(repo, ".git"))
        with index.connect(self.db) as conn:
            index.add_repo(conn, repo)
        args = argparse.Namespace(target=repo, techniques=["T1059", "T1071"])
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            rc = cmd_attack.run_tag(args)
        self.assertEqual(rc, 0)
        with index.connect(self.db) as conn:
            tags = index.get_tags(conn, repo)
        self.assertIn("attack:t1059", tags)
        self.assertIn("attack:t1071", tags)

    def test_warns_on_unknown_technique(self):
        repo = os.path.join(self.tmp, "r")
        os.makedirs(os.path.join(repo, ".git"))
        with index.connect(self.db) as conn:
            index.add_repo(conn, repo)
        args = argparse.Namespace(target=repo, techniques=["T9999"])
        with mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            rc = cmd_attack.run_tag(args)
        self.assertEqual(rc, 0)
        self.assertIn("not in the built-in lookup table", err.getvalue())

    def test_missing_repo_errors(self):
        args = argparse.Namespace(target="/nope", techniques=["T1059"])
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            rc = cmd_attack.run_tag(args)
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
