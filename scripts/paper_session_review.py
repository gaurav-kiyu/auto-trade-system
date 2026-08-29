#!/usr/bin/env python3
"""
OPB Paper Session Review Runner.

Starts ``index_app/index_trader.py --paper`` for a full NSE trading session,
captures the complete console output, gracefully stops the bot shortly after
market close (via the STOP_TRADING kill file), and writes review artifacts:

    logs/paper_session_YYYYMMDD.log            full session console log
    reports/paper_trading/session_YYYYMMDD.json  session summary (exit code,
                                                duration, mode, artifacts)
    reports/paper_trading/health_YYYYMMDD.json   post-session health check

When the session completes, a Telegram alert is sent (see
``send_completion_alert``) so the operator knows the run finished and can
review the artifacts. The alert result is recorded in the session summary
under ``completion_alert``.

Designed to be launched by the Windows Task Scheduler a few minutes before
market open (09:15 IST) and to terminate itself after market close.

Usage:
    python scripts/paper_session_review.py                # full session, stop 15:25 IST
    python scripts/paper_session_review.py --stop-at 15:25 # custom stop time (IST)
    python scripts/paper_session_review.py --max-minutes 3 # test mode: stop after N minutes
    python scripts/paper_session_review.py --dry-run       # print plan and exit
    python scripts/paper_session_review.py --no-alert      # skip the Telegram alert

Notes:
  - PAPER mode is forced via the ``--paper`` CLI flag (wired in v2.58+), so no
    real broker orders are ever placed. PaperBrokerAdapter handles all fills.
  - If the machine wakes late / the market is closed at start, the bot still
    runs and logs; it internally sleeps until the next open.
  - The STOP_TRADING kill file triggers the bot's graceful shutdown; the wrapper
    force-terminates only if the bot does not exit within the grace period.
  - Telegram credentials are resolved from OPBUYING_TELEGRAM_BOT_TOKEN /
    OPBUYING_TELEGRAM_CHAT_ID env vars first, then config.local.json /
    config.json (BOT_TOKEN + TG_CHAT_ID|CHAT_ID). Placeholder values
    ("YOUR_...") are treated as unconfigured and the alert is skipped
    gracefully - the wrapper never fails because Telegram is unavailable.
  - Set OPBUYING_TG_COMPLETION_ALERT=false (or pass --no-alert) to disable.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.datetime_ist import now_ist

# ── Telegram completion alert ───────────────────────────────────────────────
TG_ENV_TOKEN = "OPBUYING_TELEGRAM_BOT_TOKEN"
TG_ENV_CHAT_ID = "OPBUYING_TELEGRAM_CHAT_ID"
TG_ALERT_DISABLE_ENV = "OPBUYING_TG_COMPLETION_ALERT"
TG_ALERT_TIMEOUT = 20
_PLACEHOLDER_VALUES = frozenset({
    "", "YOUR_TELEGRAM_BOT_TOKEN", "your_telegram_bot_token",
    "YOUR_TELEGRAM_CHAT_ID", "your_telegram_chat_id", "YOUR_CHAT_ID",
})


# ── Defaults (IST) ───────────────────────────────────────────────────────────
MARKET_OPEN = "09:15"
MARKET_CLOSE = "15:20"
STOP_GRACE_SECONDS = 150          # how long to wait for the bot to exit cleanly
KILL_FILE = ROOT / "STOP_TRADING"
LOG_DIR = ROOT / "logs"
REPORT_DIR = ROOT / "reports" / "paper_trading"
BOT_SCRIPT = ROOT / "index_app" / "index_trader.py"


def _parse_hhmm(value: str) -> _dt.time:
    hour, minute = (int(p) for p in value.split(":"))
    return _dt.time(hour, minute)


def _minutes_until(target: _dt.time, now: _dt.datetime) -> float:
    target_dt = now.replace(hour=target.hour, minute=target.minute, second=0, microsecond=0)
    if target_dt < now:
        target_dt += _dt.timedelta(days=1)  # wrap past midnight
    return (target_dt - now).total_seconds() / 60.0


def _is_market_day(now: _dt.datetime) -> bool:
    """Weekend check only; holiday calendar is handled by the bot itself."""
    return now.weekday() < 5


def _is_real_credential(value: object) -> bool:
    """True when a credential value is present and not a placeholder."""
    text = str(value or "").strip()
    if text in _PLACEHOLDER_VALUES or text.startswith("YOUR_"):
        return False
    return bool(text)


def _load_tg_credentials() -> tuple[str, str]:
    """Resolve Telegram bot token + chat id.

    Precedence: OPBUYING_TELEGRAM_BOT_TOKEN / OPBUYING_TELEGRAM_CHAT_ID env
    vars, then config.local.json, then config.json (BOT_TOKEN + TG_CHAT_ID,
    falling back to CHAT_ID). Returns ("", "") when not configured.
    """
    token = os.environ.get(TG_ENV_TOKEN, "")
    chat_id = os.environ.get(TG_ENV_CHAT_ID, "")
    if _is_real_credential(token) and _is_real_credential(chat_id):
        return token, chat_id

    for cfg_name in ("json/config.local.json", "json/config.json"):
        cfg_path = ROOT / cfg_name
        if not cfg_path.exists():
            continue
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        token = str(cfg.get("BOT_TOKEN") or "")
        chat_id = str(cfg.get("TG_CHAT_ID") or cfg.get("CHAT_ID") or "")
        if _is_real_credential(token) and _is_real_credential(chat_id):
            return token, chat_id
    return "", ""


def _extract_json(text: str | None) -> dict | list | None:
    """Return the first JSON object found in a possibly mixed log+JSON stream.

    ``core.health_checker --format json`` may interleave plain log lines with
    the JSON payload (e.g. ``[NEWS] NewsSentinel started`` before the ``{``).
    A plain ``json.loads`` then fails with "Extra data", so we scan for the
    first balanced ``{...}`` object (string/escape aware) and parse that.

    Returns:
        parsed JSON value, or None when no valid object is found.
    """
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    while start >= 0:
        depth = 0
        in_string = False
        escaped = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start:i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break  # not valid JSON here - try the next "{"
        start = text.find("{", start + 1)
    return None


def _build_completion_message(summary: dict) -> str:
    """Format the completion alert text from a session summary dict."""
    ok = summary.get("exit_code") == 0
    status = "SUCCESS" if ok else "FAILED"
    icon = "✅" if ok else "❌"
    sep = "─" * 30
    return "\n".join([
        f"{icon} PAPER SESSION COMPLETE",
        sep,
        f"Date      : {summary.get('date', '?')}",
        f"Mode      : {summary.get('mode', 'PAPER')}",
        f"Status    : {status} (exit {summary.get('exit_code')})",
        f"Duration  : {summary.get('duration_min')} min",
        f"Reason    : {summary.get('stop_reason', '?')}",
        f"Log       : {summary.get('log_file', '?')}",
        f"Summary   : {summary.get('summary_file', '?')}",
        sep,
    ])


def send_completion_alert(summary: dict) -> dict:
    """Send a Telegram alert when the paper session completes.

    Never raises - every failure path returns ``{"sent": False, "detail": ...}``
    so the session review is never interrupted by an alert problem. The outcome
    is recorded in the session summary under ``completion_alert``.

    Returns:
        dict with keys ``sent`` (bool) and ``detail`` (str).
    """
    disable_flag = os.environ.get(TG_ALERT_DISABLE_ENV, "true").strip().lower()
    if disable_flag in ("0", "false", "no", "off"):
        return {"sent": False, "detail": "disabled via OPBUYING_TG_COMPLETION_ALERT"}

    token, chat_id = _load_tg_credentials()
    if not token or not chat_id:
        return {
            "sent": False,
            "detail": (
                f"Telegram not configured - set {TG_ENV_TOKEN} / {TG_ENV_CHAT_ID} "
                "(or BOT_TOKEN/TG_CHAT_ID in config.local.json)"
            ),
        }

    try:
        from infrastructure.adapters.notifications.telegram_adapter import _TelegramClient

        client = _TelegramClient(
            bot_token=token,
            default_chat_id=chat_id,
            enabled=True,
            cooldown_seconds=0,   # one-shot completion alert
            rate_limit_per_min=30,
            send_timeout=TG_ALERT_TIMEOUT,
        )
        try:
            ok = client.send_raw(
                text=_build_completion_message(summary),
                chat_id=chat_id,
                critical=False,
            )
            return {"sent": bool(ok), "detail": "sent" if ok else "Telegram API rejected"}
        finally:
            client.close()
    except Exception as exc:  # alert must never break the wrapper
        return {"sent": False, "detail": f"{type(exc).__name__}: {exc}"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stop-at", default="15:25", help="IST stop time HH:MM (default 15:25)")
    ap.add_argument("--max-minutes", type=float, default=None,
                    help="Test mode: stop after this many minutes regardless of clock")
    ap.add_argument("--dry-run", action="store_true", help="Print plan and exit")
    ap.add_argument("--no-health-check", action="store_true",
                    help="Skip post-session health check")
    ap.add_argument("--no-alert", action="store_true",
                    help="Skip the Telegram completion alert")
    args = ap.parse_args(argv)

    now = now_ist()
    stop_time = _parse_hhmm(args.stop_at)
    date_str = now.strftime("%Y%m%d")

    log_file = LOG_DIR / f"paper_session_{date_str}.log"
    summary_file = REPORT_DIR / f"session_{date_str}.json"
    health_file = REPORT_DIR / f"health_{date_str}.json"
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    plan = (
        f"\n{'=' * 70}\n"
        f"  OPB PAPER SESSION REVIEW\n"
        f"{'=' * 70}\n"
        f"  Date          : {now.strftime('%Y-%m-%d %H:%M:%S %Z')} (IST)\n"
        f"  Market day    : {'YES' if _is_market_day(now) else 'NO (weekend - bot will idle)'}\n"
        f"  Market open   : {MARKET_OPEN} IST\n"
        f"  Market close  : {MARKET_CLOSE} IST\n"
        f"  Scheduled stop: {args.stop_at} IST"
        + (f"  (or after {args.max_minutes} min in test mode)" if args.max_minutes else "")
        + f"\n  Mode          : PAPER (--paper flag, no real orders)\n"
        f"  Completion alert: {'DISABLED (--no-alert)' if args.no_alert else 'ENABLED (Telegram)'}\n"
        f"  Bot script    : {BOT_SCRIPT}\n"
        f"  Session log   : {log_file}\n"
        f"  Summary       : {summary_file}\n"
        f"{'=' * 70}\n"
    )
    print(plan)

    if args.dry_run:
        print("  DRY RUN - exiting without starting the bot.\n")
        return 0

    # Clear any stale STOP_TRADING file from a previous (possibly crashed)
    # run - otherwise the bot would hard-halt and exit immediately at startup,
    # silently aborting this session.
    try:
        if KILL_FILE.exists():
            KILL_FILE.unlink()
            print(f"  NOTE: removed stale {KILL_FILE.name} left by a previous run")
    except OSError as exc:
        print(f"  WARNING: could not remove stale kill file: {exc}")

    # ── Start the bot in PAPER mode with full output capture ────────────────
    log_handle = open(log_file, "a", encoding="utf-8", errors="replace")
    log_handle.write(plan)
    log_handle.write(f"\n[WRAPPER] {now.isoformat()} Starting bot subprocess...\n")
    log_handle.flush()

    env = dict(os.environ)
    env["OPBUYING_TG_STARTUP_ALERT"] = "false"  # avoid noisy startup alert
    # CREATE_NEW_PROCESS_GROUP gives the child its own process group on Windows so
    # the CTRL_C_EVENT fallback can be targeted at the bot (and only the bot).
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
    proc = subprocess.Popen(
        [sys.executable, "-m", "index_app.index_trader", "--paper"],
        cwd=str(ROOT),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        env=env,
        text=True,
        creationflags=creationflags,
    )
    start_mono = time.monotonic()
    print(f"  Bot started (PID {proc.pid}). Session log: {log_file}")
    print(f"  Waiting until {args.stop_at} IST (or {args.max_minutes} min in test mode)...\n")

    # ── Monitor until stop condition, then shut down gracefully ─────────────
    exit_code: int | None = None
    stop_reason = "not stopped"
    try:
        while True:
            if proc.poll() is not None:
                exit_code = proc.returncode
                stop_reason = f"bot exited on its own (code {exit_code})"
                break

            now = now_ist()
            if args.max_minutes is not None:
                elapsed = (time.monotonic() - start_mono) / 60.0
                if elapsed >= args.max_minutes:
                    stop_reason = f"test mode: {args.max_minutes} min elapsed"
                    break
            else:
                if _minutes_until(stop_time, now) <= 0.0:
                    stop_reason = f"scheduled stop at {args.stop_at} IST"
                    break
            time.sleep(10)

        if exit_code is None:
            print(f"\n  [{now_ist().strftime('%H:%M:%S')}] {stop_reason} - sending graceful stop...")
            # Drop the kill file - the bot's kill-file watcher trips a hard halt AND
            # signals graceful shutdown (request_shutdown sets _shutdown, so the main
            # trading loop exits and the process terminates cleanly).
            try:
                KILL_FILE.write_text("paper_session_review graceful stop", encoding="utf-8")
                print(f"  STOP_TRADING kill file created: {KILL_FILE}")
            except OSError as exc:
                print(f"  WARNING: could not write kill file: {exc}")

            # Wait for graceful exit within the grace window
            grace_deadline = time.monotonic() + STOP_GRACE_SECONDS
            while time.monotonic() < grace_deadline and proc.poll() is None:
                time.sleep(5)

            # Fallback: send CTRL_C_EVENT (or SIGINT on POSIX) so the bot raises
            # KeyboardInterrupt and runs its atexit/cleanup handlers. On Windows the
            # child must have been created in its own process group for this to work.
            if proc.poll() is None:
                print(f"  Kill file did not stop the bot within {STOP_GRACE_SECONDS}s - sending Ctrl+C...")
                try:
                    if os.name == "nt":
                        import signal as _sig
                        os.kill(proc.pid, _sig.CTRL_C_EVENT)
                    else:
                        proc.send_signal(signal.SIGINT)
                    try:
                        proc.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        pass
                except (OSError, ValueError) as exc:
                    print(f"  WARNING: Ctrl+C signal failed: {exc}")

            # Last resort: hard terminate
            if proc.poll() is None:
                print(f"  Bot still running - force terminating PID {proc.pid}")
                try:
                    proc.terminate()
                    proc.wait(timeout=30)
                except (subprocess.TimeoutExpired, OSError):
                    try:
                        proc.kill()
                        proc.wait(timeout=10)
                    except (subprocess.TimeoutExpired, OSError) as exc:
                        print(f"  WARNING: force kill failed: {exc}")
            exit_code = proc.returncode if proc.returncode is not None else -1

        # Clean up the kill file so future sessions are unaffected
        try:
            if KILL_FILE.exists():
                KILL_FILE.unlink()
        except OSError:
            pass
    finally:
        log_handle.write(
            f"\n[WRAPPER] {now_ist().isoformat()} Bot stopped. reason={stop_reason} exit_code={exit_code}\n"
        )
        log_handle.flush()
        log_handle.close()

    # ── Post-session artifacts ───────────────────────────────────────────────
    duration_min = round((time.monotonic() - start_mono) / 60.0, 1)
    summary = {
        "timestamp": now_ist().isoformat(),
        "date": date_str,
        "mode": "PAPER",
        "exit_code": exit_code,
        "stop_reason": stop_reason,
        "duration_min": duration_min,
        "log_file": str(log_file),
        "summary_file": str(summary_file),
        "market_open": MARKET_OPEN,
        "market_close": MARKET_CLOSE,
        "scheduled_stop": args.stop_at,
        "wired_paper_flag": True,
    }

    if not args.no_health_check:
        print("  Running post-session health check...")
        try:
            hc = subprocess.run(
                [sys.executable, "-m", "core.health_checker", "--format", "json"],
                capture_output=True, text=True, timeout=120, cwd=str(ROOT),
            )
            summary["health_check_exit"] = hc.returncode
            hc_json = _extract_json(hc.stdout)
            if hc_json is None:
                hc_json = _extract_json(hc.stderr)
            if hc_json is not None:
                summary["health"] = hc_json
                health_file.write_text(json.dumps(hc_json, indent=2), encoding="utf-8")
            else:
                health_file.write_text(hc.stdout or hc.stderr, encoding="utf-8")
        except (subprocess.TimeoutExpired, OSError) as exc:
            summary["health_check_error"] = str(exc)

    # ── Completion alert ───────────────────────────────────────────────────
    if args.no_alert:
        alert_result = {"sent": False, "detail": "disabled via --no-alert"}
    else:
        print("  Sending Telegram completion alert...")
        alert_result = send_completion_alert(summary)
        alert_state = "SENT" if alert_result["sent"] else "NOT SENT"
        print(f"  Completion alert: {alert_state} ({alert_result['detail']})")
    summary["completion_alert"] = alert_result
    summary_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"\n{'=' * 70}")
    print("  SESSION COMPLETE")
    print(f"  Exit code     : {exit_code}")
    print(f"  Duration      : {duration_min} min")
    print(f"  Reason        : {stop_reason}")
    print(f"  Session log   : {log_file}")
    print(f"  Summary       : {summary_file}")
    if health_file.exists():
        print(f"  Health report : {health_file}")
    print(f"  Telegram alert: {'SENT' if alert_result.get('sent') else 'NOT SENT - ' + str(alert_result.get('detail', ''))}")
    print(f"{'=' * 70}\n")
    return 0 if exit_code == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
