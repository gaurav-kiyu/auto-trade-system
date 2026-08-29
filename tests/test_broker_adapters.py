from __future__ import annotations

import datetime

from core.adapters.broker_adapters import (
    BrokerAdapter,
    BrokerRuntimeContext,
    PaperBrokerAdapter,
    broker_connection_secrets,
    build_broker_runtime_context,
    create_broker_adapter,
    create_broker_adapter_with_runtime_context,
    load_broker_factory_from_spec,
)


def _minimal_ctx(cfg: dict | None = None, log_fn=None, circuit_breaker=None) -> BrokerRuntimeContext:
    return build_broker_runtime_context(
        cfg=dict(cfg or {}),
        index_map={"NIFTY": {"nse": "NIFTY"}},
        now_fn=lambda: datetime.datetime.now(),
        log_fn=log_fn if log_fn is not None else lambda msg: None,
        send_fn=lambda msg, **kwargs: None,
        shutdown_is_set_fn=lambda: False,
        hard_halt_is_set_fn=lambda: False,
        sleep_fn=lambda secs: None,
        broker_wait_poll_sec=0.01,
        expiry_str_fn=lambda name: "25JAN",
        circuit_breaker=circuit_breaker,
    )


def _paper_factory(context: BrokerRuntimeContext) -> BrokerAdapter:
    _ = context
    return PaperBrokerAdapter()


def test_load_broker_factory_from_spec_invalid() -> None:
    assert load_broker_factory_from_spec("") is None
    assert load_broker_factory_from_spec("no_colon") is None


def test_load_broker_factory_from_spec_resolves_callable() -> None:
    fn = load_broker_factory_from_spec("tests.test_broker_adapters:_paper_factory")
    assert callable(fn)
    ctx = _minimal_ctx()
    adapter = fn(ctx)
    assert isinstance(adapter, PaperBrokerAdapter)


def test_custom_factory_overrides_kite_driver() -> None:
    ctx = _minimal_ctx({"BROKER_CUSTOM_FACTORY": "tests.test_broker_adapters:_paper_factory"})
    adapter = create_broker_adapter(
        driver="KITE",
        broker_api_enabled=True,
        paper_mode=False,
        manual_signals_only=False,
        context=ctx,
    )
    assert isinstance(adapter, PaperBrokerAdapter)


def test_create_broker_adapter_with_runtime_context_matches_manual_paper() -> None:
    adapter = create_broker_adapter_with_runtime_context(
        cfg={},
        index_map={"NIFTY": {"nse": "NIFTY"}},
        driver="KITE",
        broker_api_enabled=True,
        paper_mode=False,
        manual_signals_only=True,
        now_fn=lambda: datetime.datetime.now(),
        log_fn=lambda msg: None,
        send_fn=lambda msg: None,
        shutdown_is_set_fn=lambda: False,
        hard_halt_is_set_fn=lambda: False,
        sleep_fn=lambda secs: None,
        broker_wait_poll_sec=1.0,
        expiry_str_fn=lambda name: "",
    )
    assert adapter.place_order("NIFTY", "CALL", 1, 22500).startswith("PAPER_")


def test_build_broker_runtime_context_copies_cfg() -> None:
    cfg: dict = {"x": 1}
    ctx = build_broker_runtime_context(
        cfg=cfg,
        index_map={"N": {"nse": "N"}},
        now_fn=lambda: datetime.datetime.now(),
        log_fn=lambda msg: None,
        send_fn=lambda msg: None,
        shutdown_is_set_fn=lambda: False,
        hard_halt_is_set_fn=lambda: False,
        sleep_fn=lambda secs: None,
        broker_wait_poll_sec=1.0,
        expiry_str_fn=lambda name: "",
    )
    cfg["x"] = 2
    assert ctx.cfg["x"] == 1


def test_broker_connection_secrets_kite_prefers_broker_config() -> None:
    cfg = {
        "KITE_API_KEY": "",
        "KITE_ACCESS_TOKEN": "",
        "BROKER_CONFIG": {"api_key": "from-json", "access_token": "tok"},
    }
    sec = broker_connection_secrets(cfg, "KITE")
    assert sec["api_key"] == "from-json"
    assert sec["access_token"] == "tok"


def test_broker_connection_secrets_kite_falls_back_to_top_level() -> None:
    cfg = {"BROKER_CONFIG": {}, "KITE_API_KEY": "top", "KITE_ACCESS_TOKEN": "at"}
    sec = broker_connection_secrets(cfg, "KITE")
    assert sec["api_key"] == "top"
    assert sec["access_token"] == "at"


def test_broker_connection_secrets_angel_merges() -> None:
    cfg = {
        "BROKER_CONFIG": {"api_key": "a", "client_id": "c1"},
        "ANGEL_PASSWORD": "p",
        "ANGEL_TOTP_KEY": "t",
    }
    sec = broker_connection_secrets(cfg, "ANGEL")
    assert sec["api_key"] == "a"
    assert sec["client_id"] == "c1"
    assert sec["password"] == "p"
    assert sec["totp_key"] == "t"


def test_unknown_driver_without_custom_falls_back_to_paper() -> None:
    from unittest.mock import patch

    logs: list[str] = []

    def _log(msg: str) -> None:
        logs.append(msg)

    # Disable the master lockout AND satisfy the independent readiness gate
    # so this test actually exercises the unknown-driver fallback path, not
    # either of the two earlier short-circuits.
    ctx = _minimal_ctx({"live_trading_lockout_enabled": False}, log_fn=_log)
    with patch(
        "core.live_readiness_checker.check_live_readiness",
        return_value=_ready_report(),
    ):
        adapter = create_broker_adapter(
            driver="OTHER_BROKER",
            broker_api_enabled=True,
            paper_mode=False,
            manual_signals_only=False,
            context=ctx,
        )
    assert hasattr(adapter, '_port') and isinstance(adapter._port, PaperBrokerAdapter)
    assert any("Unknown BROKER_DRIVER" in m for m in logs)


# ── Master live-trading lockout ──────────────────────────────────────────

def test_lockout_enabled_by_default_forces_paper_for_real_driver() -> None:
    """live_trading_lockout_enabled defaults to True with no cfg key set at all."""
    logs: list[str] = []
    ctx = _minimal_ctx({}, log_fn=logs.append)
    adapter = create_broker_adapter(
        driver="KITE",
        broker_api_enabled=True,
        paper_mode=False,
        manual_signals_only=False,
        context=ctx,
    )
    assert isinstance(adapter, PaperBrokerAdapter)
    assert any("live_trading_lockout_enabled=True" in m for m in logs)


def test_lockout_does_not_block_explicit_paper_driver() -> None:
    """The lockout only intercepts real (non-paper) driver requests."""
    logs: list[str] = []
    ctx = _minimal_ctx({"BROKER_DRIVER": "PAPER"}, log_fn=logs.append)
    adapter = create_broker_adapter(
        driver="PAPER",
        broker_api_enabled=False,
        paper_mode=True,
        manual_signals_only=False,
        context=ctx,
    )
    assert isinstance(adapter, PaperBrokerAdapter)
    assert not any("live_trading_lockout_enabled=True" in m for m in logs)


# ── Automatic readiness gate (second, independent layer) ─────────────────

def test_readiness_gate_blocks_when_not_ready() -> None:
    from unittest.mock import patch

    fake_report = type("R", (), {"overall_ready": False, "summary": "NOT READY - test"})()
    ctx = _minimal_ctx({
        "live_trading_lockout_enabled": False,
        "BROKER_DRIVER": "KITE",
    })
    with patch(
        "core.live_readiness_checker.check_live_readiness",
        return_value=fake_report,
    ):
        adapter = create_broker_adapter(
            driver="KITE",
            broker_api_enabled=True,
            paper_mode=False,
            manual_signals_only=False,
            context=ctx,
        )
    assert isinstance(adapter, PaperBrokerAdapter)


def test_readiness_gate_fails_closed_on_error() -> None:
    """If the readiness check itself errors, stay in paper mode - never
    silently allow live trading just because the check couldn't run."""
    from unittest.mock import patch

    ctx = _minimal_ctx({
        "live_trading_lockout_enabled": False,
        "BROKER_DRIVER": "KITE",
    })
    with patch(
        "core.live_readiness_checker.check_live_readiness",
        side_effect=RuntimeError("db unavailable"),
    ):
        adapter = create_broker_adapter(
            driver="KITE",
            broker_api_enabled=True,
            paper_mode=False,
            manual_signals_only=False,
            context=ctx,
        )
    assert isinstance(adapter, PaperBrokerAdapter)


def _ready_report():
    return type("R", (), {"overall_ready": True, "summary": "READY - test"})()


def test_kite_dispatch_uses_context_factory_not_broken_direct_construction() -> None:
    """Regression: create_broker_adapter(driver="KITE", ...) used to construct
    KiteBrokerAdapter(context) directly, which raises AttributeError because
    KiteBrokerAdapter expects a _KiteContext (api_key/access_token/log_fn/...),
    not the full BrokerRuntimeContext. Never caught by any test because every
    real deployment path was already blocked by PAPER_MODE/BROKER_API_ENABLED
    defaults (and now live_trading_lockout_enabled) before reaching this line.
    """
    from unittest.mock import patch

    ctx = _minimal_ctx({
        "live_trading_lockout_enabled": False,
        "BROKER_DRIVER": "KITE",
        "BROKER_CONFIG": {"api_key": "x", "access_token": "y"},
    })
    sentinel = object()
    with patch(
        "core.live_readiness_checker.check_live_readiness",
        return_value=_ready_report(),
    ), patch(
        "infrastructure.adapters.brokers.kite.adapter.create_kite_adapter_from_context",
        return_value=sentinel,
    ) as mock_factory:
        adapter = create_broker_adapter(
            driver="KITE",
            broker_api_enabled=True,
            paper_mode=False,
            manual_signals_only=False,
            context=ctx,
        )
    mock_factory.assert_called_once_with(ctx)
    assert isinstance(adapter, BrokerAdapter)
    assert adapter._port is sentinel


def test_mstock_dispatch_uses_context_factory() -> None:
    from unittest.mock import patch

    ctx = _minimal_ctx({
        "live_trading_lockout_enabled": False,
        "BROKER_DRIVER": "MSTOCK",
        "BROKER_CONFIG": {"api_key": "x", "access_token": "y"},
    })
    sentinel = object()
    with patch(
        "core.live_readiness_checker.check_live_readiness",
        return_value=_ready_report(),
    ), patch(
        "infrastructure.adapters.brokers.mstock.adapter.create_mstock_adapter_from_context",
        return_value=sentinel,
    ) as mock_factory:
        adapter = create_broker_adapter(
            driver="MSTOCK",
            broker_api_enabled=True,
            paper_mode=False,
            manual_signals_only=False,
            context=ctx,
        )
    mock_factory.assert_called_once_with(ctx)
    assert isinstance(adapter, BrokerAdapter)
    assert adapter._port is sentinel


def test_readiness_gate_skipped_for_manual_mode() -> None:
    """manual_signals_only already forces paper before the readiness check
    would even run - confirm no crash/interaction between the two gates."""
    ctx = _minimal_ctx({"live_trading_lockout_enabled": False, "BROKER_DRIVER": "KITE"})
    adapter = create_broker_adapter(
        driver="KITE",
        broker_api_enabled=True,
        paper_mode=False,
        manual_signals_only=True,
        context=ctx,
    )
    assert isinstance(adapter, PaperBrokerAdapter)


def test_circuit_breaker_in_context_does_not_break_paper_adapter() -> None:
    """Passing a circuit breaker in BrokerRuntimeContext should not break PaperBrokerAdapter."""
    from core.services.circuit_breaker_service import CircuitBreakerService
    cb = CircuitBreakerService()
    ctx = _minimal_ctx({"BROKER_DRIVER": "PAPER"}, circuit_breaker=cb)
    adapter = create_broker_adapter(
        driver="PAPER",
        broker_api_enabled=False,
        paper_mode=True,
        manual_signals_only=False,
        context=ctx,
    )
    assert isinstance(adapter, BrokerAdapter)
    oid = adapter.place_order("NIFTY", "CALL", 75, 20000)
    assert oid is not None and oid.startswith("PAPER_")


# ── BrokerAdapter.get_quote() passthrough (core/live_option_quotes.py) ──────


def test_get_quote_raises_when_wrapped_paper_adapter_has_none() -> None:
    """PaperBrokerAdapter has no get_quote() - the wrapper must raise
    AttributeError (never silently fabricate a quote), which
    live_option_quotes.py's fail-open handling already expects."""
    adapter = BrokerAdapter(PaperBrokerAdapter())
    try:
        adapter.get_quote("NIFTY24DEC23500CE", exchange="NFO")
        raised = False
    except AttributeError:
        raised = True
    assert raised


def test_get_quote_delegates_to_real_port_with_exchange() -> None:
    from unittest.mock import MagicMock

    mock_port = MagicMock()
    mock_port.get_quote.return_value = "QUOTE_OBJ"
    adapter = BrokerAdapter(mock_port)
    result = adapter.get_quote("NIFTY24DEC23500CE", exchange="NFO")
    assert result == "QUOTE_OBJ"
    mock_port.get_quote.assert_called_once_with("NIFTY24DEC23500CE", exchange="NFO")


def test_get_quote_falls_back_when_port_rejects_exchange_kwarg() -> None:
    from unittest.mock import MagicMock

    mock_port = MagicMock()
    mock_port.get_quote.side_effect = [TypeError("unexpected keyword argument 'exchange'"), "QUOTE_OBJ"]
    adapter = BrokerAdapter(mock_port)
    result = adapter.get_quote("NIFTY")
    assert result == "QUOTE_OBJ"
    assert mock_port.get_quote.call_count == 2
