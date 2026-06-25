"""
Pre-session startup checklist for the index options bot.

This module is a pure function library - no globals, no I/O, no side effects.
The caller (index_trader.py) assembles the inputs from its own state and passes
them in; the result is a structured object suitable for:

  - Writing to AuditEngine as severity="AUDIT" at session start
  - Sending a critical Telegram alert if any check fails
  - Deciding whether to proceed to the scan loop

Design principle: every check must be independently verifiable by a human
reading the checklist output.  No check is silently skipped.

Usage example (in index_trader.py)::

    from core.startup_checklist import run_startup_checklist

    result = run_startup_checklist(
        capital_adj_pending=S.capital_adj_pending,
        hard_halt_clear=not _HARD_HALT.is_set(),
        vix=_last_vix,
        vix_block_threshold=VIX_BLOCK_THRESHOLD,
        data_feed_age_sec=_data_feed_age_sec(),
        data_feed_max_age_sec=SAFETY_MAX_STALE_DATA_SEC,
        positions_aligned=_session_recovery_report.positions_aligned,
        execution_mode=EXECUTION_MODE,
        config_version=_CFG.get("CONFIG_VERSION"),
        expected_config_version=1,
    )
    audit.record("startup_checklist", severity="AUDIT",
                 passed=result.passed, checks=result.as_dict())
    if not result.passed:
        send(result.summary(), critical=True)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StartupCheckItem:
    """Result of a single named pre-session check."""
    name: str
    passed: bool
    detail: str = ""

    def status_str(self) -> str:
        return "PASS" if self.passed else "FAIL"


@dataclass(frozen=True)
class StartupCheckResult:
    """Aggregated result of all pre-session checks."""
    passed: bool                      # True only when every item passed
    items: tuple[StartupCheckItem, ...]
    failed_count: int

    def summary(self) -> str:
        """One-line operator summary - suitable for a Telegram message header."""
        if self.passed:
            return f"Startup checklist: ALL {len(self.items)} checks passed."
        lines = [f"Startup checklist: {self.failed_count} of {len(self.items)} checks FAILED:"]
        for item in self.items:
            if not item.passed:
                lines.append(f"  ✗ {item.name}: {item.detail}")
        return "\n".join(lines)

    def as_dict(self) -> dict:
        """Structured representation for AuditEngine.record(**kwargs)."""
        return {
            "overall": "PASS" if self.passed else "FAIL",
            "failed_count": self.failed_count,
            "checks": [
                {"name": i.name, "status": i.status_str(), "detail": i.detail}
                for i in self.items
            ],
        }


def run_startup_checklist(
    *,
    capital_adj_pending: float,
    hard_halt_clear: bool,
    vix: float | None,
    vix_block_threshold: float,
    data_feed_age_sec: float | None,
    data_feed_max_age_sec: float,
    positions_aligned: bool,
    execution_mode: str,
    config_version: int | None = None,
    expected_config_version: int | None = None,
) -> StartupCheckResult:
    """Evaluate all pre-session safety checks and return a structured result.

    All parameters are plain values - callers extract them from their own state
    before calling this function.  This function has no side effects.

    Args:
        capital_adj_pending:      Non-zero means unresolved zombie PnL from a
                                  previous session.  Must be 0.0 to pass.
        hard_halt_clear:          True when _HARD_HALT.is_set() is False.
        vix:                      Last observed VIX value, or None if unknown.
        vix_block_threshold:      Config value VIX_BLOCK_THRESHOLD (default 27).
        data_feed_age_sec:        Seconds since the last successful data fetch,
                                  or None if never fetched.
        data_feed_max_age_sec:    Config value SAFETY_MAX_STALE_DATA_SEC.
        positions_aligned:        True when StateManager.session_recovery_report()
                                  shows all local positions confirmed by broker.
        execution_mode:           Current EXECUTION_MODE string.
        config_version:           CONFIG_VERSION read from config.json.
        expected_config_version:  The version the code expects; None skips check.
    """
    items: list[StartupCheckItem] = []

    # 1. Zombie PnL - unresolved capital adjustment from a previous session
    zombie_ok = capital_adj_pending == 0.0
    items.append(StartupCheckItem(
        name="zombie_pnl_clear",
        passed=zombie_ok,
        detail=(
            "OK" if zombie_ok
            else f"capital_adj_pending={capital_adj_pending:.2f} - "
                 "resolve manually before trading (check broker vs bot capital)"
        ),
    ))

    # 2. Hard halt - must be clear before scanning
    items.append(StartupCheckItem(
        name="hard_halt_clear",
        passed=hard_halt_clear,
        detail=(
            "OK" if hard_halt_clear
            else "HARD_HALT is set - investigate cause, clear with --clear-halt"
        ),
    ))

    # 3. VIX level - warn if already in block territory at session open
    if vix is not None:
        vix_ok = vix < vix_block_threshold
        items.append(StartupCheckItem(
            name="vix_acceptable",
            passed=vix_ok,
            detail=(
                f"VIX={vix:.1f} (block threshold={vix_block_threshold:.1f}): OK"
                if vix_ok
                else f"VIX={vix:.1f} >= block threshold={vix_block_threshold:.1f} "
                     "- all signals will be blocked until VIX drops"
            ),
        ))
    else:
        items.append(StartupCheckItem(
            name="vix_acceptable",
            passed=False,
            detail="VIX unavailable - data feed may not be ready",
        ))

    # 4. Data feed freshness
    # None means the bot just started and no data has been fetched yet - this is
    # normal at session open and must not fail the checklist.  A genuine staleness
    # problem only arises when data WAS flowing and has since stopped (age > max).
    if data_feed_age_sec is not None:
        feed_ok = data_feed_age_sec <= data_feed_max_age_sec
        items.append(StartupCheckItem(
            name="data_feed_fresh",
            passed=feed_ok,
            detail=(
                f"last fetch {data_feed_age_sec:.0f}s ago (max={data_feed_max_age_sec:.0f}s): OK"
                if feed_ok
                else f"last fetch {data_feed_age_sec:.0f}s ago - exceeds max "
                     f"{data_feed_max_age_sec:.0f}s; check data provider"
            ),
        ))
    else:
        items.append(StartupCheckItem(
            name="data_feed_fresh",
            passed=True,
            detail="initial startup - first fetch pending (expected at session open)",
        ))

    # 5. Position alignment - local state matches broker (relevant when positions carried over)
    items.append(StartupCheckItem(
        name="positions_aligned",
        passed=positions_aligned,
        detail=(
            "OK" if positions_aligned
            else "Local positions do not match broker - "
                 "reconcile manually before first trade"
        ),
    ))

    # 6. Execution mode - confirm operator knows the mode
    mode_known = execution_mode in {"MANUAL", "PAPER", "AUTO"}
    items.append(StartupCheckItem(
        name="execution_mode_valid",
        passed=mode_known,
        detail=(
            f"mode={execution_mode}: OK"
            if mode_known
            else f"Unknown EXECUTION_MODE={execution_mode!r} - check config.json"
        ),
    ))

    # 7. Config version (optional - skipped when expected_config_version is None)
    if expected_config_version is not None:
        ver_ok = (config_version == expected_config_version)
        items.append(StartupCheckItem(
            name="config_version",
            passed=ver_ok,
            detail=(
                f"CONFIG_VERSION={config_version}: OK"
                if ver_ok
                else f"Config version mismatch: file={config_version}, "
                     f"code expects={expected_config_version} - "
                     "structural key changes may be missing"
            ),
        ))

    all_passed = all(i.passed for i in items)
    return StartupCheckResult(
        passed=all_passed,
        items=tuple(items),
        failed_count=sum(1 for i in items if not i.passed),
    )


__all__ = [
    "StartupCheckItem",
    "StartupCheckResult",
    "run_startup_checklist",
]

