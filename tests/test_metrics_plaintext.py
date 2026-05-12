from core.metrics_plaintext import format_bot_metrics_plaintext


def test_format_bot_metrics_plaintext_stable_shape():
    s = format_bot_metrics_plaintext(
        capital=100_000,
        net_daily_pnl=-500,
        trade_count=3,
        open_positions=1,
        consecutive_losses=0,
        hard_halt=0,
        circuit_breaker="OK",
        config_hash="deadbeef0000",
        config_reload_status="Config stable",
        version="9.9.9-test",
        config_reload_count=2,
        last_soft_reload_ts=1713520800.5,
        perf="stages=1",
    )
    assert s.endswith("perf stages=1\n")
    lines = s.strip().split("\n")
    assert lines == [
        "capital 100000",
        "net_daily_pnl -500",
        "trade_count 3",
        "open_positions 1",
        "consecutive_losses 0",
        "hard_halt 0",
        "circuit_breaker OK",
        "config_hash deadbeef0000",
        "config_reload_status Config stable",
        "version 9.9.9-test",
        "config_reload_count 2",
        "last_soft_reload_ts 1713520800.5",
        "perf stages=1",
    ]
