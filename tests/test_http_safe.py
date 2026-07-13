"""Tests for the cross-host credential-stripping redirect handler."""

import unittest
import urllib.request

from core.http_safe import _SafeRedirectHandler, install_safe_opener


class TestSafeRedirectHandler(unittest.TestCase):
    def _redirect(self, orig_url: str, new_url: str) -> urllib.request.Request:
        req = urllib.request.Request(orig_url)
        req.add_header("Authorization", "Bearer secret")
        req.add_header("Cookie", "session=abc")
        handler = _SafeRedirectHandler()
        return handler.redirect_request(req, None, 302, "Found", {}, new_url)

    def test_strips_credentials_on_host_change(self) -> None:
        new = self._redirect(
            "https://api.github.com/x", "https://evil.example/x"
        )
        self.assertIsNotNone(new)
        self.assertNotIn("Authorization", new.headers)
        self.assertNotIn("Cookie", new.headers)

    def test_keeps_credentials_on_same_host(self) -> None:
        new = self._redirect(
            "https://api.github.com/x", "https://api.github.com/y"
        )
        self.assertIsNotNone(new)
        self.assertIn("Authorization", new.headers)

    def test_strips_on_scheme_downgrade_to_other_host(self) -> None:
        new = self._redirect(
            "https://gitlab.com/api", "http://169.254.169.254/latest"
        )
        self.assertIsNotNone(new)
        self.assertNotIn("Authorization", new.headers)


class TestInstallSafeOpener(unittest.TestCase):
    def test_idempotent(self) -> None:
        # Should not raise on repeated calls.
        install_safe_opener()
        install_safe_opener()


if __name__ == "__main__":
    unittest.main()
