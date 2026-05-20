"""
Web Dashboard (Step 4) — lightweight FastAPI remote monitoring interface.

Exposes a small HTTP API so the operator can inspect bot state, recent trades,
live signals, and system health from a browser or REST client without needing
direct console access.

SAFETY — disabled by default (``web_dashboard_enabled: false``).  The server
NEVER exposes order-entry endpoints.  It is read-only except for the
``/control/pause`` and ``/control/resume`` endpoints which require a valid
``auth_token`` header.

Endpoints
---------
    GET  /              → {"status": "ok", "version": "2.43"}
    GET  /health        → system health dict
    GET  /state         → trader_state.json snapshot
    GET  /trades        → recent closed trades (last N days)
    GET  /signals       → last N live signals
    GET  /metrics       → performance metrics summary
    GET  /autopsy       → signal autopsy report
    GET  /monte-carlo   → Monte Carlo robustness summary
    POST /control/pause → pause new entries (auth required)
    POST /control/resume→ resume entries   (auth required)

Usage
-----
    from core.web_dashboard import create_app, serve

    app = create_app(cfg, state_ref, signal_log_ref)
    serve(app, host="0.0.0.0", port=8765)

Config keys (already added in index_config.defaults.json)
---------------------------------------------------------
  web_dashboard_enabled    : bool  default false
  web_dashboard_host       : str   default "0.0.0.0"
  web_dashboard_port       : int   default 8765
  web_dashboard_auth_token : str   default ""   (empty = no auth on control)
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

_DEFAULT_HOST = "0.0.0.0"
_DEFAULT_PORT = 8765


# ── In-process signal ring buffer ─────────────────────────────────────────────

class SignalLog:
    """Thread-safe ring buffer for the last N live signals."""

    def __init__(self, maxlen: int = 200) -> None:
        self._buf: list[dict] = []
        self._maxlen = maxlen
        self._lock = threading.Lock()

    def append(self, signal: dict) -> None:
        with self._lock:
            self._buf.append({**signal, "_ts": time.time()})
            if len(self._buf) > self._maxlen:
                self._buf.pop(0)

    def recent(self, n: int = 50) -> list[dict]:
        with self._lock:
            return list(self._buf[-n:])

    def clear(self) -> None:
        with self._lock:
            self._buf.clear()


# ── App factory ───────────────────────────────────────────────────────────────

def create_app(
    cfg:           dict[str, Any] | None  = None,
    state_path:    str | None             = None,
    signal_log:    SignalLog | None       = None,
    db_path:       str                    = "trades.db",
    pause_event:   threading.Event | None = None,
    signal_queue:  Any | None            = None,
    ws_feed_manager: Any | None          = None,
    rate_limiter:  Any | None            = None,
) -> Any:
    """
    Create and return a FastAPI application.

    Args:
        cfg          : Bot config dict.
        state_path   : Path to trader_state.json.
        signal_log   : SignalLog ring buffer (optional).
        db_path      : Path to trades.db.
        pause_event  : threading.Event to set/clear for pause/resume control.
        signal_queue : ManualSignalQueue instance (optional).

    Returns:
        FastAPI app instance.

    Raises:
        ImportError if FastAPI / uvicorn are not installed.
    """
    try:
        from fastapi import Body, FastAPI, Header, HTTPException, Request
        from fastapi.responses import JSONResponse
    except ImportError as exc:
        raise ImportError(
            "FastAPI is required for the web dashboard: pip install fastapi uvicorn"
        ) from exc

    c         = cfg or {}
    auth_tok  = str(c.get("web_dashboard_auth_token", "") or "")
    webhook_auth_tok = str(c.get("webhook_auth_token", "") or "")
    _state_p  = Path(state_path or c.get("trader_state_path", "trader_state.json"))
    _sig_log  = signal_log or SignalLog()
    _db       = str(db_path or c.get("trades_db", "trades.db"))
    _pause    = pause_event or threading.Event()
    _msq      = signal_queue  # ManualSignalQueue | None

    app = FastAPI(
        title="OPB Index Options Bot Dashboard",
        version="2.43",
        docs_url="/docs",
        redoc_url=None,
    )

    # ── helpers ───────────────────────────────────────────────────────────────

    def _check_auth(authorization: str | None) -> None:
        if not auth_tok:
            return
        if authorization != f"Bearer {auth_tok}":
            raise HTTPException(status_code=401, detail="Unauthorised")

    def _read_state() -> dict:
        try:
            if _state_p.is_file():
                return json.loads(_state_p.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def _load_recent_trades(days: int = 30) -> list[dict]:
        try:
            from core.performance_metrics import load_trades
            return load_trades(_db, days=days if days > 0 else None)
        except Exception:
            return []

    # ── routes ────────────────────────────────────────────────────────────────

    @app.get("/")
    def root() -> dict:
        return {
            "status": "ok",
            "version": "2.43",
            "paused": _pause.is_set(),
            "ts": time.time(),
        }

    @app.get("/health")
    def health() -> dict:
        state = _read_state()
        resp: dict[str, Any] = {
            "status": "ok",
            "paused": _pause.is_set(),
            "daily_pnl": state.get("daily_pnl", 0),
            "open_positions": state.get("open_positions", 0),
            "hard_halt": state.get("hard_halt", False),
            "ts": time.time(),
        }
        if ws_feed_manager is not None:
            try:
                resp["ws_feed"] = ws_feed_manager.status()
            except Exception as exc:
                resp["ws_feed"] = {"error": str(exc)}
        return resp

    @app.get("/state")
    def state() -> dict:
        return _read_state()

    @app.get("/shadow-trades")
    def shadow_trades(n: int = 50) -> list:
        try:
            import sqlite3
            conn = sqlite3.connect(_db)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM shadow_trades ORDER BY created_at DESC LIMIT ?", (n,)
            ).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as exc:
            _log.debug("[DASH] /shadow-trades failed: %s", exc)
            return {"error": str(exc)}

    @app.get("/trades")
    def trades(days: int = 30, n: int = 100) -> list:
        all_trades = _load_recent_trades(days)
        return all_trades[-n:]

    @app.get("/signals")
    def signals(n: int = 50) -> list:
        sigs = _sig_log.recent(n)
        # Enhance signals with reasoning and sentiment for the UI
        for s in sigs:
            s["reasoning"] = s.get("reasoning", "No detailed reasoning available")
            s["sentiment"] = s.get("sentiment", "NEUTRAL")
        return sigs

    @app.get("/metrics")
    def metrics(days: int = 30) -> dict:
        try:
            from core.performance_metrics import compute_metrics, load_trades
            t = load_trades(_db, days=days if days > 0 else None)
            return compute_metrics(t) if t else {"trades": 0}
        except Exception as exc:
            _log.debug("[DASH] /metrics failed: %s", exc)
            return {"error": str(exc)}

    @app.get("/autopsy")
    def autopsy(days: int = 30) -> dict:
        try:
            from core.signal_autopsy import format_autopsy_report, run_autopsy
            report = run_autopsy(_db, days=days)
            return {
                "n_trades":         report.n_trades,
                "overall_win_rate": report.overall_win_rate,
                "failure_patterns": report.failure_patterns,
                "insights":         report.insights,
                "summary":          format_autopsy_report(report),
            }
        except Exception as exc:
            _log.debug("[DASH] /autopsy failed: %s", exc)
            return {"error": str(exc)}

    @app.get("/monte-carlo")
    def monte_carlo(days: int = 90, n_sims: int = 500) -> dict:
        try:
            from core.monte_carlo import format_summary, load_pnl_from_db, run_simulation
            pnls = load_pnl_from_db(_db, days=days)
            if len(pnls) < 2:
                return {"error": "Insufficient trades for Monte Carlo"}
            result = run_simulation(pnls, n_simulations=n_sims, seed=42)
            return {
                "n_trades":           result.n_trades,
                "n_simulations":      result.n_simulations,
                "median_final_pnl":   result.median_final_pnl,
                "p5_final_pnl":       result.p5_final_pnl,
                "p95_final_pnl":      result.p95_final_pnl,
                "prob_of_profit":     result.prob_of_profit,
                "median_max_drawdown": result.median_max_drawdown,
                "p95_max_drawdown":   result.p95_max_drawdown,
                "summary":            format_summary(result),
            }
        except Exception as exc:
            _log.debug("[DASH] /monte-carlo failed: %s", exc)
            return {"error": str(exc)}

    # ── Sprint D endpoints ────────────────────────────────────────────────────

    @app.get("/trades/{trade_id}/replay")
    def trade_replay(trade_id: int) -> dict:
        try:
            from core.trade_replayer import get_replay_json
            return get_replay_json(trade_id, _db)
        except Exception as exc:
            _log.debug("[DASH] /trades/%s/replay failed: %s", trade_id, exc)
            return {"error": str(exc)}

    @app.get("/analysis/sensitivity")
    def sensitivity(days: int = 60) -> dict:
        try:
            from core.sensitivity_analyzer import format_sensitivity_report, run_sensitivity_analysis
            cfg_copy = dict(c, sensitivity_report_days=days)
            results = run_sensitivity_analysis(_db, None, cfg_copy)
            return {
                "params": [
                    {"name": r.param_name, "verdict": r.verdict,
                     "sensitivity_score": r.sensitivity_score, "best_value": r.best_value,
                     "insight": r.insight}
                    for r in results
                ],
                "summary": format_sensitivity_report(results),
            }
        except Exception as exc:
            _log.debug("[DASH] /analysis/sensitivity failed: %s", exc)
            return {"error": str(exc)}

    @app.get("/analysis/heatmap")
    def heatmap(days: int = 30) -> dict:
        try:
            from core.signal_autopsy import render_ascii_heatmap, run_autopsy
            report = run_autopsy(_db, days=days)
            hm = report.time_heatmap
            if hm is None:
                return {"cells": [], "chart": ""}
            return {
                "cells": [
                    {"hour": c.hour, "day_of_week": c.day_of_week,
                     "n_trades": c.n_trades, "win_rate": c.win_rate, "avg_pnl": c.avg_pnl}
                    for c in hm.cells
                ],
                "chart": render_ascii_heatmap(hm),
            }
        except Exception as exc:
            _log.debug("[DASH] /analysis/heatmap failed: %s", exc)
            return {"error": str(exc)}

    @app.get("/health/full")
    def health_full() -> dict:
        try:
            from core.health_checker import format_health_report, run_full_health_check
            report = run_full_health_check(c, _db)
            return {
                "overall_status": report.overall_status,
                "summary": report.summary,
                "ok_count": report.ok_count,
                "warn_count": report.warn_count,
                "fail_count": report.fail_count,
                "results": [
                    {"category": r.category, "name": r.name, "status": r.status,
                     "value": r.value, "message": r.message}
                    for r in report.results
                ],
                "report": format_health_report(report),
            }
        except Exception as exc:
            _log.debug("[DASH] /health/full failed: %s", exc)
            return {"error": str(exc)}

    @app.get("/readiness")
    def readiness() -> dict:
        try:
            from core.live_readiness_checker import check_live_readiness, format_readiness_report
            report = check_live_readiness(_db, c)
            return {
                "overall_ready": report.overall_ready,
                "blocking_score": report.blocking_score,
                "readiness_score": report.readiness_score,
                "summary": report.summary,
                "recommendation": report.recommendation,
                "report": format_readiness_report(report),
            }
        except Exception as exc:
            _log.debug("[DASH] /readiness failed: %s", exc)
            return {"error": str(exc)}

    @app.post("/control/pause")
    def pause(authorization: str | None = Header(default=None)) -> dict:
        _check_auth(authorization)
        _pause.set()
        _log.warning("[DASH] Bot paused via web dashboard")
        return {"status": "paused"}

    @app.post("/control/resume")
    def resume(authorization: str | None = Header(default=None)) -> dict:
        _check_auth(authorization)
        _pause.clear()
        _log.info("[DASH] Bot resumed via web dashboard")
        return {"status": "resumed"}

    # ── v2.46 Sprint 1D: Manual Signal Queue endpoints ───────────────────────

    @app.get("/signals/pending")
    def signals_pending() -> list:
        if _msq is None:
            return []
        return [s.to_dict() for s in _msq.get_pending()]

    @app.get("/signals/manual/stats")
    def signals_stats() -> dict:
        if _msq is None:
            return {"enabled": False}
        return _msq.get_stats()

    @app.get("/signals/manual/recent")
    def signals_recent(n: int = 20) -> list:
        if _msq is None:
            return []
        return [s.to_dict() for s in _msq.get_recent(n)]

    @app.post("/signals/manual")
    def submit_signal(
        body: dict = Body(default_factory=dict),
        authorization: str | None = Header(default=None),
    ) -> dict:
        _check_auth(authorization)
        if _msq is None:
            return {"status": "error", "message": "Signal queue not initialized"}
        idx    = str(body.get("index_name", body.get("index", ""))).upper()
        dirn   = str(body.get("direction", "")).upper()
        score  = int(body.get("score", 70))
        reason = str(body.get("reason", ""))
        analyst = str(body.get("analyst_name", c.get("manual_signal_default_analyst", "Dashboard")))
        expiry = body.get("expiry")
        lots   = body.get("lots_override")
        if not idx or dirn not in ("CALL", "PUT"):
            return {"status": "error", "message": "index_name and direction (CALL/PUT) required"}
        sig = _msq.submit(idx, dirn, score, reason, source="DASHBOARD",
                          analyst_name=analyst, expiry=expiry,
                          lots_override=int(lots) if lots else None)
        _log.info("[DASH] Manual signal submitted: %s", sig.signal_id)
        return {"status": "queued", "signal_id": sig.signal_id, "signal": sig.to_dict()}

    @app.post("/signals/{signal_id}/approve")
    def approve_signal(
        signal_id: str,
        body: dict = Body(default_factory=dict),
        authorization: str | None = Header(default=None),
    ) -> dict:
        _check_auth(authorization)
        if _msq is None:
            return {"status": "error", "message": "Signal queue not initialized"}
        reviewer = str(body.get("reviewer", "Dashboard"))
        lots     = body.get("lots_override")
        ok = _msq.approve(signal_id, reviewer=reviewer,
                          lots_override=int(lots) if lots else None)
        return {"status": "approved" if ok else "error",
                "signal_id": signal_id,
                "message": "" if ok else "Signal not found or not in PENDING state"}

    @app.post("/signals/{signal_id}/reject")
    def reject_signal(
        signal_id: str,
        body: dict = Body(default_factory=dict),
        authorization: str | None = Header(default=None),
    ) -> dict:
        _check_auth(authorization)
        if _msq is None:
            return {"status": "error", "message": "Signal queue not initialized"}
        reviewer = str(body.get("reviewer", "Dashboard"))
        reason   = str(body.get("reason", "Rejected via dashboard"))
        ok = _msq.reject(signal_id, reviewer=reviewer, reason=reason)
        return {"status": "rejected" if ok else "error",
                "signal_id": signal_id,
                "message": "" if ok else "Signal not found or not in PENDING state"}

    @app.post("/signals/{signal_id}/cancel")
    def cancel_signal(
        signal_id: str,
        body: dict = Body(default_factory=dict),
        authorization: str | None = Header(default=None),
    ) -> dict:
        _check_auth(authorization)
        if _msq is None:
            return {"status": "error", "message": "Queue not initialized"}
        reason = str(body.get("reason", "Cancelled via dashboard"))
        ok = _msq.cancel(signal_id, reason=reason)
        return {"status": "cancelled" if ok else "error", "signal_id": signal_id}

    # ── v2.45 Item 21: Webhook signal receiver ────────────────────────────────

    _webhook_times: list[float] = []

    @app.post("/signals/inject")
    def inject_signal(
        body: dict = Body(default_factory=dict),
        authorization: str | None = Header(default=None),
    ) -> dict:
        if not c.get("webhook_enabled", False):
            return {"status": "disabled"}
        # Auth check: use dedicated webhook token if set, else fall back to dashboard token
        if webhook_auth_tok or auth_tok:
            expected = webhook_auth_tok or auth_tok
            if authorization != f"Bearer {expected}":
                raise HTTPException(status_code=401, detail="Unauthorised")
        # Rate limit via RateLimitingService if available, else fallback to inline
        now_ts = time.time()
        if rate_limiter is not None:
            from core.ports.rate_limiting.rate_limit_port import LimitResult
            result = rate_limiter.is_allowed("webhook", cost=1)
            if result == LimitResult.DENIED:
                retry_after = rate_limiter.get_retry_after("webhook")
                return {"status": "rate_limited", "retry_after": retry_after}
        else:
            rate_limit = int(c.get("webhook_rate_limit_per_min", 5))
            _webhook_times[:] = [t for t in _webhook_times if now_ts - t < 60.0]
            if len(_webhook_times) >= rate_limit:
                return {"status": "rate_limited", "calls_last_min": len(_webhook_times)}
        payload = body or {}
        _webhook_times.append(now_ts)
        _sig_log.append({**payload, "source": "webhook"})
        _log.info("[DASH] /signals/inject received: %s", payload.get("symbol", "?"))
        return {"status": "queued", "ts": now_ts}

    # ── v2.45 Item 22: Options chain visualization ────────────────────────────

    @app.get("/chain/{index}")
    def chain_viz(index: str) -> dict:
        if not c.get("chain_viz_enabled", True):
            return {"status": "disabled"}
        try:
            import yfinance as yf
            sym_map = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK", "FINNIFTY": "NIFTY_FIN_SERVICE.NS"}
            sym = sym_map.get(index.upper(), "^NSEI")
            tk  = yf.Ticker(sym)
            exp = tk.options[0] if tk.options else None
            if exp is None:
                return {"index": index, "error": "no expiry dates"}
            chain = tk.option_chain(exp)
            calls = chain.calls[["strike", "lastPrice", "openInterest", "impliedVolatility"]].to_dict("records")
            puts  = chain.puts[["strike", "lastPrice", "openInterest", "impliedVolatility"]].to_dict("records")
            return {"index": index, "expiry": exp, "calls": calls[:20], "puts": puts[:20]}
        except Exception as exc:
            return {"index": index, "error": str(exc)}

    return app


# ── Server ────────────────────────────────────────────────────────────────────

def serve(
    app: Any,
    *,
    host: str = _DEFAULT_HOST,
    port: int = _DEFAULT_PORT,
    log_level: str = "warning",
) -> None:
    """
    Start the uvicorn server in a daemon thread.

    Returns immediately — the server runs in the background.
    Call this only when ``web_dashboard_enabled=true``.
    """
    try:
        import uvicorn
    except ImportError as exc:
        raise ImportError(
            "uvicorn is required to serve the dashboard: pip install uvicorn"
        ) from exc

    config = uvicorn.Config(app, host=host, port=port, log_level=log_level)
    server = uvicorn.Server(config)

    t = threading.Thread(target=server.run, daemon=True, name="web_dashboard")
    t.start()
    _log.info("[DASH] Dashboard started at http://%s:%d", host, port)


# ── Convenience launcher (called from index_trader.py) ───────────────────────

def maybe_start_dashboard(
    cfg:           dict[str, Any],
    state_path:    str | None             = None,
    signal_log:    SignalLog | None       = None,
    db_path:       str                    = "trades.db",
    pause_event:   threading.Event | None = None,
    signal_queue:  Any | None            = None,
    ws_feed_manager: Any | None          = None,
    rate_limiter:  Any | None            = None,
) -> Any | None:
    """
    Start the web dashboard server if ``web_dashboard_enabled=true``.

    Returns the FastAPI app (for testing) or None if disabled / import failure.
    All exceptions are caught — never blocks the main thread.
    """
    c = cfg or {}
    if not c.get("web_dashboard_enabled", False):
        return None
    try:
        # Auto-configure rate limiter from config if not explicitly provided
        if rate_limiter is None:
            try:
                from core.services.rate_limiting_service import RateLimitingService
                from core.ports.rate_limiting.rate_limit_port import RateLimitConfig
                rl = RateLimitingService()
                rl.update_config("webhook", RateLimitConfig(
                    limit=int(c.get("rate_limiter_webhook_limit", c.get("webhook_rate_limit_per_min", 5))),
                    window=int(c.get("rate_limiter_webhook_window_secs", c.get("webhook_rate_limit_per_min", 5) > 0 and 60 or 60)),
                    algorithm="fixed_window",
                ))
                rate_limiter = rl
            except Exception:
                pass
        app = create_app(c, state_path, signal_log, db_path, pause_event, signal_queue, ws_feed_manager, rate_limiter)
        host = str(c.get("web_dashboard_host", _DEFAULT_HOST))
        port = int(c.get("web_dashboard_port", _DEFAULT_PORT))
        serve(app, host=host, port=port)
        return app
    except Exception as exc:
        _log.warning("[DASH] Dashboard startup failed (non-fatal): %s", exc)
        return None
