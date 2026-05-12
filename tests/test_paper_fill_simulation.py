"""
Tests for Phase 2 — Realistic Paper Fill Simulation.

Covers:
  - PaperFill dataclass structure
  - PaperBrokerAdapter: backward-compatible default construction
  - PaperBrokerAdapter: fill price simulation with slippage
  - PaperBrokerAdapter: liquidity filter (OI / volume threshold)
  - PaperBrokerAdapter: configure_paper_simulation() post-construction wiring
  - PaperBrokerAdapter: get_fill_price() / get_filled_quantity() return values
  - PaperBrokerAdapter: paper_fill_stats() EOD summary
  - trade_journal: slippage_drift column present after _init_db()
"""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from typing import Any

import pytest

from core.adapters.broker_adapters import PaperBrokerAdapter, PaperFill


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_price_getter(price: float):
    """Returns a price_getter that always returns `price`."""
    def getter(name: str, direction: str, strike: int) -> float:
        return price
    return getter


def _make_oi_getter(oi: int, volume: int):
    """Returns an oi_getter that always returns (oi, volume)."""
    def getter(name: str, direction: str, strike: int):
        return oi, volume
    return getter


# ── Class 1: Default construction (backward compatibility) ────────────────────


class TestPaperBrokerAdapterDefaults:
    def test_place_order_returns_paper_prefix(self):
        adapter = PaperBrokerAdapter()
        oid = adapter.place_order("NIFTY", "CALL", 50, 22500)
        assert oid.startswith("PAPER_")

    def test_exit_order_returns_paper_exit_prefix(self):
        adapter = PaperBrokerAdapter()
        oid = adapter.exit_order("NIFTY", "PUT", 50, 22000)
        assert oid.startswith("PAPER_EXIT_")

    def test_order_status_always_complete(self):
        adapter = PaperBrokerAdapter()
        assert adapter.get_order_status("any_id") == "COMPLETE"

    def test_wait_for_fill_always_true(self):
        adapter = PaperBrokerAdapter()
        assert adapter.wait_for_fill("any_id") is True

    def test_get_fill_price_none_when_no_price_getter(self):
        """Without price_getter, fill price is unknown (0.0 stored → None returned)."""
        adapter = PaperBrokerAdapter()
        oid = adapter.place_order("NIFTY", "CALL", 50, 22500)
        assert adapter.get_fill_price(oid) is None

    def test_get_filled_quantity_full_when_no_oi_getter(self):
        """Without oi_getter, no liquidity check → full quantity returned."""
        adapter = PaperBrokerAdapter()
        oid = adapter.place_order("NIFTY", "CALL", 50, 22500)
        assert adapter.get_filled_quantity(oid) == 50

    def test_paper_fill_record_stored(self):
        adapter = PaperBrokerAdapter()
        oid = adapter.place_order("NIFTY", "CALL", 50, 22500)
        rec = adapter.get_paper_fill(oid)
        assert isinstance(rec, PaperFill)
        assert rec.name == "NIFTY"
        assert rec.direction == "CALL"
        assert rec.strike == 22500
        assert rec.qty == 50
        assert rec.is_entry is True

    def test_exit_fill_is_marked_not_entry(self):
        adapter = PaperBrokerAdapter()
        oid = adapter.exit_order("BANKNIFTY", "PUT", 25, 48000)
        rec = adapter.get_paper_fill(oid)
        assert rec is not None
        assert rec.is_entry is False


# ── Class 2: Slippage simulation ──────────────────────────────────────────────


class TestSlippageSimulation:
    def test_entry_fill_above_mid(self):
        """Entry: buyer pays mid × (1 + slippage_pct/100)."""
        mid = 100.0
        adapter = PaperBrokerAdapter(
            price_getter=_make_price_getter(mid),
            cfg={"paper_slippage_pct": 0.5},
        )
        oid = adapter.place_order("NIFTY", "CALL", 50, 22500)
        rec = adapter.get_paper_fill(oid)
        assert rec is not None
        assert rec.mid_price == 100.0
        assert abs(rec.fill_price - 100.5) < 0.01  # mid × 1.005
        assert rec.slippage_amt > 0

    def test_exit_fill_below_mid(self):
        """Exit: seller gets mid × (1 - slippage_pct/100)."""
        mid = 100.0
        adapter = PaperBrokerAdapter(
            price_getter=_make_price_getter(mid),
            cfg={"paper_slippage_pct": 0.5},
        )
        oid = adapter.exit_order("NIFTY", "CALL", 50, 22500)
        rec = adapter.get_paper_fill(oid)
        assert rec is not None
        assert abs(rec.fill_price - 99.5) < 0.01  # mid × 0.995
        assert rec.slippage_amt < 0  # exit: fill < mid

    def test_get_fill_price_returns_simulated_price(self):
        mid = 150.0
        adapter = PaperBrokerAdapter(
            price_getter=_make_price_getter(mid),
            cfg={"paper_slippage_pct": 1.0},
        )
        oid = adapter.place_order("NIFTY", "CALL", 50, 22500)
        fill = adapter.get_fill_price(oid)
        assert fill is not None
        assert abs(fill - 151.5) < 0.01  # 150 × 1.01

    def test_zero_price_returns_none(self):
        adapter = PaperBrokerAdapter(price_getter=_make_price_getter(0.0))
        oid = adapter.place_order("NIFTY", "CALL", 50, 22500)
        assert adapter.get_fill_price(oid) is None

    def test_custom_slippage_pct(self):
        mid = 200.0
        adapter = PaperBrokerAdapter(
            price_getter=_make_price_getter(mid),
            cfg={"paper_slippage_pct": 2.0},
        )
        oid = adapter.place_order("NIFTY", "PUT", 50, 22000)
        rec = adapter.get_paper_fill(oid)
        assert rec is not None
        assert abs(rec.fill_price - 204.0) < 0.01  # 200 × 1.02

    def test_default_slippage_pct_is_05(self):
        mid = 100.0
        adapter = PaperBrokerAdapter(price_getter=_make_price_getter(mid))
        oid = adapter.place_order("NIFTY", "CALL", 50, 22500)
        rec = adapter.get_paper_fill(oid)
        assert rec is not None
        assert abs(rec.fill_price - 100.5) < 0.01


# ── Class 3: Liquidity filter ─────────────────────────────────────────────────


class TestLiquidityFilter:
    def test_liquid_option_fills_normally(self):
        adapter = PaperBrokerAdapter(
            oi_getter=_make_oi_getter(oi=1000, volume=500),
            cfg={"min_oi_threshold": 500, "min_volume_threshold": 100},
        )
        oid = adapter.place_order("NIFTY", "CALL", 50, 22500)
        rec = adapter.get_paper_fill(oid)
        assert rec is not None
        assert rec.liquidity_skipped is False
        assert rec.oi == 1000
        assert rec.volume == 500
        assert adapter.get_filled_quantity(oid) == 50

    def test_low_oi_skips_fill(self):
        adapter = PaperBrokerAdapter(
            oi_getter=_make_oi_getter(oi=100, volume=500),
            cfg={"min_oi_threshold": 500, "min_volume_threshold": 100},
        )
        oid = adapter.place_order("NIFTY", "CALL", 50, 22500)
        rec = adapter.get_paper_fill(oid)
        assert rec is not None
        assert rec.liquidity_skipped is True
        assert adapter.get_filled_quantity(oid) == 0

    def test_low_volume_skips_fill(self):
        adapter = PaperBrokerAdapter(
            oi_getter=_make_oi_getter(oi=1000, volume=50),
            cfg={"min_oi_threshold": 500, "min_volume_threshold": 100},
        )
        oid = adapter.place_order("NIFTY", "CALL", 50, 22500)
        rec = adapter.get_paper_fill(oid)
        assert rec is not None
        assert rec.liquidity_skipped is True
        assert adapter.get_filled_quantity(oid) == 0

    def test_no_oi_getter_means_no_filter(self):
        adapter = PaperBrokerAdapter()
        oid = adapter.place_order("NIFTY", "CALL", 50, 22500)
        assert adapter.get_filled_quantity(oid) == 50

    def test_oi_getter_returning_none_passes(self):
        """If oi_getter returns None (chain unavailable), do not block the fill."""
        adapter = PaperBrokerAdapter(oi_getter=lambda n, d, s: None)
        oid = adapter.place_order("NIFTY", "CALL", 50, 22500)
        rec = adapter.get_paper_fill(oid)
        assert rec is not None
        assert rec.liquidity_skipped is False

    def test_oi_getter_exception_passes(self):
        def bad_getter(n, d, s):
            raise RuntimeError("chain down")

        adapter = PaperBrokerAdapter(oi_getter=bad_getter)
        oid = adapter.place_order("NIFTY", "CALL", 50, 22500)
        assert adapter.get_filled_quantity(oid) == 50


# ── Class 4: configure_paper_simulation ──────────────────────────────────────


class TestConfigurePaperSimulation:
    def test_configure_adds_price_getter(self):
        adapter = PaperBrokerAdapter()
        adapter.configure_paper_simulation(price_getter=_make_price_getter(80.0))
        oid = adapter.place_order("NIFTY", "CALL", 50, 22500)
        assert adapter.get_fill_price(oid) is not None

    def test_configure_adds_oi_getter_blocking(self):
        adapter = PaperBrokerAdapter()
        adapter.configure_paper_simulation(
            oi_getter=_make_oi_getter(oi=10, volume=5),
            cfg={"min_oi_threshold": 500, "min_volume_threshold": 100},
        )
        oid = adapter.place_order("NIFTY", "CALL", 50, 22500)
        assert adapter.get_filled_quantity(oid) == 0

    def test_configure_updates_cfg(self):
        adapter = PaperBrokerAdapter(
            price_getter=_make_price_getter(100.0),
            cfg={"paper_slippage_pct": 0.5},
        )
        adapter.configure_paper_simulation(cfg={"paper_slippage_pct": 2.0})
        oid = adapter.place_order("NIFTY", "CALL", 50, 22500)
        rec = adapter.get_paper_fill(oid)
        assert rec is not None
        assert abs(rec.fill_price - 102.0) < 0.01  # 100 × 1.02

    def test_configure_none_args_no_op(self):
        """Passing None for optional args should not clear existing getters."""
        adapter = PaperBrokerAdapter(price_getter=_make_price_getter(100.0))
        adapter.configure_paper_simulation(price_getter=None)
        # Price getter is not cleared — configure_paper_simulation skips None
        oid = adapter.place_order("NIFTY", "CALL", 50, 22500)
        assert adapter.get_fill_price(oid) is not None


# ── Class 5: paper_fill_stats ─────────────────────────────────────────────────


class TestPaperFillStats:
    def test_empty_stats(self):
        adapter = PaperBrokerAdapter()
        stats = adapter.paper_fill_stats()
        assert stats["fills"] == 0
        assert stats["avg_slippage_pct"] == 0.0
        assert stats["liquidity_skipped"] == 0

    def test_stats_after_fills(self):
        adapter = PaperBrokerAdapter(
            price_getter=_make_price_getter(100.0),
            oi_getter=_make_oi_getter(oi=1000, volume=500),
            cfg={"paper_slippage_pct": 0.5, "min_oi_threshold": 500, "min_volume_threshold": 100},
        )
        adapter.place_order("NIFTY", "CALL", 50, 22500)
        adapter.place_order("NIFTY", "PUT", 50, 22000)
        stats = adapter.paper_fill_stats()
        assert stats["fills"] == 2
        assert stats["avg_slippage_pct"] > 0
        assert stats["liquidity_skipped"] == 0

    def test_stats_counts_skipped(self):
        adapter = PaperBrokerAdapter(
            oi_getter=_make_oi_getter(oi=10, volume=5),
            cfg={"min_oi_threshold": 500, "min_volume_threshold": 100},
        )
        adapter.place_order("NIFTY", "CALL", 50, 22500)
        adapter.place_order("NIFTY", "PUT", 50, 22000)
        stats = adapter.paper_fill_stats()
        assert stats["liquidity_skipped"] == 2


# ── Class 6: Trade journal migration ─────────────────────────────────────────


class TestTradeJournalMigration:
    def test_slippage_drift_column_exists_on_fresh_db(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        from core.trade_journal import TradeJournal
        j = TradeJournal(db_path)
        conn = sqlite3.connect(db_path)
        cursor = conn.execute("PRAGMA table_info(journal)")
        columns = {row[1] for row in cursor.fetchall()}
        conn.close()
        assert "slippage_drift" in columns

    def test_slippage_drift_column_added_to_existing_db(self):
        """Simulate a pre-Phase2 DB (has journal table but no slippage_drift) — migration adds it."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        # Create a realistic pre-Phase2 journal table (has tier but no slippage_drift)
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE journal (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id         TEXT,
                symbol           TEXT,
                direction        TEXT,
                entry_ts         TEXT,
                fill_ts          TEXT,
                score            INTEGER,
                tier             TEXT,
                confidence       REAL,
                regime           TEXT,
                quality_score    REAL,
                soft_blocks      TEXT,
                expected_entry   REAL,
                expected_sl      REAL,
                expected_tp      REAL,
                expected_pnl     REAL,
                expected_rr      REAL,
                actual_entry     REAL,
                actual_exit      REAL,
                actual_pnl       REAL,
                exit_reason      TEXT,
                entry_slippage   REAL,
                exit_slippage    REAL,
                total_slippage   REAL,
                execution_delay_ms INTEGER,
                lots             INTEGER,
                position_pct     REAL,
                lot_size         INTEGER,
                mode             TEXT,
                is_winner        INTEGER,
                gross_pnl        REAL,
                net_pnl          REAL,
                pct_pnl          REAL,
                bars_held        INTEGER,
                rr_achieved      REAL,
                score_vs_outcome REAL,
                pnl_vs_expected  REAL,
                quality_accurate INTEGER,
                created_at       TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS ix_journal_symbol ON journal(symbol)")
        conn.execute("CREATE INDEX IF NOT EXISTS ix_journal_tier ON journal(tier)")
        conn.execute("CREATE INDEX IF NOT EXISTS ix_journal_entry_ts ON journal(entry_ts)")
        conn.execute("CREATE INDEX IF NOT EXISTS ix_journal_mode ON journal(mode)")
        conn.execute("CREATE INDEX IF NOT EXISTS ix_journal_created_at ON journal(created_at)")
        conn.commit()
        conn.close()
        # TradeJournal._init_db() migration must add slippage_drift
        from core.trade_journal import TradeJournal
        j = TradeJournal(db_path)
        conn = sqlite3.connect(db_path)
        cursor = conn.execute("PRAGMA table_info(journal)")
        columns = {row[1] for row in cursor.fetchall()}
        conn.close()
        assert "slippage_drift" in columns
