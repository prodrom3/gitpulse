import io
import json
import unittest
from unittest import mock

from core.models import RepoResult, RepoStatus
from core.output import (
    Color,
    _supports_color,
    print_human_summary,
    print_json_summary,
    print_progress,
)


class TestColor(unittest.TestCase):
    def test_enabled_wraps_with_ansi(self):
        c = Color(enabled=True)
        result = c.green("hello")
        self.assertEqual(result, "\033[32mhello\033[0m")

    def test_disabled_returns_plain(self):
        c = Color(enabled=False)
        result = c.green("hello")
        self.assertEqual(result, "hello")

    def test_all_colors(self):
        c = Color(enabled=True)
        self.assertIn("\033[32m", c.green("x"))
        self.assertIn("\033[33m", c.yellow("x"))
        self.assertIn("\033[31m", c.red("x"))
        self.assertIn("\033[36m", c.cyan("x"))
        self.assertIn("\033[1m", c.bold("x"))
        self.assertIn("\033[2m", c.dim("x"))

    def test_all_colors_disabled(self):
        c = Color(enabled=False)
        self.assertEqual(c.green("x"), "x")
        self.assertEqual(c.yellow("x"), "x")
        self.assertEqual(c.red("x"), "x")
        self.assertEqual(c.cyan("x"), "x")
        self.assertEqual(c.bold("x"), "x")
        self.assertEqual(c.dim("x"), "x")


class TestSupportsColor(unittest.TestCase):
    @mock.patch.dict("os.environ", {"NO_COLOR": "1"})
    def test_no_color_env(self):
        self.assertFalse(_supports_color())

    @mock.patch("sys.stdout", new_callable=lambda: lambda: io.StringIO())
    def test_not_tty(self, mock_stdout):
        self.assertFalse(_supports_color())


class TestPrintProgress(unittest.TestCase):
    def test_suppressed_in_json_mode(self):
        r = RepoResult("/tmp/repo", RepoStatus.UPDATED)
        with mock.patch("sys.stderr", new_callable=io.StringIO) as mock_err:
            print_progress(1, 10, r, json_mode=True)
            self.assertEqual(mock_err.getvalue(), "")

    def test_suppressed_in_quiet_mode(self):
        r = RepoResult("/tmp/repo", RepoStatus.UPDATED)
        with mock.patch("sys.stderr", new_callable=io.StringIO) as mock_err:
            print_progress(1, 10, r, quiet=True)
            self.assertEqual(mock_err.getvalue(), "")

    @mock.patch("core.output._make_color", return_value=Color(enabled=False))
    def test_prints_counter_and_status(self, mock_color):
        r = RepoResult("/tmp/repo", RepoStatus.UPDATED)
        with mock.patch("sys.stderr", new_callable=io.StringIO) as mock_err:
            print_progress(3, 10, r)
            output = mock_err.getvalue()
            self.assertIn("[3/10]", output)
            self.assertIn("updated", output)
            self.assertIn("/tmp/repo", output)

    @mock.patch("core.output._make_color", return_value=Color(enabled=False))
    def test_unknown_total(self, mock_color):
        r = RepoResult("/tmp/repo", RepoStatus.SKIPPED, reason="dirty")
        with mock.patch("sys.stderr", new_callable=io.StringIO) as mock_err:
            print_progress(2, None, r)
            self.assertIn("[2/?]", mock_err.getvalue())


class TestPrintHumanSummary(unittest.TestCase):
    @mock.patch("core.output._make_color", return_value=Color(enabled=False))
    def test_all_categories(self, mock_color):
        results = [
            RepoResult("/r/a", RepoStatus.UPDATED),
            RepoResult("/r/b", RepoStatus.FETCHED),
            RepoResult("/r/c", RepoStatus.UP_TO_DATE),
            RepoResult("/r/d", RepoStatus.SKIPPED, reason="dirty"),
            RepoResult("/r/e", RepoStatus.FAILED, reason="timeout"),
        ]
        with mock.patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            print_human_summary(results, 5)
            output = mock_out.getvalue()

        self.assertIn("Updated (1)", output)
        self.assertIn("Fetched (1)", output)
        self.assertIn("Already up-to-date (1)", output)
        self.assertIn("Skipped (1)", output)
        self.assertIn("Failed (1)", output)
        self.assertIn("/r/a", output)
        self.assertIn("/r/d - dirty", output)
        self.assertIn("Total: 5", output)

    @mock.patch("core.output._make_color", return_value=Color(enabled=False))
    def test_empty_results(self, mock_color):
        with mock.patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            print_human_summary([], 0)
            output = mock_out.getvalue()

        self.assertIn("Summary", output)
        self.assertIn("Total: 0", output)


class TestPrintJsonSummary(unittest.TestCase):
    def test_valid_json(self):
        results = [
            RepoResult("/r/a", RepoStatus.UPDATED, branch="main"),
            RepoResult("/r/b", RepoStatus.FAILED, reason="error"),
        ]
        with mock.patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            print_json_summary(results, 2)
            data = json.loads(mock_out.getvalue())

        self.assertEqual(data["total"], 2)
        self.assertEqual(data["counts"]["updated"], 1)
        self.assertEqual(data["counts"]["failed"], 1)
        self.assertEqual(data["counts"]["fetched"], 0)
        self.assertEqual(len(data["repositories"]), 2)
        self.assertEqual(data["repositories"][0]["status"], "updated")
        self.assertEqual(data["repositories"][0]["branch"], "main")

    def test_empty_results(self):
        with mock.patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            print_json_summary([], 0)
            data = json.loads(mock_out.getvalue())

        self.assertEqual(data["total"], 0)
        self.assertEqual(data["repositories"], [])


if __name__ == "__main__":
    unittest.main()
