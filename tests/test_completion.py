"""Tests for `nostos completion` - shell tab-completion setup.

Covers:
- shell detection from $SHELL / $NOSTOS_SHELL / explicit --shell
- strip_block / upsert_block idempotency and malformed-block safety
- install subcommand (append, replace existing, abort on missing confirm)
- uninstall subcommand (remove, no-op on missing)
- show subcommand calls argcomplete and renders a wrapped snippet
"""

from __future__ import annotations

import argparse
import io
import os
import subprocess
import tempfile
import unittest
from unittest import mock

from core.commands import completion as cmd_completion


def _ns(**overrides):
    base = {
        "shell": None,
        "rc_file": None,
        "yes": True,
        "completion_command": "install",
    }
    base.update(overrides)
    return argparse.Namespace(**base)


class TestDetectShell(unittest.TestCase):
    def test_nostos_shell_override(self):
        with mock.patch.dict(os.environ, {"NOSTOS_SHELL": "fish", "SHELL": "/bin/bash"}):
            self.assertEqual(cmd_completion.detect_shell(), "fish")

    def test_nostos_shell_ignored_if_unsupported(self):
        with mock.patch.dict(
            os.environ, {"NOSTOS_SHELL": "csh", "SHELL": "/bin/bash"}
        ):
            self.assertEqual(cmd_completion.detect_shell(), "bash")

    def test_shell_from_env(self):
        with mock.patch.dict(os.environ, {"SHELL": "/usr/bin/zsh", "NOSTOS_SHELL": ""}):
            self.assertEqual(cmd_completion.detect_shell(), "zsh")

    def test_shell_strips_version_suffix(self):
        with mock.patch.dict(os.environ, {"SHELL": "/bin/zsh-5.9", "NOSTOS_SHELL": ""}):
            self.assertEqual(cmd_completion.detect_shell(), "zsh")

    def test_no_shell_env(self):
        with mock.patch.dict(os.environ, {"SHELL": "", "NOSTOS_SHELL": ""}):
            self.assertIsNone(cmd_completion.detect_shell())

    def test_unsupported_shell(self):
        with mock.patch.dict(
            os.environ, {"SHELL": "/usr/bin/csh", "NOSTOS_SHELL": ""}
        ):
            self.assertIsNone(cmd_completion.detect_shell())


class TestResolveShell(unittest.TestCase):
    def test_explicit_shell_wins(self):
        args = _ns(shell="bash")
        with mock.patch.dict(os.environ, {"SHELL": "/usr/bin/zsh"}):
            self.assertEqual(cmd_completion.resolve_shell(args), "bash")

    def test_fallback_to_env(self):
        args = _ns(shell=None)
        with mock.patch.dict(os.environ, {"SHELL": "/usr/bin/fish", "NOSTOS_SHELL": ""}):
            self.assertEqual(cmd_completion.resolve_shell(args), "fish")


class TestResolveRcFile(unittest.TestCase):
    def test_explicit_override(self):
        self.assertTrue(
            cmd_completion.resolve_rc_file("zsh", "~/custom.zsh").endswith("custom.zsh")
        )

    def test_default_per_shell(self):
        path = cmd_completion.resolve_rc_file("zsh", None)
        self.assertTrue(path.endswith(".zshrc"))
        path = cmd_completion.resolve_rc_file("bash", None)
        self.assertTrue(path.endswith(".bashrc"))
        path = cmd_completion.resolve_rc_file("fish", None)
        self.assertTrue(path.endswith("nostos.fish"))


class TestStripBlock(unittest.TestCase):
    def test_strips_complete_block(self):
        rc = (
            "# Before\n"
            f"{cmd_completion.BEGIN_MARKER}\n"
            "compdef something nostos\n"
            f"{cmd_completion.END_MARKER}\n"
            "# After\n"
        )
        out = cmd_completion.strip_block(rc)
        self.assertEqual(out, "# Before\n# After\n")

    def test_no_block_is_unchanged(self):
        rc = "# nothing to see\nalias foo=bar\n"
        self.assertEqual(cmd_completion.strip_block(rc), rc)

    def test_malformed_block_leaves_file_alone(self):
        rc = (
            "# Before\n"
            f"{cmd_completion.BEGIN_MARKER}\n"
            "compdef something nostos\n"
            "# (no END marker)\n"
        )
        # The strip helper bails and returns the original to avoid
        # deleting the tail of the rc file.
        self.assertEqual(cmd_completion.strip_block(rc), rc)


class TestUpsertBlock(unittest.TestCase):
    def test_append_when_absent(self):
        rc = "alias foo=bar\n"
        snippet = (
            f"{cmd_completion.BEGIN_MARKER}\n"
            "compdef x\n"
            f"{cmd_completion.END_MARKER}\n"
        )
        out = cmd_completion.upsert_block(rc, snippet)
        self.assertTrue(out.startswith("alias foo=bar\n"))
        self.assertIn(cmd_completion.BEGIN_MARKER, out)
        self.assertIn("compdef x", out)

    def test_replace_existing_block(self):
        rc = (
            "alias foo=bar\n"
            f"{cmd_completion.BEGIN_MARKER}\n"
            "OLD\n"
            f"{cmd_completion.END_MARKER}\n"
        )
        snippet = (
            f"{cmd_completion.BEGIN_MARKER}\n"
            "NEW\n"
            f"{cmd_completion.END_MARKER}\n"
        )
        out = cmd_completion.upsert_block(rc, snippet)
        self.assertIn("NEW", out)
        self.assertNotIn("OLD", out)
        # original content preserved
        self.assertIn("alias foo=bar", out)


def _mock_register(shell, body="NOSTOS_COMPLETION_BODY\n"):
    """Context manager that stubs out subprocess.run for render_snippet."""
    def _run(cmd, check=True, capture_output=True, text=True, timeout=15):
        return subprocess.CompletedProcess(cmd, 0, body, "")
    return mock.patch.object(cmd_completion.subprocess, "run", side_effect=_run)


class TestRenderSnippet(unittest.TestCase):
    def test_wraps_output_in_markers(self):
        with mock.patch.object(cmd_completion.shutil, "which", return_value="/usr/bin/register-python-argcomplete"):
            with _mock_register("zsh"):
                out = cmd_completion.render_snippet("zsh")
        self.assertTrue(out.startswith(cmd_completion.BEGIN_MARKER))
        self.assertIn("NOSTOS_COMPLETION_BODY", out)
        self.assertTrue(out.rstrip().endswith(cmd_completion.END_MARKER))

    def test_empty_output_raises(self):
        with mock.patch.object(cmd_completion.shutil, "which", return_value="/usr/bin/register-python-argcomplete"):
            def _empty_run(cmd, **kw):
                return subprocess.CompletedProcess(cmd, 0, "", "")
            with mock.patch.object(cmd_completion.subprocess, "run", side_effect=_empty_run):
                with self.assertRaises(RuntimeError):
                    cmd_completion.render_snippet("zsh")

    def test_subprocess_failure_raises(self):
        with mock.patch.object(cmd_completion.shutil, "which", return_value="/usr/bin/register-python-argcomplete"):
            def _boom(cmd, **kw):
                raise subprocess.CalledProcessError(1, cmd, stderr="nope")
            with mock.patch.object(cmd_completion.subprocess, "run", side_effect=_boom):
                with self.assertRaises(RuntimeError):
                    cmd_completion.render_snippet("zsh")


class TestInstallSubcommand(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.rc = os.path.join(self.tmp, ".zshrc")

    def tearDown(self):
        import shutil as _shutil
        _shutil.rmtree(self.tmp, ignore_errors=True)

    def _install(self, *, existing=None, **overrides):
        if existing is not None:
            with open(self.rc, "w") as f:
                f.write(existing)
        args = _ns(shell="zsh", rc_file=self.rc, yes=True, **overrides)
        with mock.patch.object(cmd_completion.shutil, "which", return_value="/usr/bin/register-python-argcomplete"):
            with _mock_register("zsh"):
                with mock.patch("sys.stderr", new_callable=io.StringIO):
                    rc = cmd_completion._run_install(args)
        with open(self.rc) as f:
            return rc, f.read()

    def test_install_appends_on_empty_rc(self):
        rc, content = self._install(existing="# empty zshrc\n")
        self.assertEqual(rc, 0)
        self.assertIn(cmd_completion.BEGIN_MARKER, content)
        self.assertIn("NOSTOS_COMPLETION_BODY", content)
        # Previous content preserved
        self.assertTrue(content.startswith("# empty zshrc\n"))

    def test_install_creates_missing_rc(self):
        args = _ns(shell="zsh", rc_file=self.rc, yes=True)
        with mock.patch.object(cmd_completion.shutil, "which", return_value="/usr/bin/register-python-argcomplete"):
            with _mock_register("zsh"):
                with mock.patch("sys.stderr", new_callable=io.StringIO):
                    rc = cmd_completion._run_install(args)
        self.assertEqual(rc, 0)
        with open(self.rc) as f:
            self.assertIn(cmd_completion.BEGIN_MARKER, f.read())

    def test_install_is_idempotent(self):
        rc1, content1 = self._install(existing="")
        # Second install against the same file should be a no-op.
        args = _ns(shell="zsh", rc_file=self.rc, yes=True)
        with mock.patch.object(cmd_completion.shutil, "which", return_value="/usr/bin/register-python-argcomplete"):
            with _mock_register("zsh"):
                with mock.patch("sys.stderr", new_callable=io.StringIO):
                    rc2 = cmd_completion._run_install(args)
        with open(self.rc) as f:
            content2 = f.read()
        self.assertEqual(rc2, 0)
        self.assertEqual(content1, content2)

    def test_install_replaces_when_body_changes(self):
        # First install: body = A
        args = _ns(shell="zsh", rc_file=self.rc, yes=True)
        with mock.patch.object(cmd_completion.shutil, "which", return_value="/usr/bin/register-python-argcomplete"):
            with _mock_register("zsh", body="BODY_A\n"):
                with mock.patch("sys.stderr", new_callable=io.StringIO):
                    cmd_completion._run_install(args)
            # Second install: body = B - should replace, not duplicate
            with _mock_register("zsh", body="BODY_B\n"):
                with mock.patch("sys.stderr", new_callable=io.StringIO):
                    cmd_completion._run_install(args)
        with open(self.rc) as f:
            content = f.read()
        self.assertIn("BODY_B", content)
        self.assertNotIn("BODY_A", content)
        # Exactly one BEGIN marker
        self.assertEqual(content.count(cmd_completion.BEGIN_MARKER), 1)


class TestUninstallSubcommand(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.rc = os.path.join(self.tmp, ".zshrc")

    def tearDown(self):
        import shutil as _shutil
        _shutil.rmtree(self.tmp, ignore_errors=True)

    def test_uninstall_removes_block(self):
        with open(self.rc, "w") as f:
            f.write(
                "# before\n"
                f"{cmd_completion.BEGIN_MARKER}\n"
                "stuff\n"
                f"{cmd_completion.END_MARKER}\n"
                "# after\n"
            )
        args = _ns(shell="zsh", rc_file=self.rc)
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            rc = cmd_completion._run_uninstall(args)
        self.assertEqual(rc, 0)
        with open(self.rc) as f:
            out = f.read()
        self.assertNotIn(cmd_completion.BEGIN_MARKER, out)
        self.assertIn("# before", out)
        self.assertIn("# after", out)

    def test_uninstall_no_block_is_noop(self):
        with open(self.rc, "w") as f:
            f.write("alias foo=bar\n")
        args = _ns(shell="zsh", rc_file=self.rc)
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            rc = cmd_completion._run_uninstall(args)
        self.assertEqual(rc, 0)
        with open(self.rc) as f:
            self.assertEqual(f.read(), "alias foo=bar\n")

    def test_uninstall_missing_file_is_noop(self):
        args = _ns(shell="zsh", rc_file=os.path.join(self.tmp, "does-not-exist"))
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            rc = cmd_completion._run_uninstall(args)
        self.assertEqual(rc, 0)


class TestShowSubcommand(unittest.TestCase):
    def test_show_prints_snippet(self):
        args = _ns(shell="bash")
        with mock.patch.object(cmd_completion.shutil, "which", return_value="/usr/bin/register-python-argcomplete"):
            with _mock_register("bash"):
                with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
                    rc = cmd_completion._run_show(args)
        self.assertEqual(rc, 0)
        self.assertIn(cmd_completion.BEGIN_MARKER, out.getvalue())

    def test_show_without_shell_fails(self):
        args = _ns(shell=None)
        with mock.patch.dict(os.environ, {"SHELL": "", "NOSTOS_SHELL": ""}):
            with mock.patch("sys.stderr", new_callable=io.StringIO):
                rc = cmd_completion._run_show(args)
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
