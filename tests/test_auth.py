import os
import sys
import tempfile
import unittest
from unittest import mock

from core import auth as _auth_mod
from core.auth import AuthConfig, _is_auth_file_safe, load_auth

_NEEDS_TOML = unittest.skipIf(
    _auth_mod._toml is None,
    "no TOML parser available (Python 3.10 without tomli); auth.toml "
    "loading is fail-closed by design in this environment",
)


def _write(tmp: str, body: str, mode: int = 0o600) -> str:
    p = os.path.join(tmp, "auth.toml")
    with open(p, "w") as f:
        f.write(body)
    if sys.platform != "win32":
        os.chmod(p, mode)
    return p


class TestAuthConfigObject(unittest.TestCase):
    def test_provider_defaults(self):
        cfg = AuthConfig(hosts={"github.com": {}, "gitlab.com": {}})
        self.assertEqual(cfg.provider_for("github.com"), "github")
        self.assertEqual(cfg.provider_for("gitlab.com"), "gitlab")

    def test_provider_override(self):
        cfg = AuthConfig(hosts={"git.internal": {"provider": "gitea"}})
        self.assertEqual(cfg.provider_for("git.internal"), "gitea")

    def test_provider_unknown_returns_none(self):
        cfg = AuthConfig()
        self.assertIsNone(cfg.provider_for("unknown.example"))

    def test_resolve_token_env(self):
        cfg = AuthConfig(hosts={"github.com": {"token_env": "GH_TEST_TOK"}})
        with mock.patch.dict(os.environ, {"GH_TEST_TOK": "ghp_secret"}):
            self.assertEqual(cfg.resolve_token("github.com"), "ghp_secret")

    def test_resolve_token_env_missing_returns_none(self):
        cfg = AuthConfig(hosts={"github.com": {"token_env": "NOT_SET_ANYWHERE_123"}})
        env = {k: v for k, v in os.environ.items() if k != "NOT_SET_ANYWHERE_123"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertIsNone(cfg.resolve_token("github.com"))

    def test_resolve_token_inline(self):
        cfg = AuthConfig(hosts={"github.com": {"token": "ghp_inline"}})
        self.assertEqual(cfg.resolve_token("github.com"), "ghp_inline")

    def test_token_env_takes_precedence_over_inline(self):
        cfg = AuthConfig(
            hosts={
                "github.com": {
                    "token_env": "GH_TEST_TOK",
                    "token": "ghp_inline",
                }
            }
        )
        with mock.patch.dict(os.environ, {"GH_TEST_TOK": "ghp_env"}):
            self.assertEqual(cfg.resolve_token("github.com"), "ghp_env")

    def test_resolve_token_unknown_host(self):
        cfg = AuthConfig()
        self.assertIsNone(cfg.resolve_token("anything.example"))

    def test_is_allowed_default_fail_closed(self):
        cfg = AuthConfig(hosts={"github.com": {}})
        self.assertTrue(cfg.is_allowed("github.com"))
        self.assertFalse(cfg.is_allowed("random.example"))

    def test_is_allowed_with_allow_unknown(self):
        cfg = AuthConfig(hosts={}, allow_unknown=True)
        self.assertTrue(cfg.is_allowed("random.example"))


class TestLoadAuth(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_missing_file_returns_empty(self):
        cfg = load_auth(os.path.join(self.tmp, "nothing.toml"))
        self.assertEqual(cfg.hosts, {})
        self.assertFalse(cfg.allow_unknown)

    @_NEEDS_TOML
    def test_parses_full_config(self):
        body = """
[hosts."github.com"]
token_env = "GITHUB_TOKEN"

[hosts."gitlab.internal"]
provider  = "gitlab"
token_env = "CORP_GITLAB_TOKEN"

[defaults]
allow_unknown = true
"""
        cfg = load_auth(_write(self.tmp, body))
        self.assertIn("github.com", cfg.hosts)
        self.assertIn("gitlab.internal", cfg.hosts)
        self.assertEqual(cfg.hosts["github.com"]["token_env"], "GITHUB_TOKEN")
        self.assertEqual(cfg.hosts["gitlab.internal"]["provider"], "gitlab")
        self.assertTrue(cfg.allow_unknown)

    def test_malformed_toml_returns_empty(self):
        cfg = load_auth(_write(self.tmp, "this is not [toml"))
        self.assertEqual(cfg.hosts, {})
        self.assertFalse(cfg.allow_unknown)

    @unittest.skipIf(sys.platform == "win32", "Unix-only perm check")
    def test_rejects_world_readable(self):
        path = _write(self.tmp, '[hosts."x"]\n', mode=0o644)
        cfg = load_auth(path)
        self.assertEqual(cfg.hosts, {})

    @unittest.skipIf(sys.platform == "win32", "Unix-only perm check")
    def test_rejects_world_writable(self):
        path = _write(self.tmp, '[hosts."x"]\n', mode=0o602)
        cfg = load_auth(path)
        self.assertEqual(cfg.hosts, {})

    @_NEEDS_TOML
    @unittest.skipIf(sys.platform == "win32", "Unix-only perm check")
    def test_accepts_0600(self):
        path = _write(self.tmp, '[hosts."github.com"]\n', mode=0o600)
        cfg = load_auth(path)
        self.assertIn("github.com", cfg.hosts)

    def test_nonexistent_path_is_unsafe(self):
        self.assertFalse(_is_auth_file_safe("/nonexistent/path"))


if __name__ == "__main__":
    unittest.main()
