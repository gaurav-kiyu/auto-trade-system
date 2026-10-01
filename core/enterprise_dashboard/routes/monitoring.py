"""Monitoring route registration for the Enterprise Dashboard.

Handles: /api/system/notifications/*, /api/broker/info, /api/ml/status,
/api/system/data-providers/*, /api/performance/comparison.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import Depends, Request
from fastapi.responses import StreamingResponse

from core.enterprise_dashboard.utils import _get_provider_error_info, _record_provider_request
from core.pnl_attribution import compute_pnl_attribution

_log = logging.getLogger(__name__)


def register_monitoring_routes(app, dashboard, admin_only, operator_or_admin) -> None:  # type: ignore[no-untyped-def]
    """Register monitoring, broker, ML, data provider, and notification routes.

    Args:
        app: FastAPI application instance.
        dashboard: EnterpriseDashboard instance.
        admin_only: FastAPI Depends for admin role.
        operator_or_admin: FastAPI Depends for operator or admin role.

    """
    # ── Real-Time Notifications: SSE Stream ────────────────────────────────

    @app.get("/api/system/notifications/stream")
    async def api_notifications_stream(user: Any = Depends(dashboard._auth_deps.require_auth_optional)):  # type: ignore[no-untyped-def]
        """Server-Sent Events stream for real-time notifications."""
        async def _event_generator() -> AsyncGenerator[str, None]:  # type: ignore[no-untyped-def]
            recent = dashboard._notifications.recent(20)
            yield f"event: connected\ndata: {json.dumps({'status': 'ok', 'recent': recent})}\n\n"
            async for notif in dashboard._notifications.subscribe():
                yield f"event: notification\ndata: {json.dumps(notif)}\n\n"
        return StreamingResponse(_event_generator(), media_type="text/event-stream")

    # ── Notifications REST API ─────────────────────────────────────────────

    @app.get("/api/system/notifications")
    async def api_notifications_list(
        n: int = 100,
        user: Any = Depends(dashboard._auth_deps.require_auth_optional),
    ):  # type: ignore[no-untyped-def]
        """Get recent notifications."""
        items = dashboard._notifications.recent(n)
        unacknowledged = [x for x in items if not x.get("acknowledged", False)]
        return {
            "notifications": items,
            "total": len(items),
            "unacknowledged": len(unacknowledged),
            "timestamp": time.time(),
        }

    # ── Manual paper-trade queue (1-click "Trade" button on signal screens) ─
    # Submits into the real ManualSignalQueue (core/manual_signal.py, db/manual_signals.db)
    # for the live trading loop to pick up on its next cycle - NOT an instant
    # synchronous fill. Previously this button called /api/v1/trade/paper-trade,
    # a route that never existed anywhere in the codebase; the frontend's catch
    # block then showed a fake "trade executed" success alert regardless.

    @app.post("/api/v1/trade/paper-trade")
    async def api_submit_paper_trade(request: Request, user: Any = Depends(dashboard._auth_deps.require_auth)):  # type: ignore[no-untyped-def]
        from core.manual_signal import build_signal_queue

        body = await request.json()
        symbol = str(body.get("symbol") or "").upper()
        direction = str(body.get("direction") or "CALL").upper()
        score = int(body.get("score") or 70)
        if not symbol:
            return {"success": False, "error": "symbol is required"}

        if dashboard._manual_signal_queue is None:
            dashboard._manual_signal_queue = build_signal_queue(dashboard._cfg)
        queue = dashboard._manual_signal_queue
        if queue is None:
            return {
                "success": False,
                "error": "Manual signal queue is disabled (manual_signal_enabled=false) - "
                         "no paper trade was submitted.",
            }

        sig = queue.submit(
            symbol, direction, score,
            reason=f"Dashboard 1-click paper trade by {user.username}",
            source="DASHBOARD", analyst_name=user.username,
        )
        return {
            "success": True,
            "status": "queued",
            "signal_id": sig.signal_id,
            "message": "Queued for paper execution - the trading loop will pick this up "
                       "on its next scan cycle (not an instant fill).",
        }

    @app.post("/api/system/notifications/{notif_id}/acknowledge")
    async def api_notifications_acknowledge(notif_id: str, user: Any = Depends(dashboard._auth_deps.require_auth)):  # type: ignore[no-untyped-def]
        """Acknowledge a single notification."""
        ok = dashboard._notifications.acknowledge(notif_id)
        return {"success": ok, "notification_id": notif_id}

    @app.post("/api/system/notifications/acknowledge-all")
    async def api_notifications_acknowledge_all(request: Request, user: Any = Depends(dashboard._auth_deps.require_auth)):  # type: ignore[no-untyped-def]
        """Acknowledge all notifications, optionally filtered by severity."""
        body = await request.json()
        severity = body.get("severity", None)
        count = dashboard._notifications.acknowledge_all(severity=severity)
        return {"success": True, "count": count}

    @app.post("/api/system/notifications/push")
    async def api_notifications_push(request: Request, user: Any = Depends(operator_or_admin)):  # type: ignore[no-untyped-def]
        """Push a notification programmatically."""
        body = await request.json()
        notif = dashboard._notifications.push(
            message=body.get("message", ""),
            severity=body.get("severity", "INFO"),
            category=body.get("category", "system"),
            source=body.get("source", "api"),
            details=body.get("details"),
        )
        return {"success": True, "notification": notif.to_dict()}

    # ── Broker Info API ────────────────────────────────────────────────────

    @app.get("/api/broker/info")
    async def api_broker_info(user: Any = Depends(dashboard._auth_deps.require_auth_optional)):  # type: ignore[no-untyped-def]
        """Report the configured broker driver honestly.

        Previously hardcoded "status": "connected" unconditionally - this
        module never actually checks connectivity, and while
        live_trading_lockout_enabled forces PaperBrokerAdapter (the default,
        safe state for this project's paper-only phase), claiming a live
        broker is "connected" was simply false. last_connected/requests_today/
        error_rate/failover_active were inert placeholders with no real
        tracking behind them; reported as null/not-tracked rather than
        fabricated numbers.
        """
        lockout_on = bool(dashboard._cfg.get("live_trading_lockout_enabled", True))
        execution_mode = str(dashboard._cfg.get("execution_mode", "paper")).lower()
        is_paper = lockout_on or execution_mode == "paper"
        return {
            "status": "paper_mode" if is_paper else "not_tracked",
            "broker_name": dashboard._cfg.get("broker_name", "Zerodha"),
            "mode": dashboard._cfg.get("execution_mode", "paper"),
            "latency_ms": dashboard._bot_refs.get("broker_latency"),
            "adapter": dashboard._cfg.get("broker_adapter", "kite"),
            "last_connected": None,
            "requests_today": None,
            "error_rate": None,
            "failover_active": False,
            "note": "No real broker connectivity check exists yet - this reflects configured mode only.",
        }

    # ── ML Status API ──────────────────────────────────────────────────────

    @app.get("/api/ml/status")
    async def api_ml_status(user: Any = Depends(dashboard._auth_deps.require_auth_optional)):  # type: ignore[no-untyped-def]
        return {
            "model_loaded": dashboard._bot_refs.get("ml_model_loaded", False),
            "accuracy": dashboard._bot_refs.get("ml_accuracy"),
            "brier_score": dashboard._bot_refs.get("ml_brier_score"),
            "last_training": dashboard._bot_refs.get("ml_last_training"),
            "classifier_type": "LightGBM",
            "n_features": dashboard._bot_refs.get("ml_n_features"),
            "training_samples": dashboard._bot_refs.get("ml_training_samples"),
            "drift_detected": dashboard._bot_refs.get("ml_drift_detected", False),
            "total_predictions": dashboard._bot_refs.get("ml_total_predictions", 0),
            "avg_confidence": dashboard._bot_refs.get("ml_avg_confidence"),
            "calibration_score": dashboard._bot_refs.get("ml_calibration_score"),
            "psi": dashboard._bot_refs.get("ml_psi"),
        }

    # ── Data Provider Status ───────────────────────────────────────────────

    @app.get("/api/system/data-providers")
    async def api_data_providers(user: Any = Depends(dashboard._auth_deps.require_auth_optional)):  # type: ignore[no-untyped-def]
        """Get status of all registered market data providers."""
        mds = dashboard._bot_refs.get("market_data_service")
        if mds is None:
            return {"status": "unavailable", "detail": "MarketDataService not wired"}
        try:
            adapters = mds.list_adapters()
            health = mds.health_check()
            providers_list = []
            for name, info in adapters.items():
                providers_list.append({
                    "name": name,
                    "type": info.get("adapter_type", "unknown"),
                    "asset_classes": info.get("asset_classes", []),
                    "priority": info.get("priority", 10),
                    "connected": info.get("connected", False),
                })
            return {
                "status": "ok",
                "total": health.get("total_adapters", 0),
                "connected": health.get("connected_adapters", 0),
                "disconnected": health.get("disconnected_adapters", 0),
                "providers": providers_list,
                "timestamp": time.time(),
            }
        except (ValueError, TypeError, AttributeError, RuntimeError) as exc:
            _log.warning("[DASH] Data providers status error: %s", exc)
            return {"status": "error", "detail": str(exc)}

    @app.get("/api/system/data-providers/health")
    async def api_data_providers_health(user: Any = Depends(dashboard._auth_deps.require_auth_optional)):  # type: ignore[no-untyped-def]
        """Get aggregate health metrics for the market data provider mesh."""
        mds = dashboard._bot_refs.get("market_data_service")
        if mds is None:
            return {"status": "unavailable", "detail": "MarketDataService not wired"}
        try:
            health = mds.health_check()
            total = health.get("total_adapters", 0)
            connected = health.get("connected_adapters", 0)
            disconnected = health.get("disconnected_adapters", 0)
            details = health.get("adapter_details", {})

            if total == 0:
                overall = "idle"
            elif connected == total:
                overall = "healthy"
            elif connected > 0:
                overall = "degraded"
            else:
                overall = "critical"

            _record_provider_request()
            error_info = _get_provider_error_info(details)

            return {
                "status": overall,
                "total": total,
                "connected": connected,
                "disconnected": disconnected,
                "health_pct": round((connected / total * 100) if total > 0 else 0, 1),
                "adapter_details": details,
                "error_tracking": error_info,
                "timestamp": time.time(),
            }
        except (ValueError, TypeError, AttributeError, RuntimeError) as exc:
            _log.warning("[DASH] Data providers health error: %s", exc)
            return {"status": "error", "detail": str(exc)}

    # ── Performance Comparison API ─────────────────────────────────────────

    # ── P&L Attribution API ────────────────────────────────────────────────

    @app.get("/api/pnl-attribution")
    async def api_pnl_attribution(user: Any = Depends(dashboard._auth_deps.require_auth_optional)):  # type: ignore[no-untyped-def]
        """Get P&L attribution breakdown by direction, regime, session, and score tier.

        Returns:
            Dict with total_pnl, unrealized_pnl, realized_pnl, open_positions,
            and breakdown categories: by_direction, by_regime, by_session, by_asset.

        """
        try:
            days = 90
            results = compute_pnl_attribution(db_path=dashboard._db_path, days=days, cfg=dashboard._cfg)

            if not results:
                return {
                    "total_pnl": 0.0,
                    "unrealized_pnl": 0.0,
                    "realized_pnl": 0.0,
                    "open_positions": 0,
                    "by_direction": {},
                    "by_regime": {},
                    "by_session": {},
                    "by_asset": {},
                }

            # Group results by dimension
            by_direction = {}
            by_regime = {}
            by_session = {}
            by_score = {}
            by_asset = {}

            total_pnl = 0.0

            for r in results:
                bucket_dict = {
                    "trades": r.trades,
                    "wins": r.wins,
                    "losses": r.trades - r.wins,
                    "win_rate": r.win_rate,
                    "total_pnl": r.total_pnl,
                    "avg_pnl": r.avg_pnl,
                }
                if r.dimension == "direction":
                    by_direction[r.bucket] = bucket_dict
                    total_pnl += r.total_pnl
                elif r.dimension == "regime":
                    by_regime[r.bucket] = bucket_dict
                elif r.dimension == "session":
                    by_session[r.bucket] = bucket_dict
                elif r.dimension == "score_tier":
                    by_score[r.bucket] = bucket_dict
                elif r.dimension == "asset":
                    by_asset[r.bucket] = bucket_dict

            state = dashboard._read_state()
            unrealized = float(state.get("unrealized_pnl", 0.0) or 0.0)

            return {
                "total_pnl": round(total_pnl + unrealized, 2),
                "unrealized_pnl": round(unrealized, 2),
                "realized_pnl": round(total_pnl, 2),
                "open_positions": state.get("open_positions", 0),
                "by_direction": by_direction,
                "by_regime": by_regime,
                "by_session": by_session,
                "by_score": by_score,
                "by_asset": by_asset if by_asset else by_score,
            }
        except ImportError as exc:
            _log.warning("[DASH] PnL attribution unavailable: %s", exc)
            return {"error": "PnL attribution module not available", "detail": str(exc)}
        except (ValueError, TypeError, RuntimeError, OSError, AttributeError) as exc:
            _log.warning("[DASH] PnL attribution error: %s", exc)
            return {"error": str(exc)}

    @app.get("/api/performance/comparison")
    async def api_performance_comparison(request: Request, user: Any = Depends(dashboard._auth_deps.require_auth_optional)):  # type: ignore[no-untyped-def]
        """Get comprehensive performance comparison data."""
        try:
            from core.performance_metrics import (
                compute_metrics,
                generate_insights,
                load_trades,
                metrics_by_direction,
                metrics_by_exit_reason,
                metrics_by_index,
                metrics_by_regime,
                metrics_by_score_bin,
            )

            days_str = request.query_params.get("days", "90")
            mode = request.query_params.get("mode", None)
            try:
                days = int(days_str)
            except (ValueError, TypeError):
                days = 90

            trades = load_trades(dashboard._db_path, mode=mode, days=days)

            if not trades:
                return {
                    "status": "ok",
                    "trades_count": 0,
                    "note": "Benchmark comparison unavailable — no executed-trade dataset",
                    "overall": {},
                    "by_regime": {},
                    "by_score_bin": {},
                    "by_direction": {},
                    "by_index": {},
                    "by_exit_reason": {},
                    "insights": [],
                    "period_days": days,
                    "timestamp": time.time(),
                }

            overall = compute_metrics(trades)
            insights = generate_insights(trades)

            return {
                "status": "ok",
                "trades_count": len(trades),
                "overall": overall,
                "by_regime": metrics_by_regime(trades),
                "by_score_bin": metrics_by_score_bin(trades),
                "by_direction": metrics_by_direction(trades),
                "by_index": metrics_by_index(trades),
                "by_exit_reason": metrics_by_exit_reason(trades),
                "insights": insights,
                "period_days": days,
                "period_mode": mode,
                "timestamp": time.time(),
            }
        except ImportError as exc:
            _log.warning("[DASH] Performance comparison unavailable: %s", exc)
            return {"status": "unavailable", "detail": "performance_metrics module not available"}
        except (ValueError, TypeError, RuntimeError, OSError) as exc:
            _log.warning("[DASH] Performance comparison error: %s", exc)
            return {"status": "error", "detail": str(exc)}

    # ── Institutional Upgrades: GEX, Sector Radar, AI Debrief, & Telegram Webhook ──

    @app.get("/api/market/sector-radar")
    async def api_sector_radar(user: Any = Depends(dashboard._auth_deps.require_auth_optional)):  # type: ignore[no-untyped-def]
        """NSE Sector Rotation, Relative Strength (RS) & Quadrants."""
        from core.market.sector_rotation_radar import SectorRotationRadar
        matrix = SectorRotationRadar.get_live_sector_matrix()
        has_real_data = any(not r.get("is_demo_data") for r in matrix) if matrix else False
        if has_real_data:
            return {
                "status": "available",
                "sectors": matrix,
                "timestamp": time.time(),
            }
        return {
            "status": "unavailable",
            "message": "Live production feed not connected",
            "sectors": [],
            "timestamp": time.time(),
        }

    @app.get("/api/options/gex-analysis")
    async def api_options_gex(symbol: str = "NIFTY", spot: float = 24500.0):  # type: ignore[no-untyped-def]
        """Institutional Gamma Exposure (GEX), IV Percentile & Volatility Flip from real options data."""
        from pathlib import Path as _P
        import sqlite3
        from core.options.gex_iv_engine import GammaExposureEngine
        from dataclasses import asdict

        sym = symbol.upper()
        snap_path = _P(dashboard._cfg.get("oi_snapshot_db_path", dashboard._cfg.get("OI_SNAPSHOT_DB_PATH", "db/oi_snapshots.db")))
        strikes_data = []

        if snap_path.is_file():
            try:
                conn = sqlite3.connect(str(snap_path))
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('snapshots', 'oi_snapshots')")
                tables = {r[0] for r in cur.fetchall()}
                if "snapshots" in tables:
                    cur.execute("SELECT * FROM snapshots WHERE index_name = ? ORDER BY timestamp DESC, strike ASC", (sym,))
                    rows = cur.fetchall()
                    if rows:
                        latest_ts = rows[0]["timestamp"]
                        latest_rows = [r for r in rows if r["timestamp"] == latest_ts]
                        spot = float(latest_rows[0]["spot_price"] or spot)
                        for r in latest_rows:
                            strikes_data.append({
                                "strike": float(r["strike"]),
                                "call_oi": int(r["call_oi"] or 0),
                                "put_oi": int(r["put_oi"] or 0),
                                "call_iv": float(r["call_iv"] or 15.0),
                                "put_iv": float(r["put_iv"] or 15.0),
                                "dte": 4.0,
                            })
                elif "oi_snapshots" in tables:
                    cur.execute("SELECT * FROM oi_snapshots WHERE index_name = ? AND strike IS NOT NULL ORDER BY ts DESC, strike ASC", (sym,))
                    rows = cur.fetchall()
                    if rows:
                        latest_ts = rows[0]["ts"]
                        latest_rows = [r for r in rows if r["ts"] == latest_ts]
                        for r in latest_rows:
                            strikes_data.append({
                                "strike": float(r["strike"]),
                                "call_oi": int(r["call_oi"] or 0),
                                "put_oi": int(r["put_oi"] or 0),
                                "call_iv": 15.0,
                                "put_iv": 15.0,
                                "dte": 4.0,
                            })
                conn.close()
            except sqlite3.Error:
                pass

        if strikes_data:
            result = GammaExposureEngine.analyze_options_chain(spot_price=spot, options_data=strikes_data)
            res = asdict(result)
            res["is_demo_data"] = False
            return res

        return {
            "status": "unavailable",
            "message": f"Live Options Chain strike data currently unavailable / waiting for market feed for {sym}",
            "spot_price": spot,
            "total_net_gex_cr": 0.0,
            "zero_gamma_flip": None,
            "call_wall_strike": None,
            "put_wall_strike": None,
            "market_regime": "NEUTRAL",
            "strikes_gex": [],
            "iv_rank_pct": 0.0,
            "iv_percentile_pct": 0.0,
            "iv_status": "UNAVAILABLE",
            "is_demo_data": False,
        }

    @app.get("/api/v1/journal/ai-debrief")
    async def api_journal_ai_debrief(date: str | None = None):  # type: ignore[no-untyped-def]
        """Automated AI Post-Market Cognitive Trade Journal Debrief."""
        from core.ai.post_market_debrief import PostMarketDebriefEngine
        return PostMarketDebriefEngine.generate_daily_debrief(trade_date=date)

    @app.post("/api/telegram/webhook")
    async def api_telegram_webhook(request: Request):  # type: ignore[no-untyped-def]
        """Handles 1-Click Telegram Inline Button Callbacks."""
        from core.telegram.callback_handler import TelegramActionHandler
        try:
            body = await request.json()
            callback_query = body.get("callback_query", {})
            cb_data = callback_query.get("data", "")
            user_id = str(callback_query.get("from", {}).get("id", "unknown"))
            res = TelegramActionHandler.process_callback_action(cb_data, user_id)
            return {"status": "ok", "result": res}
        except Exception as ex:
            return {"status": "error", "detail": str(ex)}

    # ── Native Web Push Notifications (PWA Foundation) ───────────────
    _push_subscriptions: list[dict[str, Any]] = []

    @app.get("/api/v1/push/vapid-public-key")
    async def api_push_vapid_key(user: Any = Depends(dashboard._auth_deps.require_auth_optional)):  # type: ignore[no-untyped-def]
        """Get standard VAPID public key for Web Push."""
        key = str(dashboard._cfg.get(
            "VAPID_PUBLIC_KEY",
            "BEl62iUYgUivxIkv69yViEuiBIa-Ib9-SkvMeAtA3LFgDzkrxZJjSgSnfckjBJuBkr3qBUYIHBQFLXYp5Nksh8U",
        ))
        return {
            "publicKey": key,
            "status": "ok",
        }

    @app.post("/api/v1/push/subscribe")
    async def api_push_subscribe(request: Request, user: Any = Depends(dashboard._auth_deps.require_auth_optional)):  # type: ignore[no-untyped-def]
        """Register a browser push subscription."""
        try:
            sub_data = await request.json()
            if sub_data and sub_data not in _push_subscriptions:
                _push_subscriptions.append(sub_data)
            return {"status": "ok", "message": "Subscription registered successfully", "active_subscriptions": len(_push_subscriptions)}
        except Exception as exc:
            return {"status": "error", "detail": str(exc)}

    # ── Layer 2 Institutional Upgrades: Copier, Order Flow CVD, Margin Radar, & Sandbox ──

    @app.get("/api/copier/accounts")
    async def api_copier_accounts(user: Any = Depends(admin_only)):  # type: ignore[no-untyped-def]
        """Get linked client accounts and copied orders history."""
        from core.execution.trade_copier import MasterTradeCopier
        copier = MasterTradeCopier.get_instance()
        accounts = [a for a in copier.get_linked_accounts() if not a.get("is_demo_data")]
        return {
            "status": "available" if accounts else "unavailable",
            "message": "Active linked accounts" if accounts else "Live production feed not connected",
            "accounts": accounts,
            "history": copier.get_execution_history(50) if accounts else [],
            "timestamp": time.time(),
        }

    @app.post("/api/copier/execute")
    async def api_copier_execute(request: Request, user: Any = Depends(admin_only)):  # type: ignore[no-untyped-def]
        """Execute a master trade and replicate to all linked accounts."""
        from core.execution.trade_copier import MasterTradeCopier
        body = await request.json()
        sym = body.get("symbol", "NIFTY")
        dirn = body.get("direction", "BUY")
        qty = int(body.get("master_quantity", 100))
        price = float(body.get("entry_price", 100.0))
        copier = MasterTradeCopier.get_instance()
        return copier.execute_master_order(symbol=sym, direction=dirn, entry_price=price, master_quantity=qty)

    @app.get("/api/market/order-flow")
    async def api_order_flow(symbol: str = "NIFTY", price: float = 24500.0, volume: int = 150000, change_pct: float = 1.25):  # type: ignore[no-untyped-def]
        """Order Flow, Cumulative Volume Delta (CVD) and Absorption Signals."""
        from dataclasses import asdict

        from core.market.order_flow_cvd import OrderFlowCVDEngine
        res = OrderFlowCVDEngine.calculate_order_flow(symbol=symbol, current_price=price, volume_total=volume, price_change_pct=change_pct)
        return asdict(res)

    @app.get("/api/portfolio/margin-radar")
    async def api_portfolio_margin_radar(user: Any = Depends(dashboard._auth_deps.require_auth_optional)):  # type: ignore[no-untyped-def]
        """Broker Margin & Collateral Radar."""
        from core.portfolio.margin_radar import MultiBrokerMarginRadar
        margins = MultiBrokerMarginRadar.get_consolidated_margins()
        is_demo = bool(margins.get("is_demo_data", True))
        if not is_demo and margins.get("brokers"):
            return margins
        return {
            "status": "unavailable",
            "message": "Live production feed not connected",
            "brokers": [],
            "total_collateral": 0.0,
            "total_used": 0.0,
            "total_available": 0.0,
            "peak_margin_alert": False,
        }

    @app.get("/api/backtest/run-sandbox")
    async def api_backtest_run_sandbox(
        strategy: str = "Multi-Timeframe Trend Breakout",
        symbol: str = "NIFTY",
        rsi_lower: int = 30,
        rsi_upper: int = 70,
        adx_cutoff: int = 25,
        ema_fast: int = 9,
        ema_slow: int = 21,
        vwap_mult: float = 1.8,
        period_days: int = 252,
    ):  # type: ignore[no-untyped-def]
        """Run interactive strategy parameter sandbox backtest simulation."""
        from dataclasses import asdict

        from core.backtest.strategy_sandbox import StrategySandboxStudio
        res = StrategySandboxStudio.run_sandbox_simulation(
            strategy_name=strategy,
            symbol=symbol,
            rsi_lower=rsi_lower,
            rsi_upper=rsi_upper,
            adx_cutoff=adx_cutoff,
            ema_fast=ema_fast,
            ema_slow=ema_slow,
            vwap_mult=vwap_mult,
            period_days=period_days,
        )
        return asdict(res)

    # ── Layer 3 Pinnacle Quant Endpoints: FII/DII, 0DTE Harvester, Iceberg SOR, & Copilot ──

    @app.get("/api/market/fii-dii-positioning")
    async def api_fii_dii_positioning(user: Any = Depends(dashboard._auth_deps.require_auth_optional)):  # type: ignore[no-untyped-def]
        """NSE Participant-wise Open Interest Positioning & Trap Alerts."""
        from core.market.fii_dii_flow_radar import FiiDiiFlowRadar
        data = FiiDiiFlowRadar.get_participant_positioning()
        is_demo = bool(data.get("is_demo_data", True))
        if not is_demo and data.get("participants"):
            return data
        return {
            "status": "unavailable",
            "message": "Live production feed not connected",
            "participants": [],
            "smart_money_traps": [],
            "institutional_sentiment": "UNAVAILABLE",
            "timestamp": time.time(),
        }

    @app.get("/api/strategy/0dte-status")
    async def api_0dte_status(symbol: str = "NIFTY", spot: float = 24520.0, user: Any = Depends(dashboard._auth_deps.require_auth_optional)):  # type: ignore[no-untyped-def]
        """0DTE Expiry Day Straddle / Delta-Neutral Harvester status."""
        from core.strategy.expiry_0dte_harvester import Expiry0DTEHarvester
        status = Expiry0DTEHarvester.get_live_harvest_status(index_symbol=symbol, spot=spot)
        is_demo = bool(status.get("is_demo_data", True))
        if not is_demo and status.get("legs"):
            return status
        return {
            "status": "unavailable",
            "message": "Live production feed not connected",
            "active": False,
            "legs": [],
            "total_pnl": 0.0,
            "delta_neutrality": "UNAVAILABLE",
        }

    @app.post("/api/execution/iceberg-slice")
    async def api_iceberg_slice(request: Request):  # type: ignore[no-untyped-def]
        """Institutional Smart Order Routing (SOR) & Iceberg Order Slicing."""
        from core.execution.iceberg_sor_engine import IcebergSOREngine
        body = await request.json()
        sym = body.get("symbol", "TCS")
        side = body.get("side", "BUY")
        qty = int(body.get("total_quantity", 5000))
        price = float(body.get("benchmark_price", 2268.0))
        tranches = int(body.get("num_tranches", 10))
        return IcebergSOREngine.slice_and_execute(symbol=sym, side=side, total_quantity=qty, benchmark_price=price, num_tranches=tranches)

    @app.get("/api/copilot/query")
    async def api_copilot_query(q: str = ""):  # type: ignore[no-untyped-def]
        """Natural Language AI Copilot Query Engine."""
        from core.ai.copilot_command_bar import AICopilotEngine
        return AICopilotEngine.process_query(q)

    # ── 100% Free Direct UPI Billing & Auto-Provisioning Endpoints ──

    @app.get("/api/billing/plans")
    async def api_billing_plans():  # type: ignore[no-untyped-def]
        """List all subscription plans."""
        from core.billing.upi_billing_engine import UpiBillingEngine
        return UpiBillingEngine.get_plans()

    @app.get("/api/billing/upi-details")
    async def api_billing_upi_details():  # type: ignore[no-untyped-def]
        """Return active UPI VPA, payee name, and custom scanner availability."""
        from core.billing.upi_billing_engine import UpiBillingEngine
        return UpiBillingEngine.get_upi_details()

    @app.get("/api/billing/upi-qr-image")
    async def api_billing_upi_qr_image():  # type: ignore[no-untyped-def]
        """Serve the uploaded custom UPI scanner image if available."""
        from fastapi.responses import FileResponse, JSONResponse

        from core.billing.upi_billing_engine import UpiBillingEngine

        qr_path = UpiBillingEngine.get_custom_qr_path()
        if not qr_path or not qr_path.exists():
            return JSONResponse(status_code=404, content={"detail": "No custom UPI QR scanner uploaded"})

        ext = qr_path.suffix.lower()
        media_types = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".svg": "image/svg+xml",
        }
        media_type = media_types.get(ext, "image/png")
        return FileResponse(
            str(qr_path),
            media_type=media_type,
            headers={"Cache-Control": "no-cache, must-revalidate"},
        )

    @app.get("/api/billing/generate-qr")
    async def api_billing_generate_qr(plan_id: str = "plan_options_vip", username: str = "guest"):  # type: ignore[no-untyped-def]
        """Generate native NPCI UPI QR string and render URI."""
        from core.billing.upi_billing_engine import UpiBillingEngine
        return UpiBillingEngine.generate_upi_qr_string(plan_id=plan_id, username=username)

    @app.post("/api/billing/confirm-upi-payment")
    async def api_billing_confirm(  # type: ignore[no-untyped-def]
        request: Request, user: Any = Depends(dashboard._auth_deps.require_auth),
    ):
        """Auto-provision user permissions upon UPI payment confirmation.

        Fail-closed security enforcement: Automated self-activation of paid plans
        without genuine PSP payment-gateway verification is strictly blocked.
        """
        from fastapi.responses import JSONResponse

        from core.billing.upi_billing_engine import UpiBillingEngine
        body = await request.json()
        pid = body.get("plan_id", "plan_options_vip")
        ref = (body.get("ref") or body.get("transaction_ref") or "").strip()
        if not ref or ref == "UPI-DIRECT":
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "error_code": "UTR_REQUIRED",
                    "message": "Valid UPI Transaction ID / UTR is required to record payment confirmation.",
                },
            )
        result = UpiBillingEngine.confirm_and_provision_user(
            username=user.username, plan_id=pid, transaction_ref=ref,
        )
        success = bool(result.get("success"))
        try:
            action = "billing_self_confirmed_payment" if success else "billing_payment_verification_blocked"
            dashboard._auth._audit_log(
                action, user.username, "",
                {
                    "plan_id": pid,
                    "transaction_ref": ref,
                    "success": success,
                    "error_code": result.get("error_code", "SUCCESS" if success else "REJECTED"),
                    "price_inr": result.get("price_inr", 0),
                },
                success=success,
            )
        except (ValueError, AttributeError, TypeError, OSError) as e:
            _log.warning("[DASH] Billing confirmation audit log write failed: %s", e)
        status_code = 200 if success else 400
        return JSONResponse(status_code=status_code, content=result)


    # ── 100% Free Disaster Recovery & Local Snapshot Endpoints ──

    @app.post("/api/backup/trigger-snapshot")
    async def api_backup_trigger(user: Any = Depends(admin_only)):  # type: ignore[no-untyped-def]
        """Trigger an instant compressed database snapshot with SHA-256 integrity check."""
        from core.backup.disaster_recovery import DisasterRecoveryEngine
        result = DisasterRecoveryEngine.create_snapshot()
        try:
            dashboard._auth._audit_log("backup_snapshot_triggered", user.username, "", {"result": result})
        except (ValueError, AttributeError, TypeError, OSError) as e:
            _log.warning("[DASH] Backup snapshot audit log write failed: %s", e)
        return result

    @app.get("/api/backup/list-snapshots")
    async def api_backup_list(user: Any = Depends(admin_only)):  # type: ignore[no-untyped-def]
        """List all local rotating snapshots."""
        from core.backup.disaster_recovery import DisasterRecoveryEngine
        return DisasterRecoveryEngine.list_snapshots()

    @app.post("/api/backup/restore-snapshot")
    async def api_backup_restore(request: Request, user: Any = Depends(admin_only)):  # type: ignore[no-untyped-def]
        """Restore all databases and state files from a selected snapshot archive.

        Previously had NO auth dependency at all and no audit trail - anyone
        able to reach this endpoint could roll back every DB/state file in
        the system with zero record of who did it or why.
        """
        from core.backup.disaster_recovery import DisasterRecoveryEngine
        body = await request.json()
        snap_id = body.get("snapshot_id", "")
        result = DisasterRecoveryEngine.restore_snapshot(snapshot_id=snap_id)
        try:
            dashboard._auth._audit_log(
                "backup_snapshot_restored", user.username, "",
                {"snapshot_id": snap_id, "result": result.get("success") if isinstance(result, dict) else None},
            )
        except (ValueError, AttributeError, TypeError, OSError) as e:
            _log.warning("[DASH] Backup restore audit log write failed: %s", e)
        return result


import threading

_lock = threading.RLock()




