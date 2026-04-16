"""Static HTML dashboard generator for gitpulse.

Consumes a digest dict (from core.digest.build_digest) and renders
a self-contained HTML file with inline CSS. No JavaScript framework,
no external assets, no CDN links. The result can be opened in any
browser, emailed, or served from a static file server.

Zero runtime dependencies beyond the stdlib.
"""

from __future__ import annotations

import html
from typing import Any


def render_html(digest: dict[str, Any], *, title: str = "gitpulse fleet health") -> str:
    """Produce a standalone HTML string from a digest dict."""
    now = digest.get("generated_at", "")
    counts = digest.get("counts", {})
    total = counts.get("total", 0)
    by_status = counts.get("by_status", {})

    sections: list[str] = []

    # Status bar
    status_bars = []
    palette = {
        "new": "#3b82f6",
        "reviewed": "#6b7280",
        "in-use": "#22c55e",
        "dropped": "#9ca3af",
        "flagged": "#ef4444",
    }
    for status, count in sorted(by_status.items()):
        color = palette.get(status, "#6b7280")
        pct = (count / total * 100) if total else 0
        status_bars.append(
            f'<div style="background:{color};width:{pct:.1f}%;min-width:2px" '
            f'title="{_e(status)}: {count}"></div>'
        )
    sections.append(
        '<div class="status-bar">' + "".join(status_bars) + "</div>"
    )

    # Counts summary
    status_pills = " ".join(
        f'<span class="pill" style="background:{palette.get(s, "#6b7280")}">'
        f"{_e(s)} {c}</span>"
        for s, c in sorted(by_status.items())
    )
    sections.append(f'<div class="summary">Total: {total} {status_pills}</div>')

    # Each digest section as a table
    sections.append(_section("New intakes", digest.get("added", []), _row_added))
    sections.append(
        _section("Refreshed upstream", digest.get("refreshed", []), _row_refreshed)
    )
    sections.append(
        _section(
            "Archived upstream (supply-chain flag)",
            digest.get("archived", []),
            _row_archived,
        )
    )
    sections.append(
        _section("Operator-flagged", digest.get("flagged", []), _row_flagged)
    )
    sections.append(
        _section(
            f"Stale local (untouched > {digest.get('stale_days', 90)}d)",
            digest.get("stale_local", []),
            _row_stale,
        )
    )
    sections.append(
        _section(
            f"Dormant upstream (no push > {digest.get('dormant_days', 365)}d)",
            digest.get("dormant", []),
            _row_dormant,
        )
    )

    body = "\n".join(sections)
    return _TEMPLATE.replace("{{TITLE}}", _e(title)).replace(
        "{{GENERATED}}", _e(now)
    ).replace("{{BODY}}", body)


# ---------- helpers ----------


def _e(text: Any) -> str:
    return html.escape(str(text))


def _section(
    title: str,
    rows: list[dict[str, Any]],
    formatter: Any,
) -> str:
    if not rows:
        return (
            f'<div class="section"><h2>{_e(title)} (0)</h2>'
            f"<p>None.</p></div>"
        )
    header, body_rows = formatter(rows)
    trs = "".join(f"<tr>{''.join(f'<td>{_e(c)}</td>' for c in r)}</tr>" for r in body_rows)
    ths = "".join(f"<th>{_e(h)}</th>" for h in header)
    return (
        f'<div class="section"><h2>{_e(title)} ({len(rows)})</h2>'
        f"<table><thead><tr>{ths}</tr></thead><tbody>{trs}</tbody></table></div>"
    )


def _row_added(rows: list[dict[str, Any]]) -> tuple[list[str], list[list[str]]]:
    header = ["ID", "Path", "Tags", "Source"]
    body = [
        [
            str(r.get("id", "")),
            str(r.get("path", "")),
            ",".join(r.get("tags", [])),
            str(r.get("source") or "-"),
        ]
        for r in rows
    ]
    return header, body


def _row_refreshed(rows: list[dict[str, Any]]) -> tuple[list[str], list[list[str]]]:
    header = ["ID", "Path", "Archived", "Last push", "Release"]
    body = [
        [
            str(r.get("id", "")),
            str(r.get("path", "")),
            str(bool(r.get("archived"))),
            str(r.get("last_push") or "-"),
            str(r.get("latest_release") or "-"),
        ]
        for r in rows
    ]
    return header, body


def _row_archived(rows: list[dict[str, Any]]) -> tuple[list[str], list[list[str]]]:
    header = ["ID", "Path", "Host", "Owner/Name"]
    body = [
        [
            str(r.get("id", "")),
            str(r.get("path", "")),
            str(r.get("host") or "-"),
            f"{r.get('owner') or ''}/{r.get('name') or ''}",
        ]
        for r in rows
    ]
    return header, body


def _row_flagged(rows: list[dict[str, Any]]) -> tuple[list[str], list[list[str]]]:
    header = ["ID", "Path", "Added"]
    body = [
        [str(r.get("id", "")), str(r.get("path", "")), str(r.get("added_at") or "-")]
        for r in rows
    ]
    return header, body


def _row_stale(rows: list[dict[str, Any]]) -> tuple[list[str], list[list[str]]]:
    header = ["ID", "Path", "Last touched"]
    body = [
        [
            str(r.get("id", "")),
            str(r.get("path", "")),
            str(r.get("last_touched_at") or "never"),
        ]
        for r in rows
    ]
    return header, body


def _row_dormant(rows: list[dict[str, Any]]) -> tuple[list[str], list[list[str]]]:
    header = ["ID", "Path", "Last push"]
    body = [
        [str(r.get("id", "")), str(r.get("path", "")), str(r.get("last_push") or "-")]
        for r in rows
    ]
    return header, body


# ---------- template ----------


_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{TITLE}}</title>
<style>
  :root { --bg: #0f172a; --fg: #e2e8f0; --muted: #94a3b8; --border: #334155; --card: #1e293b; }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: system-ui, -apple-system, sans-serif; background: var(--bg); color: var(--fg); padding: 2rem; max-width: 1200px; margin: 0 auto; }
  h1 { font-size: 1.5rem; margin-bottom: 0.25rem; }
  .meta { color: var(--muted); font-size: 0.85rem; margin-bottom: 1.5rem; }
  .status-bar { display: flex; height: 8px; border-radius: 4px; overflow: hidden; margin-bottom: 1rem; gap: 2px; }
  .summary { margin-bottom: 2rem; }
  .pill { display: inline-block; padding: 0.15rem 0.5rem; border-radius: 4px; color: #fff; font-size: 0.8rem; margin-right: 0.25rem; }
  .section { background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 1rem; margin-bottom: 1rem; }
  .section h2 { font-size: 1rem; margin-bottom: 0.75rem; }
  .section p { color: var(--muted); font-size: 0.9rem; }
  table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
  th { text-align: left; color: var(--muted); border-bottom: 1px solid var(--border); padding: 0.4rem 0.5rem; }
  td { padding: 0.4rem 0.5rem; border-bottom: 1px solid var(--border); word-break: break-all; }
  tr:last-child td { border-bottom: none; }
</style>
</head>
<body>
<h1>{{TITLE}}</h1>
<p class="meta">Generated {{GENERATED}} by gitpulse</p>
{{BODY}}
</body>
</html>
"""
