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

from core.commands import topics as cmd_topics
from core.topic_rules import load_rules


class _RulesTestCase(unittest.TestCase):
    """Patches topic_rules_path to a temp file so each test is isolated."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.rules_path = os.path.join(self.tmp, "topic_rules.toml")
        # Both modules look up the path via paths.topic_rules_path,
        # but each imports it under a different name.
        self._patches = [
            mock.patch("core.topic_rules.topic_rules_path", return_value=self.rules_path),
            mock.patch("core.topic_rules.config_dir", return_value=self.tmp),
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


if __name__ == "__main__":
    unittest.main()
