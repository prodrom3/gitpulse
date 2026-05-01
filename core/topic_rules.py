"""Topic curation for upstream auto-tag imports.

Applies two transformations to the list of topics returned by an
upstream probe before they become local tags:

    deny  - drop these topics entirely (junk, single-letter, repo names,
            event markers like 'hacktoberfest').
    alias - rewrite source -> target so synonyms collapse to one
            canonical form (e.g. 'penetration-testing' -> 'pentest').

Rules live in $XDG_CONFIG_HOME/nostos/topic_rules.toml. The file is
optional: if it does not exist the rules are empty and topics pass
through unchanged. The file is owned-by-user / not world-writable
checked the same way as auth.toml.

Schema:

    deny = ["foo", "hacktoberfest", "ubuntu"]

    [alias]
    "penetration-testing" = "pentest"
    "red-teaming"         = "redteam"

The alias step runs after deny, so an aliased target that itself is
denied will still be dropped. Aliases are applied at most once - no
chaining - so cycles are impossible.
"""

from __future__ import annotations

import logging
import os
import stat
import sys
from typing import Any

from .paths import ensure_config_dir, topic_rules_path

# Python 3.11+ ships tomllib; on 3.10 we fall back to tomli if installed.
_toml: Any = None
try:
    import tomllib as _toml  # type: ignore[import-not-found,no-redef,unused-ignore]
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    try:
        import tomli as _toml  # type: ignore[import-not-found,no-redef]
    except ModuleNotFoundError:
        pass


class TopicRules:
    """In-memory view of topic_rules.toml.

    Empty by default. `apply()` is a no-op when both deny and alias are
    empty, so callers can use this without checking first.
    """

    def __init__(
        self,
        deny: list[str] | None = None,
        alias: dict[str, str] | None = None,
    ) -> None:
        self.deny: set[str] = {self._norm(d) for d in (deny or []) if isinstance(d, str)}
        self.deny.discard("")
        self.alias: dict[str, str] = {}
        for src, dst in (alias or {}).items():
            if not isinstance(src, str) or not isinstance(dst, str):
                continue
            ns = self._norm(src)
            nd = self._norm(dst)
            if ns and nd:
                self.alias[ns] = nd

    @staticmethod
    def _norm(name: str) -> str:
        return name.strip().lower()

    def apply(self, topics: list[str]) -> list[str]:
        """Return a curated, deduped list of topics.

        Steps:
        1. Lowercase, strip, drop empties / non-strings.
        2. Drop anything in deny.
        3. Replace via alias (single hop, no chaining).
        4. Drop any alias target that ends up in deny.
        5. Dedupe while preserving first-seen order.
        """
        seen: set[str] = set()
        out: list[str] = []
        for raw in topics:
            if not isinstance(raw, str):
                continue
            name = self._norm(raw)
            if not name or name in self.deny:
                continue
            name = self.alias.get(name, name)
            if name in self.deny or name in seen:
                continue
            seen.add(name)
            out.append(name)
        return out


def _is_rules_file_safe(path: str) -> bool:
    """Reject if not owned by current user or world-writable on Unix."""
    try:
        st = os.stat(path)
    except OSError:
        return False
    if sys.platform == "win32":
        return True
    if st.st_uid != os.getuid():
        logging.warning(
            f"Ignoring {path}: owned by uid {st.st_uid}, not current user"
        )
        return False
    if st.st_mode & stat.S_IWOTH:
        logging.warning(
            f"Ignoring {path}: world-writable (fix with: chmod 600 {path})"
        )
        return False
    return True


def load_rules(path: str | None = None) -> TopicRules:
    """Load the rules file. Returns an empty TopicRules if the file is
    missing, unsafe, or malformed. Never raises."""
    cfg_path = path or topic_rules_path()
    if not os.path.isfile(cfg_path):
        return TopicRules()
    if not _is_rules_file_safe(cfg_path):
        return TopicRules()
    if _toml is None:
        logging.warning(
            f"Ignoring {cfg_path}: no TOML parser available on this Python."
        )
        return TopicRules()

    try:
        with open(cfg_path, "rb") as f:
            data = _toml.load(f)
    except (OSError, _toml.TOMLDecodeError) as e:
        logging.warning(f"Ignoring {cfg_path}: parse error ({e})")
        return TopicRules()

    deny_raw = data.get("deny", [])
    alias_raw = data.get("alias", {})
    deny = deny_raw if isinstance(deny_raw, list) else []
    alias = alias_raw if isinstance(alias_raw, dict) else {}
    return TopicRules(deny=deny, alias=alias)


def save_rules(rules: TopicRules, path: str | None = None) -> str:
    """Serialize rules to disk as TOML. Returns the path written.

    Creates the config directory if missing. Writes to a temp file and
    renames atomically so a crash mid-write cannot corrupt the file.
    On Unix the file is chmod'd to 0600.
    """
    if path is None:
        ensure_config_dir()
        path = topic_rules_path()
    else:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    body = dump_rules(rules)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(body)
    os.replace(tmp, path)
    if sys.platform != "win32":
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    return path


def parse_rules_from_text(text: str) -> TopicRules:
    """Parse a TOML rules document from a string.

    Used for `nostos topics import` where the source is a file path
    the user passed explicitly (or stdin). Skips the owned-by-user /
    not-world-writable checks that load_rules() applies to the
    canonical config-dir file, since the caller has already chosen
    to trust the source.

    Raises ValueError on malformed TOML.
    """
    if _toml is None:
        raise ValueError("no TOML parser available on this Python")
    try:
        data = _toml.loads(text)
    except _toml.TOMLDecodeError as e:
        raise ValueError(f"parse error: {e}") from None
    deny_raw = data.get("deny", [])
    alias_raw = data.get("alias", {})
    deny = deny_raw if isinstance(deny_raw, list) else []
    alias = alias_raw if isinstance(alias_raw, dict) else {}
    return TopicRules(deny=deny, alias=alias)


def merge_rules(base: TopicRules, incoming: TopicRules) -> TopicRules:
    """Return a new TopicRules with deny = base.deny union incoming.deny
    and alias = base.alias overlaid with incoming.alias (incoming wins
    on conflict)."""
    merged_alias: dict[str, str] = dict(base.alias)
    merged_alias.update(incoming.alias)
    return TopicRules(
        deny=sorted(base.deny | incoming.deny),
        alias=merged_alias,
    )


def dump_rules(rules: TopicRules) -> str:
    """Serialize a TopicRules to TOML.

    Hand-rolled to keep nostos zero-dep; the schema is small and fixed
    enough that a 20-line writer is preferable to a runtime dependency.
    """
    lines: list[str] = [
        "# nostos topic curation rules.",
        "# Edit via `nostos topics` or by hand. See `nostos topics --help`.",
        "",
    ]
    if rules.deny:
        items = ", ".join(f'"{_escape(n)}"' for n in sorted(rules.deny))
        lines.append(f"deny = [{items}]")
    else:
        lines.append("deny = []")
    lines.append("")
    lines.append("[alias]")
    for src in sorted(rules.alias):
        dst = rules.alias[src]
        lines.append(f'"{_escape(src)}" = "{_escape(dst)}"')
    lines.append("")
    return "\n".join(lines)


def _escape(s: str) -> str:
    """Minimal TOML basic-string escaping for our restricted charset.

    Topic names are kebab-case ASCII in practice; we still escape
    backslash and double-quote defensively. No multi-line strings, no
    control chars are expected in the input.
    """
    return s.replace("\\", "\\\\").replace('"', '\\"')


__all__ = [
    "TopicRules",
    "load_rules",
    "save_rules",
    "parse_rules_from_text",
    "dump_rules",
    "merge_rules",
]
