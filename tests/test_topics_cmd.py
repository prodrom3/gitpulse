"""Tests for the `nostos topics` subcommand."""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from core import index as _index
from core.commands import topics as cmd_topics
from core.topic_rules import load_rules


class _RulesTestCase(unittest.TestCase):
    """Patches topic_rules_path to a temp file so each test is isolated."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.rules_path = os.path.join(self.tmp, "topic_rules.toml")
        self._patches = [
            mock.patch("core.topic_rules.topic_rules_path", return_value=self.rules_path),
            mock.patch("core.topic_rules.ensure_config_dir", return_value=self.tmp),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestTopicsList(_RulesTestCase):
    def test_list_empty_human(self):
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            rc = cmd_topics.run_list(argparse.Namespace(json=False))
        self.assertEqual(rc, 0)
        text = out.getvalue()
        self.assertIn("deny: (empty)", text)
        self.assertIn("alias: (empty)", text)

    def test_list_json(self):
        # seed a rule via the deny verb
        cmd_topics.run_deny(argparse.Namespace(topics=["foo", "bar"]))
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out, \
             mock.patch("sys.stderr", new_callable=io.StringIO):
            rc = cmd_topics.run_list(argparse.Namespace(json=True))
        self.assertEqual(rc, 0)
        data = json.loads(out.getvalue())
        self.assertEqual(sorted(data["deny"]), ["bar", "foo"])
        self.assertEqual(data["alias"], {})


class TestTopicsDenyAllow(_RulesTestCase):
    def test_deny_then_allow(self):
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            cmd_topics.run_deny(argparse.Namespace(topics=["foo", "BAR", "foo"]))
        rules = load_rules(self.rules_path)
        # Lowercased and deduped on save:
        self.assertEqual(rules.deny, {"foo", "bar"})

        with mock.patch("sys.stderr", new_callable=io.StringIO):
            cmd_topics.run_allow(argparse.Namespace(topics=["bar"]))
        rules = load_rules(self.rules_path)
        self.assertEqual(rules.deny, {"foo"})


class TestTopicsAliasUnalias(_RulesTestCase):
    def test_alias_then_unalias(self):
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            cmd_topics.run_alias(argparse.Namespace(src="Red-Teaming", dst="redteam"))
        rules = load_rules(self.rules_path)
        self.assertEqual(rules.alias, {"red-teaming": "redteam"})

        with mock.patch("sys.stderr", new_callable=io.StringIO):
            cmd_topics.run_unalias(argparse.Namespace(sources=["red-teaming"]))
        rules = load_rules(self.rules_path)
        self.assertEqual(rules.alias, {})

    def test_alias_rejects_empty(self):
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            rc = cmd_topics.run_alias(argparse.Namespace(src=" ", dst="redteam"))
        self.assertEqual(rc, 1)


class TestTopicsExportImport(_RulesTestCase):
    def _seed(self, deny=None, alias=None):
        if deny:
            with mock.patch("sys.stderr", new_callable=io.StringIO):
                cmd_topics.run_deny(argparse.Namespace(topics=deny))
        if alias:
            for src, dst in alias.items():
                with mock.patch("sys.stderr", new_callable=io.StringIO):
                    cmd_topics.run_alias(argparse.Namespace(src=src, dst=dst))

    def test_export_to_stdout_default(self):
        self._seed(deny=["foo"], alias={"a": "b"})
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            rc = cmd_topics.run_export(argparse.Namespace(path="-"))
        self.assertEqual(rc, 0)
        body = out.getvalue()
        self.assertIn('deny = ["foo"]', body)
        self.assertIn('"a" = "b"', body)

    def test_export_to_file(self):
        self._seed(deny=["foo"])
        out_path = os.path.join(self.tmp, "exported.toml")
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            rc = cmd_topics.run_export(argparse.Namespace(path=out_path))
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.isfile(out_path))
        with open(out_path, encoding="utf-8") as f:
            self.assertIn('"foo"', f.read())

    def test_import_merge_unions_deny_and_overlays_alias(self):
        # Local has its own customizations:
        self._seed(deny=["local-junk"], alias={"keep": "this"})
        # Incoming wants to add a deny + replace one alias:
        incoming = os.path.join(self.tmp, "incoming.toml")
        with open(incoming, "w", encoding="utf-8") as f:
            f.write('deny = ["new-junk"]\n[alias]\n"red-teaming" = "redteam"\n')

        with mock.patch("sys.stderr", new_callable=io.StringIO):
            rc = cmd_topics.run_import(argparse.Namespace(source=incoming, mode="merge"))
        self.assertEqual(rc, 0)

        rules = load_rules(self.rules_path)
        self.assertEqual(rules.deny, {"local-junk", "new-junk"})
        self.assertEqual(
            rules.alias,
            {"keep": "this", "red-teaming": "redteam"},
        )

    def test_import_replace_drops_local(self):
        self._seed(deny=["local-junk"], alias={"keep": "this"})
        incoming = os.path.join(self.tmp, "incoming.toml")
        with open(incoming, "w", encoding="utf-8") as f:
            f.write('deny = ["only-this"]\n')

        with mock.patch("sys.stderr", new_callable=io.StringIO):
            rc = cmd_topics.run_import(
                argparse.Namespace(source=incoming, mode="replace")
            )
        self.assertEqual(rc, 0)

        rules = load_rules(self.rules_path)
        self.assertEqual(rules.deny, {"only-this"})
        self.assertEqual(rules.alias, {})

    def test_import_from_stdin(self):
        text = 'deny = ["from-stdin"]\n[alias]\n"x" = "y"\n'
        with mock.patch("sys.stdin", io.StringIO(text)), \
             mock.patch("sys.stderr", new_callable=io.StringIO):
            rc = cmd_topics.run_import(argparse.Namespace(source="-", mode="merge"))
        self.assertEqual(rc, 0)
        rules = load_rules(self.rules_path)
        self.assertEqual(rules.deny, {"from-stdin"})
        self.assertEqual(rules.alias, {"x": "y"})

    def test_import_malformed_returns_error(self):
        bad = os.path.join(self.tmp, "bad.toml")
        with open(bad, "w", encoding="utf-8") as f:
            f.write("not = = valid")
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            rc = cmd_topics.run_import(argparse.Namespace(source=bad, mode="merge"))
        self.assertEqual(rc, 1)

    def test_import_missing_file_returns_error(self):
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            rc = cmd_topics.run_import(
                argparse.Namespace(source="/no/such/file", mode="merge")
            )
        self.assertEqual(rc, 1)


class _IndexAndRulesTestCase(unittest.TestCase):
    """Like _RulesTestCase but also patches the index DB to a temp file
    so apply-mode tests can seed real repo + tag rows."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.rules_path = os.path.join(self.tmp, "topic_rules.toml")
        self.db = os.path.join(self.tmp, "index.db")
        self._patches = [
            mock.patch("core.topic_rules.topic_rules_path", return_value=self.rules_path),
            mock.patch("core.topic_rules.ensure_config_dir", return_value=self.tmp),
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


class TestTopicsApply(_IndexAndRulesTestCase):
    def _seed_rules(self, deny=None, alias=None):
        if deny:
            with mock.patch("sys.stderr", new_callable=io.StringIO):
                cmd_topics.run_deny(argparse.Namespace(topics=list(deny)))
        if alias:
            for src, dst in alias.items():
                with mock.patch("sys.stderr", new_callable=io.StringIO):
                    cmd_topics.run_alias(argparse.Namespace(src=src, dst=dst))

    def _seed_repo(self, path, tags):
        with _index.connect(self.db) as conn:
            return _index.add_repo(conn, path, tags=list(tags))

    def _args(self, **overrides):
        base = {"repo": None, "dry_run": False, "json": False}
        base.update(overrides)
        return argparse.Namespace(**base)

    def test_apply_drops_denied_tags(self):
        self._seed_rules(deny=["foo"])
        rid = self._seed_repo("/t/r", tags=["foo", "keep"])
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            rc = cmd_topics.run_apply(self._args())
        self.assertEqual(rc, 0)
        with _index.connect(self.db) as conn:
            self.assertEqual(_index.get_tags(conn, rid), ["keep"])

    def test_apply_rewrites_alias_to_canonical(self):
        self._seed_rules(alias={"red-teaming": "redteam"})
        rid = self._seed_repo("/t/r", tags=["red-teaming", "c2"])
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            cmd_topics.run_apply(self._args())
        with _index.connect(self.db) as conn:
            self.assertEqual(sorted(_index.get_tags(conn, rid)), ["c2", "redteam"])

    def test_apply_when_target_already_present_just_drops_source(self):
        self._seed_rules(alias={"python3": "python"})
        rid = self._seed_repo("/t/r", tags=["python", "python3"])
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            cmd_topics.run_apply(self._args())
        with _index.connect(self.db) as conn:
            self.assertEqual(_index.get_tags(conn, rid), ["python"])

    def test_apply_idempotent(self):
        self._seed_rules(alias={"red-teaming": "redteam"})
        rid = self._seed_repo("/t/r", tags=["red-teaming"])
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            cmd_topics.run_apply(self._args())
            cmd_topics.run_apply(self._args())  # no-op the second time
        with _index.connect(self.db) as conn:
            self.assertEqual(_index.get_tags(conn, rid), ["redteam"])

    def test_apply_dry_run_does_not_mutate(self):
        self._seed_rules(deny=["foo"])
        rid = self._seed_repo("/t/r", tags=["foo", "keep"])
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            cmd_topics.run_apply(self._args(dry_run=True))
        with _index.connect(self.db) as conn:
            self.assertEqual(sorted(_index.get_tags(conn, rid)), ["foo", "keep"])

    def test_apply_single_repo_targeting(self):
        self._seed_rules(deny=["foo"])
        rid_a = self._seed_repo("/t/a", tags=["foo", "keep"])
        rid_b = self._seed_repo("/t/b", tags=["foo", "keep"])
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            cmd_topics.run_apply(self._args(repo="/t/a"))
        with _index.connect(self.db) as conn:
            self.assertEqual(_index.get_tags(conn, rid_a), ["keep"])
            # /t/b untouched:
            self.assertEqual(sorted(_index.get_tags(conn, rid_b)), ["foo", "keep"])

    def test_apply_no_rules_is_noop(self):
        rid = self._seed_repo("/t/r", tags=["foo", "keep"])
        with mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            rc = cmd_topics.run_apply(self._args())
        self.assertEqual(rc, 0)
        self.assertIn("no rules loaded", err.getvalue())
        with _index.connect(self.db) as conn:
            self.assertEqual(sorted(_index.get_tags(conn, rid)), ["foo", "keep"])

    def test_apply_json_summary_shape(self):
        self._seed_rules(deny=["foo"], alias={"red-teaming": "redteam"})
        self._seed_repo("/t/a", tags=["foo", "red-teaming"])
        self._seed_repo("/t/b", tags=["clean"])  # already curated; should not appear
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out, \
             mock.patch("sys.stderr", new_callable=io.StringIO):
            cmd_topics.run_apply(self._args(json=True))
        data = json.loads(out.getvalue())
        self.assertFalse(data["dry_run"])
        self.assertEqual(data["repos_changed"], 1)
        self.assertEqual(data["tags_removed"], 2)
        self.assertEqual(data["tags_added"], 1)
        self.assertEqual(data["changes"][0]["added"], ["redteam"])
        self.assertEqual(sorted(data["changes"][0]["removed"]), ["foo", "red-teaming"])

    def test_apply_missing_repo_returns_error(self):
        self._seed_rules(deny=["foo"])
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            rc = cmd_topics.run_apply(self._args(repo="/nope"))
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
