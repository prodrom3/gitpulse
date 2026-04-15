import unittest
from unittest import mock

from core.cli import (
    _inject_default_verb,
    _rewrite_legacy_argv,
    build_parser,
    get_version,
)


class TestGetVersion(unittest.TestCase):
    def test_reads_version_file(self):
        version = get_version()
        self.assertRegex(version, r"^\d+\.\d+\.\d+$")

    def test_returns_unknown_when_both_sources_missing(self):
        from importlib.metadata import PackageNotFoundError

        with mock.patch(
            "core.cli._pkg_version", side_effect=PackageNotFoundError("gitpulse")
        ), mock.patch("builtins.open", side_effect=OSError("not found")):
            self.assertEqual(get_version(), "unknown")


def _parse(argv):
    """Parse argv through the full legacy shim + default verb injection."""
    argv = _rewrite_legacy_argv(list(argv))
    argv = _inject_default_verb(argv)
    return build_parser().parse_args(argv)


class TestPullParser(unittest.TestCase):
    @mock.patch("core.commands.pull.load_config")
    def _parse_pull(self, argv, mock_config, config_overrides=None):
        mock_config.return_value = {
            "depth": 5,
            "workers": 8,
            "timeout": 120,
            "max_log_files": 20,
            "rebase": False,
            "exclude_patterns": [],
            "clone_dir": None,
        }
        if config_overrides:
            mock_config.return_value.update(config_overrides)
        with mock.patch("sys.argv", ["gitpulse"] + list(argv)):
            return _parse(argv)

    def test_default_verb_is_pull(self):
        args = self._parse_pull([])
        self.assertEqual(args.command, "pull")
        self.assertFalse(args.dry_run)
        self.assertFalse(args.rebase)

    def test_explicit_pull(self):
        args = self._parse_pull(["pull", "--dry-run"])
        self.assertTrue(args.dry_run)

    def test_positional_path_injects_pull(self):
        args = self._parse_pull(["/tmp/repos"])
        self.assertEqual(args.command, "pull")
        self.assertEqual(args.path, "/tmp/repos")

    def test_flags_without_verb(self):
        args = self._parse_pull(["--dry-run", "--workers", "16"])
        self.assertEqual(args.command, "pull")
        self.assertTrue(args.dry_run)
        self.assertEqual(args.workers, 16)

    def test_rebase_from_config(self):
        args = self._parse_pull([], config_overrides={"rebase": True})
        self.assertTrue(args.rebase)

    def test_cli_overrides_config(self):
        args = self._parse_pull(
            ["--depth", "10"], config_overrides={"depth": 3}
        )
        self.assertEqual(args.depth, 10)

    def test_fetch_only(self):
        args = self._parse_pull(["--fetch-only"])
        self.assertTrue(args.fetch_only)

    def test_exclude(self):
        args = self._parse_pull(["--exclude", "archived-*", "temp-*"])
        self.assertEqual(args.exclude, ["archived-*", "temp-*"])

    def test_from_index(self):
        args = self._parse_pull(["--from-index"])
        self.assertTrue(args.from_index)

    def test_quiet_short(self):
        args = self._parse_pull(["-q"])
        self.assertTrue(args.quiet)


class TestLegacyFlagShim(unittest.TestCase):
    def test_dash_dash_add_becomes_add(self):
        with mock.patch("core.cli._deprecate"):
            out = _rewrite_legacy_argv(["--add", "/tmp/r"])
        self.assertEqual(out, ["add", "/tmp/r"])

    def test_dash_dash_remove_becomes_rm(self):
        with mock.patch("core.cli._deprecate"):
            out = _rewrite_legacy_argv(["--remove", "/tmp/r"])
        self.assertEqual(out, ["rm", "/tmp/r"])

    def test_dash_dash_list_becomes_list(self):
        with mock.patch("core.cli._deprecate"):
            out = _rewrite_legacy_argv(["--list"])
        self.assertEqual(out, ["list"])

    def test_unrelated_args_pass_through(self):
        out = _rewrite_legacy_argv(["pull", "--rebase"])
        self.assertEqual(out, ["pull", "--rebase"])

    def test_empty_argv(self):
        self.assertEqual(_rewrite_legacy_argv([]), [])


class TestDefaultVerbInjection(unittest.TestCase):
    def test_known_verb_unchanged(self):
        self.assertEqual(_inject_default_verb(["list"]), ["list"])
        self.assertEqual(_inject_default_verb(["pull", "--rebase"]), ["pull", "--rebase"])

    def test_unknown_first_positional_gets_pull(self):
        self.assertEqual(_inject_default_verb(["/tmp/r"]), ["pull", "/tmp/r"])

    def test_only_flags_gets_pull(self):
        self.assertEqual(_inject_default_verb(["--dry-run"]), ["pull", "--dry-run"])

    def test_help_is_not_rewritten(self):
        self.assertEqual(_inject_default_verb(["--help"]), ["--help"])
        self.assertEqual(_inject_default_verb(["-h"]), ["-h"])

    def test_version_is_not_rewritten(self):
        self.assertEqual(_inject_default_verb(["--version"]), ["--version"])

    def test_empty_argv_gets_pull(self):
        self.assertEqual(_inject_default_verb([]), ["pull"])


if __name__ == "__main__":
    unittest.main()
