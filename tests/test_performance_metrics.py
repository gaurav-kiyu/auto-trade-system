"""Tests for core.performance_metrics - trade analytics and drawdown."""
from __future__ import annotations

from core.performance_metrics import (
    compute_drawdown,
    compute_metrics,
    generate_insights,
    load_trades,
    metrics_by_exit_reason,
    metrics_by_regime,
    metrics_by_score_bin,
)


class TestLoadTrades:
    def test_returns_empty_list_for_missing_db(self) -> None:
        result = load_trades(db_path="nonexistent_missing.db")
        assert result == []

    def test_returns_empty_list_for_empty_db(self, temp_db: str) -> None:
        result = load_trades(db_path=temp_db)
        assert result == []

    def test_fallback_to_execution_orders_empty(self, temp_db: str) -> None:
        """Fallback from trades to execution_orders table (empty table)."""
        import sqlite3
        conn = sqlite3.connect(temp_db)
        conn.execute("CREATE TABLE execution_orders (order_id TEXT, symbol TEXT, created_at TEXT)")
        conn.commit()
        conn.close()
        result = load_trades(db_path=temp_db)
        assert result == []

    def test_fallback_to_execution_orders_with_data(self, temp_db: str) -> None:
        """Fallback loads rows from execution_orders table."""
        import sqlite3
        conn = sqlite3.connect(temp_db)
        conn.execute("CREATE TABLE execution_orders (order_id TEXT, symbol TEXT, direction TEXT, quantity INT, status TEXT, created_at TEXT)")
        conn.execute("INSERT INTO execution_orders VALUES ('o1', 'NIFTY', 'CALL', 75, 'FILLED', '2026-06-20T10:00:00')")
        conn.execute("INSERT INTO execution_orders VALUES ('o2', 'BANKNIFTY', 'PUT', 50, 'FILLED', '2026-06-20T10:30:00')")
        conn.commit()
        conn.close()
        result = load_trades(db_path=temp_db)
        assert len(result) == 2
        assert result[0]["symbol"] in ("NIFTY", "BANKNIFTY")

    def test_legacy_trades_table_priority(self, temp_db: str) -> None:
        """trades table is tried first; execution_orders ignored if trades exists."""
        import sqlite3
        conn = sqlite3.connect(temp_db)
        conn.execute("CREATE TABLE trades (id INT, ts TEXT, index_name TEXT, direction TEXT, entry REAL, exit_price REAL, qty INT, gross_pnl REAL, net_pnl REAL, reason TEXT, mode TEXT)")
        conn.execute("INSERT INTO trades VALUES (1, '2026-06-20T10:00:00', 'NIFTY', 'CALL', 100, 150, 75, 3750, 3500, 'TP', 'PAPER')")
        # Also create execution_orders (should not be queried)
        conn.execute("CREATE TABLE execution_orders (order_id TEXT, symbol TEXT, created_at TEXT)")
        conn.execute("INSERT INTO execution_orders VALUES ('o1', 'IGNORED', '2026-06-20T10:00:00')")
        conn.commit()
        conn.close()
        result = load_trades(db_path=temp_db)
        assert len(result) == 1
        assert result[0]["index_name"] == "NIFTY"

    def test_fallback_with_mode_filter(self, temp_db: str) -> None:
        """Fallback works with mode filter (mode column exists on execution_orders)."""
        import sqlite3
        conn = sqlite3.connect(temp_db)
        conn.execute("CREATE TABLE execution_orders (order_id TEXT, symbol TEXT, direction TEXT, quantity INT, status TEXT, mode TEXT, created_at TEXT)")
        conn.execute("INSERT INTO execution_orders VALUES ('o1', 'NIFTY', 'CALL', 75, 'FILLED', 'PAPER', '2026-06-20T10:00:00')")
        conn.execute("INSERT INTO execution_orders VALUES ('o2', 'BANKNIFTY', 'PUT', 50, 'FILLED', 'LIVE', '2026-06-20T10:30:00')")
        conn.commit()
        conn.close()
        result = load_trades(db_path=temp_db, mode="PAPER")
        assert len(result) == 1
        assert result[0]["symbol"] == "NIFTY"

    def test_fallback_mode_filter_missing_column(self, temp_db: str) -> None:
        """Fallback with mode= returns [] gracefully when execution_orders lacks mode column."""
        import sqlite3
        conn = sqlite3.connect(temp_db)
        conn.execute("CREATE TABLE execution_orders (order_id TEXT, symbol TEXT, created_at TEXT)")
        conn.execute("INSERT INTO execution_orders VALUES ('o1', 'NIFTY', '2026-06-20T10:00:00')")
        conn.commit()
        conn.close()
        result = load_trades(db_path=temp_db, mode="PAPER")
        assert result == []

    def test_fallback_with_days_filter(self, temp_db: str) -> None:
        """Fallback works with days filter (uses created_at column)."""
        import datetime
        import sqlite3
        conn = sqlite3.connect(temp_db)
        conn.execute("CREATE TABLE execution_orders (order_id TEXT, symbol TEXT, created_at TEXT)")
        recent = (datetime.datetime.now() - datetime.timedelta(hours=1)).isoformat()
        old = (datetime.datetime.now() - datetime.timedelta(days=10)).isoformat()
        conn.execute("INSERT INTO execution_orders VALUES ('o1', 'RECENT', ?)", (recent,))
        conn.execute("INSERT INTO execution_orders VALUES ('o2', 'OLD', ?)", (old,))
        conn.commit()
        conn.close()
        result = load_trades(db_path=temp_db, days=3)
        assert len(result) == 1
        assert result[0]["symbol"] == "RECENT"


class TestComputeMetrics:
    def test_empty_trades(self) -> None:
        metrics = compute_metrics([])
        assert metrics["trades"] == 0

    def test_all_winners(self) -> None:
        trades = [
            {"net_pnl": 100, "gross_pnl": 120, "direction": "CALL", "reason": "take_profit"},
            {"net_pnl": 200, "gross_pnl": 220, "direction": "PUT", "reason": "take_profit"},
        ]
        metrics = compute_metrics(trades)
        assert metrics["trades"] == 2
        assert metrics["winners"] == 2
        assert metrics["win_rate"] == 100.0

    def test_mixed_results(self) -> None:
        trades = [
            {"net_pnl": 100, "gross_pnl": 120, "direction": "CALL", "reason": "take_profit"},
            {"net_pnl": -50, "gross_pnl": -50, "direction": "PUT", "reason": "stop_loss"},
            {"net_pnl": -10, "gross_pnl": -10, "direction": "CALL", "reason": "stop_loss"},
        ]
        metrics = compute_metrics(trades)
        assert metrics["trades"] == 3
        assert metrics["winners"] == 1
        assert metrics["losers"] == 2

    def test_sharpe_per_trade(self) -> None:
        trades = [{"net_pnl": 50 + i * 10} for i in range(10)]
        metrics = compute_metrics(trades)
        assert "sharpe_per_trade" in metrics

    def test_profit_factor(self) -> None:
        trades = [
            {"net_pnl": 300, "gross_pnl": 300},
            {"net_pnl": -100, "gross_pnl": -100},
        ]
        metrics = compute_metrics(trades)
        assert metrics["profit_factor"] == 3.0

    def test_profit_factor_as_inf_str(self) -> None:
        trades = [{"net_pnl": 100, "gross_pnl": 100}]
        metrics = compute_metrics(trades)
        assert metrics["profit_factor"] == "inf"

    def test_max_drawdown_in_metrics(self) -> None:
        trades = [{"net_pnl": 100}, {"net_pnl": -50}]
        metrics = compute_metrics(trades)
        assert "max_drawdown" in metrics


class TestComputeDrawdown:
    def test_no_drawdown(self) -> None:
        trades = [{"net_pnl": 100}, {"net_pnl": 100}]
        dd = compute_drawdown(trades)
        assert dd["max_drawdown"] == 0.0

    def test_with_drawdown(self) -> None:
        trades = [{"net_pnl": 1000}, {"net_pnl": -500}, {"net_pnl": -300}, {"net_pnl": 200}]
        dd = compute_drawdown(trades)
        assert dd["max_drawdown"] > 0.0

    def test_empty_trades(self) -> None:
        dd = compute_drawdown([])
        assert dd["max_drawdown"] == 0.0


class TestMetricsByRegime:
    def test_empty_trades(self) -> None:
        result = metrics_by_regime([])
        assert result == {}

    def test_groups_by_regime(self) -> None:
        trades = [
            {"net_pnl": 100, "regime": "TRENDING"},
            {"net_pnl": -50, "regime": "CHOPPY"},
            {"net_pnl": 200, "regime": "TRENDING"},
        ]
        result = metrics_by_regime(trades)
        assert "TRENDING" in result
        assert "CHOPPY" in result
        assert result["TRENDING"]["trades"] == 2
        assert result["CHOPPY"]["trades"] == 1
        assert "win_rate" in result["TRENDING"]
        assert "avg_pnl" in result["TRENDING"]
        assert "total_pnl" in result["TRENDING"]


class TestMetricsByScoreBin:
    def test_empty_trades(self) -> None:
        result = metrics_by_score_bin([])
        assert result == {}

    def test_bins_high_scores(self) -> None:
        trades = [{"net_pnl": 100, "score": 85}, {"net_pnl": 200, "score": 92}]
        result = metrics_by_score_bin(trades)
        assert any("80" in k for k in result)


class TestMetricsByExitReason:
    def test_empty_trades(self) -> None:
        result = metrics_by_exit_reason([])
        assert result == {}


class TestGenerateInsights:
    def test_empty_trades(self) -> None:
        insights = generate_insights([])
        assert isinstance(insights, list)

    def test_insights_are_strings(self) -> None:
        trades = [{"net_pnl": 100, "direction": "CALL", "reason": "take_profit"}]
        insights = generate_insights(trades)
        assert all(isinstance(i, str) for i in insights)
