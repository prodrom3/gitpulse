"""Tests for core.topic_rules: rule loading, apply transform, save round-trip."""

from __future__ import annotations

import os
import tempfile
import unittest

from core.topic_rules import TopicRules, load_rules, save_rules


class TestApply(unittest.TestCase):
    def test_pass_through_when_empty(self):
        rules = TopicRules()
        self.assertEqual(rules.apply(["c2", "redteam"]), ["c2", "redteam"])

    def test_lowercase_and_dedupe(self):
        rules = TopicRules()
        self.assertEqual(
            rules.apply(["C2", "Redteam", "c2", "redteam"]),
            ["c2", "redteam"],
        )

    def test_drops_non_strings_and_empties(self):
        rules = TopicRules()
        # type: ignore[list-item] - intentionally heterogeneous
        self.assertEqual(rules.apply(["c2", "", None, 7, "redteam"]), ["c2", "redteam"])  # type: ignore[list-item]

    def test_deny_drops_topics(self):
        rules = TopicRules(deny=["foo", "Hacktoberfest"])
        self.assertEqual(
            rules.apply(["c2", "foo", "redteam", "hacktoberfest"]),
            ["c2", "redteam"],
        )

    def test_alias_rewrites(self):
        rules = TopicRules(alias={"penetration-testing": "pentest", "red-teaming": "redteam"})
        self.assertEqual(
            rules.apply(["penetration-testing", "red-teaming", "c2"]),
            ["pentest", "redteam", "c2"],
        )

    def test_alias_target_subject_to_deny(self):
        rules = TopicRules(deny=["spam"], alias={"foo": "spam"})
        self.assertEqual(rules.apply(["foo", "c2"]), ["c2"])

    def test_alias_no_chaining(self):
        # b -> c, a -> b: applying once yields 'b' not 'c'.
        rules = TopicRules(alias={"a": "b", "b": "c"})
        self.assertEqual(sorted(rules.apply(["a", "b"])), ["b", "c"])

    def test_alias_collapses_to_existing(self):
        rules = TopicRules(alias={"pentesting": "pentest"})
        # 'pentest' already in the list; the aliased 'pentesting' must not duplicate.
        self.assertEqual(rules.apply(["pentest", "pentesting"]), ["pentest"])


class TestSaveLoadRoundTrip(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "topic_rules.toml")

    def tearDown(self):
        try:
            os.remove(self.path)
        except OSError:
            pass
        os.rmdir(self.tmp)

    def test_round_trip(self):
        rules = TopicRules(
            deny=["foo", "hacktoberfest"],
            alias={"penetration-testing": "pentest", "red-teaming": "redteam"},
        )
        save_rules(rules, path=self.path)
        loaded = load_rules(self.path)
        self.assertEqual(loaded.deny, {"foo", "hacktoberfest"})
        self.assertEqual(
            loaded.alias,
            {"penetration-testing": "pentest", "red-teaming": "redteam"},
        )

    def test_load_missing_file_returns_empty(self):
        loaded = load_rules(os.path.join(self.tmp, "does-not-exist.toml"))
        self.assertEqual(loaded.deny, set())
        self.assertEqual(loaded.alias, {})

    def test_load_malformed_returns_empty(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("not = valid = toml")
        loaded = load_rules(self.path)
        self.assertEqual(loaded.deny, set())
        self.assertEqual(loaded.alias, {})

    def test_save_with_special_chars_escaped(self):
        rules = TopicRules(alias={'has"quote': 'with\\backslash'})
        save_rules(rules, path=self.path)
        loaded = load_rules(self.path)
        self.assertEqual(loaded.alias, {'has"quote': 'with\\backslash'})


if __name__ == "__main__":
    unittest.main()
