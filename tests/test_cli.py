import tempfile
import unittest
from unittest import mock

from core.cli import get_version, parse_args


class TestGetVersion(unittest.TestCase):
    def test_reads_version_file(self):
        version = get_version()
        self.assertRegex(version, r"^\d+\.\d+\.\d+$")

    def test_returns_unknown_on_missing_file(self):
        from importlib.metadata import PackageNotFoundError

        with mock.patch("core.cli._pkg_version", side_effect=PackageNotFoundError("gitpulse")), \
             mock.patch("builtins.open", side_effect=OSError("not found")):
            version = get_version()
        self.assertEqual(version, "unknown")


class TestParseArgs(unittest.TestCase):
    @mock.patch("core.cli.load_config")
    def _parse(self, argv, mock_config, config_overrides=None):
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
        with mock.patch("sys.argv", ["gitpulse"] + argv):
            return parse_args()

    def test_defaults(self):
        args = self._parse([])
        self.assertEqual(args.depth, 5)
        self.assertEqual(args.workers, 8)
        self.assertEqual(args.timeout, 120)
        self.assertFalse(args.dry_run)
        self.assertFalse(args.fetch_only)
        self.assertFalse(args.rebase)
        self.assertFalse(args.json)
        self.assertFalse(args.quiet)

    def test_path_argument(self):
        with tempfile.TemporaryDirectory() as d:
            args = self._parse([d])
            self.assertEqual(args.path, d)

    def test_dry_run(self):
        args = self._parse(["--dry-run"])
        self.assertTrue(args.dry_run)

    def test_fetch_only(self):
        args = self._parse(["--fetch-only"])
        self.assertTrue(args.fetch_only)

    def test_rebase(self):
        args = self._parse(["--rebase"])
        self.assertTrue(args.rebase)

    def test_depth(self):
        args = self._parse(["--depth", "10"])
        self.assertEqual(args.depth, 10)

    def test_workers(self):
        args = self._parse(["--workers", "16"])
        self.assertEqual(args.workers, 16)

    def test_timeout(self):
        args = self._parse(["--timeout", "60"])
        self.assertEqual(args.timeout, 60)

    def test_exclude(self):
        args = self._parse(["--exclude", "archived-*", "temp-*"])
        self.assertEqual(args.exclude, ["archived-*", "temp-*"])

    def test_json(self):
        args = self._parse(["--json"])
        self.assertTrue(args.json)

    def test_quiet_short(self):
        args = self._parse(["-q"])
        self.assertTrue(args.quiet)

    def test_quiet_long(self):
        args = self._parse(["--quiet"])
        self.assertTrue(args.quiet)

    def test_config_defaults_applied(self):
        args = self._parse([], config_overrides={"depth": 3, "workers": 4, "rebase": True})
        self.assertEqual(args.depth, 3)
        self.assertEqual(args.workers, 4)
        self.assertTrue(args.rebase)

    def test_cli_overrides_config(self):
        args = self._parse(
            ["--depth", "10", "--workers", "16"],
            config_overrides={"depth": 3, "workers": 4},
        )
        self.assertEqual(args.depth, 10)
        self.assertEqual(args.workers, 16)

    def test_version_flag(self):
        with self.assertRaises(SystemExit) as cm:
            self._parse(["--version"])
        self.assertEqual(cm.exception.code, 0)

    def test_add_flag(self):
        args = self._parse(["--add", "/tmp/repo"])
        self.assertEqual(args.add, "/tmp/repo")

    def test_add_with_url(self):
        args = self._parse(["--add", "https://github.com/user/repo.git"])
        self.assertEqual(args.add, "https://github.com/user/repo.git")

    def test_remove_flag(self):
        args = self._parse(["--remove", "/tmp/repo"])
        self.assertEqual(args.remove, "/tmp/repo")

    def test_list_watchlist_flag(self):
        args = self._parse(["--list"])
        self.assertTrue(args.list_watchlist)

    def test_watchlist_flag(self):
        args = self._parse(["--watchlist"])
        self.assertTrue(args.watchlist)

    def test_clone_dir_flag(self):
        args = self._parse(["--clone-dir", "/tmp/clones"])
        self.assertEqual(args.clone_dir, "/tmp/clones")

    def test_clone_dir_default_none(self):
        args = self._parse([])
        self.assertIsNone(args.clone_dir)

    def test_clone_dir_from_config(self):
        args = self._parse([], config_overrides={"clone_dir": "/home/user/repos"})
        self.assertEqual(args.clone_dir, "/home/user/repos")

    def test_clone_dir_cli_overrides_config(self):
        args = self._parse(
            ["--clone-dir", "/tmp/override"],
            config_overrides={"clone_dir": "/home/user/repos"},
        )
        self.assertEqual(args.clone_dir, "/tmp/override")

    def test_defaults_include_watchlist_flags(self):
        args = self._parse([])
        self.assertIsNone(args.add)
        self.assertIsNone(args.remove)
        self.assertFalse(args.list_watchlist)
        self.assertFalse(args.watchlist)

    def test_path_default_none(self):
        args = self._parse([])
        self.assertIsNone(args.path)


if __name__ == "__main__":
    unittest.main()
