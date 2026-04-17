import os
import tempfile
import time
import unittest
from unittest import mock

from core.logging_config import _get_logs_directory, rotate_logs, setup_logging


class TestRotateLogs(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _create_log(self, name, delay=0):
        path = os.path.join(self.tmpdir, name)
        with open(path, "w") as f:
            f.write("log content")
        if delay:
            time.sleep(delay)
        return path

    def test_no_rotation_under_limit(self):
        for i in range(3):
            self._create_log(f"test-{i}.log")

        rotate_logs(self.tmpdir, max_files=5)
        remaining = os.listdir(self.tmpdir)
        self.assertEqual(len(remaining), 3)

    def test_rotates_oldest_files(self):
        paths = []
        for i in range(5):
            p = self._create_log(f"2026-01-0{i + 1}.log")
            paths.append(p)
            # Touch files with increasing mtime
            os.utime(p, (1000 + i, 1000 + i))

        rotate_logs(self.tmpdir, max_files=3)
        remaining = set(os.listdir(self.tmpdir))
        self.assertEqual(len(remaining), 3)
        # Oldest two should be removed
        self.assertNotIn("2026-01-01.log", remaining)
        self.assertNotIn("2026-01-02.log", remaining)
        self.assertIn("2026-01-03.log", remaining)
        self.assertIn("2026-01-04.log", remaining)
        self.assertIn("2026-01-05.log", remaining)

    def test_empty_directory(self):
        rotate_logs(self.tmpdir, max_files=5)
        self.assertEqual(os.listdir(self.tmpdir), [])

    def test_ignores_non_log_files(self):
        self._create_log("keep.txt")
        for i in range(3):
            self._create_log(f"test-{i}.log")

        rotate_logs(self.tmpdir, max_files=2)
        remaining = os.listdir(self.tmpdir)
        # .txt file should not be counted or removed
        self.assertIn("keep.txt", remaining)

    def test_max_files_zero_removes_all(self):
        for i in range(3):
            self._create_log(f"test-{i}.log")

        rotate_logs(self.tmpdir, max_files=0)
        log_files = [f for f in os.listdir(self.tmpdir) if f.endswith(".log")]
        self.assertEqual(len(log_files), 0)


class TestLogsDirectory(unittest.TestCase):
    def test_logs_dir_is_absolute(self):
        logs_dir = _get_logs_directory()
        self.assertTrue(os.path.isabs(logs_dir))

    def test_logs_dir_lives_under_data_dir(self):
        from core.paths import data_dir as _data_dir

        logs_dir = _get_logs_directory()
        self.assertEqual(
            os.path.realpath(logs_dir),
            os.path.realpath(os.path.join(_data_dir(), "logs")),
        )

    def test_logs_dir_basename_is_logs(self):
        self.assertEqual(os.path.basename(_get_logs_directory()), "logs")


class TestSetupLoggingSymlinkProtection(unittest.TestCase):
    def test_rejects_symlinked_logs_dir(self):
        with tempfile.TemporaryDirectory() as real_target:
            with tempfile.TemporaryDirectory() as parent:
                symlink_path = os.path.join(parent, "logs")
                try:
                    os.symlink(real_target, symlink_path)
                except OSError:
                    self.skipTest("Cannot create symlinks on this system")

                with mock.patch("core.logging_config._get_logs_directory", return_value=symlink_path):
                    with self.assertRaises(SystemExit):
                        setup_logging()


if __name__ == "__main__":
    unittest.main()
