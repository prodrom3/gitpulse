import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from core.watchlist import (
    _is_watchlist_safe,
    _safe_clone_env,
    add_to_watchlist,
    clone_repo,
    extract_repo_name,
    is_remote_url,
    load_watchlist,
    remove_from_watchlist,
)


class TestIsRemoteUrl(unittest.TestCase):
    def test_https_github(self) -> None:
        self.assertTrue(is_remote_url("https://github.com/user/repo.git"))

    def test_https_gitlab(self) -> None:
        self.assertTrue(is_remote_url("https://gitlab.com/group/repo"))

    def test_http(self) -> None:
        self.assertTrue(is_remote_url("http://internal.host/repo.git"))

    def test_ssh_git_at(self) -> None:
        self.assertTrue(is_remote_url("git@github.com:user/repo.git"))

    def test_ssh_protocol(self) -> None:
        self.assertTrue(is_remote_url("ssh://git@github.com/user/repo"))

    def test_git_protocol(self) -> None:
        self.assertTrue(is_remote_url("git://github.com/user/repo.git"))

    def test_local_path(self) -> None:
        self.assertFalse(is_remote_url("/home/user/repo"))

    def test_relative_path(self) -> None:
        self.assertFalse(is_remote_url("../repo"))

    def test_windows_path(self) -> None:
        self.assertFalse(is_remote_url("C:\\Users\\user\\repo"))


class TestExtractRepoName(unittest.TestCase):
    def test_https_with_git_suffix(self) -> None:
        self.assertEqual(
            extract_repo_name("https://github.com/user/repo.git"), "repo"
        )

    def test_https_without_suffix(self) -> None:
        self.assertEqual(
            extract_repo_name("https://github.com/user/repo"), "repo"
        )

    def test_https_trailing_slash(self) -> None:
        self.assertEqual(
            extract_repo_name("https://github.com/user/repo/"), "repo"
        )

    def test_ssh_format(self) -> None:
        self.assertEqual(
            extract_repo_name("git@github.com:user/repo.git"), "repo"
        )

    def test_gitlab_subgroup(self) -> None:
        self.assertEqual(
            extract_repo_name("https://gitlab.com/group/subgroup/repo"), "repo"
        )

    def test_ssh_with_subgroup(self) -> None:
        self.assertEqual(
            extract_repo_name("git@gitlab.com:group/subgroup/repo.git"), "repo"
        )


class TestCloneRepo(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_already_cloned(self) -> None:
        repo_dir = os.path.join(self.tmpdir, "repo")
        os.makedirs(os.path.join(repo_dir, ".git"))
        result = clone_repo("https://github.com/user/repo.git", self.tmpdir)
        self.assertEqual(result, repo_dir)

    def test_target_exists_but_not_repo(self) -> None:
        os.makedirs(os.path.join(self.tmpdir, "repo"))
        result = clone_repo("https://github.com/user/repo.git", self.tmpdir)
        self.assertIsNone(result)

    @mock.patch("core.watchlist.subprocess.run")
    def test_successful_clone(self, mock_run: mock.Mock) -> None:
        mock_run.return_value = subprocess.CompletedProcess([], 0, "", "")
        target = os.path.join(self.tmpdir, "repo")
        clone_repo("https://github.com/user/repo.git", self.tmpdir)
        # Two calls: clone --no-checkout, then checkout
        self.assertEqual(mock_run.call_count, 2)
        clone_cmd = mock_run.call_args_list[0][0][0]
        self.assertEqual(clone_cmd, ["git", "clone", "--no-checkout",
                                     "https://github.com/user/repo.git", target])
        checkout_cmd = mock_run.call_args_list[1][0][0]
        self.assertEqual(checkout_cmd, ["git", "checkout"])

    @mock.patch("core.watchlist.subprocess.run")
    def test_clone_timeout(self, mock_run: mock.Mock) -> None:
        mock_run.side_effect = subprocess.TimeoutExpired("git", 120)
        result = clone_repo("https://github.com/user/repo.git", self.tmpdir)
        self.assertIsNone(result)

    @mock.patch("core.watchlist.subprocess.run")
    def test_clone_failure(self, mock_run: mock.Mock) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(
            128, "git", stderr="fatal: repository not found"
        )
        result = clone_repo("https://github.com/user/repo.git", self.tmpdir)
        self.assertIsNone(result)

    def test_creates_clone_dir_if_missing(self) -> None:
        clone_dir = os.path.join(self.tmpdir, "new-dir")
        with mock.patch("core.watchlist.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess([], 0, "", "")
            clone_repo("https://github.com/user/repo.git", clone_dir)
        self.assertTrue(os.path.isdir(clone_dir))

    @mock.patch("core.watchlist.subprocess.run")
    def test_clone_uses_safe_env(self, mock_run: mock.Mock) -> None:
        mock_run.return_value = subprocess.CompletedProcess([], 0, "", "")
        clone_repo("https://github.com/user/repo.git", self.tmpdir)
        # Both calls should have env with hooks disabled
        for call in mock_run.call_args_list:
            env = call[1].get("env", {})
            self.assertEqual(env.get("GIT_CONFIG_KEY_0"), "core.hooksPath")
            self.assertEqual(env.get("GIT_CONFIG_VALUE_0"), "/dev/null")


class TestSafeCloneEnv(unittest.TestCase):
    def test_disables_hooks(self) -> None:
        env = _safe_clone_env()
        self.assertEqual(env["GIT_CONFIG_KEY_0"], "core.hooksPath")
        self.assertEqual(env["GIT_CONFIG_VALUE_0"], "/dev/null")

    def test_restricts_file_protocol(self) -> None:
        env = _safe_clone_env()
        self.assertEqual(env["GIT_CONFIG_KEY_1"], "protocol.file.allow")
        self.assertEqual(env["GIT_CONFIG_VALUE_1"], "user")

    def test_sets_config_count(self) -> None:
        env = _safe_clone_env()
        self.assertEqual(env["GIT_CONFIG_COUNT"], "2")

    def test_inherits_parent_env(self) -> None:
        env = _safe_clone_env()
        self.assertIn("PATH", env)


class TestAddToWatchlistWithUrl(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.wl_path = os.path.join(self.tmpdir, ".nostos_repos")
        self.clone_dir = os.path.join(self.tmpdir, "clones")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_clones_and_adds_url(self) -> None:
        repo_dir = os.path.join(self.clone_dir, "repo")
        os.makedirs(os.path.join(repo_dir, ".git"))

        with mock.patch("core.watchlist.get_watchlist_path", return_value=self.wl_path), \
             mock.patch("core.watchlist.clone_repo", return_value=repo_dir):
            result = add_to_watchlist(
                "https://github.com/user/repo.git", clone_dir=self.clone_dir
            )

        self.assertTrue(result)
        with open(self.wl_path) as f:
            self.assertIn(os.path.realpath(repo_dir), f.read())

    def test_returns_false_on_clone_failure(self) -> None:
        with mock.patch("core.watchlist.get_watchlist_path", return_value=self.wl_path), \
             mock.patch("core.watchlist.clone_repo", return_value=None):
            result = add_to_watchlist(
                "https://github.com/user/repo.git", clone_dir=self.clone_dir
            )

        self.assertFalse(result)
        self.assertFalse(os.path.exists(self.wl_path))


class TestWatchlistSafety(unittest.TestCase):
    def _write_file(self, content: str) -> str:
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".nostos_repos", delete=False)
        f.write(content)
        f.close()
        self.addCleanup(os.unlink, f.name)
        return f.name

    @unittest.skipIf(sys.platform == "win32", "Unix-only ownership check")
    def test_safe_file(self) -> None:
        path = self._write_file("/tmp/repo\n")
        self.assertTrue(_is_watchlist_safe(path))

    @unittest.skipIf(sys.platform == "win32", "Unix-only ownership check")
    def test_rejects_world_writable(self) -> None:
        path = self._write_file("/tmp/repo\n")
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IWOTH)
        self.assertFalse(_is_watchlist_safe(path))

    def test_returns_true_on_windows(self) -> None:
        path = self._write_file("/tmp/repo\n")
        with mock.patch("core.watchlist.sys") as mock_sys:
            mock_sys.platform = "win32"
            self.assertTrue(_is_watchlist_safe(path))

    def test_nonexistent_path(self) -> None:
        self.assertFalse(_is_watchlist_safe("/nonexistent/file"))


class TestLoadWatchlist(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_repo(self, name: str) -> str:
        repo_dir = os.path.join(self.tmpdir, name)
        os.makedirs(os.path.join(repo_dir, ".git"), exist_ok=True)
        return repo_dir

    def _write_watchlist(self, content: str) -> str:
        path = os.path.join(self.tmpdir, ".nostos_repos")
        with open(path, "w") as f:
            f.write(content)
        return path

    def test_loads_valid_repos(self) -> None:
        repo_a = self._make_repo("repo-a")
        repo_b = self._make_repo("repo-b")
        wl_path = self._write_watchlist(f"{repo_a}\n{repo_b}\n")

        with mock.patch("core.watchlist.get_watchlist_path", return_value=wl_path):
            repos = load_watchlist()

        self.assertEqual(len(repos), 2)
        self.assertIn(os.path.realpath(repo_a), repos)
        self.assertIn(os.path.realpath(repo_b), repos)

    def test_skips_blank_lines_and_comments(self) -> None:
        repo = self._make_repo("repo")
        wl_path = self._write_watchlist(f"\n# A comment\n{repo}\n\n# Another\n")

        with mock.patch("core.watchlist.get_watchlist_path", return_value=wl_path):
            repos = load_watchlist()

        self.assertEqual(len(repos), 1)

    def test_warns_about_stale_entries(self) -> None:
        repo = self._make_repo("repo")
        wl_path = self._write_watchlist(f"{repo}\n/nonexistent/stale-repo\n")

        with mock.patch("core.watchlist.get_watchlist_path", return_value=wl_path):
            repos = load_watchlist()

        self.assertEqual(len(repos), 1)

    def test_empty_file(self) -> None:
        wl_path = self._write_watchlist("")
        with mock.patch("core.watchlist.get_watchlist_path", return_value=wl_path):
            repos = load_watchlist()
        self.assertEqual(repos, [])

    def test_no_file(self) -> None:
        with mock.patch("core.watchlist.get_watchlist_path", return_value="/nonexistent"):
            repos = load_watchlist()
        self.assertEqual(repos, [])


class TestAddToWatchlist(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.wl_path = os.path.join(self.tmpdir, ".nostos_repos")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_repo(self, name: str) -> str:
        repo_dir = os.path.join(self.tmpdir, name)
        os.makedirs(os.path.join(repo_dir, ".git"), exist_ok=True)
        return repo_dir

    def test_adds_valid_repo(self) -> None:
        repo = self._make_repo("repo-a")
        with mock.patch("core.watchlist.get_watchlist_path", return_value=self.wl_path):
            result = add_to_watchlist(repo)

        self.assertTrue(result)
        with open(self.wl_path) as f:
            content = f.read()
        self.assertIn(os.path.realpath(repo), content)

    def test_rejects_non_repo(self) -> None:
        non_repo = os.path.join(self.tmpdir, "not-a-repo")
        os.makedirs(non_repo)
        with mock.patch("core.watchlist.get_watchlist_path", return_value=self.wl_path):
            result = add_to_watchlist(non_repo)

        self.assertFalse(result)

    def test_rejects_duplicate(self) -> None:
        repo = self._make_repo("repo-a")
        with mock.patch("core.watchlist.get_watchlist_path", return_value=self.wl_path):
            add_to_watchlist(repo)
            result = add_to_watchlist(repo)

        self.assertFalse(result)

    def test_appends_to_existing(self) -> None:
        repo_a = self._make_repo("repo-a")
        repo_b = self._make_repo("repo-b")
        with mock.patch("core.watchlist.get_watchlist_path", return_value=self.wl_path):
            add_to_watchlist(repo_a)
            add_to_watchlist(repo_b)

        with open(self.wl_path) as f:
            lines = [line.strip() for line in f if line.strip()]
        self.assertEqual(len(lines), 2)


class TestRemoveFromWatchlist(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.wl_path = os.path.join(self.tmpdir, ".nostos_repos")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_repo(self, name: str) -> str:
        repo_dir = os.path.join(self.tmpdir, name)
        os.makedirs(os.path.join(repo_dir, ".git"), exist_ok=True)
        return repo_dir

    def test_removes_existing_entry(self) -> None:
        repo_a = self._make_repo("repo-a")
        repo_b = self._make_repo("repo-b")
        with mock.patch("core.watchlist.get_watchlist_path", return_value=self.wl_path):
            add_to_watchlist(repo_a)
            add_to_watchlist(repo_b)
            result = remove_from_watchlist(repo_a)

        self.assertTrue(result)
        with open(self.wl_path) as f:
            content = f.read()
        self.assertNotIn(os.path.realpath(repo_a), content)
        self.assertIn(os.path.realpath(repo_b), content)

    def test_returns_false_for_missing_entry(self) -> None:
        repo = self._make_repo("repo")
        with mock.patch("core.watchlist.get_watchlist_path", return_value=self.wl_path):
            add_to_watchlist(repo)
            result = remove_from_watchlist("/nonexistent/repo")

        self.assertFalse(result)

    def test_returns_false_when_no_file(self) -> None:
        with mock.patch("core.watchlist.get_watchlist_path", return_value="/nonexistent"):
            result = remove_from_watchlist("/tmp/repo")

        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
