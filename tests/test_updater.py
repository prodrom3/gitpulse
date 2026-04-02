import subprocess
import unittest
from unittest import mock

from core.models import RepoResult, RepoStatus
from core.updater import (
    MIN_GIT_VERSION,
    SSHMultiplexer,
    check_git_version,
    check_repo_state,
    fetch_repo,
    sanitize_log_output,
    update_repository,
)


class TestSanitizeLogOutput(unittest.TestCase):
    def test_strips_https_credentials(self):
        text = "fatal: could not read from https://user:token123@github.com/repo.git"
        result = sanitize_log_output(text)
        self.assertIn("https://***@github.com", result)
        self.assertNotIn("user:token123", result)

    def test_strips_http_credentials(self):
        text = "http://admin:secret@internal.host/repo"
        result = sanitize_log_output(text)
        self.assertIn("http://***@internal.host", result)
        self.assertNotIn("admin:secret", result)

    def test_preserves_ssh_urls(self):
        text = "git@github.com:user/repo.git"
        result = sanitize_log_output(text)
        self.assertEqual(result, text)

    def test_preserves_clean_https(self):
        text = "https://github.com/user/repo.git"
        result = sanitize_log_output(text)
        self.assertEqual(result, text)

    def test_preserves_plain_text(self):
        text = "fatal: not a git repository"
        result = sanitize_log_output(text)
        self.assertEqual(result, text)


def _mock_run(responses):
    """Create a side_effect function for subprocess.run that returns different
    CompletedProcess results based on call order."""
    call_count = [0]

    def side_effect(*args, **kwargs):
        idx = call_count[0]
        call_count[0] += 1
        if idx < len(responses):
            return responses[idx]
        return subprocess.CompletedProcess(args[0], 0, "", "")

    return side_effect


class TestCheckRepoState(unittest.TestCase):
    @mock.patch("core.updater.subprocess.run")
    def test_detached_head(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 0, "HEAD\n", "")
        ok, reason, branch = check_repo_state("/tmp/repo")
        self.assertFalse(ok)
        self.assertIn("detached HEAD", reason)
        self.assertIsNone(branch)

    @mock.patch("core.updater.subprocess.run")
    def test_no_upstream(self, mock_run):
        mock_run.side_effect = _mock_run([
            subprocess.CompletedProcess([], 0, "main\n", ""),
            subprocess.CompletedProcess([], 128, "", "fatal: no upstream"),
        ])
        ok, reason, branch = check_repo_state("/tmp/repo")
        self.assertFalse(ok)
        self.assertIn("no upstream", reason)
        self.assertEqual(branch, "main")

    @mock.patch("core.updater.subprocess.run")
    def test_dirty_working_tree(self, mock_run):
        mock_run.side_effect = _mock_run([
            subprocess.CompletedProcess([], 0, "main\n", ""),
            subprocess.CompletedProcess([], 0, "origin/main\n", ""),
            subprocess.CompletedProcess([], 0, " M file.txt\n", ""),
        ])
        ok, reason, branch = check_repo_state("/tmp/repo")
        self.assertFalse(ok)
        self.assertIn("dirty working tree", reason)
        self.assertEqual(branch, "main")

    @mock.patch("core.updater.subprocess.run")
    def test_clean_repo(self, mock_run):
        mock_run.side_effect = _mock_run([
            subprocess.CompletedProcess([], 0, "main\n", ""),
            subprocess.CompletedProcess([], 0, "origin/main\n", ""),
            subprocess.CompletedProcess([], 0, "\n", ""),
        ])
        ok, reason, branch = check_repo_state("/tmp/repo")
        self.assertTrue(ok)
        self.assertIsNone(reason)
        self.assertEqual(branch, "main")

    @mock.patch("core.updater.subprocess.run")
    def test_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired("git", 10)
        ok, reason, branch = check_repo_state("/tmp/repo")
        self.assertFalse(ok)
        self.assertIn("timed out", reason)


class TestFetchRepo(unittest.TestCase):
    @mock.patch("core.updater.subprocess.run")
    def test_behind_by_n(self, mock_run):
        mock_run.side_effect = _mock_run([
            subprocess.CompletedProcess([], 0, "", ""),
            subprocess.CompletedProcess([], 0, "3\n", ""),
        ])
        count, err = fetch_repo("/tmp/repo", timeout=30)
        self.assertEqual(count, 3)
        self.assertIsNone(err)

    @mock.patch("core.updater.subprocess.run")
    def test_up_to_date(self, mock_run):
        mock_run.side_effect = _mock_run([
            subprocess.CompletedProcess([], 0, "", ""),
            subprocess.CompletedProcess([], 0, "0\n", ""),
        ])
        count, err = fetch_repo("/tmp/repo", timeout=30)
        self.assertEqual(count, 0)
        self.assertIsNone(err)

    @mock.patch("core.updater.subprocess.run")
    def test_timeout_returns_error(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired("git", 30)
        count, err = fetch_repo("/tmp/repo", timeout=30)
        self.assertEqual(count, -1)
        self.assertIn("timed out", err)


class TestUpdateRepository(unittest.TestCase):
    @mock.patch("core.updater.get_remote_url", return_value="https://github.com/user/repo")
    @mock.patch("core.updater.fetch_repo", return_value=(0, None))
    @mock.patch("core.updater.check_repo_state", return_value=(True, None, "main"))
    def test_up_to_date(self, mock_state, mock_fetch, mock_url):
        result = update_repository("/tmp/repo")
        self.assertEqual(result.status, RepoStatus.UP_TO_DATE)
        self.assertEqual(result.branch, "main")

    @mock.patch("core.updater.get_remote_url", return_value=None)
    @mock.patch("core.updater.check_repo_state", return_value=(False, "detached HEAD", None))
    def test_skipped(self, mock_state, mock_url):
        result = update_repository("/tmp/repo")
        self.assertEqual(result.status, RepoStatus.SKIPPED)
        self.assertEqual(result.reason, "detached HEAD")

    @mock.patch("core.updater.subprocess.run")
    @mock.patch("core.updater.get_remote_url", return_value="https://github.com/user/repo")
    @mock.patch("core.updater.fetch_repo", return_value=(5, None))
    @mock.patch("core.updater.check_repo_state", return_value=(True, None, "main"))
    def test_fetch_only(self, mock_state, mock_fetch, mock_url, mock_run):
        result = update_repository("/tmp/repo", fetch_only=True)
        self.assertEqual(result.status, RepoStatus.FETCHED)
        self.assertIn("5 commits behind", result.reason)
        mock_run.assert_not_called()

    @mock.patch("core.updater.subprocess.run")
    @mock.patch("core.updater.get_remote_url", return_value="https://github.com/user/repo")
    @mock.patch("core.updater.fetch_repo", return_value=(2, None))
    @mock.patch("core.updater.check_repo_state", return_value=(True, None, "main"))
    def test_successful_pull(self, mock_state, mock_fetch, mock_url, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 0, "Updating abc..def\n", "")
        result = update_repository("/tmp/repo")
        self.assertEqual(result.status, RepoStatus.UPDATED)
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        self.assertEqual(cmd, ["git", "pull"])

    @mock.patch("core.updater.subprocess.run")
    @mock.patch("core.updater.get_remote_url", return_value="https://github.com/user/repo")
    @mock.patch("core.updater.fetch_repo", return_value=(2, None))
    @mock.patch("core.updater.check_repo_state", return_value=(True, None, "main"))
    def test_pull_with_rebase(self, mock_state, mock_fetch, mock_url, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 0, "Rebasing\n", "")
        result = update_repository("/tmp/repo", rebase=True)
        self.assertEqual(result.status, RepoStatus.UPDATED)
        cmd = mock_run.call_args[0][0]
        self.assertEqual(cmd, ["git", "pull", "--rebase"])

    @mock.patch("core.updater.subprocess.run")
    @mock.patch("core.updater.get_remote_url", return_value="https://github.com/user/repo")
    @mock.patch("core.updater.fetch_repo", return_value=(1, None))
    @mock.patch("core.updater.check_repo_state", return_value=(True, None, "main"))
    def test_pull_timeout(self, mock_state, mock_fetch, mock_url, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired("git", 120)
        result = update_repository("/tmp/repo", timeout=120)
        self.assertEqual(result.status, RepoStatus.FAILED)
        self.assertIn("timed out", result.reason)

    @mock.patch("core.updater.subprocess.run")
    @mock.patch("core.updater.get_remote_url", return_value="https://github.com/user/repo")
    @mock.patch("core.updater.fetch_repo", return_value=(1, None))
    @mock.patch("core.updater.check_repo_state", return_value=(True, None, "main"))
    def test_pull_error(self, mock_state, mock_fetch, mock_url, mock_run):
        mock_run.side_effect = subprocess.CalledProcessError(1, "git", stderr="merge conflict")
        result = update_repository("/tmp/repo")
        self.assertEqual(result.status, RepoStatus.FAILED)
        self.assertIn("merge conflict", result.reason)

    @mock.patch("core.updater.get_remote_url", return_value="https://github.com/user/repo")
    @mock.patch("core.updater.fetch_repo", return_value=(-1, "timed out after 30s"))
    @mock.patch("core.updater.check_repo_state", return_value=(True, None, "main"))
    def test_fetch_error(self, mock_state, mock_fetch, mock_url):
        result = update_repository("/tmp/repo")
        self.assertEqual(result.status, RepoStatus.FAILED)
        self.assertIn("timed out", result.reason)


class TestSSHMultiplexer(unittest.TestCase):
    @mock.patch("core.updater.sys")
    def test_disabled_on_windows(self, mock_sys):
        mock_sys.platform = "win32"
        ssh = SSHMultiplexer()
        ssh.__init__()  # re-init with mocked platform
        # Manually set since __init__ already ran with real sys
        ssh.enabled = False
        ssh.setup()
        self.assertIsNone(ssh.get_env())

    def test_cleanup_when_no_setup(self):
        ssh = SSHMultiplexer()
        ssh.enabled = False
        ssh.cleanup()
        self.assertIsNone(ssh.control_dir)


class TestCheckGitVersion(unittest.TestCase):
    @mock.patch("core.updater.subprocess.run")
    def test_safe_version_no_warning(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 0, "git version 2.45.1\n", "")
        with mock.patch("core.updater.logging") as mock_log:
            check_git_version()
            mock_log.warning.assert_not_called()

    @mock.patch("core.updater.subprocess.run")
    def test_newer_version_no_warning(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 0, "git version 2.47.0\n", "")
        with mock.patch("core.updater.logging") as mock_log:
            check_git_version()
            mock_log.warning.assert_not_called()

    @mock.patch("core.updater.subprocess.run")
    def test_old_version_warns(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 0, "git version 2.39.1\n", "")
        with mock.patch("core.updater.logging") as mock_log:
            check_git_version()
            mock_log.warning.assert_called_once()
            warning_msg = mock_log.warning.call_args[0][0]
            self.assertIn("CVE-2024-32002", warning_msg)

    @mock.patch("core.updater.subprocess.run")
    def test_windows_version_format(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            [], 0, "git version 2.45.1.windows.1\n", ""
        )
        with mock.patch("core.updater.logging") as mock_log:
            check_git_version()
            mock_log.warning.assert_not_called()

    @mock.patch("core.updater.subprocess.run")
    def test_timeout_warns(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired("git", 10)
        with mock.patch("core.updater.logging") as mock_log:
            check_git_version()
            mock_log.warning.assert_called_once()

    @mock.patch("core.updater.subprocess.run")
    def test_git_not_found(self, mock_run):
        mock_run.side_effect = FileNotFoundError("git not found")
        with mock.patch("core.updater.logging") as mock_log:
            check_git_version()
            mock_log.warning.assert_called_once()


if __name__ == "__main__":
    unittest.main()
