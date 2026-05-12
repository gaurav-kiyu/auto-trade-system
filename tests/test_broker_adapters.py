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


def _minimal_ctx(cfg: dict | None = None, log_fn=None) -> BrokerRuntimeContext:
    return build_broker_runtime_context(
        cfg=dict(cfg or {}),
        index_map={"NIFTY": {"nse": "NIFTY"}},
        now_fn=lambda: datetime.datetime.now(),
        log_fn=log_fn if log_fn is not None else lambda msg: None,
        send_fn=lambda msg: None,
        shutdown_is_set_fn=lambda: False,
        hard_halt_is_set_fn=lambda: False,
        sleep_fn=lambda secs: None,
        broker_wait_poll_sec=0.01,
        expiry_str_fn=lambda name: "25JAN",
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
    logs: list[str] = []

    def _log(msg: str) -> None:
        logs.append(msg)

    ctx = _minimal_ctx({}, log_fn=_log)
    adapter = create_broker_adapter(
        driver="OTHER_BROKER",
        broker_api_enabled=True,
        paper_mode=False,
        manual_signals_only=False,
        context=ctx,
    )
    assert isinstance(adapter, PaperBrokerAdapter)
    assert any("Unknown BROKER_DRIVER" in m for m in logs)
