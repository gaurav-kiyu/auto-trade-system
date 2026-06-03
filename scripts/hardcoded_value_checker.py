"""
Hardcoded Value Checker (v2.46 Sprint 0).

CI guard — scans the codebase for values that must live in config, not code.
Exits 0 if clean, exits 1 and prints violations if any found.

Usage:
    python scripts/hardcoded_value_checker.py [--warn-only]
    python scripts/hardcoded_value_checker.py --help

Rules checked
-------------
R05  datetime.now() (local time) — must use now_ist() from core.datetime_ist
     (datetime.now(timezone.utc) is allowed for audit/UTC logging)
R06  time.sleep() in core/ modules (warn only — some background threads allowed)
R10  import anthropic / import openai / from anthropic — prohibited AI SDKs
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SCAN_DIRS = ["core", "index_app"]

# Global excludes — these files/patterns are never checked for any rule
_GLOBAL_EXCLUDES = [
    "scripts/hardcoded_value_checker.py",
    "scripts/generate_config_schemas.py",
]


def _is_code_line(line: str) -> bool:
    """Return True if the line is not a pure comment or docstring line."""
    stripped = line.strip()
    return bool(stripped) and not stripped.startswith("#")


class Violation:
    __slots__ = ("rule_id", "severity", "description", "file", "line_no", "line")

    def __init__(self, rule_id, severity, description, file, line_no, line):
        self.rule_id = rule_id
        self.severity = severity
        self.description = description
        self.file = file
        self.line_no = line_no
        self.line = line.rstrip()

    def __str__(self) -> str:
        return (
            f"  [{self.rule_id}] {self.file}:{self.line_no}\n"
            f"    {self.description}\n"
            f"    >>> {self.line}"
        )


# ── Rules ────────────────────────────────────────────────────────────────────────

_RULES: list[dict] = [
    {
        "id": "R05",
        "desc": "datetime.now() (local time) — use now_ist() from core.datetime_ist",
        # Match datetime.now( but NOT datetime.now(timezone.utc) or datetime.now(tz=
        "pattern": re.compile(r"datetime\.now\s*\(\s*\)"),
        "exclude_files": {
            # ── stdlib / infrastructure (UTC timestamps OK) ──
            "core/datetime_ist.py",
            "core/audit_engine.py",
            "core/retention_engine.py",
            # ── known pre-existing violations (fix in future sprint) ──
            "core/auto_tuner.py",
            "core/event_calendar.py",
            "core/ml_classifier.py",
            "core/report_generator.py",
            "core/session_classifier.py",
            "core/slippage_model.py",
            "index_app/gui/_desk_body.py",
            "index_app/index_trader.py",
        },
        "code_only": True,  # skip pure comment lines
        "severity": "error",
    },
    {
        "id": "R06",
        "desc": "time.sleep() in core/ — background threads should prefer shutdown-aware waits",
        "pattern": re.compile(r"\btime\.sleep\s*\("),
        "exclude_files": {
            "core/news_sentinel.py",     # intentional background thread
            "core/health_checker.py",    # background thread
            "core/yf_bar_fetch.py",      # rate-limit sleep in fetcher thread
            "core/telegram_queue.py",    # queue worker thread
            "core/signal_importer.py",   # watcher thread
            "core/ai_engine.py",         # cooldown sleep in AI engine
        },
        "code_only": True,
        "severity": "warn",
    },
    {
        "id": "R10",
        "desc": "AI SDK detected (anthropic/openai) — prohibited per project policy",
        "pattern": re.compile(r"^\s*(import\s+(anthropic|openai)|from\s+anthropic\s+import)", re.MULTILINE),
        "exclude_files": set(),
        "code_only": False,  # catch even in strings / comments
        "severity": "error",
    },
]


# ── Scanner ───────────────────────────────────────────────────────────────────────

def _relative(path: Path) -> str:
    return str(path.relative_to(_ROOT)).replace("\\", "/")


def _globally_excluded(path: Path) -> bool:
    rel = _relative(path)
    for pat in _GLOBAL_EXCLUDES:
        if rel == pat or path.name == pat:
            return True
    return False


def check_file(path: Path) -> list[Violation]:
    violations = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except (OSError, UnicodeDecodeError):
        return violations

    rel = _relative(path)
    for rule in _RULES:
        if rel in rule["exclude_files"]:
            continue
        rx = rule["pattern"]
        for i, line in enumerate(lines, start=1):
            if rule["code_only"] and not _is_code_line(line):
                continue
            if rx.search(line):
                violations.append(Violation(
                    rule["id"], rule["severity"], rule["desc"], rel, i, line
                ))
    return violations


def collect_files() -> list[Path]:
    files = []
    for d in _SCAN_DIRS:
        p = _ROOT / d
        if p.exists():
            files.extend(p.rglob("*.py"))
    return [f for f in files if not _globally_excluded(f)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--warn-only", action="store_true",
                        help="Treat all violations as warnings (exit 0)")
    args = parser.parse_args()

    files = collect_files()
    all_violations: list[Violation] = []
    for f in sorted(files):
        all_violations.extend(check_file(f))

    errors   = [v for v in all_violations if v.severity == "error"]
    warnings = [v for v in all_violations if v.severity == "warn"]

    if warnings:
        print(f"\nHardcoded value checker — {len(warnings)} warning(s):")
        for v in warnings:
            print(v)
        print()

    if errors:
        print(f"Hardcoded value checker — {len(errors)} ERROR(s) (CI blocking):")
        for v in errors:
            print(v)
        print()

    if not all_violations:
        print(f"Hardcoded value checker: {len(files)} files scanned — all clean.")
        return 0

    if errors and not args.warn_only:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
