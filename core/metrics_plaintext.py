"""Plain-text /metrics body shared by stock and index trader processes.


__all__ = [
    "format_bot_metrics_plaintext",
]

Keeping one formatter avoids silent drift when operators scrape both bots
or when new observability fields are added.
"""

__all__ = [
    "format_bot_metrics_plaintext",
]


def format_bot_metrics_plaintext(
    *,
    capital: float | int,
    net_daily_pnl: float | int,
    trade_count: int,
    open_positions: int,
    consecutive_losses: int,
    hard_halt: int,
    circuit_breaker: object,
    config_hash: str,
    config_reload_status: str,
    version: str,
    config_reload_count: int,
    last_soft_reload_ts: float,
    perf: str,
) -> str:
    return (
        f"capital {capital}\nnet_daily_pnl {net_daily_pnl}\ntrade_count {trade_count}\n"
        f"open_positions {open_positions}\nconsecutive_losses {consecutive_losses}\n"
        f"hard_halt {hard_halt}\ncircuit_breaker {circuit_breaker}\n"
        f"config_hash {config_hash}\nconfig_reload_status {config_reload_status}\nversion {version}\n"
        f"config_reload_count {config_reload_count}\nlast_soft_reload_ts {last_soft_reload_ts}\n"
        f"perf {perf}\n"
    )
