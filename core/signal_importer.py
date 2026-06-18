"""
Signal Importer (v2.46 Sprint 1F).

Import manual signals from CSV files or free-text strings.
Normalises input and submits to ManualSignalQueue.

Formats supported
-----------------
CSV columns (order-independent, header required):
    index_name, direction, score, reason, expiry, lots_override,
    sl_override, target_override, analyst_name

Text (space-separated):
    "BANKNIFTY CALL 82 gap_fill_setup"
    "NIFTY PUT 78"

Public API
----------
    import_from_csv(filepath, queue, cfg, analyst) → ImportResult
    import_from_text(text, queue, cfg, analyst)    → ImportResult
    parse_signal_text(text)                        → dict | None

CLI
---
    python -m core.signal_importer --file signals.csv
    python -m core.signal_importer --text "BANKNIFTY CALL 82 reason"
"""
from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

_VALID_INDICES    = {"NIFTY", "BANKNIFTY", "FINNIFTY"}
_VALID_DIRECTIONS = {"CALL", "PUT"}

# ── Result dataclass ───────────────────────────────────────────────────────────

@dataclass
class ImportResult:
    total:     int = 0
    accepted:  int = 0
    rejected:  int = 0
    errors:    list[str] = field(default_factory=list)
    signal_ids: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.accepted > 0 and self.rejected == 0

    def summary(self) -> str:
        return (f"Import: {self.total} rows - "
                f"{self.accepted} accepted, {self.rejected} rejected")


# ── Text parser ────────────────────────────────────────────────────────────────

def parse_signal_text(text: str) -> dict[str, Any] | None:
    """
    Parse a free-text signal line into a dict.

    Accepted formats:
      "BANKNIFTY CALL 82"
      "BANKNIFTY CALL 82 gap fill breakout"
      "banknifty call 82 some reason here"

    Returns dict with keys: index_name, direction, score, reason
    Returns None if text cannot be parsed.
    """
    text = text.strip()
    if not text:
        return None
    parts = text.split(None, 3)  # max 4 parts: index, direction, score, reason
    if len(parts) < 3:
        return None

    index_name = parts[0].upper()
    direction  = parts[1].upper()
    try:
        score = int(parts[2])
    except ValueError:
        return None

    reason = parts[3] if len(parts) > 3 else ""

    if index_name not in _VALID_INDICES:
        return None
    if direction not in _VALID_DIRECTIONS:
        return None
    if not 0 <= score <= 100:
        return None

    return {
        "index_name": index_name,
        "direction": direction,
        "score": score,
        "reason": reason,
    }


# ── CSV import ─────────────────────────────────────────────────────────────────

def import_from_csv(
    filepath: str | Path,
    queue,
    cfg: dict[str, Any] | None = None,
    analyst: str = "CSV",
) -> ImportResult:
    """
    Import signals from a CSV file.

    Required CSV columns: index_name, direction, score
    Optional CSV columns: reason, expiry, lots_override, sl_override,
                          target_override, analyst_name

    Example CSV:
        index_name,direction,score,reason
        BANKNIFTY,CALL,82,gap fill
        NIFTY,PUT,75,

    Returns ImportResult.
    """
    result = ImportResult()
    path = Path(filepath)
    if not path.is_file():
        result.errors.append(f"File not found: {filepath}")
        return result

    try:
        text = path.read_text(encoding="utf-8-sig")  # handle BOM
    except (OSError, UnicodeDecodeError) as exc:
        result.errors.append(f"Cannot read file: {exc}")
        return result

    return _import_from_csv_text(text, queue, cfg, analyst, result)


def import_from_csv_text(
    csv_text: str,
    queue,
    cfg: dict[str, Any] | None = None,
    analyst: str = "CSV",
) -> ImportResult:
    """Import signals from a CSV string (e.g. from web upload)."""
    return _import_from_csv_text(csv_text, queue, cfg, analyst, ImportResult())


def _import_from_csv_text(
    csv_text: str,
    queue,
    cfg: dict[str, Any] | None = None,
    analyst: str = "CSV",
    result: ImportResult | None = None,
) -> ImportResult:
    r = result or ImportResult()
    c = cfg or {}
    default_analyst = c.get("manual_signal_default_analyst", analyst)

    csv_text = csv_text.lstrip("﻿")  # strip UTF-8 BOM if present
    try:
        reader = csv.DictReader(io.StringIO(csv_text))
        rows = list(reader)
    except (csv.Error, StopIteration, OSError) as exc:
        r.errors.append(f"CSV parse error: {exc}")
        return r

    for i, row in enumerate(rows, start=2):  # start=2 because row 1 is header
        r.total += 1
        norm = {k.strip().lower(): v.strip() for k, v in row.items() if k}

        # Required fields
        index_name = norm.get("index_name", norm.get("index", "")).upper()
        direction  = norm.get("direction", "").upper()
        score_raw  = norm.get("score", "")

        if index_name not in _VALID_INDICES:
            r.rejected += 1
            r.errors.append(f"Row {i}: invalid index_name={index_name!r}")
            continue
        if direction not in _VALID_DIRECTIONS:
            r.rejected += 1
            r.errors.append(f"Row {i}: invalid direction={direction!r}")
            continue
        try:
            score = int(score_raw)
        except ValueError:
            r.rejected += 1
            r.errors.append(f"Row {i}: invalid score={score_raw!r}")
            continue
        if not 0 <= score <= 100:
            r.rejected += 1
            r.errors.append(f"Row {i}: score {score} out of range 0-100")
            continue

        # Optional fields
        reason      = norm.get("reason", "")
        expiry      = norm.get("expiry") or None
        row_analyst = norm.get("analyst_name", "") or default_analyst
        try:
            lots_override = int(norm["lots_override"]) if norm.get("lots_override") else None
        except ValueError:
            lots_override = None
        try:
            sl_override = float(norm["sl_override"]) if norm.get("sl_override") else None
        except ValueError:
            sl_override = None
        try:
            target_override = float(norm["target_override"]) if norm.get("target_override") else None
        except ValueError:
            target_override = None

        if queue is None:
            r.rejected += 1
            r.errors.append(f"Row {i}: signal queue not initialized")
            continue

        try:
            sig = queue.submit(
                index_name, direction, score, reason,
                source="CSV",
                analyst_name=row_analyst,
                expiry=expiry,
                lots_override=lots_override,
                sl_override=sl_override,
                target_override=target_override,
            )
            r.accepted += 1
            r.signal_ids.append(sig.signal_id)
            _log.info("[IMPORTER] Row %d: submitted %s", i, sig.signal_id)
        except (ValueError, TypeError, AttributeError, KeyError, OSError) as exc:
            r.rejected += 1
            r.errors.append(f"Row {i}: submit failed - {exc}")

    return r


# ── Text import ────────────────────────────────────────────────────────────────

def import_from_text(
    text: str,
    queue,
    cfg: dict[str, Any] | None = None,
    analyst: str = "TEXT",
) -> ImportResult:
    """
    Import one or more signals from newline-separated text.

    Each line: "INDEX DIRECTION SCORE [reason]"
    Blank lines and lines starting with # are skipped.
    """
    result = ImportResult()
    c = cfg or {}
    default_analyst = c.get("manual_signal_default_analyst", analyst)

    for i, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        result.total += 1
        parsed = parse_signal_text(line)
        if parsed is None:
            result.rejected += 1
            result.errors.append(f"Line {i}: cannot parse {line!r}")
            continue
        if queue is None:
            result.rejected += 1
            result.errors.append(f"Line {i}: signal queue not initialized")
            continue
        try:
            sig = queue.submit(
                parsed["index_name"], parsed["direction"], parsed["score"],
                parsed.get("reason", ""),
                source="TEXT", analyst_name=default_analyst,
            )
            result.accepted += 1
            result.signal_ids.append(sig.signal_id)
        except (ValueError, TypeError, AttributeError, KeyError, OSError) as exc:
            result.rejected += 1
            result.errors.append(f"Line {i}: submit failed - {exc}")

    return result


# ── Directory watcher ──────────────────────────────────────────────────────────

def watch_directory(
    watch_dir: str | Path,
    queue,
    cfg: dict[str, Any] | None = None,
    stop_event=None,
) -> None:
    """
    Poll a directory for new .csv files and import them.
    Processed files are renamed with .done suffix.
    Runs in caller's thread - call from a daemon thread.
    """
    import time
    c = cfg or {}
    poll_secs = int(c.get("signal_importer_poll_secs", 30))
    path = Path(watch_dir)
    path.mkdir(parents=True, exist_ok=True)
    _log.info("[IMPORTER] Watching %s every %ds", path, poll_secs)

    while True:
        if stop_event and stop_event.is_set():
            break
        try:
            for f in sorted(path.glob("*.csv")):
                _log.info("[IMPORTER] Found %s", f.name)
                result = import_from_csv(f, queue, c)
                _log.info("[IMPORTER] %s: %s", f.name, result.summary())
                for err in result.errors:
                    _log.warning("[IMPORTER] %s", err)
                f.rename(f.with_suffix(".done"))
        except (OSError, ValueError, TypeError) as exc:
            _log.warning("[IMPORTER] Watch error: %s", exc)
        if stop_event:
            stop_event.wait(timeout=poll_secs)
        else:
            time.sleep(poll_secs)


# ── CLI ────────────────────────────────────────────────────────────────────────

def _cli() -> None:
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Import manual trading signals into the queue.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m core.signal_importer --file signals.csv
  python -m core.signal_importer --text "BANKNIFTY CALL 82 gap_fill"
  python -m core.signal_importer --watch incoming_signals/
  python -m core.signal_importer --parse "NIFTY CALL 75"
""",
    )
    parser.add_argument("--file",    help="CSV file to import")
    parser.add_argument("--text",    help="Text line(s) to import")
    parser.add_argument("--watch",   help="Directory to watch for CSV files")
    parser.add_argument("--parse",   help="Parse a text line and print result (no DB write)")
    parser.add_argument("--db",      default="manual_signals.db", help="Signal DB path")
    parser.add_argument("--analyst", default="CLI", help="Analyst name to tag imports")
    args = parser.parse_args()

    if args.parse:
        result = parse_signal_text(args.parse)
        if result:
            print(f"Parsed: {result}")
        else:
            print(f"❌ Cannot parse: {args.parse!r}")
        sys.exit(0 if result else 1)

    # Build queue
    try:
        from core.manual_signal import ManualSignalQueue
        queue = ManualSignalQueue({"manual_signal_db_path": args.db})
    except (ImportError, OSError, ValueError, TypeError) as exc:
        print(f"❌ Cannot open signal queue: {exc}")
        sys.exit(1)

    if args.file:
        result = import_from_csv(args.file, queue, analyst=args.analyst)
        print(result.summary())
        for err in result.errors:
            print(f"  ⚠️  {err}")
        for sid in result.signal_ids:
            print(f"  ✅ {sid}")
        sys.exit(0 if result.ok else 1)

    if args.text:
        result = import_from_text(args.text, queue, analyst=args.analyst)
        print(result.summary())
        for err in result.errors:
            print(f"  ⚠️  {err}")
        for sid in result.signal_ids:
            print(f"  ✅ {sid}")
        sys.exit(0 if result.ok else 1)

    if args.watch:
        print(f"Watching {args.watch} (Ctrl+C to stop)…")
        watch_directory(args.watch, queue)

    parser.print_help()


if __name__ == "__main__":
    _cli()
