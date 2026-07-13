"""Shared HTTP hardening for nostos network calls.

nostos attaches an `Authorization: Bearer <token>` header to upstream
probe and self-update requests. Python's default redirect handling
copies request headers onto the redirected request, so a host that
responds with a 3xx redirect to a different host would receive the
token. That host is only ever one already listed in auth.toml, but a
compromised or misconfigured allowed host should still not be able to
harvest a token destined for a different host.

This module installs a process-wide opener whose redirect handler drops
credential-bearing headers whenever a redirect crosses to a different
host. Call sites keep using `urllib.request.urlopen`, which delegates to
the installed opener, so the hardening applies without changing (or
un-mockable-ing) the existing request code.
"""

from __future__ import annotations

import urllib.request
from urllib.parse import urlparse

# Headers that must not survive a cross-host redirect.
_SENSITIVE_HEADERS: tuple[str, ...] = ("Authorization", "Cookie")


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Strip credential headers when a redirect changes host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is None:
            return None
        old_host = urlparse(req.full_url).hostname
        new_host = urlparse(newurl).hostname
        if old_host != new_host:
            for header in _SENSITIVE_HEADERS:
                # Request stores header keys capitalised; remove_header
                # applies the same capitalisation, so this matches.
                new.remove_header(header)
        return new


_installed = False


def install_safe_opener() -> None:
    """Install the credential-stripping opener as the process default.

    Idempotent: safe to call from every module that performs network I/O.
    """
    global _installed
    if _installed:
        return
    urllib.request.install_opener(
        urllib.request.build_opener(_SafeRedirectHandler())
    )
    _installed = True
