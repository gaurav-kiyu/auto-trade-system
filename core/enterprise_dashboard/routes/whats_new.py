""""What's New" page for the Enterprise Dashboard.

Renders the latest CHANGELOG.md entry so an admin can discover new features
from inside the running dashboard, instead of needing to read the repo's
markdown files directly. Several features added in the same release as this
module (signal "order placed" tracking, the /placed Telegram command,
archive-before-delete signal retention, the installable PWA, the payoff
calculator) were otherwise only discoverable by reading CHANGELOG.md or
CLAUDE.md by hand - this closes that discoverability gap going forward for
whatever ships next, without needing another hand-written page each time.

Deliberately a minimal, purpose-built renderer (bold/code/nested bullets)
rather than a new markdown-library dependency - CHANGELOG.md's structure in
this repo is consistently simple enough that a general markdown parser would
be more machinery than the job needs.
"""

from __future__ import annotations

import html
import logging
import re
from pathlib import Path

_log = logging.getLogger(__name__)

# core/enterprise_dashboard/routes/whats_new.py -> ROOT is 4 parents up.
_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_CHANGELOG_PATH = _ROOT / "CHANGELOG.md"

_VERSION_HEADING_RE = re.compile(r"^##\s+v?([0-9][0-9.]*)\s*\(([^)]*)\)\s*$")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_CODE_RE = re.compile(r"`([^`]+?)`")


def _inline_format(text: str) -> str:
    """Escape then apply **bold** / `code` inline formatting."""
    escaped = html.escape(text)
    escaped = _BOLD_RE.sub(r"<strong>\1</strong>", escaped)
    escaped = _CODE_RE.sub(r"<code>\1</code>", escaped)
    return escaped


def _render_bullets(lines: list[str]) -> str:
    """Render a flat list of '-'-prefixed lines (2-space nesting) as <ul>."""
    html_parts: list[str] = []
    # Stack of (indent_level, open) - track how many <ul> levels are open.
    open_levels: list[int] = []

    def _indent_of(line: str) -> int:
        stripped = line.lstrip(" ")
        return (len(line) - len(stripped)) // 2

    for raw_line in lines:
        if not raw_line.strip().startswith("-"):
            continue
        indent = _indent_of(raw_line)
        content = raw_line.strip()[1:].strip()

        while open_levels and open_levels[-1] > indent:
            html_parts.append("</ul>")
            open_levels.pop()
        if not open_levels or open_levels[-1] < indent:
            html_parts.append("<ul>")
            open_levels.append(indent)

        html_parts.append(f"<li>{_inline_format(content)}</li>")

    while open_levels:
        html_parts.append("</ul>")
        open_levels.pop()

    return "".join(html_parts)


def get_latest_changelog_entry() -> dict:
    """Parse CHANGELOG.md and return the newest version's entry as HTML.

    Returns a dict with version, date, and html (rendered body), or an
    "unavailable" status dict if the file is missing or empty - this page
    must never crash the dashboard just because CHANGELOG.md moved.
    """
    if not _CHANGELOG_PATH.is_file():
        return {"status": "unavailable", "detail": "CHANGELOG.md not found"}

    try:
        text = _CHANGELOG_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        _log.warning("[DASH] Failed to read CHANGELOG.md: %s", exc)
        return {"status": "unavailable", "detail": str(exc)}

    lines = text.splitlines()
    start_idx = None
    version, date = "", ""
    for i, line in enumerate(lines):
        m = _VERSION_HEADING_RE.match(line.strip())
        if m:
            start_idx = i
            version, date = m.group(1), m.group(2)
            break

    if start_idx is None:
        return {"status": "unavailable", "detail": "No version heading found in CHANGELOG.md"}

    end_idx = len(lines)
    for j in range(start_idx + 1, len(lines)):
        if _VERSION_HEADING_RE.match(lines[j].strip()):
            end_idx = j
            break

    body_lines = lines[start_idx + 1:end_idx]
    body_html = _render_bullets(body_lines)

    return {
        "status": "ok",
        "version": version,
        "date": date,
        "html": body_html or "<p>No details recorded for this release.</p>",
    }
