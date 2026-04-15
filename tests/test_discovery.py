import os
import tempfile
import unittest

from core.discovery import discover_repositories, is_excluded, validate_path


class TestIsExcluded(unittest.TestCase):
    def test_matches_wildcard(self):
        self.assertTrue(is_excluded("/home/user/archived-old", ["archived-*"]))

    def test_no_match(self):
        self.assertFalse(is_excluded("/home/user/my-project", ["archived-*"]))

    def test_empty_patterns(self):
        self.assertFalse(is_excluded("/home/user/anything", []))

    def test_multiple_patterns(self):
        patterns = ["archived-*", "temp-*", ".backup-*"]
        self.assertTrue(is_excluded("/home/user/temp-stuff", patterns))
        self.assertFalse(is_excluded("/home/user/production", patterns))

    def test_exact_match(self):
        self.assertTrue(is_excluded("/home/user/vendor", ["vendor"]))
        self.assertFalse(is_excluded("/home/user/vendor-lib", ["vendor"]))


class TestValidatePath(unittest.TestCase):
    def test_valid_directory(self):
        with tempfile.TemporaryDirectory() as d:
            result = validate_path(d)
            self.assertEqual(result, os.path.realpath(d))

    def test_invalid_path_exits(self):
        with self.assertRaises(SystemExit):
            validate_path("/nonexistent/path/that/does/not/exist")

    def test_resolves_symlinks(self):
        with tempfile.TemporaryDirectory() as d:
            result = validate_path(d)
            self.assertFalse(os.path.islink(result))


class TestDiscoverRepositories(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.root, ignore_errors=True)

    def _make_repo(self, *parts):
        repo_dir = os.path.join(self.root, *parts)
        os.makedirs(os.path.join(repo_dir, ".git"), exist_ok=True)
        return repo_dir

    def _make_dir(self, *parts):
        d = os.path.join(self.root, *parts)
        os.makedirs(d, exist_ok=True)
        return d

    def test_finds_repos(self):
        repo_a = self._make_repo("repo-a")
        repo_b = self._make_repo("repo-b")
        results = list(discover_repositories(self.root))
        self.assertEqual(sorted(results), sorted([repo_a, repo_b]))

    def test_no_repos(self):
        self._make_dir("empty-dir")
        results = list(discover_repositories(self.root))
        self.assertEqual(results, [])

    def test_depth_limit(self):
        self._make_repo("level1", "level2", "deep-repo")
        results = list(discover_repositories(self.root, max_depth=1))
        self.assertEqual(results, [])

    def test_depth_limit_includes_shallow(self):
        shallow = self._make_repo("shallow-repo")
        self._make_repo("a", "b", "c", "deep-repo")
        results = list(discover_repositories(self.root, max_depth=2))
        self.assertEqual(results, [shallow])

    def test_exclude_patterns(self):
        self._make_repo("my-project")
        self._make_repo("archived-old")
        self._make_repo("temp-stuff")
        results = list(
            discover_repositories(self.root, exclude_patterns=["archived-*", "temp-*"])
        )
        self.assertEqual(len(results), 1)
        self.assertIn("my-project", results[0])

    def test_skips_hidden_directories(self):
        self._make_dir(".hidden", "sub")
        visible = self._make_repo("visible-repo")
        results = list(discover_repositories(self.root))
        self.assertEqual(results, [visible])

    def test_does_not_descend_into_found_repos(self):
        parent = self._make_repo("parent-repo")
        self._make_repo("parent-repo", "nested-repo")
        results = list(discover_repositories(self.root))
        self.assertEqual(results, [parent])

    def test_generator_yields_incrementally(self):
        self._make_repo("repo-a")
        self._make_repo("repo-b")
        gen = discover_repositories(self.root)
        first = next(gen)
        self.assertIsNotNone(first)


if __name__ == "__main__":
    unittest.main()
