"""Auto-Learner - Fully configurable, trade-history + AI-journal-driven threshold tuner.

Extends core.adaptive_learning with:
  • AI journal feedback loop (win/loss patterns from LLM verdicts)
  • Per-symbol learning state (not just global)
  • Configurable learning rates and decay - all via config keys
  • Regime/strength performance matrix with auto-decay
  • Knowledge Base integration (cross-domain pattern learning)
  • Pattern Learner integration (learn from incidents, code reviews, test failures)
  • Full persistence: JSON state file + optional CSV export

Config keys (all under AUTO_LEARNER in config.json):
    AUTO_LEARNER_ENABLED           bool
    AUTO_LEARNER_STATE_FILE        str   - path to learner state JSON
    AUTO_LEARNER_LOOKBACK          int   - trades to look back (default 40)
    AUTO_LEARNER_WIN_SCORE_DECAY   float - score_adj decrement on WIN (default 2.0)
    AUTO_LEARNER_LOSS_SCORE_INC    float - score_adj increment on LOSS (default 3.0)
    AUTO_LEARNER_CONFIDENCE_WIN_INC float - confidence bump on WIN (default 1.0)
    AUTO_LEARNER_CONFIDENCE_LOSS_DEC float - confidence drop on LOSS (default 1.0)
    AUTO_LEARNER_STREAK_BOOST_AT   int   - consecutive wins before applying discount (default 3)
    AUTO_LEARNER_LOSS_STREAK_HALT  int   - consecutive losses before halting (default 3)
    AUTO_LEARNER_MAX_BONUS         int   - max score bonus (default 8)
    AUTO_LEARNER_MAX_DISCOUNT      int   - max score discount (default 3)
    AUTO_LEARNER_AI_JOURNAL_WEIGHT float - weight of AI journal vs raw trades (default 0.3)
    AUTO_LEARNER_REGIME_DECAY      float - per-cycle decay for regime stats (default 0.98)
    AUTO_LEARNER_PER_SYMBOL        bool  - track per-symbol learning (default False)
    AUTO_LEARNER_CSV_EXPORT_FILE   str   - optional CSV export path
"""
from __future__ import annotations

import json
import logging
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .adaptive_learning import (
    adaptive_threshold_adjustment,
    clamp_learning_state,
    live_signal_confidence,
    recent_trade_learning_snapshot,
    update_learning_after_exit,
)

# Lazy imports for Knowledge Base and Pattern Learner (optional dependencies)
# These are imported on-demand to avoid circular imports

log = logging.getLogger(__name__)

# ─── Defaults ─────────────────────────────────────────────────────────────────
_DEFAULTS: dict[str, Any] = {
    "AUTO_LEARNER_ENABLED": True,
    "AUTO_LEARNER_STATE_FILE": "backups/learner_state.json",
    "AUTO_LEARNER_LOOKBACK": 40,
    "AUTO_LEARNER_WIN_SCORE_DECAY": 2.0,
    "AUTO_LEARNER_LOSS_SCORE_INC": 3.0,
    "AUTO_LEARNER_CONFIDENCE_WIN_INC": 1.0,
    "AUTO_LEARNER_CONFIDENCE_LOSS_DEC": 1.0,
    "AUTO_LEARNER_STREAK_BOOST_AT": 3,
    "AUTO_LEARNER_LOSS_STREAK_HALT": 3,
    "AUTO_LEARNER_MAX_BONUS": 8,
    "AUTO_LEARNER_MAX_DISCOUNT": 3,
    "AUTO_LEARNER_AI_JOURNAL_WEIGHT": 0.3,
    "AUTO_LEARNER_REGIME_DECAY": 0.98,
    "AUTO_LEARNER_PER_SYMBOL": False,
    "AUTO_LEARNER_CSV_EXPORT_FILE": "",
}


@dataclass
class LearnerConfig:
    enabled: bool = True
    state_file: str = "backups/learner_state.json"
    lookback: int = 40
    win_score_decay: float = 2.0
    loss_score_inc: float = 3.0
    confidence_win_inc: float = 1.0
    confidence_loss_dec: float = 1.0
    streak_boost_at: int = 3
    loss_streak_halt: int = 3
    max_bonus: int = 8
    max_discount: int = 3
    ai_journal_weight: float = 0.3
    regime_decay: float = 0.98
    per_symbol: bool = False
    csv_export_file: str = ""


def learner_config_from_cfg(cfg: dict[str, Any]) -> LearnerConfig:
    m = {**_DEFAULTS, **{k: v for k, v in cfg.items() if k.startswith("AUTO_LEARNER")}}
    return LearnerConfig(
        enabled=bool(m["AUTO_LEARNER_ENABLED"]),
        state_file=str(m["AUTO_LEARNER_STATE_FILE"]),
        lookback=int(m["AUTO_LEARNER_LOOKBACK"]),
        win_score_decay=float(m["AUTO_LEARNER_WIN_SCORE_DECAY"]),
        loss_score_inc=float(m["AUTO_LEARNER_LOSS_SCORE_INC"]),
        confidence_win_inc=float(m["AUTO_LEARNER_CONFIDENCE_WIN_INC"]),
        confidence_loss_dec=float(m["AUTO_LEARNER_CONFIDENCE_LOSS_DEC"]),
        streak_boost_at=int(m["AUTO_LEARNER_STREAK_BOOST_AT"]),
        loss_streak_halt=int(m["AUTO_LEARNER_LOSS_STREAK_HALT"]),
        max_bonus=int(m["AUTO_LEARNER_MAX_BONUS"]),
        max_discount=int(m["AUTO_LEARNER_MAX_DISCOUNT"]),
        ai_journal_weight=float(m["AUTO_LEARNER_AI_JOURNAL_WEIGHT"]),
        regime_decay=float(m["AUTO_LEARNER_REGIME_DECAY"]),
        per_symbol=bool(m["AUTO_LEARNER_PER_SYMBOL"]),
        csv_export_file=str(m.get("AUTO_LEARNER_CSV_EXPORT_FILE") or ""),
    )


# ─── Atomic File Write Helper ──────────────────────────────────────────────────

def _atomic_write_state(file_path: Path, content: str) -> None:
    """Write JSON content to file atomically using temp file + rename.

    This prevents corruption if multiple processes write simultaneously.
    Pattern: write to temp → flush → close → rename → done.
    On Windows the temp file must be closed before rename to release the lock.

    Raises:
        OSError: If write or rename fails

    """
    file_path.parent.mkdir(parents=True, exist_ok=True)

    # Write to temp file in same directory (ensures same filesystem for atomic rename)
    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        dir=file_path.parent,
        prefix=".tmp_",
        suffix=".json",
        delete=False,
        encoding="utf-8",
    )
    tmp_path = Path(tmp.name)
    try:
        tmp.write(content)
        tmp.close()  # Must close before rename on Windows (releases file lock)
        tmp_path.replace(file_path)
    except OSError as e:
        tmp_path.unlink(missing_ok=True)
        raise OSError(f"Atomic write to {file_path} failed: {e}") from e


# ─── AutoLearner ──────────────────────────────────────────────────────────────

class AutoLearner:
    """Persistent adaptive learner that wraps core.adaptive_learning with:
      - AI journal feedback (if AIEngine is running)
      - Per-symbol state (optional)
      - Configurable learning rates
      - Automatic state persistence

    Usage:
        learner = AutoLearner(learner_cfg, log_fn=log_msg)
        learner.load()

        # After signal generation:
        delta, reason = learner.threshold_adjustment(symbol, regime, strength, trades)

        # After trade exit:
        learner.record_exit(symbol, tag, regime, strength, net_pnl)
        learner.save()
    """

    def __init__(
        self,
        cfg: LearnerConfig,
        *,
        log_fn: Any = None,
        ai_journal_file: str = "",
    ) -> None:
        self._cfg = cfg
        self._log = log_fn or (lambda msg: log.info(msg))
        self._ai_journal_file = ai_journal_file
        self._lock = threading.RLock()

        # Global learning state (mirrors existing trader_state.json structure)
        self._global_state: dict[str, Any] = {
            "score_adj": 0,
            "confidence": 0,
            "streak": 0,
        }
        # Per-symbol state (optional)
        self._symbol_states: dict[str, dict[str, Any]] = {}
        # Regime performance matrix
        self._regime_matrix: dict[str, dict[str, Any]] = {}
        # AI journal stats cache (refresh on each exit)
        self._ai_stats: dict[str, Any] = {}
        self._ai_stats_ts: float = 0.0
        # Knowledge Base integration (lazy loaded)
        self._kb: Any = None
        self._pattern_learner: Any = None

    # ── persistence ──────────────────────────────────────────────────────────

    def load(self, existing_state: dict[str, Any] | None = None) -> None:
        """Load from file or bootstrap from an existing in-memory state dict."""
        with self._lock:
            state_path = Path(self._cfg.state_file)
            if state_path.exists():
                try:
                    saved = json.loads(state_path.read_text(encoding="utf-8"))
                    self._global_state.update({
                        k: saved[k] for k in ("score_adj", "confidence", "streak") if k in saved
                    })
                    self._symbol_states = dict(saved.get("symbol_states") or {})
                    self._regime_matrix = dict(saved.get("regime_matrix") or {})
                    self._log(f"[LEARNER] Loaded state from {state_path}")
                except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
                    self._log(f"[LEARNER] State load failed ({exc}); starting fresh")
            elif existing_state:
                self._global_state.update({
                    k: existing_state[k]
                    for k in ("score_adj", "confidence", "streak")
                    if k in existing_state
                })
            clamp_learning_state(self._global_state)

    def save(self) -> None:
        """Persist current learning state to file (atomic write)."""
        if not self._cfg.enabled:
            return
        with self._lock:
            state_path = Path(self._cfg.state_file)
            out = {
                **self._global_state,
                "symbol_states": self._symbol_states,
                "regime_matrix": self._regime_matrix,
                "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            try:
                content = json.dumps(out, indent=2)
                _atomic_write_state(state_path, content)
            except (OSError, json.JSONDecodeError) as exc:
                self._log(f"[LEARNER] State save failed: {exc}")

    def export_global_state(self) -> dict[str, Any]:
        """Return a copy of global learning state (for injecting into trader_state)."""
        with self._lock:
            return dict(self._global_state)

    def import_global_state(self, state: dict[str, Any]) -> None:
        """Sync global state from external dict (e.g., trader_state.json)."""
        with self._lock:
            for k in ("score_adj", "confidence", "streak"):
                if k in state:
                    self._global_state[k] = state[k]
            clamp_learning_state(self._global_state)

    # ── AI journal feedback ───────────────────────────────────────────────────

    def _refresh_ai_stats(self) -> None:
        """Refresh cached AI journal stats (at most once per 60 s)."""
        now = time.monotonic()
        if now - self._ai_stats_ts < 60.0 or not self._ai_journal_file:
            return
        path = Path(self._ai_journal_file)
        if not path.exists():
            self._ai_stats_ts = now
            return
        try:
            lines = path.read_text(encoding="utf-8").splitlines()[-200:]
            entries = []
            for line in lines:
                try:
                    entries.append(json.loads(line))
                except (json.JSONDecodeError, ValueError, TypeError) as e:
                    log.debug("[AUTO_LEARNER] non-critical error: %s", e)
            skips = sum(1 for e in entries if e.get("verdict") == "SKIP")
            total = max(1, len(entries))
            self._ai_stats = {
                "skip_rate": skips / total,
                "count": len(entries),
                "avg_delta": sum(int(e.get("score_delta") or 0) for e in entries) / total,
            }
        except (OSError, json.JSONDecodeError, AttributeError) as e:
            log.debug("[AUTO_LEARNER] non-critical error: %s", e)
        self._ai_stats_ts = now

    # ── threshold adjustment (drop-in for adaptive_threshold_adjustment) ─────

    def threshold_adjustment(
        self,
        symbol: str,
        regime: str,
        strength: str,
        trades: list[dict[str, Any]],
    ) -> tuple[int, str]:
        """Return (delta_points, reason).
        Combines adaptive_learning logic with AI journal weight and per-symbol data.
        """
        if not self._cfg.enabled:
            return (0, "learner disabled")

        with self._lock:
            self._refresh_ai_stats()
            global_state = dict(self._global_state)

        snap = recent_trade_learning_snapshot(trades, self._cfg.lookback, global_state)
        delta, reason = adaptive_threshold_adjustment(
            snap,
            regime=regime,
            strength=strength,
            enabled=True,
            max_bonus=self._cfg.max_bonus,
            max_discount=self._cfg.max_discount,
        )

        # AI journal feedback: if LLM has been skipping a lot, add extra caution
        ai_stats = self._ai_stats
        if ai_stats.get("count", 0) >= 10:
            skip_rate = float(ai_stats.get("skip_rate", 0.0))
            ai_delta_adj = float(ai_stats.get("avg_delta", 0.0))
            if skip_rate > 0.5:
                ai_extra = max(1, round(skip_rate * self._cfg.ai_journal_weight * 5))
                delta += ai_extra
                reason += f", AI skip-heavy (+{ai_extra})"
            elif ai_delta_adj < -1.0:
                ai_extra = 1
                delta += ai_extra
                reason += ", AI negative bias (+1)"

        # Per-symbol adjustment
        if self._cfg.per_symbol:
            sym_state = self._symbol_states.get(symbol, {})
            sym_adj = int(sym_state.get("score_adj", 0))
            if sym_adj:
                direction = "+" if sym_adj > 0 else ""
                reason += f", sym_adj={direction}{sym_adj}"
            delta += sym_adj

        delta = max(-self._cfg.max_discount, min(self._cfg.max_bonus, delta))
        return (int(delta), reason)

    def signal_confidence(
        self,
        symbol: str,
        sig: dict[str, Any],
        trades: list[dict[str, Any]],
        default_threshold: int,
    ) -> tuple[int, str]:
        """Return (confidence 1-99, band A/B/C/D)."""
        with self._lock:
            snap = recent_trade_learning_snapshot(trades, self._cfg.lookback, dict(self._global_state))
        return live_signal_confidence(sig, default_threshold=default_threshold, trade_snap=snap)

    # ── post-exit learning update ─────────────────────────────────────────────

    def record_exit(
        self,
        symbol: str,
        tag: str,           # "WIN" | "LOSS" | "ZOMBIE" | "BREAKEVEN"
        regime: str = "",
        strength: str = "",
        net_pnl: float = 0.0,
    ) -> None:
        """Update global (and optionally per-symbol) learning state after a trade exit."""
        if not self._cfg.enabled:
            return
        with self._lock:
            # Global update
            update_learning_after_exit(self._global_state, tag)
            # Apply configurable rates (override the fixed nudges in adaptive_learning)
            if tag == "WIN":
                self._global_state["score_adj"] = max(
                    -10,
                    self._global_state["score_adj"] - int(self._cfg.win_score_decay),
                )
                self._global_state["confidence"] = min(
                    5,
                    self._global_state["confidence"] + int(self._cfg.confidence_win_inc),
                )
            elif tag not in ("ZOMBIE",):
                self._global_state["score_adj"] = min(
                    10,
                    self._global_state["score_adj"] + int(self._cfg.loss_score_inc),
                )
                self._global_state["confidence"] = max(
                    -5,
                    self._global_state["confidence"] - int(self._cfg.confidence_loss_dec),
                )
            clamp_learning_state(self._global_state)

            # Per-symbol state
            if self._cfg.per_symbol:
                sym = self._symbol_states.setdefault(symbol, {"score_adj": 0, "confidence": 0, "streak": 0})
                if tag == "WIN":
                    sym["score_adj"] = max(-10, sym.get("score_adj", 0) - 1)
                    sym["confidence"] = min(5, sym.get("confidence", 0) + 1)
                elif tag not in ("ZOMBIE",):
                    sym["score_adj"] = min(10, sym.get("score_adj", 0) + 2)
                    sym["confidence"] = max(-5, sym.get("confidence", 0) - 1)
                clamp_learning_state(sym)

            # Regime matrix update
            reg_key = str(regime or "UNKNOWN")
            st_key = str(strength or "MODERATE")
            rm = self._regime_matrix.setdefault(reg_key, {})
            rm_st = rm.setdefault(st_key, {"count": 0, "wins": 0, "net": 0.0})
            rm_st["count"] = int(rm_st["count"]) + 1
            if tag == "WIN":
                rm_st["wins"] = int(rm_st["wins"]) + 1
            rm_st["net"] = round(float(rm_st["net"]) + net_pnl, 2)
            # Apply decay to all regime buckets (older data fades); prune stale entries
            for _r, _stmap in self._regime_matrix.items():
                for _s, _b in _stmap.items():
                    _b["net"] = round(float(_b["net"]) * self._cfg.regime_decay, 2)
            for _r in list(self._regime_matrix):
                self._regime_matrix[_r] = {
                    _s: _b for _s, _b in self._regime_matrix[_r].items()
                    if abs(float(_b["net"])) >= 0.01 or int(_b.get("count", 0)) > 0
                }
                if not self._regime_matrix[_r]:
                    del self._regime_matrix[_r]

        self._log(
            f"[LEARNER] {symbol} exit={tag} regime={regime} "
            f"global adj={self._global_state['score_adj']} "
            f"conf={self._global_state['confidence']}",
        )

    # ── Knowledge Base Integration ─────────────────────────────────────────

    def _ensure_kb(self) -> None:
        """Lazy-load Knowledge Base and Pattern Learner."""
        if self._kb is None:
            try:
                from core.knowledge_base import get_knowledge_base
                self._kb = get_knowledge_base()
            except ImportError:
                self._kb = False  # Mark as unavailable
        if self._pattern_learner is None:
            try:
                from core.pattern_learner import get_pattern_learner
                self._pattern_learner = get_pattern_learner()
            except ImportError:
                self._pattern_learner = False

    def learn_from_exit(
        self,
        symbol: str,
        tag: str,
        net_pnl: float = 0.0,
        regime: str = "",
    ) -> None:
        """Record trade outcome to Knowledge Base for cross-domain learning.

        Creates KB entries that correlate trading patterns with outcomes,
        enabling the system to learn from wins/losses across sessions.
        """
        self._ensure_kb()
        if not self._kb:
            return

        # Simple pattern: symbol + regime + outcome
        outcome = "WIN" if tag == "WIN" else "LOSS" if tag == "LOSS" else "BREAKEVEN"
        pattern = f"Trade {outcome}: {symbol} in {regime or 'unknown'} regime (PnL: {net_pnl:+.2f})"
        solution = (
            f"Continue current strategy for {symbol} in {regime} regime"
            if tag == "WIN"
            else f"Review {symbol} entry criteria in {regime} regime"
        )

        self._kb.add_entry(
            pattern_type="LESSON_LEARNED",
            pattern=pattern,
            solution=solution,
            source="auto_learner.learn_from_exit",
            confidence=0.6 if tag == "WIN" or tag == "LOSS" else 0.4,
            tags=["trade", symbol.lower(), outcome.lower(), regime.lower()],
            metadata={"symbol": symbol, "regime": regime, "tag": tag, "pnl": net_pnl},
        )

    def query_knowledge_base(
        self,
        query: str,
        max_results: int = 5,
    ) -> list[dict[str, Any]]:
        """Query the Knowledge Base for relevant patterns.

        Args:
            query: Search text.
            max_results: Maximum results to return.

        Returns:
            List of matching entries as dicts.
        """
        self._ensure_kb()
        if not self._kb:
            return []
        results = self._kb.find_similar(query, max_results=max_results)
        return [r.to_dict() for r in results]

    # ── Pattern Learner Integration ─────────────────────────────────────

    def learn_from_review(self, pr_id: str, comments: list[str],
                          author: str = "") -> int:
        """Learn from a code review via Pattern Learner.

        Args:
            pr_id: Pull request identifier.
            comments: Review comments.
            author: Optional reviewer name.

        Returns:
            Number of patterns extracted.
        """
        self._ensure_kb()
        if not self._pattern_learner:
            return 0
        entries = self._pattern_learner.learn_from_code_review(
            pr_id=pr_id, comments=comments, author=author,
        )
        return len(entries)

    def learn_from_failure(self, test_name: str, error_message: str,
                           module: str = "") -> int:
        """Learn from a test failure via Pattern Learner.

        Args:
            test_name: Failing test name.
            error_message: Error message.
            module: Optional module path.

        Returns:
            Number of patterns extracted.
        """
        self._ensure_kb()
        if not self._pattern_learner:
            return 0
        entries = self._pattern_learner.learn_from_test_failure(
            test_name=test_name, error_message=error_message, module=module,
        )
        return len(entries)

    def learn_from_incident(self, incident_type: str, probable_cause: str,
                            recommended_fix: str, severity: str = "MEDIUM") -> int:
        """Learn from an incident via Pattern Learner.

        Args:
            incident_type: Type of incident.
            probable_cause: Probable cause.
            recommended_fix: Recommended fix.
            severity: Severity level.

        Returns:
            Number of patterns extracted.
        """
        self._ensure_kb()
        if not self._pattern_learner:
            return 0
        class _MockResult:
            pass
        r = _MockResult()
        r.incident_type = incident_type
        r.incident_message = probable_cause
        r.probable_cause = probable_cause
        r.severity = severity
        r.recommended_fix = recommended_fix
        r.evidence = []
        r.impacted_modules = []
        entries = self._pattern_learner.learn_from_incident(r)
        return len(entries)

    # ── analytics summary ─────────────────────────────────────────────────────

    def regime_win_rates(self) -> dict[str, dict[str, float]]:
        """Return win-rate % per regime+strength from the internal matrix."""
        result: dict[str, dict[str, float]] = {}
        with self._lock:
            for regime, stmap in self._regime_matrix.items():
                result[regime] = {}
                for strength, b in stmap.items():
                    cnt = max(1, int(b.get("count", 1)))
                    wins = int(b.get("wins", 0))
                    result[regime][strength] = round(wins / cnt * 100, 1)
        return result

    def summary_str(self) -> str:
        with self._lock:
            g = self._global_state
        wr = self.regime_win_rates()
        wr_lines = []
        for reg, stmap in wr.items():
            for st, rate in stmap.items():
                wr_lines.append(f"  {reg}/{st}: {rate}%")
        wr_text = "\n".join(wr_lines) if wr_lines else "  (no data)"
        return (
            f"AutoLearner - adj={g['score_adj']} conf={g['confidence']} streak={g['streak']}\n"
            f"Regime/Strength Win Rates:\n{wr_text}"
        )


# ─── Singleton factory ────────────────────────────────────────────────────────

_learner_instance: AutoLearner | None = None
_learner_lock = threading.RLock()


def get_auto_learner(
    cfg: dict[str, Any],
    *,
    log_fn: Any = None,
    ai_journal_file: str = "",
) -> AutoLearner:
    """Return the process-level AutoLearner (creates + loads on first call)."""
    global _learner_instance
    with _learner_lock:
        if _learner_instance is None:
            lc = learner_config_from_cfg(cfg)
            _learner_instance = AutoLearner(lc, log_fn=log_fn, ai_journal_file=ai_journal_file)
            _learner_instance.load()
    return _learner_instance


def reset_auto_learner() -> None:
    """Force-reset singleton (tests only)."""
    global _learner_instance
    with _learner_lock:
        _learner_instance = None


# ── CLI ──────────────────────────────────────────────────────────────────────


def _al_cli() -> None:
    """Auto-Learner CLI entry point. Run with: python -m core.auto_learner"""
    import argparse
    import json as _json

    ap = argparse.ArgumentParser(
        prog="python -m core.auto_learner",
        description="Auto-Learner — Trade-history and AI-journal driven adaptive learner (Pillar 7)",
    )
    ap.add_argument("--status", action="store_true", help="Show learner state and regime win rates")
    ap.add_argument("--query", type=str, metavar="QUERY",
                    help="Query knowledge base for similar patterns")
    ap.add_argument("--record-exit", type=str, metavar="SYMBOL:TAG:PNL:REGIME",
                    help="Record a trade exit (e.g. NIFTY:WIN:100:TRENDING)")
    ap.add_argument("--learn-review", type=str, metavar="PR_ID:COMMENT1|COMMENT2",
                    help="Learn from a code review")
    ap.add_argument("--learn-failure", type=str, metavar="TEST:ERROR:MODULE",
                    help="Learn from a test failure")
    ap.add_argument("--learn-incident", type=str, metavar="TYPE:CAUSE:FIX:SEVERITY",
                    help="Learn from an incident")
    ap.add_argument("--json", action="store_true", help="Output as JSON")
    args = ap.parse_args()

    learner = get_auto_learner({"AUTO_LEARNER_ENABLED": True})

    if args.record_exit:
        parts = args.record_exit.split(":")
        if len(parts) < 3:
            print("Error: --record-exit format must be SYMBOL:TAG:PNL[:REGIME]")
            raise SystemExit(1)
        symbol, tag, pnl_str = parts[0], parts[1], parts[2]
        regime = parts[3] if len(parts) > 3 else ""
        pnl = float(pnl_str)
        learner.record_exit(symbol, tag, regime=regime, net_pnl=pnl)
        learner.learn_from_exit(symbol, tag, net_pnl=pnl, regime=regime)
        learner.save()
        print(f"[LEARNER] Recorded {tag} for {symbol} (PNL: {pnl:+.2f})")
        if args.json:
            print(_json.dumps(learner.export_global_state(), indent=2))
        return

    if args.query:
        results = learner.query_knowledge_base(args.query, max_results=10)
        if args.json:
            print(_json.dumps(results, indent=2))
        else:
            print(f"[LEARNER] KB results for '{args.query}':\n")
            for r in results:
                print(f"  [{r.get('confidence', 0):.0%}] ({r.get('frequency', 1)}x) "
                      f"{r.get('pattern', '')[:100]}")
                if r.get('solution'):
                    print(f"       -> {r['solution'][:80]}")
        return

    if args.learn_review:
        parts = args.learn_review.split(":", 1)
        if len(parts) != 2:
            print("Error: --learn-review format must be PR_ID:COMMENT1|COMMENT2")
            raise SystemExit(1)
        comments = [c.strip() for c in parts[1].split("|") if c.strip()]
        count = learner.learn_from_review(parts[0], comments)
        print(f"[LEARNER] Learned {count} patterns from review {parts[0]}")
        return

    if args.learn_failure:
        parts = args.learn_failure.split(":", 2)
        if len(parts) != 3:
            print("Error: --learn-failure format must be TEST:ERROR:MODULE")
            raise SystemExit(1)
        count = learner.learn_from_failure(parts[0], parts[1], module=parts[2])
        print(f"[LEARNER] Learned {count} patterns from failure '{parts[0]}'")
        return

    if args.learn_incident:
        parts = args.learn_incident.split(":", 3)
        if len(parts) < 3:
            print("Error: --learn-incident format must be TYPE:CAUSE:FIX[:SEVERITY]")
            raise SystemExit(1)
        severity = parts[3] if len(parts) > 3 else "MEDIUM"
        count = learner.learn_from_incident(parts[0], parts[1], parts[2], severity)
        print(f"[LEARNER] Learned {count} patterns from incident '{parts[0]}'")
        return

    if args.status or not any([args.query, args.record_exit,
                                args.learn_review, args.learn_failure, args.learn_incident]):
        if args.json:
            state = learner.export_global_state()
            state["regime_win_rates"] = learner.regime_win_rates()
            print(_json.dumps(state, indent=2))
        else:
            print(learner.summary_str())
        return

    ap.print_help()


if __name__ == "__main__":
    _al_cli()


__all__ = [
    "AutoLearner",
    "LearnerConfig",
    "get_auto_learner",
    "learner_config_from_cfg",
    "log",
    "reset_auto_learner",
]

