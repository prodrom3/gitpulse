"""Tests for core.topic_rules: rule loading, apply transform, save round-trip."""

from __future__ import annotations

import os
import tempfile
import unittest

from core.topic_rules import (
    TopicRules,
    dump_rules,
    load_rules,
    merge_rules,
    parse_rules_from_text,
    save_rules,
)


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


class TestParseFromText(unittest.TestCase):
    def test_parses_inline_string(self):
        text = """
deny = ["foo", "bar"]

[alias]
"red-teaming" = "redteam"
"""
        rules = parse_rules_from_text(text)
        self.assertEqual(rules.deny, {"foo", "bar"})
        self.assertEqual(rules.alias, {"red-teaming": "redteam"})

    def test_malformed_raises_value_error(self):
        with self.assertRaises(ValueError):
            parse_rules_from_text("this is = = not toml")


class TestDumpRules(unittest.TestCase):
    def test_dump_round_trip_through_parse(self):
        rules = TopicRules(deny=["foo"], alias={"x": "y"})
        text = dump_rules(rules)
        round_tripped = parse_rules_from_text(text)
        self.assertEqual(round_tripped.deny, {"foo"})
        self.assertEqual(round_tripped.alias, {"x": "y"})

    def test_empty_rules_dump_is_valid_toml(self):
        text = dump_rules(TopicRules())
        rules = parse_rules_from_text(text)
        self.assertEqual(rules.deny, set())
        self.assertEqual(rules.alias, {})


class TestMergeRules(unittest.TestCase):
    def test_deny_is_unioned(self):
        a = TopicRules(deny=["foo", "bar"])
        b = TopicRules(deny=["baz", "foo"])
        merged = merge_rules(a, b)
        self.assertEqual(merged.deny, {"foo", "bar", "baz"})

    def test_alias_overlays_incoming_wins(self):
        a = TopicRules(alias={"src": "old", "keep": "this"})
        b = TopicRules(alias={"src": "new"})
        merged = merge_rules(a, b)
        self.assertEqual(merged.alias, {"src": "new", "keep": "this"})

    def test_does_not_mutate_inputs(self):
        a = TopicRules(deny=["foo"], alias={"x": "y"})
        b = TopicRules(deny=["bar"], alias={"a": "b"})
        merge_rules(a, b)
        self.assertEqual(a.deny, {"foo"})
        self.assertEqual(b.deny, {"bar"})

    def test_drops_inverse_alias_from_base(self):
        # Real-world scenario: 1.4.2 had `offsec -> offensive-security`,
        # 1.4.3 reversed it to `offensive-security -> offsec`. After a
        # `--merge` import, both directions would coexist and apply()
        # would oscillate every run. The merge step must drop the
        # stale base entry.
        base = TopicRules(alias={"offsec": "offensive-security"})
        incoming = TopicRules(alias={"offensive-security": "offsec"})
        merged = merge_rules(base, incoming)
        self.assertEqual(merged.alias, {"offensive-security": "offsec"})
        self.assertNotIn("offsec", merged.alias)

    def test_keeps_unrelated_base_alias_when_target_unchanged(self):
        # If incoming touches A but base has independent B -> C, the
        # B -> C entry must survive intact.
        base = TopicRules(alias={"keep": "this", "src": "old-target"})
        incoming = TopicRules(alias={"src": "new-target"})
        merged = merge_rules(base, incoming)
        self.assertEqual(merged.alias, {"keep": "this", "src": "new-target"})

    def test_does_not_drop_when_targets_differ(self):
        # Base: A -> B. Incoming: A -> C. (Same source, different target -
        # not an inversion, just a retarget. Incoming wins; base's other
        # entries should remain.)
        base = TopicRules(alias={"a": "b", "x": "y"})
        incoming = TopicRules(alias={"a": "c"})
        merged = merge_rules(base, incoming)
        self.assertEqual(merged.alias, {"a": "c", "x": "y"})


if __name__ == "__main__":
    unittest.main()
