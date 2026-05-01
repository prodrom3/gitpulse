"""Tests for core.upstream.

Network I/O is fully mocked: every test substitutes urllib.request.urlopen
for a fake that returns canned responses or raises canned exceptions.
"""

import io
import json
import unittest
import urllib.error
from unittest import mock

from core.auth import AuthConfig
from core.upstream import (
    GiteaProbe,
    GitHubProbe,
    GitLabProbe,
    HostNotAllowed,
    ProbeError,
    ProbeHTTPError,
    ProviderUnknown,
    parse_remote_url,
    probe_upstream,
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


class TestParseRemoteUrl(unittest.TestCase):
    def test_ssh_git_at(self):
        self.assertEqual(
            parse_remote_url("git@github.com:prodrom3/nostos.git"),
            ("github.com", "prodrom3", "nostos"),
        )

    def test_ssh_protocol(self):
        self.assertEqual(
            parse_remote_url("ssh://git@gitlab.com/group/project.git"),
            ("gitlab.com", "group", "project"),
        )

    def test_https_with_dotgit(self):
        self.assertEqual(
            parse_remote_url("https://github.com/prodrom3/nostos.git"),
            ("github.com", "prodrom3", "nostos"),
        )

    def test_https_no_dotgit(self):
        self.assertEqual(
            parse_remote_url("https://github.com/prodrom3/nostos"),
            ("github.com", "prodrom3", "nostos"),
        )

    def test_gitlab_subgroup(self):
        self.assertEqual(
            parse_remote_url("https://gitlab.com/group/sub/project.git"),
            ("gitlab.com", "group/sub", "project"),
        )

    def test_self_hosted(self):
        self.assertEqual(
            parse_remote_url("https://git.internal.corp/t/r.git"),
            ("git.internal.corp", "t", "r"),
        )

    def test_rejects_garbage(self):
        self.assertIsNone(parse_remote_url(""))
        self.assertIsNone(parse_remote_url("not-a-url"))
        self.assertIsNone(parse_remote_url("https://github.com/only-one-segment"))


class TestGitHubProbe(unittest.TestCase):
    def test_fetch_populates_fields(self):
        probe = GitHubProbe()
        repo_body = {
            "description": "desc",
            "stargazers_count": 100,
            "forks_count": 5,
            "open_issues_count": 3,
            "archived": False,
            "default_branch": "main",
            "pushed_at": "2026-04-10T00:00:00Z",
            "license": {"spdx_id": "MIT"},
            "topics": ["c2", "Redteam", "redteam", "", 42, "mythic"],
        }
        release_body = {"tag_name": "v1.2.3"}

        def fake_urlopen(req, timeout=15):
            url = req.full_url
            if url.endswith("/releases/latest"):
                return _ok(release_body)
            return _ok(repo_body, {"X-RateLimit-Remaining": "4999"})

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            result = probe.fetch("github.com", "prodrom3", "nostos", "ghp_xxx")
        self.assertEqual(result["stars"], 100)
        self.assertFalse(result["archived"])
        self.assertEqual(result["default_branch"], "main")
        self.assertEqual(result["last_push"], "2026-04-10T00:00:00Z")
        self.assertEqual(result["license"], "MIT")
        self.assertEqual(result["latest_release"], "v1.2.3")
        # Topics are lowercased, deduped, non-strings dropped.
        self.assertEqual(result["topics"], ["c2", "redteam", "mythic"])

    def test_fetch_topics_missing_returns_empty_list(self):
        probe = GitHubProbe()
        repo_body = {"archived": False, "default_branch": "main"}

        def fake_urlopen(req, timeout=15):
            if req.full_url.endswith("/releases/latest"):
                raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, io.BytesIO(b""))
            return _ok(repo_body)

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            result = probe.fetch("github.com", "o", "r", None)
        self.assertEqual(result["topics"], [])

    def test_sends_bearer_token(self):
        captured = []

        def fake_urlopen(req, timeout=15):
            captured.append(dict(req.header_items()))
            return _ok(
                {"archived": True, "default_branch": "main", "pushed_at": None, "license": None}
            )

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            GitHubProbe().fetch("github.com", "o", "r", "my_secret")

        # First call is repo; Authorization must be present, token must not leak into error paths.
        self.assertIn("Authorization", captured[0])
        self.assertIn("Bearer my_secret", captured[0]["Authorization"])

    def test_release_404_is_tolerated(self):
        def fake_urlopen(req, timeout=15):
            if req.full_url.endswith("/releases/latest"):
                raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, io.BytesIO(b""))
            return _ok({"archived": False})

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            result = GitHubProbe().fetch("github.com", "o", "r", None)
        self.assertIsNone(result["latest_release"])

    def test_401_raises_probe_http_error(self):
        def fake_urlopen(req, timeout=15):
            raise urllib.error.HTTPError(
                req.full_url, 401, "Unauthorized", {}, io.BytesIO(b'{"message":"bad token"}')
            )

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            with self.assertRaises(ProbeHTTPError) as cm:
                GitHubProbe().fetch("github.com", "o", "r", "bogus")
        self.assertEqual(cm.exception.status, 401)
        # Make sure the token never leaks into the exception message.
        self.assertNotIn("bogus", str(cm.exception))

    def test_timeout_raises_probe_error(self):
        def fake_urlopen(req, timeout=15):
            raise TimeoutError("deadline")

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            with self.assertRaises(ProbeError):
                GitHubProbe().fetch("github.com", "o", "r", None)

    def test_ghe_uses_v3_base(self):
        self.assertEqual(
            GitHubProbe.api_base("git.internal.corp"),
            "https://git.internal.corp/api/v3",
        )


class TestGitLabProbe(unittest.TestCase):
    def test_fetch_maps_fields(self):
        body = {
            "description": "d",
            "star_count": 7,
            "forks_count": 2,
            "open_issues_count": 1,
            "archived": False,
            "default_branch": "master",
            "last_activity_at": "2026-04-11T00:00:00Z",
            "license": {"key": "mit", "nickname": "MIT License"},
        }

        def fake_urlopen(req, timeout=15):
            if "/releases" in req.full_url:
                return _ok([{"tag_name": "v0.9"}])
            return _ok(body)

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            result = GitLabProbe().fetch("gitlab.com", "group", "project", None)
        self.assertEqual(result["stars"], 7)
        self.assertEqual(result["default_branch"], "master")
        self.assertEqual(result["license"], "MIT License")
        self.assertEqual(result["latest_release"], "v0.9")


class TestGiteaProbe(unittest.TestCase):
    def test_fetch_maps_fields(self):
        body = {
            "description": "d",
            "stars_count": 3,
            "forks_count": 1,
            "open_issues_count": 0,
            "archived": True,
            "default_branch": "main",
            "updated_at": "2026-03-01T00:00:00Z",
        }
        with mock.patch("urllib.request.urlopen", side_effect=lambda *a, **k: _ok(body)):
            result = GiteaProbe().fetch("git.corp", "t", "r", None)
        self.assertTrue(result["archived"])
        self.assertEqual(result["stars"], 3)
        self.assertEqual(result["last_push"], "2026-03-01T00:00:00Z")


class TestProbeUpstreamDispatcher(unittest.TestCase):
    def test_offline_kills_probe(self):
        cfg = AuthConfig(hosts={"github.com": {"token_env": "X"}})
        with self.assertRaises(ProbeError):
            probe_upstream("https://github.com/o/r.git", cfg, offline=True)

    def test_unknown_host_rejected(self):
        cfg = AuthConfig()  # no hosts, allow_unknown=False
        with self.assertRaises(HostNotAllowed):
            probe_upstream("https://random.example/o/r.git", cfg)

    def test_allow_unknown_permits_probe(self):
        # github.com has an implicit default provider even if not
        # listed in hosts; allow_unknown lets the call proceed.
        cfg = AuthConfig(hosts={}, allow_unknown=True)
        with mock.patch(
            "urllib.request.urlopen",
            side_effect=lambda *a, **k: _ok({"archived": False}),
        ):
            result = probe_upstream("https://github.com/o/r.git", cfg)
        self.assertEqual(result["provider"], "github")
        self.assertIn("fetched_at", result)

    def test_unknown_provider_on_configured_host(self):
        # Host listed but no provider (e.g. a home-grown host).
        cfg = AuthConfig(hosts={"odd.host.corp": {}})
        with self.assertRaises(ProviderUnknown):
            probe_upstream("https://odd.host.corp/o/r.git", cfg)

    def test_github_probe_selected(self):
        cfg = AuthConfig(hosts={"github.com": {}})
        with mock.patch(
            "urllib.request.urlopen",
            side_effect=lambda *a, **k: _ok({"archived": False, "default_branch": "main"}),
        ):
            result = probe_upstream("git@github.com:o/r.git", cfg)
        self.assertEqual(result["provider"], "github")
        self.assertEqual(result["host"], "github.com")
        self.assertEqual(result["owner"], "o")
        self.assertEqual(result["name"], "r")
        self.assertIsNotNone(result["fetched_at"])

    def test_gitlab_self_hosted_requires_explicit_provider(self):
        # host configured but provider not set -> no default for non-standard host
        cfg = AuthConfig(hosts={"gitlab.internal": {}})
        with self.assertRaises(ProviderUnknown):
            probe_upstream("https://gitlab.internal/g/p.git", cfg)

    def test_gitlab_self_hosted_with_explicit_provider(self):
        cfg = AuthConfig(
            hosts={"gitlab.internal": {"provider": "gitlab"}}
        )
        with mock.patch(
            "urllib.request.urlopen",
            side_effect=lambda *a, **k: _ok({"star_count": 5}),
        ):
            result = probe_upstream("https://gitlab.internal/g/p.git", cfg)
        self.assertEqual(result["provider"], "gitlab")
        self.assertEqual(result["stars"], 5)


if __name__ == "__main__":
    unittest.main()
