"""Tests for the tag-bucket categorization used by `nostos tags --grouped`."""

from __future__ import annotations

import unittest

from core.tag_buckets import BUCKETS, DISPLAY_ORDER, bucket_for


class TestBucketFor(unittest.TestCase):
    def test_known_disciplines(self):
        for tag in ("recon", "pentest", "redteam", "bugbounty", "websec"):
            self.assertEqual(bucket_for(tag), "discipline", tag)

    def test_known_attack_classes(self):
        for tag in ("xss", "csrf", "ssrf", "subdomain-takeover", "command-injection"):
            self.assertEqual(bucket_for(tag), "attack-class", tag)

    def test_known_recon_techniques(self):
        for tag in ("subdomain", "dns", "github-recon", "wayback"):
            self.assertEqual(bucket_for(tag), "recon-technique", tag)

    def test_known_languages(self):
        for tag in ("python", "go", "golang", "javascript", "ruby", "lua"):
            self.assertEqual(bucket_for(tag), "language", tag)

    def test_known_os(self):
        for tag in ("linux", "kali", "windows", "osx", "termux"):
            self.assertEqual(bucket_for(tag), "os", tag)

    def test_unknown_falls_through_to_other(self):
        self.assertEqual(bucket_for("totally-made-up-tag-name-xyz"), "other")

    def test_known_desktop_env(self):
        for tag in ("dotfiles", "nord", "wayland", "sway", "i3", "hyprland", "tmux"):
            self.assertEqual(bucket_for(tag), "desktop-env", tag)

    def test_175_additions_categorized(self):
        # Tags moved out of `other` in 1.4.7. Spot-check each bucket.
        self.assertEqual(bucket_for("nmap"), "project-name")
        self.assertEqual(bucket_for("atomic"), "project-name")
        self.assertEqual(bucket_for("cheatsheet"), "tool-kind")
        self.assertEqual(bucket_for("detection"), "tool-kind")
        self.assertEqual(bucket_for("cms"), "recon-technique")
        self.assertEqual(bucket_for("gf-patterns"), "recon-technique")
        self.assertEqual(bucket_for("crypto"), "tech")
        self.assertEqual(bucket_for("grep"), "tech")
        self.assertEqual(bucket_for("web"), "tech")

    def test_case_insensitive(self):
        self.assertEqual(bucket_for("XSS"), "attack-class")
        self.assertEqual(bucket_for("Python"), "language")
        self.assertEqual(bucket_for("  golang  "), "language")  # whitespace tolerant

    def test_first_match_wins_priority(self):
        # `fuzzing` is in both recon-technique and could be tool-kind;
        # whichever bucket appears first in the BUCKETS table wins.
        self.assertIn(bucket_for("fuzzing"), {"recon-technique", "tool-kind"})

    def test_bucket_table_has_no_overlap_within_a_single_bucket(self):
        # Sanity: each bucket is a frozenset, so duplicate tags within
        # one bucket are silently collapsed; we still want to ensure no
        # bucket accidentally references a tag that belongs to a more
        # specific bucket downstream of it.
        seen: dict[str, str] = {}
        for bucket_name, tags in BUCKETS:
            for tag in tags:
                if tag in seen:
                    # First-match-wins is intentional. We just assert
                    # that the resolved bucket is the first one.
                    self.assertEqual(bucket_for(tag), seen[tag])
                else:
                    seen[tag] = bucket_name

    def test_display_order_covers_every_bucket_name(self):
        bucket_names = {name for name, _ in BUCKETS}
        self.assertTrue(
            bucket_names.issubset(set(DISPLAY_ORDER)),
            f"BUCKETS has names not in DISPLAY_ORDER: "
            f"{bucket_names - set(DISPLAY_ORDER)}",
        )
        self.assertEqual(
            DISPLAY_ORDER[-1],
            "other",
            "'other' must be last in DISPLAY_ORDER",
        )


if __name__ == "__main__":
    unittest.main()
