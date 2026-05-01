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


if __name__ == "__main__":
    unittest.main()
