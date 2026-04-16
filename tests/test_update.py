"""Tests for the self-update module and the update subcommand."""

import argparse
import io
import json
import unittest
import urllib.error
from unittest import mock

from core import updater_self as _self
from core.commands import update as cmd_update


class _Response:
    def __init__(self, body, headers=None):
        self._body = body.encode("utf-8") if isinstance(body, str) else body
        self.headers = headers or {}

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def _release_body(tag: str):
    return _Response(json.dumps({"tag_name": tag, "name": f"Release {tag}"}))


class TestVersionMath(unittest.TestCase):
    def test_normalize_variants(self):
        self.assertEqual(_self.normalize_tag("v2.4.0"), "2.4.0")
        self.assertEqual(_self.normalize_tag("2.4.0"), "2.4.0")
        self.assertEqual(_self.normalize_tag("release-2.4.0"), "2.4.0")

    def test_normalize_rejects_garbage(self):
        with self.assertRaises(_self.UpdateError):
            _self.normalize_tag("not-a-version")

    def test_version_tuple_rejects_malformed(self):
        with self.assertRaises(_self.UpdateError):
            _self.version_tuple("2.4")
        with self.assertRaises(_self.UpdateError):
            _self.version_tuple("2.4.x")

    def test_is_newer(self):
        self.assertTrue(_self.is_newer("2.4.0", "2.3.0"))
        self.assertTrue(_self.is_newer("2.4.1", "2.4.0"))
        self.assertFalse(_self.is_newer("2.3.0", "2.4.0"))
        self.assertFalse(_self.is_newer("2.4.0", "2.4.0"))

    def test_is_newer_returns_false_on_malformed(self):
        self.assertFalse(_self.is_newer("garbage", "2.4.0"))


class TestFetchLatestRelease(unittest.TestCase):
    def test_parses_valid_response(self):
        with mock.patch(
            "urllib.request.urlopen", side_effect=lambda *a, **k: _release_body("v2.4.0")
        ):
            data = _self.fetch_latest_release()
        self.assertEqual(data["tag_name"], "v2.4.0")

    def test_sends_bearer_token_when_given(self):
        captured = []

        def fake(req, timeout=10):
            captured.append(dict(req.header_items()))
            return _release_body("v2.4.0")

        with mock.patch("urllib.request.urlopen", side_effect=fake):
            _self.fetch_latest_release(token="ghp_test")
        self.assertIn("Authorization", captured[0])
        self.assertIn("Bearer ghp_test", captured[0]["Authorization"])

    def test_http_error_raises(self):
        import io as _io

        def raise_http(*a, **k):
            raise urllib.error.HTTPError(
                "u", 500, "Server Error", {}, _io.BytesIO(b"")
            )

        with mock.patch("urllib.request.urlopen", side_effect=raise_http):
            with self.assertRaises(_self.UpdateError):
                _self.fetch_latest_release()

    def test_timeout_raises(self):
        with mock.patch("urllib.request.urlopen", side_effect=TimeoutError("deadline")):
            with self.assertRaises(_self.UpdateError):
                _self.fetch_latest_release()


class TestDetectInstallMethod(unittest.TestCase):
    def test_reports_source_when_repo_root(self):
        # Our test runner IS in the repo, so detection must find it.
        d = _self.detect_install_method()
        self.assertEqual(d["method"], "source")
        self.assertIn("git -C", d["upgrade_cmd"])
        self.assertIsNotNone(d["source_dir"])

    def test_falls_back_to_pipx_when_not_a_repo(self):
        with mock.patch("core.updater_self._looks_like_nostos_repo", return_value=False), mock.patch(
            "core.updater_self._pipx_has_nostos", return_value=True
        ):
            d = _self.detect_install_method()
        self.assertEqual(d["method"], "pipx")
        self.assertEqual(d["upgrade_cmd"], "pipx upgrade nostos")

    def test_falls_back_to_pip_when_neither(self):
        with mock.patch("core.updater_self._looks_like_nostos_repo", return_value=False), mock.patch(
            "core.updater_self._pipx_has_nostos", return_value=False
        ):
            d = _self.detect_install_method()
        self.assertEqual(d["method"], "pip")
        self.assertIn("pip install", d["upgrade_cmd"])


class TestRunUpgrade(unittest.TestCase):
    def test_source_runs_git_pull(self):
        with mock.patch("subprocess.run") as mr:
            mr.return_value = mock.Mock(returncode=0, stdout="Fast-forward", stderr="")
            out = _self.run_upgrade(
                {"method": "source", "source_dir": "/tmp/gp", "upgrade_cmd": ""}
            )
        mr.assert_called_once()
        called = mr.call_args[0][0]
        self.assertEqual(called[:2], ["git", "-C"])
        self.assertIn("/tmp/gp", called)
        self.assertIn("Fast-forward", out)

    def test_pipx_runs_pipx_upgrade(self):
        with mock.patch("subprocess.run") as mr:
            mr.return_value = mock.Mock(returncode=0, stdout="upgraded", stderr="")
            _self.run_upgrade({"method": "pipx", "source_dir": None, "upgrade_cmd": ""})
        called = mr.call_args[0][0]
        self.assertEqual(called, ["pipx", "upgrade", "nostos"])

    def test_pip_raises_instead_of_running(self):
        with self.assertRaises(_self.UpdateError):
            _self.run_upgrade(
                {"method": "pip", "source_dir": None,
                 "upgrade_cmd": "pip install --upgrade ..."}
            )

    def test_nonzero_return_code_raises(self):
        with mock.patch("subprocess.run") as mr:
            mr.return_value = mock.Mock(returncode=1, stdout="", stderr="boom")
            with self.assertRaises(_self.UpdateError):
                _self.run_upgrade(
                    {"method": "source", "source_dir": "/tmp/x", "upgrade_cmd": ""}
                )


class TestVerifyReleaseTag(unittest.TestCase):
    def test_valid_signature(self):
        with mock.patch("subprocess.run") as mr:
            # First call is fetch --tags; second is verify-tag
            mr.side_effect = [
                mock.Mock(returncode=0, stdout="", stderr=""),
                mock.Mock(returncode=0, stdout="Good signature", stderr=""),
            ]
            ok, out = _self.verify_release_tag("2.5.0", "/tmp/gp")
        self.assertTrue(ok)
        self.assertIn("Good signature", out)
        # verify-tag must use v-prefixed tag
        verify_call = mr.call_args_list[1][0][0]
        self.assertIn("v2.5.0", verify_call)

    def test_invalid_signature(self):
        with mock.patch("subprocess.run") as mr:
            mr.side_effect = [
                mock.Mock(returncode=0, stdout="", stderr=""),
                mock.Mock(returncode=1, stdout="", stderr="BAD signature"),
            ]
            ok, out = _self.verify_release_tag("2.5.0", "/tmp/gp")
        self.assertFalse(ok)
        self.assertIn("BAD signature", out)

    def test_already_vprefixed_tag(self):
        with mock.patch("subprocess.run") as mr:
            mr.side_effect = [
                mock.Mock(returncode=0, stdout="", stderr=""),
                mock.Mock(returncode=0, stdout="ok", stderr=""),
            ]
            _self.verify_release_tag("v2.5.0", "/tmp/gp")
        # Should NOT double-prefix to vv2.5.0
        verify_call = mr.call_args_list[1][0][0]
        self.assertIn("v2.5.0", verify_call)
        self.assertNotIn("vv2.5.0", " ".join(verify_call))

    def test_git_not_found_raises(self):
        with mock.patch("subprocess.run", side_effect=FileNotFoundError("git")):
            with self.assertRaises(_self.UpdateError):
                _self.verify_release_tag("2.5.0", "/tmp/gp")


class TestUpdateCommand(unittest.TestCase):
    def _args(self, **overrides):
        base = {"check": False, "offline": False, "yes": False, "verify": False}
        base.update(overrides)
        return argparse.Namespace(**base)

    def test_offline_prints_and_returns_zero(self):
        with mock.patch("core.commands._common.maybe_migrate_watchlist"), mock.patch(
            "sys.stdout", new_callable=io.StringIO
        ) as out, mock.patch("sys.stderr", new_callable=io.StringIO):
            rc = cmd_update.run(self._args(offline=True))
        self.assertEqual(rc, 0)
        self.assertIn("nostos", out.getvalue())
        self.assertIn("upgrade_cmd", out.getvalue())

    def test_check_reports_up_to_date(self):
        with mock.patch("core.commands._common.maybe_migrate_watchlist"), mock.patch(
            "core.commands.update._self.fetch_latest_release",
            return_value={"tag_name": "v0.0.1"},  # older than our local
        ), mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            rc = cmd_update.run(self._args(check=True))
        self.assertEqual(rc, 0)
        self.assertIn("up to date", out.getvalue())

    def test_check_reports_update_available(self):
        with mock.patch("core.commands._common.maybe_migrate_watchlist"), mock.patch(
            "core.cli.get_version", return_value="2.4.0"
        ), mock.patch(
            "core.commands.update._self.fetch_latest_release",
            return_value={"tag_name": "v99.99.99"},
        ), mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            rc = cmd_update.run(self._args(check=True))
        self.assertEqual(rc, 0)
        self.assertIn("update available", out.getvalue())

    def test_network_error_fails_cleanly(self):
        with mock.patch("core.commands._common.maybe_migrate_watchlist"), mock.patch(
            "core.commands.update._self.fetch_latest_release",
            side_effect=_self.UpdateError("network error"),
        ), mock.patch("sys.stderr", new_callable=io.StringIO):
            rc = cmd_update.run(self._args(check=True))
        self.assertEqual(rc, 1)

    def test_pip_install_method_prints_manual_instructions(self):
        """When an upgrade is available but install method is 'pip',
        the command prints manual guidance and returns 0 without
        running anything."""
        with mock.patch("core.commands._common.maybe_migrate_watchlist"), mock.patch(
            "core.cli.get_version", return_value="2.3.0"
        ), mock.patch(
            "core.commands.update._self.detect_install_method",
            return_value={
                "method": "pip", "source_dir": None,
                "upgrade_cmd": "pip install --upgrade x", "notes": "n",
            },
        ), mock.patch(
            "core.commands.update._self.fetch_latest_release",
            return_value={"tag_name": "v2.4.0"},
        ), mock.patch("sys.stdout", new_callable=io.StringIO), mock.patch(
            "sys.stderr", new_callable=io.StringIO
        ) as err:
            rc = cmd_update.run(self._args())
        self.assertEqual(rc, 0)
        self.assertIn("Automatic upgrade is not supported", err.getvalue())

    def test_yes_skips_confirm(self):
        with mock.patch("core.commands._common.maybe_migrate_watchlist"), mock.patch(
            "core.cli.get_version", return_value="2.3.0"
        ), mock.patch(
            "core.commands.update._self.detect_install_method",
            return_value={
                "method": "source", "source_dir": "/tmp/gp",
                "upgrade_cmd": "git -C /tmp/gp pull --ff-only", "notes": "",
            },
        ), mock.patch(
            "core.commands.update._self.fetch_latest_release",
            return_value={"tag_name": "v2.4.0"},
        ), mock.patch(
            "core.commands.update._self.run_upgrade",
            return_value="Fast-forward",
        ), mock.patch("builtins.input", side_effect=AssertionError("input must not be called")), mock.patch(
            "sys.stdout", new_callable=io.StringIO
        ), mock.patch("sys.stderr", new_callable=io.StringIO):
            rc = cmd_update.run(self._args(yes=True))
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
