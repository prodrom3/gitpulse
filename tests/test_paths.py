import os
import stat
import sys
import tempfile
import unittest
from unittest import mock

from core import paths


class TestXdgResolution(unittest.TestCase):
    def test_xdg_config_home_respects_env(self):
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": "/custom/cfg"}):
            self.assertEqual(paths.xdg_config_home(), "/custom/cfg")

    def test_xdg_data_home_respects_env(self):
        with mock.patch.dict(os.environ, {"XDG_DATA_HOME": "/custom/data"}):
            self.assertEqual(paths.xdg_data_home(), "/custom/data")

    @unittest.skipIf(sys.platform == "win32", "Unix default paths only")
    def test_xdg_config_home_default_unix(self):
        env = {k: v for k, v in os.environ.items() if k != "XDG_CONFIG_HOME"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertTrue(paths.xdg_config_home().endswith("/.config"))

    @unittest.skipIf(sys.platform == "win32", "Unix default paths only")
    def test_xdg_data_home_default_unix(self):
        env = {k: v for k, v in os.environ.items() if k != "XDG_DATA_HOME"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertTrue(paths.xdg_data_home().endswith("/.local/share"))

    def test_config_dir_ends_with_nostos(self):
        self.assertTrue(paths.config_dir().endswith("nostos"))

    def test_data_dir_ends_with_nostos(self):
        self.assertTrue(paths.data_dir().endswith("nostos"))

    def test_index_db_is_inside_data_dir(self):
        self.assertTrue(paths.index_db_path().startswith(paths.data_dir()))
        self.assertTrue(paths.index_db_path().endswith("index.db"))

    def test_auth_config_is_inside_config_dir(self):
        self.assertTrue(paths.auth_config_path().startswith(paths.config_dir()))
        self.assertTrue(paths.auth_config_path().endswith("auth.toml"))


class TestEnsureDirs(unittest.TestCase):
    def test_ensure_config_dir_creates_and_chmods(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": tmp}):
                result = paths.ensure_config_dir()
                self.assertTrue(os.path.isdir(result))
                if sys.platform != "win32":
                    mode = stat.S_IMODE(os.stat(result).st_mode)
                    self.assertEqual(mode, 0o700)

    def test_ensure_data_dir_creates_and_chmods(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"XDG_DATA_HOME": tmp}):
                result = paths.ensure_data_dir()
                self.assertTrue(os.path.isdir(result))
                if sys.platform != "win32":
                    mode = stat.S_IMODE(os.stat(result).st_mode)
                    self.assertEqual(mode, 0o700)

    def test_ensure_config_dir_tightens_existing_loose_perms(self):
        if sys.platform == "win32":
            self.skipTest("Unix-only perm check")
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": tmp}):
                loose = os.path.join(tmp, "nostos")
                os.makedirs(loose, mode=0o755)
                os.chmod(loose, 0o755)
                paths.ensure_config_dir()
                mode = stat.S_IMODE(os.stat(loose).st_mode)
                self.assertEqual(mode, 0o700)


if __name__ == "__main__":
    unittest.main()
