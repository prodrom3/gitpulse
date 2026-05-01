"""Tests for the `nostos tags` subcommand and its index helpers."""

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
from core.commands import tags as cmd_tags


class _TagsTestCase(unittest.TestCase):
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

    def _seed(self, repos: dict[str, list[str]]) -> None:
        with _index.connect(self.db) as conn:
            for path, tags in repos.items():
                _index.add_repo(conn, path, tags=list(tags))

    def _args(self, **overrides):
        base = {
            "include_orphans": False,
            "prune_orphans": False,
            "grouping": None,
            "json": False,
        }
        base.update(overrides)
        return argparse.Namespace(**base)


class TestListHelper(_TagsTestCase):
    def test_lists_attached_tags_with_counts(self):
        self._seed({"/t/a": ["c2", "redteam"], "/t/b": ["c2"], "/t/c": []})
        with _index.connect(self.db) as conn:
            entries = _index.list_tags_with_counts(conn)
        self.assertEqual(entries, [("c2", 2), ("redteam", 1)])

    def test_excludes_orphans_by_default(self):
        # Seed a tag, then detach it from every repo to create an orphan.
        self._seed({"/t/a": ["sole-attachment"]})
        with _index.connect(self.db) as conn:
            _index.remove_tags(conn, "/t/a", ["sole-attachment"])
            entries = _index.list_tags_with_counts(conn)
        self.assertEqual(entries, [])

    def test_include_orphans_returns_zero_count_rows(self):
        self._seed({"/t/a": ["sole"]})
        with _index.connect(self.db) as conn:
            _index.remove_tags(conn, "/t/a", ["sole"])
            entries = _index.list_tags_with_counts(conn, include_orphans=True)
        self.assertEqual(entries, [("sole", 0)])


class TestPruneOrphans(_TagsTestCase):
    def test_prune_removes_only_orphans(self):
        self._seed({"/t/a": ["keep", "drop"]})
        with _index.connect(self.db) as conn:
            _index.remove_tags(conn, "/t/a", ["drop"])
            pruned = _index.prune_orphan_tags(conn)
        self.assertEqual(pruned, 1)
        with _index.connect(self.db) as conn:
            entries = _index.list_tags_with_counts(conn, include_orphans=True)
        self.assertEqual(entries, [("keep", 1)])

    def test_prune_with_no_orphans_returns_zero(self):
        self._seed({"/t/a": ["x"]})
        with _index.connect(self.db) as conn:
            self.assertEqual(_index.prune_orphan_tags(conn), 0)


class TestTagsCommand(_TagsTestCase):
    def test_human_output_includes_counts(self):
        self._seed({"/t/a": ["c2", "redteam"], "/t/b": ["c2"]})
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out, \
             mock.patch("sys.stderr", new_callable=io.StringIO):
            rc = cmd_tags.run(self._args())
        self.assertEqual(rc, 0)
        text = out.getvalue()
        self.assertIn("c2", text)
        self.assertIn("redteam", text)
        # c2 should appear before redteam (count desc)
        self.assertLess(text.index("c2"), text.index("redteam"))

    def test_empty_index_message(self):
        with mock.patch("sys.stdout", new_callable=io.StringIO), \
             mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            rc = cmd_tags.run(self._args())
        self.assertEqual(rc, 0)
        self.assertIn("no tags", err.getvalue())

    def test_json_shape(self):
        self._seed({"/t/a": ["c2"], "/t/b": ["c2", "redteam"]})
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            cmd_tags.run(self._args(json=True))
        data = json.loads(out.getvalue())
        self.assertEqual(data["total_tags"], 2)
        self.assertEqual(data["orphans_pruned"], 0)
        names = {entry["name"]: entry["repos"] for entry in data["tags"]}
        self.assertEqual(names, {"c2": 2, "redteam": 1})

    def test_grouped_output_has_bucket_headers(self):
        self._seed({
            "/t/a": ["recon", "pentest"],          # discipline
            "/t/b": ["xss", "csrf"],               # attack-class
            "/t/c": ["python", "golang"],          # language
            "/t/d": ["nord-theme-totally-made-up"],  # other
        })
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out, \
             mock.patch("sys.stderr", new_callable=io.StringIO):
            cmd_tags.run(self._args(grouping="grouped"))
        text = out.getvalue()
        self.assertIn("[discipline]", text)
        self.assertIn("[attack-class]", text)
        self.assertIn("[language]", text)
        self.assertIn("[other]", text)
        # Bucket order: discipline appears before language appears before other.
        self.assertLess(text.index("[discipline]"), text.index("[language]"))
        self.assertLess(text.index("[language]"), text.index("[other]"))

    def test_flat_output_has_no_bucket_headers(self):
        self._seed({"/t/a": ["recon", "xss", "python"]})
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out, \
             mock.patch("sys.stderr", new_callable=io.StringIO):
            cmd_tags.run(self._args(grouping="flat"))
        text = out.getvalue()
        self.assertNotIn("[discipline]", text)
        self.assertNotIn("[attack-class]", text)
        # All three tags still appear:
        for tag in ("recon", "xss", "python"):
            self.assertIn(tag, text)

    def test_grouped_sub_buckets_within_attack_class(self):
        # Mix of sub-bucketed tags within attack-class.
        self._seed({
            "/t/a": ["xss", "csrf"],         # web-attacks
            "/t/b": ["subdomain-takeover"],  # subdomain
            "/t/c": ["vulnerability"],       # general
        })
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out, \
             mock.patch("sys.stderr", new_callable=io.StringIO):
            cmd_tags.run(self._args(grouping="grouped"))
        text = out.getvalue()
        # The bucket header is present:
        self.assertIn("[attack-class]", text)
        # And the sub-bucket headers appear in display order:
        self.assertIn("(web-attacks)", text)
        self.assertIn("(subdomain)", text)
        self.assertIn("(general)", text)
        self.assertLess(text.index("(web-attacks)"), text.index("(subdomain)"))
        self.assertLess(text.index("(subdomain)"), text.index("(general)"))

    def test_grouped_recon_sub_buckets(self):
        self._seed({
            "/t/a": ["dns", "subdomain"],         # dns + subdomain
            "/t/b": ["github-recon", "wayback"],  # web-recon
            "/t/c": ["osint"],                    # osint
        })
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out, \
             mock.patch("sys.stderr", new_callable=io.StringIO):
            cmd_tags.run(self._args(grouping="grouped"))
        text = out.getvalue()
        self.assertIn("[recon-technique]", text)
        self.assertIn("(subdomain)", text)
        self.assertIn("(dns)", text)
        self.assertIn("(web-recon)", text)
        self.assertIn("(osint)", text)

    def test_grouped_flat_buckets_have_no_sub_headers(self):
        # `language` doesn't define sub-buckets - no `(...)` grouping.
        self._seed({"/t/a": ["python", "golang"]})
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out, \
             mock.patch("sys.stderr", new_callable=io.StringIO):
            cmd_tags.run(self._args(grouping="grouped"))
        text = out.getvalue()
        self.assertIn("[language]", text)
        self.assertNotIn("(", text)  # no sub-bucket parens at all

    def test_json_includes_sub_bucket_field(self):
        self._seed({"/t/a": ["xss", "python"]})
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out, \
             mock.patch("sys.stderr", new_callable=io.StringIO):
            cmd_tags.run(self._args(json=True))
        data = json.loads(out.getvalue())
        by_name = {entry["name"]: entry for entry in data["tags"]}
        # xss is in attack-class -> web-attacks sub-bucket
        self.assertEqual(by_name["xss"]["sub_bucket"], "web-attacks")
        # python's bucket has no sub-buckets defined -> sub_bucket is None
        self.assertIsNone(by_name["python"]["sub_bucket"])

    def test_grouped_skips_empty_buckets(self):
        # A fleet with only language tags should produce only the
        # `[language]` section, no others.
        self._seed({"/t/a": ["python", "golang"]})
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out, \
             mock.patch("sys.stderr", new_callable=io.StringIO):
            cmd_tags.run(self._args(grouping="grouped"))
        text = out.getvalue()
        self.assertIn("[language]", text)
        self.assertNotIn("[discipline]", text)
        self.assertNotIn("[attack-class]", text)
        self.assertNotIn("[other]", text)

    def test_default_grouping_follows_isatty(self):
        self._seed({"/t/a": ["recon"]})
        # Force isatty=True -> grouped:
        with mock.patch("sys.stdout") as fake_stdout:
            fake_stdout.isatty.return_value = True
            buf = io.StringIO()
            fake_stdout.write = buf.write
            with mock.patch("sys.stderr", new_callable=io.StringIO):
                cmd_tags.run(self._args())
        self.assertIn("[discipline]", buf.getvalue())

        # Force isatty=False -> flat:
        with mock.patch("sys.stdout") as fake_stdout:
            fake_stdout.isatty.return_value = False
            buf = io.StringIO()
            fake_stdout.write = buf.write
            with mock.patch("sys.stderr", new_callable=io.StringIO):
                cmd_tags.run(self._args())
        self.assertNotIn("[discipline]", buf.getvalue())

    def test_json_includes_bucket_field(self):
        self._seed({"/t/a": ["xss", "python"]})
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out, \
             mock.patch("sys.stderr", new_callable=io.StringIO):
            cmd_tags.run(self._args(json=True))
        data = json.loads(out.getvalue())
        by_name = {entry["name"]: entry for entry in data["tags"]}
        self.assertEqual(by_name["xss"]["bucket"], "attack-class")
        self.assertEqual(by_name["python"]["bucket"], "language")

    def test_prune_flag_actually_prunes(self):
        self._seed({"/t/a": ["keep", "drop"]})
        with _index.connect(self.db) as conn:
            _index.remove_tags(conn, "/t/a", ["drop"])
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out, \
             mock.patch("sys.stderr", new_callable=io.StringIO):
            cmd_tags.run(self._args(prune_orphans=True, json=True))
        data = json.loads(out.getvalue())
        self.assertEqual(data["orphans_pruned"], 1)
        # Re-running shows nothing left to prune.
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out, \
             mock.patch("sys.stderr", new_callable=io.StringIO):
            cmd_tags.run(self._args(prune_orphans=True, json=True))
        data = json.loads(out.getvalue())
        self.assertEqual(data["orphans_pruned"], 0)


if __name__ == "__main__":
    unittest.main()
