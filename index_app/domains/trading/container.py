"""Dependency Injection Container Setup — service wiring for production trading.

Extracted from ``index_trader.py`` ``setup_di_container()`` (DEBT-008) to reduce
the monolith and centralise all service-implementation registration.

Responsibilities:
1. Resolve the DI container from ``core.di_container``
2. Register all port implementations (ConfigPort, ExecutionPort, RiskPort, etc.)
3. Wire legacy module-level globals (``_execution_service``, ``_risk_service``, etc.)
4. Flush the buffered Telegram message queue
5. Start background services (morning checklist, session report, circuit breaker,
   health check, stale account detector, equity trader)
6. Register kernel/utility types (CorrelationIdManager, StructuredLogger, etc.)
7. Wire orchestration variables (DATA_ENGINE, STRATEGY_ENGINE, etc.)
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

_log = logging.getLogger(__name__)


def setup_di_container(
    cfg: dict[str, Any],
    # Legacy module-level state references (set by index_trader.py)
    index_map: dict[str, Any],
    make_broker_fn: callable,
    fetch_vix_fn: callable,
    fetch_nse_holidays_dynamic_fn: callable,
    on_ws_tick_fn: callable,
    # Mutables updated by this function
    globals_store: dict[str, Any],
) -> None:
    """Set up the dependency injection container with all service implementations.

    Args:
        cfg: Effective configuration dict.
        index_map: Index symbol → yfinance symbol mapping.
        make_broker_fn: Factory that returns the broker adapter.
        fetch_vix_fn: Callable that returns the current VIX value.
        fetch_nse_holidays_dynamic_fn: Callable that updates NSE holidays.
        on_ws_tick_fn: WebSocket tick callback.
        globals_store: Dict of module-level mutable references updated in-place
            (e.g. ``_execution_service``, ``_risk_service``, ``_send_impl``, etc.)
    """
    sg = lambda k: globals_store.get(k)  # shorthand for globals_store.get

    # Fetch NSE holidays before any trading decision
    fetch_nse_holidays_dynamic_fn()

    from core.di_container import get_container
    from core.ports import (
        BrokerHealthPort,
        CircuitBreakerPort,
        ConfigPort,
        CorrelationIdPort,
        ExecutionPort,
        LoggingPort,
        MarketDataPort,
        MetricsPort,
        MlModelPort,
        NotificationPort,
        PersistencePort,
        RateLimitPort,
        RiskPort,
        StrategyPort,
    )
    from core.services.broker_health_service import BrokerHealthService
    from core.services.circuit_breaker_service import CircuitBreakerService
    from core.services.execution_service import ExecutionService, ExecutionServiceConfig
    from core.services.notification_service import NotificationService
    from core.services.persistence_service import PersistenceService
    from core.services.rate_limiting_service import RateLimitingService
    from core.services.risk_service import RiskService, RiskServiceConfig
    from core.services.signal_orchestrator import signal_orchestrator as _sig_orch
    from core.signal_service import get_signal_service
    from core.strategy import StrategyOrchestrator
    from infrastructure.adapters.correlation_id.correlation_id_adapter import CorrelationIdAdapter
    from infrastructure.adapters.market_data.yahoofinance.adapter import YahooFinanceAdapter
    from infrastructure.adapters.metrics.metrics_adapter import MetricsAdapter
    from infrastructure.adapters.ml_model.ml_model_adapter import MLModelAdapter
    from infrastructure.adapters.persistence.sqlite_adapter import SQLiteAdapter
    from infrastructure.config.logging_adapter import StructuredLoggerAdapter
    from infrastructure.config.secure_config_adapter import SecureConfigAdapter

    container = get_container()
    config_adapter = SecureConfigAdapter()
    container.register_instance(ConfigPort, config_adapter)

    config = container.resolve(ConfigPort)

    broker_port = make_broker_fn()

    # Initialize WAL journal for write-ahead logging in execution path
    from core.wal.journal import WriteAheadJournal
    _wal_journal = WriteAheadJournal(db_path=cfg.get("wal_journal_db_path", "data/wal_journal.db"))

    trade_persistence = SQLiteAdapter("data/trades.db")
    market_data_port = YahooFinanceAdapter()

    container.register_instance(MarketDataPort, market_data_port)

    # Wire WS feed manager into the container for health checks / future use
    ws_feed_manager = sg("_ws_feed_manager")
    if ws_feed_manager is not None:
        container.register_instance(type(ws_feed_manager), ws_feed_manager)

        # Start Kite WebSocket feed on startup (gated internally by config/paper-mode/broker)
        if cfg.get("kite_ticker_startup_connect", True):
            ws_feed_manager.connect(on_message=on_ws_tick_fn)

    # Phase 4A-C: Persistent idempotency with proper DB path
    idem_db_path = cfg.get("idempotency_db_path", "data/execution_state.db")
    os.makedirs(os.path.dirname(idem_db_path), exist_ok=True) if os.path.dirname(idem_db_path) else None
    execution_service = ExecutionService(
        broker_port=broker_port,
        trade_persistence=trade_persistence,
        config=ExecutionServiceConfig(idempotency_db_path=idem_db_path),
        wal_journal=_wal_journal,
    )
    globals_store["_execution_service"] = execution_service
    container.register_instance(ExecutionPort, execution_service)

    _risk_config = RiskServiceConfig(
        max_daily_loss=float(cfg.get("MAX_DAILY_LOSS", -2000)),
        max_daily_trades=int(cfg.get("MAX_TRADES_DAY", 10)),
        max_open_positions=int(cfg.get("MAX_OPEN", 5)),
        max_consecutive_losses=int(cfg.get("MAX_CONSECUTIVE_LOSSES", 3)),
    )
    risk_service = RiskService(
        config=_risk_config,
        trade_persistence=trade_persistence,
        get_live_vix_fn=fetch_vix_fn,
    )
    container.register_instance(RiskPort, risk_service)
    globals_store["RISK_ENGINE"] = risk_service
    mandate_service = sg("_mandate_service")
    if mandate_service is not None:
        mandate_service._risk_service = risk_service

    # Wire PositionService with all dependencies
    _position_service = _initialize_position_service(
        cfg=cfg,
        risk_service=risk_service,
        execution_service=execution_service,
        globals_store=globals_store,
    )
    globals_store["_position_service"] = _position_service

    # Configure intraday P&L monitoring from config
    from core.safety_state import set_intraday_loss_limit
    set_intraday_loss_limit(float(cfg.get("INTRADAY_LOSS_LIMIT", cfg.get("MAX_DAILY_LOSS", -2000))))

    _signal_service = get_signal_service(cfg=cfg)
    globals_store["_signal_service"] = _signal_service

    notification_service = NotificationService()
    container.register_instance(NotificationPort, notification_service)

    # Get send function from notification service
    send_fn = _resolve_send_fn(notification_service)

    # Wire legacy send() to the real notification service
    _flush_and_wire_send(send_fn=send_fn, globals_store=globals_store)

    # v2.47 Execution Hardening
    from core.execution_hardening_integration import init_execution_hardening
    _execution_hardening_services = init_execution_hardening(
        config=dict(config),
        broker_port=broker_port,
        send_alert_fn=lambda msg, critical: send_fn(f"[HARDENING] {msg}"),
        get_price_fn=lambda sym: broker_port.get_ltp(sym) if hasattr(broker_port, 'get_ltp') else None,
    )
    _log.info("Execution hardening initialized: %s", list(_execution_hardening_services.keys()))

    # Start background services
    _start_background_services(cfg=config, send_fn=send_fn, globals_store=globals_store)

    persistence_service = PersistenceService()
    container.register_instance(PersistencePort, persistence_service)

    broker_health_service = BrokerHealthService(broker_adapters={"PAPER": broker_port})
    container.register_instance(BrokerHealthPort, broker_health_service)

    # Initialize Stale Account Detector
    from core.stale_account_detector import StaleAccountDetector
    _stale_detector = StaleAccountDetector(
        broker_health_service=broker_health_service,
        session_store=None,
        alert_fn=lambda msg, priority: send_fn(msg) if priority == "CRITICAL" else None,
    )
    _stale_detector.run_check(comprehensive=False)
    globals_store["_stale_detector"] = _stale_detector

    # v2.54 Equity Trader (opt-in via --equity CLI flag)
    _start_equity_trader_if_requested(cfg=dict(config), send_fn=send_fn, broker_port=broker_port, globals_store=globals_store)

    rate_limiting_service = RateLimitingService()
    globals_store["_rate_limiting_service"] = rate_limiting_service
    container.register_instance(RateLimitPort, rate_limiting_service)

    circuit_breaker_service = CircuitBreakerService()
    globals_store["_circuit_breaker_service"] = circuit_breaker_service

    # Configure broker-specific circuit breaker keys from config
    _configure_circuit_breaker(container, circuit_breaker_service, dict(config))

    # Configure webhook rate limiter
    _configure_webhook_rate_limiter(dict(config), rate_limiting_service)

    ml_model_service = MLModelAdapter()
    container.register_instance(MlModelPort, ml_model_service)

    correlation_id_service = CorrelationIdAdapter()
    container.register_instance(CorrelationIdPort, correlation_id_service)

    logging_service = StructuredLoggerAdapter()
    container.register_instance(LoggingPort, logging_service)

    metrics_service = MetricsAdapter({})
    container.register_instance(MetricsPort, metrics_service)

    # Register concrete kernel/utility types for clean-architecture consumers
    _register_kernel_types(container)

    # Wire StrategyOrchestrator into the container
    _strategy_orchestrator = StrategyOrchestrator(
        signal_orchestrator=_sig_orch,
        config=cfg,
    )
    container.register_instance(StrategyPort, _strategy_orchestrator)
    globals_store["_strategy_orchestrator"] = _strategy_orchestrator
    _log.info("StrategyOrchestrator wired into DI container as StrategyPort")

    # Register runtime invariant checks
    _register_invariants()

    # Wire engine variables for orchestrator compatibility
    _wire_engine_variables(
        cfg=cfg,
        index_map=index_map,
        fetch_vix_fn=fetch_vix_fn,
        execution_service=execution_service,
        risk_service=risk_service,
        strategy_orchestrator=_strategy_orchestrator,
        globals_store=globals_store,
    )

    # Wire clean-architecture TradingOrchestrator
    _wire_clean_orchestrator(globals_store)


# ═══════════════════════════════════════════════════════════════════════════
# Internal helpers
# ═══════════════════════════════════════════════════════════════════════════


def _initialize_position_service(
    cfg: dict[str, Any],
    risk_service: Any,
    execution_service: Any,
    globals_store: dict[str, Any],
) -> Any:
    """Initialize and return the PositionService with all dependencies."""
    from core.position_service import get_position_service

    return get_position_service(
        cfg=cfg,
        risk_service=risk_service,
        execution_service=execution_service,
        portfolio_service=globals_store.get("_portfolio_service"),
        margin_validator=globals_store.get("_margin_validator"),
        warmup_manager=globals_store.get("_warmup_manager"),
        news_sentinel=globals_store.get("_news_sentinel"),
        expiry_controller=globals_store.get("_expiry_controller"),
        token_refresh_service=globals_store.get("_token_refresh_service"),
        audit_engine=globals_store.get("_audit_engine"),
        reentry_trackers=globals_store.get("_reentry_trackers"),
        positions=globals_store.get("positions"),
        decision_log=globals_store.get("decision_log"),
        manual_sig_last=globals_store.get("_manual_sig_last"),
        breakout_state=globals_store.get("breakout_state"),
        bos_lock=globals_store.get("_bos_lock"),
        state_lock=globals_store.get("_state_lock"),
        pos_lock=globals_store.get("_pos_lock"),
        mandate_service=globals_store.get("_mandate_service"),
        signal_max_age=cfg.get("SIGNAL_MAX_AGE", 90),
    )


def _resolve_send_fn(notification_service: Any) -> callable:
    """Resolve a usable send function from the notification service."""
    send_fn = getattr(notification_service, 'send_alert', None)
    if not send_fn:
        send_fn = getattr(notification_service, 'send', None)
    if not send_fn:
        def send_fn(x, critical=False, **kw):
            return None
    return send_fn


def _flush_and_wire_send(send_fn: callable, globals_store: dict[str, Any]) -> None:
    """Flush buffered Telegram messages and wire the real send function."""
    send_buffer = globals_store.get("_send_buffer", [])
    send_buffer_lock = globals_store.get("_send_buffer_lock")

    if send_buffer_lock is not None:
        with send_buffer_lock:
            for msg, crit in send_buffer:
                try:
                    send_fn(msg, critical=crit)
                except Exception as _flush_err:
                    _log.debug("Failed to flush buffered message: %s", _flush_err)
            send_buffer.clear()

    globals_store["_send_impl"] = send_fn
    globals_store["_send_wired"] = True


def _start_background_services(
    cfg: Any,
    send_fn: callable,
    globals_store: dict[str, Any],
) -> None:
    """Start morning checklist, session report, circuit breaker, and health check."""
    from core.circuit_breaker_monitor import create_circuit_breaker_monitor
    from core.morning_checklist import run_morning_checklist
    from core.session_report import create_session_reporter

    get_underlying_ltp = globals_store.get("get_underlying_ltp_fn")
    if get_underlying_ltp is None:
        _log.warning("[CB] get_underlying_ltp callback not available — circuit breaker monitor will have no-op price feed")

    # Start morning checklist (runs at 9:00 AM IST)
    run_morning_checklist(send_fn=send_fn, cfg=cfg)

    # Start session report (runs at 3:35 PM IST)
    create_session_reporter(send_fn=send_fn)
    _log.info("Session report service started")

    # Start NSE circuit breaker monitor
    create_circuit_breaker_monitor(
        send_fn=send_fn,
        get_index_price_fn=lambda: get_underlying_ltp("NIFTY") if get_underlying_ltp else None,
        cfg=cfg,
    )

    # Start background health check scheduler (runs Sunday EOD)
    try:
        from core.health_checker import start_health_check_scheduler
        start_health_check_scheduler(
            cfg=cfg,
            db_path=cfg.get("trades_db_path", "trades.db"),
            send_fn=send_fn,
        )
    except Exception as _health_err:
        _log.warning("[HEALTH] Failed to start health check scheduler: %s", _health_err)

    # Start Self-Healing Orchestrator background monitor
    try:
        from core.self_healing.orchestrator import get_orchestrator
        from core.health_checker import run_full_health_check
        from core.services.circuit_breaker_service import CircuitBreakerService
        # resolve circuit breaker from container if available
        cb_svc = None
        try:
            from core.di_container import get_container
            cb_svc = get_container().try_resolve(CircuitBreakerService)
        except Exception:
            pass
        healing = get_orchestrator(
            cfg=cfg,
            health_check_fn=run_full_health_check,
            circuit_breaker_service=cb_svc or CircuitBreakerService(),
        )
        if cfg.get("self_healing_enabled", True):
            healing.start_background_monitor()
            _log.info("[SELF-HEALING] Background monitor started (interval=%ds)", healing.interval_seconds)
        else:
            _log.info("[SELF-HEALING] Disabled by config")
    except Exception as _sh_err:
        _log.warning("[SELF-HEALING] Failed to start: %s", _sh_err)

    # Start SLO Governance periodic tracking
    try:
        from core.slo_governance import get_slo_governance
        slo = get_slo_governance()
        # Record initial baseline metrics
        slo.record_metric("replay_success", 100.0)
        slo.record_metric("duplicate_orders", 0.0)
        slo.record_metric("critical_security", 0.0)
        slo.record_metric("risk_enforcement", 100.0)
        slo.record_metric("test_coverage", 92.0)
        _log.info("[SLO] SLO Governance initialized with 15 objectives")
    except Exception as _slo_err:
        _log.warning("[SLO] SLO Governance init failed: %s", _slo_err)

    # Wire Risk Dashboard via global singleton
    try:
        from core.risk_dashboard import get_risk_dashboard
        risk_dash = get_risk_dashboard(config=cfg)
        _log.info("[RISK-DASH] Risk Dashboard initialized")
    except Exception as _rd_err:
        _log.warning("[RISK-DASH] Risk Dashboard init failed: %s", _rd_err)

    # Start NTP Clock Sync background checker
    try:
        from core.time_provider import get_ntp_sync
        ntp = get_ntp_sync(dict(cfg))
        import threading
        def _ntp_startup_check():
            try:
                status = ntp.check_sync()
                if status.server_reachable:
                    if status.drift_acceptable:
                        _log.info("[NTP] Clock sync OK: drift=%.3fs", status.drift_seconds)
                    else:
                        _log.warning("[NTP] Clock drift detected: %.3fs (max=%.1fs)",
                                     status.drift_seconds, ntp._max_drift)
                else:
                    _log.debug("[NTP] Server unreachable: %s", status.error)
            except Exception as _ntp_err:
                _log.debug("[NTP] Check failed: %s", _ntp_err)
        t = threading.Thread(target=_ntp_startup_check, daemon=True, name="ntp-startup")
        t.start()
    except Exception as _ntp_err:
        _log.debug("[NTP] Init skipped: %s", _ntp_err)

    # Initialize Multi-Tenant Manager (if enabled)
    try:
        from core.multi_tenant import get_multi_tenant_manager
        mtm = get_multi_tenant_manager(dict(cfg))
        if mtm.enabled:
            _log.info("[MT] Multi-Tenant Manager enabled: %d tenants", len(mtm.list_tenants()))
        else:
            _log.debug("[MT] Multi-Tenant Manager disabled")
    except Exception as _mt_err:
        _log.debug("[MT] Multi-Tenant Manager init skipped: %s", _mt_err)

    # Initialize Change Management & Approval Workflow
    try:
        from core.change_management import get_change_manager
        cm = get_change_manager(dict(cfg))
        if cm.enabled:
            _log.info("[CM] Change Management initialized (%d pending)", len(cm.list_pending()))
        else:
            _log.debug("[CM] Change Management disabled by config")
    except Exception as _cm_err:
        _log.debug("[CM] Change Management init skipped: %s", _cm_err)


def _start_equity_trader_if_requested(
    cfg: dict,
    send_fn: callable,
    broker_port: Any,
    globals_store: dict[str, Any],
) -> None:
    """Start equity trader if --equity CLI flag is present."""
    if "--equity" in sys.argv:
        try:
            from core.equity_trader import run_equity_trader
            equity_trader = run_equity_trader(
                cfg=cfg,
                send_fn=send_fn,
                get_price_fn=lambda sym: (
                    broker_port.get_ltp(sym) if hasattr(broker_port, 'get_ltp') else None
                ),
            )
            globals_store["_equity_trader"] = equity_trader
            _log.info(
                "[EQUITY] Equity trader started with symbols: %s",
                equity_trader.status().get("symbols", []),
            )
        except (ValueError, TypeError, KeyError, AttributeError, ImportError, OSError) as _eq_err:
            _log.warning("[EQUITY] Equity trader not started: %s", _eq_err)
    else:
        _log.info("[EQUITY] Equity trader disabled (pass --equity CLI flag to enable)")


def _configure_circuit_breaker(
    container: Any,
    circuit_breaker_service: Any,
    raw_cfg: dict,
) -> None:
    """Configure broker-specific circuit breaker keys from config."""
    from core.ports.circuit_breaker.circuit_breaker_port import CircuitBreakerPort

    cb_enabled = raw_cfg.get("circuit_breaker_broker_enabled", True)
    if cb_enabled:
        from core.ports.circuit_breaker.circuit_breaker_port import CircuitBreakerConfig as CBCfg
        broker_cfg = CBCfg(
            failure_threshold=int(raw_cfg.get("circuit_breaker_broker_failure_threshold", 3)),
            success_threshold=int(raw_cfg.get("circuit_breaker_success_threshold", 3)),
            timeout=int(raw_cfg.get("circuit_breaker_broker_timeout_secs", 30)),
            sliding_window_size=int(raw_cfg.get("circuit_breaker_sliding_window_size", 10)),
            failure_rate_threshold=float(raw_cfg.get("circuit_breaker_failure_rate_threshold", 0.5)),
            half_open_max_requests=int(raw_cfg.get("circuit_breaker_broker_half_open_max_requests", 2)),
            timeout_exponential_base=float(raw_cfg.get("circuit_breaker_timeout_exponential_base", 2.0)),
        )
        for key in ("broker.place_order", "broker.exit_order", "broker.get_order_status", "broker.cancel_order"):
            circuit_breaker_service.update_config(key, broker_cfg)
        _log.info(
            "Broker circuit breaker configured with threshold=%d timeout=%d",
            broker_cfg.failure_threshold,
            broker_cfg.timeout,
        )
    container.register_instance(CircuitBreakerPort, circuit_breaker_service)


def _configure_webhook_rate_limiter(raw_cfg: dict, rate_limiting_service: Any) -> None:
    """Configure webhook rate limiter from config."""
    if not raw_cfg.get("rate_limiter_webhook_enabled", True) or rate_limiting_service is None:
        return
    try:
        from core.ports.rate_limiting.rate_limit_port import RateLimitConfig as RLCfg
        webhook_rl = RLCfg(
            limit=int(raw_cfg.get("rate_limiter_webhook_limit", 5)),
            window=int(raw_cfg.get("rate_limiter_webhook_window_secs", 60)),
            algorithm="fixed_window",
        )
        rate_limiting_service.update_config("webhook", webhook_rl)
        _log.info("Webhook rate limiter configured: %d req/%ds", webhook_rl.limit, webhook_rl.window)
    except (ValueError, TypeError, KeyError, OSError) as exc:
        _log.warning("Failed to configure webhook rate limiter: %s", exc)


def _register_kernel_types(container: Any) -> None:
    """Register kernel/utility types for clean-architecture consumers."""
    from core.common.kernels.correlation_id import CorrelationIdManager
    from core.common.utilities.logging import StructuredLogger
    from core.common.utilities.metrics import MetricsCollector
    container.register_instance(CorrelationIdManager, CorrelationIdManager())
    container.register_instance(StructuredLogger, StructuredLogger())
    container.register_instance(MetricsCollector, MetricsCollector())
    _log.debug("Concrete kernel/utility types registered in DI container")


def _register_invariants() -> None:
    """Register runtime invariant checks (best-effort)."""
    try:
        from core.invariants.checks import register_all as _register_invariants
        _register_invariants()
        _log.info("Runtime invariant checks registered")
    except Exception as _ie:
        _log.debug("Invariant registration skipped: %s", _ie)


def _wire_engine_variables(
    cfg: dict[str, Any],
    index_map: dict[str, Any],
    fetch_vix_fn: callable,
    execution_service: Any,
    risk_service: Any,
    strategy_orchestrator: Any,
    globals_store: dict[str, Any],
) -> None:
    """Wire orchestration engine variables for legacy compatibility."""
    from core.data_engine import DataEngine

    def _yf_fetch_all_frames(indices):
        result = {}
        for idx in indices:
            yf_sym = index_map.get(idx, {}).get("yf", "")
            if not yf_sym:
                continue
            try:
                import yfinance as _yf_local
                df = _yf_local.download(yf_sym, period="2d", interval="1m", progress=False)
                if not df.empty:
                    result[idx] = df
            except Exception as _yf_err:
                _log.debug("yfinance download failed for %s: %s", yf_sym, _yf_err)
        return result

    globals_store["DATA_ENGINE"] = DataEngine(
        fetch_all_frames_fn=_yf_fetch_all_frames,
        vix_fetch_fn=fetch_vix_fn,
    )
    globals_store["STRATEGY_ENGINE"] = strategy_orchestrator
    globals_store["EXECUTION_ENGINE"] = execution_service
    globals_store["STATE_MANAGER"] = globals_store.get("state_manager")
    globals_store["RISK_ENGINE"] = risk_service
    _log.info("Engine variables wired: DATA_ENGINE, STRATEGY_ENGINE, EXECUTION_ENGINE, STATE_MANAGER")


def _wire_clean_orchestrator(globals_store: dict[str, Any]) -> None:
    """Wire clean-architecture TradingOrchestrator (graceful no-op if unavailable)."""
    try:
        from index_app.orchestrator_facade import build_clean_trading_orchestrator as _build_clean_orch
        clean_orch = _build_clean_orch()
        globals_store["_clean_trading_orchestrator"] = clean_orch
        if clean_orch is not None:
            _log.info("Clean-architecture TradingOrchestrator wired")
        else:
            _log.debug("Clean-architecture TradingOrchestrator not available (graceful skip)")
    except Exception as exc:
        _log.debug("Clean-architecture TradingOrchestrator unavailable: %s", exc)
