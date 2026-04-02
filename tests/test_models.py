import unittest

from core.models import RepoResult, RepoStatus


class TestRepoStatus(unittest.TestCase):
    def test_enum_values(self):
        self.assertEqual(RepoStatus.UPDATED.value, "updated")
        self.assertEqual(RepoStatus.UP_TO_DATE.value, "up-to-date")
        self.assertEqual(RepoStatus.FETCHED.value, "fetched")
        self.assertEqual(RepoStatus.SKIPPED.value, "skipped")
        self.assertEqual(RepoStatus.FAILED.value, "failed")

    def test_all_statuses_present(self):
        names = {s.name for s in RepoStatus}
        self.assertEqual(names, {"UPDATED", "UP_TO_DATE", "FETCHED", "SKIPPED", "FAILED"})


class TestRepoResult(unittest.TestCase):
    def test_defaults(self):
        r = RepoResult("/tmp/repo", RepoStatus.UPDATED)
        self.assertEqual(r.path, "/tmp/repo")
        self.assertEqual(r.status, RepoStatus.UPDATED)
        self.assertIsNone(r.reason)
        self.assertIsNone(r.branch)
        self.assertIsNone(r.remote_url)

    def test_full_construction(self):
        r = RepoResult(
            "/tmp/repo", RepoStatus.SKIPPED,
            reason="dirty working tree",
            branch="main",
            remote_url="git@github.com:user/repo.git",
        )
        self.assertEqual(r.reason, "dirty working tree")
        self.assertEqual(r.branch, "main")
        self.assertEqual(r.remote_url, "git@github.com:user/repo.git")

    def test_to_dict(self):
        r = RepoResult(
            "/tmp/repo", RepoStatus.FAILED,
            reason="timed out", branch="dev", remote_url="https://example.com/repo",
        )
        d = r.to_dict()
        self.assertEqual(d["path"], "/tmp/repo")
        self.assertEqual(d["status"], "failed")
        self.assertEqual(d["reason"], "timed out")
        self.assertEqual(d["branch"], "dev")
        self.assertEqual(d["remote_url"], "https://example.com/repo")

    def test_to_dict_with_none_fields(self):
        r = RepoResult("/tmp/repo", RepoStatus.UP_TO_DATE)
        d = r.to_dict()
        self.assertIsNone(d["reason"])
        self.assertIsNone(d["branch"])
        self.assertIsNone(d["remote_url"])


if __name__ == "__main__":
    unittest.main()
