import os
import stat
import sys
import tempfile
import unittest
from unittest import mock

from core.config import (
    DEFAULT_DEPTH,
    DEFAULT_MAX_LOG_FILES,
    DEFAULT_TIMEOUT,
    DEFAULT_WORKERS,
    _is_config_safe,
    load_config,
)


class TestLoadConfigDefaults(unittest.TestCase):
    def test_defaults_when_no_file(self):
        with mock.patch("core.config.get_config_path", return_value="/nonexistent/.gitpulserc"):
            config = load_config()

        self.assertEqual(config["depth"], DEFAULT_DEPTH)
        self.assertEqual(config["workers"], DEFAULT_WORKERS)
        self.assertEqual(config["timeout"], DEFAULT_TIMEOUT)
        self.assertEqual(config["max_log_files"], DEFAULT_MAX_LOG_FILES)
        self.assertFalse(config["rebase"])
        self.assertEqual(config["exclude_patterns"], [])


class TestLoadConfigFromFile(unittest.TestCase):
    def _write_config(self, content):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".gitpulserc", delete=False)
        f.write(content)
        f.close()
        self.addCleanup(os.unlink, f.name)
        return f.name

    def test_full_config(self):
        path = self._write_config(
            "[defaults]\n"
            "depth = 10\n"
            "workers = 16\n"
            "timeout = 60\n"
            "max_log_files = 5\n"
            "rebase = true\n"
            "\n"
            "[exclude]\n"
            "patterns = archived-*, temp-*, .backup-*\n"
        )
        with mock.patch("core.config.get_config_path", return_value=path):
            config = load_config()

        self.assertEqual(config["depth"], 10)
        self.assertEqual(config["workers"], 16)
        self.assertEqual(config["timeout"], 60)
        self.assertEqual(config["max_log_files"], 5)
        self.assertTrue(config["rebase"])
        self.assertEqual(config["exclude_patterns"], ["archived-*", "temp-*", ".backup-*"])

    def test_partial_config(self):
        path = self._write_config(
            "[defaults]\n"
            "workers = 4\n"
        )
        with mock.patch("core.config.get_config_path", return_value=path):
            config = load_config()

        self.assertEqual(config["workers"], 4)
        self.assertEqual(config["depth"], DEFAULT_DEPTH)
        self.assertEqual(config["timeout"], DEFAULT_TIMEOUT)
        self.assertEqual(config["exclude_patterns"], [])

    def test_empty_exclude_patterns(self):
        path = self._write_config(
            "[exclude]\n"
            "patterns = \n"
        )
        with mock.patch("core.config.get_config_path", return_value=path):
            config = load_config()

        self.assertEqual(config["exclude_patterns"], [])

    def test_empty_file(self):
        path = self._write_config("")
        with mock.patch("core.config.get_config_path", return_value=path):
            config = load_config()

        self.assertEqual(config["depth"], DEFAULT_DEPTH)
        self.assertEqual(config["workers"], DEFAULT_WORKERS)


class TestConfigSafety(unittest.TestCase):
    def _write_config(self, content):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".gitpulserc", delete=False)
        f.write(content)
        f.close()
        self.addCleanup(os.unlink, f.name)
        return f.name

    @unittest.skipIf(sys.platform == "win32", "Unix-only ownership check")
    def test_safe_config_owned_by_user(self):
        path = self._write_config("[defaults]\nworkers = 4\n")
        self.assertTrue(_is_config_safe(path))

    @unittest.skipIf(sys.platform == "win32", "Unix-only ownership check")
    def test_rejects_world_writable(self):
        path = self._write_config("[defaults]\nworkers = 4\n")
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IWOTH)
        self.assertFalse(_is_config_safe(path))

    @unittest.skipIf(sys.platform == "win32", "Unix-only ownership check")
    def test_rejects_wrong_owner(self):
        path = self._write_config("[defaults]\n")
        with mock.patch("os.stat") as mock_stat:
            fake_stat = os.stat(path)
            mock_stat.return_value = mock.Mock(
                st_uid=fake_stat.st_uid + 1,
                st_mode=fake_stat.st_mode,
            )
            self.assertFalse(_is_config_safe(path))

    def test_returns_true_on_windows(self):
        with mock.patch("core.config.sys") as mock_sys:
            mock_sys.platform = "win32"
            self.assertTrue(_is_config_safe("/any/path"))

    def test_unsafe_config_returns_defaults(self):
        path = self._write_config("[defaults]\nworkers = 99\n")
        with mock.patch("core.config.get_config_path", return_value=path), \
             mock.patch("core.config._is_config_safe", return_value=False):
            config = load_config()
        self.assertEqual(config["workers"], DEFAULT_WORKERS)

    def test_nonexistent_path(self):
        self.assertFalse(_is_config_safe("/nonexistent/file"))


if __name__ == "__main__":
    unittest.main()
