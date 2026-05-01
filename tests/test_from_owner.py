"""Tests for `nostos add --from-owner` and the underlying
core.upstream.list_owner_repos helper."""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import tempfile
import unittest
import urllib.error
from unittest import mock

from core import index
from core.auth import AuthConfig
from core.commands import add as cmd_add
from core.topic_rules import TopicRules
from core.upstream import (
    ProbeHTTPError,
    list_owner_repos,
)


class _Response:
    def __init__(self, body, headers=None):
        self._body = body.encode("utf-8") if isinstance(body, str) else body
        self.headers = headers or {}

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _ok(json_body, headers=None):
    return _Response(json.dumps(json_body), headers=headers or {})


# ---------- list_owner_repos ----------


class TestListOwnerRepos(unittest.TestCase):
    def _stub_repos(self, n: int, *, fork=False, archived=False, lang="Go", stars=10):
        return [
            {
                "name": f"repo{i}",
                "full_name": f"owner/repo{i}",
                "clone_url": f"https://github.com/owner/repo{i}.git",
                "html_url": f"https://github.com/owner/repo{i}",
                "fork": fork,
                "archived": archived,
                "language": lang,
                "stargazers_count": stars + i,
                "topics": ["pentest"],
                "description": None,
                "default_branch": "main",
            }
            for i in range(n)
        ]

    def test_user_endpoint_happy_path(self):
        bodies = [self._stub_repos(3), []]

        def fake_urlopen(req, timeout=None):
            url = req.full_url
            self.assertIn("/users/owner/repos", url)
            body = bodies.pop(0)
            return _ok(body)

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            out = list_owner_repos("github.com", "owner", token="t")
        self.assertEqual(len(out), 3)
        self.assertEqual(out[0]["full_name"], "owner/repo0")

    def test_falls_back_to_org_endpoint_on_404(self):
        seen_urls: list[str] = []

        def fake_urlopen(req, timeout=None):
            seen_urls.append(req.full_url)
            if "/users/" in req.full_url:
                raise urllib.error.HTTPError(
                    req.full_url, 404, "Not Found", {}, io.BytesIO(b"")
                )
            return _ok(self._stub_repos(2))

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            out = list_owner_repos("github.com", "the-org", token="t")
        self.assertEqual(len(out), 2)
        self.assertTrue(any("/users/the-org/" in u for u in seen_urls))
        self.assertTrue(any("/orgs/the-org/" in u for u in seen_urls))

    def test_404_on_both_endpoints_raises(self):
        def fake_urlopen(req, timeout=None):
            raise urllib.error.HTTPError(
                req.full_url, 404, "Not Found", {}, io.BytesIO(b"")
            )

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            with self.assertRaises(ProbeHTTPError) as cm:
                list_owner_repos("github.com", "ghost", token=None)
        self.assertEqual(cm.exception.status, 404)

    def test_filters_forks_by_default(self):
        body = self._stub_repos(2) + self._stub_repos(2, fork=True)

        def fake_urlopen(req, timeout=None):
            return _ok(body if "page=1" in req.full_url else [])

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            out = list_owner_repos("github.com", "owner", token=None)
        self.assertEqual(len(out), 2)
        self.assertTrue(all(not r["fork"] for r in out))

    def test_include_forks(self):
        body = self._stub_repos(1) + self._stub_repos(1, fork=True)

        def fake_urlopen(req, timeout=None):
            return _ok(body if "page=1" in req.full_url else [])

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            out = list_owner_repos("github.com", "owner", token=None, include_forks=True)
        self.assertEqual(len(out), 2)

    def test_filters_archived_by_default(self):
        body = self._stub_repos(2) + self._stub_repos(2, archived=True)

        def fake_urlopen(req, timeout=None):
            return _ok(body if "page=1" in req.full_url else [])

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            out = list_owner_repos("github.com", "owner", token=None)
        self.assertEqual(len(out), 2)
        self.assertTrue(all(not r["archived"] for r in out))


# ---------- _filter_owner_repos ----------


class TestFilters(unittest.TestCase):
    def _r(self, name="repo", lang="Go", stars=0):
        return {"name": name, "language": lang, "stargazers_count": stars}

    def test_match_regex(self):
        repos = [self._r("nuclei"), self._r("httpx"), self._r("naabu")]
        out = cmd_add._filter_owner_repos(
            repos, match="^n", lang=None, limit=None
        )
        self.assertEqual([r["name"] for r in out], ["nuclei", "naabu"])

    def test_invalid_regex_raises(self):
        with self.assertRaises(ValueError):
            cmd_add._filter_owner_repos(
                [self._r()], match="(unclosed", lang=None, limit=None
            )

    def test_lang_case_insensitive(self):
        repos = [
            self._r("a", lang="Go"),
            self._r("b", lang="Python"),
            self._r("c", lang="GO"),
        ]
        out = cmd_add._filter_owner_repos(repos, match=None, lang="go", limit=None)
        self.assertEqual({r["name"] for r in out}, {"a", "c"})

    def test_limit_takes_top_by_stars(self):
        repos = [
            self._r("a", stars=1),
            self._r("b", stars=5),
            self._r("c", stars=3),
        ]
        out = cmd_add._filter_owner_repos(repos, match=None, lang=None, limit=2)
        self.assertEqual([r["name"] for r in out], ["b", "c"])

    def test_no_filters_returns_input_unchanged(self):
        repos = [self._r("a"), self._r("b")]
        out = cmd_add._filter_owner_repos(
            repos, match=None, lang=None, limit=None
        )
        self.assertEqual(out, repos)


# ---------- end-to-end nostos add --from-owner ----------


class TestAddFromOwner(unittest.TestCase):
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

    def _args(self, **overrides):
        clone_dir = os.path.join(self.tmp, "clones")
        os.makedirs(clone_dir, exist_ok=True)
        base = {
            "target": None,
            "tag": ["recon"],
            "source": None,
            "note": None,
            "status": "new",
            "quiet_upstream": False,
            "auto_tags": False,
            "clone_dir": clone_dir,
            "from_owner": "projectdiscovery",
            "include_forks": False,
            "include_archived": False,
            "limit": None,
            "match": None,
            "lang": None,
        }
        base.update(overrides)
        return argparse.Namespace(**base)

    def _stub_repos(self, names, **defaults):
        return [
            {
                "name": n,
                "full_name": f"projectdiscovery/{n}",
                "clone_url": f"https://github.com/projectdiscovery/{n}.git",
                "html_url": f"https://github.com/projectdiscovery/{n}",
                "fork": defaults.get("fork", False),
                "archived": defaults.get("archived", False),
                "language": defaults.get("language", "Go"),
                "stargazers_count": defaults.get("stars", 100),
                "topics": [],
                "description": None,
                "default_branch": "main",
            }
            for n in names
        ]

    def _seed_clone_dir(self, *names: str) -> dict[str, str]:
        """Pre-create fake clone targets so clone_repo's "already cloned"
        path triggers and no real git is invoked."""
        out = {}
        clone_dir = os.path.join(self.tmp, "clones")
        for name in names:
            target = os.path.join(clone_dir, name)
            os.makedirs(os.path.join(target, ".git"))
            out[name] = target
        return out

    def test_happy_path_adds_each_repo(self):
        names = ["nuclei", "httpx", "naabu"]
        self._seed_clone_dir(*names)
        repos = self._stub_repos(names)

        with mock.patch(
            "core.commands.add.list_owner_repos", return_value=repos
        ), mock.patch(
            "core.commands.add.load_auth",
            return_value=AuthConfig(hosts={"github.com": {}}),
        ), mock.patch(
            "core.commands.add.load_topic_rules", return_value=TopicRules(),
        ), mock.patch("sys.stderr", new_callable=io.StringIO):
            rc = cmd_add.run(self._args())
        self.assertEqual(rc, 0)
        with index.connect(self.db) as conn:
            rows = index.list_repos(conn)
        self.assertEqual(len(rows), 3)
        for row in rows:
            self.assertIn("recon", row["tags"])

    def test_match_filter_narrows_set(self):
        self._seed_clone_dir("nuclei", "naabu")
        repos = self._stub_repos(["nuclei", "httpx", "naabu"])

        with mock.patch(
            "core.commands.add.list_owner_repos", return_value=repos
        ), mock.patch(
            "core.commands.add.load_auth",
            return_value=AuthConfig(hosts={"github.com": {}}),
        ), mock.patch(
            "core.commands.add.load_topic_rules", return_value=TopicRules(),
        ), mock.patch("sys.stderr", new_callable=io.StringIO):
            cmd_add.run(self._args(match="^n"))
        with index.connect(self.db) as conn:
            paths = sorted(r["path"] for r in index.list_repos(conn))
        self.assertEqual(len(paths), 2)
        self.assertTrue(all("nuclei" in p or "naabu" in p for p in paths))

    def test_limit_caps_top_n_by_stars(self):
        self._seed_clone_dir("alpha", "beta")
        repos = [
            *self._stub_repos(["alpha"], stars=10),
            *self._stub_repos(["beta"], stars=5),
            *self._stub_repos(["gamma"], stars=1),
        ]

        with mock.patch(
            "core.commands.add.list_owner_repos", return_value=repos
        ), mock.patch(
            "core.commands.add.load_auth",
            return_value=AuthConfig(hosts={"github.com": {}}),
        ), mock.patch(
            "core.commands.add.load_topic_rules", return_value=TopicRules(),
        ), mock.patch("sys.stderr", new_callable=io.StringIO):
            cmd_add.run(self._args(limit=2))
        with index.connect(self.db) as conn:
            paths = {os.path.basename(r["path"]) for r in index.list_repos(conn)}
        self.assertEqual(paths, {"alpha", "beta"})

    def test_unconfigured_host_fails_closed(self):
        with mock.patch(
            "core.commands.add.load_auth", return_value=AuthConfig(),
        ), mock.patch("core.commands.add.list_owner_repos") as mock_list, \
             mock.patch("sys.stderr", new_callable=io.StringIO):
            rc = cmd_add.run(self._args())
        self.assertEqual(rc, 1)
        mock_list.assert_not_called()

    def test_unknown_owner_returns_clean_error(self):
        with mock.patch(
            "core.commands.add.list_owner_repos",
            side_effect=ProbeHTTPError(404, "Not Found"),
        ), mock.patch(
            "core.commands.add.load_auth",
            return_value=AuthConfig(hosts={"github.com": {}}),
        ), mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            rc = cmd_add.run(self._args())
        self.assertEqual(rc, 1)
        self.assertIn("not found", err.getvalue().lower())

    def test_target_and_from_owner_mutually_exclusive(self):
        with mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            rc = cmd_add.run(self._args(target="/some/path"))
        self.assertEqual(rc, 1)
        self.assertIn("mutually exclusive", err.getvalue())


if __name__ == "__main__":
    unittest.main()
