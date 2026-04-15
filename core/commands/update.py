"""`gitpulse update` - check for / apply a gitpulse self-update.

Flow:
1. --offline: print the install-method detection and the current
   version; never contact the network.
2. --check: make one HTTPS GET to api.github.com/repos/prodrom3/
   gitpulse/releases/latest, compare against the running version,
   print a single line summary, exit 0.
3. default (no --check): same release check, then if an upgrade is
   available AND the install method supports an automatic upgrade,
   prompt for confirmation (or --yes to skip) and run it.

This command is the only part of gitpulse that reaches out to
github.com in its default configuration. It is an opt-in network
call on the user's explicit command; --offline kills it hard.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

from .. import updater_self as _self
from ._common import fail, maybe_migrate_watchlist


def add_parser(subparsers: Any) -> None:
    p = subparsers.add_parser(
        "update",
        help="Check for / apply a gitpulse self-update",
        description=(
            "Compare the running gitpulse version against the latest "
            "release and (optionally) apply an upgrade. The network "
            "call goes only to api.github.com; --offline hard-disables it."
        ),
    )
    p.add_argument(
        "--check",
        action="store_true",
        help="Only report current vs. latest; do not upgrade.",
    )
    p.add_argument(
        "--offline",
        action="store_true",
        help="Do not contact the network; print local state only.",
    )
    p.add_argument(
        "--yes",
        action="store_true",
        help="Skip the confirm prompt when an upgrade is applied.",
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    maybe_migrate_watchlist()

    # Lazy import to avoid the circular import with core.cli.
    from ..cli import get_version as _get_version

    current = _get_version()
    detection = _self.detect_install_method()

    if args.offline:
        print(f"gitpulse {current} (install method: {detection['method']})")
        print(f"  upgrade_cmd: {detection['upgrade_cmd']}")
        print(f"  note: {detection['notes']}")
        print("offline mode: no release check performed.", file=sys.stderr)
        return 0

    token = os.environ.get("GITHUB_TOKEN") or None
    try:
        release = _self.fetch_latest_release(token=token)
    except _self.UpdateError as e:
        return fail(str(e))

    remote_tag_raw = release.get("tag_name") or release.get("name") or ""
    try:
        remote = _self.normalize_tag(remote_tag_raw)
    except _self.UpdateError as e:
        return fail(f"cannot parse GitHub release tag: {e}")

    newer = _self.is_newer(remote, current)
    summary = (
        f"gitpulse {current} (install method: {detection['method']}) "
        f"-> latest release: {remote} "
        f"{'[update available]' if newer else '[up to date]'}"
    )
    print(summary)

    if args.check or not newer:
        return 0

    method = detection["method"]
    if method not in {"source", "pipx"}:
        print(
            "Automatic upgrade is not supported for this install method.",
            file=sys.stderr,
        )
        print(
            f"  run manually: {detection['upgrade_cmd']}",
            file=sys.stderr,
        )
        return 0

    if not args.yes:
        prompt = f"Apply upgrade {current} -> {remote}? [y/N]: "
        try:
            confirm = input(prompt).strip().lower()
        except EOFError:
            confirm = ""
        if confirm not in {"y", "yes"}:
            print("upgrade cancelled", file=sys.stderr)
            return 0

    try:
        out = _self.run_upgrade(detection)
    except _self.UpdateError as e:
        return fail(str(e))

    if out:
        print(out)
    print(
        f"upgrade applied via {method}: {detection['upgrade_cmd']}",
        file=sys.stderr,
    )
    return 0
