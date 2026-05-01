"""Tests for the tag-bucket categorization used by `nostos tags --grouped`."""

from __future__ import annotations

import unittest

from core.tag_buckets import (
    BUCKETS,
    DISPLAY_ORDER,
    SUB_BUCKET_DISPLAY_ORDER,
    SUB_BUCKETS,
    bucket_for,
    sub_bucket_for,
)


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


class TestSubBucketFor(unittest.TestCase):
    def test_attack_class_web_attacks(self):
        for tag in ("xss", "csrf", "ssrf", "cors", "command-injection",
                    "open-redirect", "dom-xss", "crlf-injection"):
            self.assertEqual(sub_bucket_for(tag, "attack-class"), "web-attacks", tag)

    def test_attack_class_subdomain(self):
        for tag in ("subdomain-takeover", "takeover", "hostile",
                    "hostile-subdomain-takeover"):
            self.assertEqual(sub_bucket_for(tag, "attack-class"), "subdomain", tag)

    def test_attack_class_general_falls_through(self):
        # Tags in attack-class but not in any specific sub-bucket
        # land in the 'general' sub-bucket.
        for tag in ("vulnerability", "exploit", "exploitation", "bypass"):
            self.assertEqual(sub_bucket_for(tag, "attack-class"), "general", tag)

    def test_attack_class_unknown_falls_to_other(self):
        self.assertEqual(
            sub_bucket_for("totally-unknown-attack-tag", "attack-class"), "other"
        )

    def test_recon_subdomain(self):
        for tag in ("subdomain", "subdomains", "vertical-corelation",
                    "horizontal-corelation"):
            self.assertEqual(sub_bucket_for(tag, "recon-technique"), "subdomain", tag)

    def test_recon_dns(self):
        for tag in ("dns", "dns-resolver", "massdns"):
            self.assertEqual(sub_bucket_for(tag, "recon-technique"), "dns", tag)

    def test_recon_web_recon(self):
        for tag in ("github-recon", "visual-recon", "js-enumeration",
                    "wayback", "cms"):
            self.assertEqual(sub_bucket_for(tag, "recon-technique"), "web-recon", tag)

    def test_recon_osint(self):
        for tag in ("osint", "acquisitions", "asn", "reconnaissance", "recon"):
            self.assertEqual(sub_bucket_for(tag, "recon-technique"), "osint", tag)

    def test_bucket_without_subbuckets_returns_none(self):
        # `language`, `os`, `tech`, etc. don't define sub-buckets.
        self.assertIsNone(sub_bucket_for("python", "language"))
        self.assertIsNone(sub_bucket_for("linux", "os"))
        self.assertIsNone(sub_bucket_for("anything", "other"))

    def test_sub_bucket_display_order_covers_real_subs(self):
        for bucket, sub_table in SUB_BUCKETS.items():
            ordered = SUB_BUCKET_DISPLAY_ORDER.get(bucket, ())
            sub_names = {name for name, _ in sub_table}
            # 'other' is synthetic - allowed to be in display order
            # but not in the data table.
            self.assertTrue(
                sub_names.issubset(set(ordered)),
                f"{bucket}: SUB_BUCKETS has names not in display order: "
                f"{sub_names - set(ordered)}",
            )
            self.assertEqual(
                ordered[-1], "other",
                f"{bucket}: 'other' must be last in SUB_BUCKET_DISPLAY_ORDER",
            )


class TestNewMindmapTags(unittest.TestCase):
    """Tags pulled from the Pentesting/Bug Bounty Mindmap (Rohit Gautam)
    that we adopted in 1.5.1."""

    def test_corelation_tags(self):
        self.assertEqual(bucket_for("vertical-corelation"), "recon-technique")
        self.assertEqual(bucket_for("horizontal-corelation"), "recon-technique")
        self.assertEqual(
            sub_bucket_for("vertical-corelation", "recon-technique"), "subdomain"
        )

    def test_acquisitions_and_asn(self):
        self.assertEqual(bucket_for("acquisitions"), "recon-technique")
        self.assertEqual(bucket_for("asn"), "recon-technique")
        self.assertEqual(sub_bucket_for("acquisitions", "recon-technique"), "osint")

    def test_web_application_attacks_umbrella(self):
        self.assertEqual(bucket_for("web-application-attacks"), "discipline")

    def test_certificate_transparency(self):
        self.assertEqual(bucket_for("certificate-transparency"), "recon-technique")
        self.assertEqual(
            sub_bucket_for("certificate-transparency", "recon-technique"),
            "web-recon",
        )


if __name__ == "__main__":
    unittest.main()
