"""Tests for core/reconciliation_engine.py — local vs broker position comparison."""

from __future__ import annotations

from core.reconciliation_engine import (
    ReconciliationEngine,
    ReconciliationItem,
    ReconciliationReport,
)


def _broker_snapshot_empty() -> dict:
    return {}


def _broker_snapshot_nifty_qty_10() -> dict:
    return {"NIFTY": {"qty": 10, "avg_price": 19500.0}}


class TestInit:
    def test_default_tolerance(self) -> None:
        engine = ReconciliationEngine(broker_snapshot_fn=_broker_snapshot_empty)
        assert engine._price_tolerance_pct == 0.05

    def test_custom_tolerance(self) -> None:
        engine = ReconciliationEngine(
            broker_snapshot_fn=_broker_snapshot_empty,
            price_tolerance_pct=0.1,
        )
        assert engine._price_tolerance_pct == 0.1

    def test_qty_mismatch_halts_default(self) -> None:
        engine = ReconciliationEngine(broker_snapshot_fn=_broker_snapshot_empty)
        assert engine._qty_mismatch_halts is True

    def test_report_broker_only_default(self) -> None:
        engine = ReconciliationEngine(broker_snapshot_fn=_broker_snapshot_empty)
        assert engine._report_broker_only_positions is True


class TestNormalize:
    def test_dict_identity(self) -> None:
        engine = ReconciliationEngine(broker_snapshot_fn=_broker_snapshot_empty)
        result = engine._normalize({"NIFTY": {"qty": 10}})
        assert result == {"NIFTY": {"qty": 10}}

    def test_list_of_dicts(self) -> None:
        engine = ReconciliationEngine(broker_snapshot_fn=_broker_snapshot_empty)
        result = engine._normalize([
            {"tradingsymbol": "NIFTY", "qty": 10},
            {"tradingsymbol": "BANKNIFTY", "qty": 5},
        ])
        assert result["NIFTY"]["qty"] == 10
        assert result["BANKNIFTY"]["qty"] == 5

    def test_symbol_in_any_key(self) -> None:
        engine = ReconciliationEngine(broker_snapshot_fn=_broker_snapshot_empty)
        result = engine._normalize([{"symbol": "FINNIFTY", "qty": 3}])
        assert "FINNIFTY" in result

    def test_name_fallback(self) -> None:
        engine = ReconciliationEngine(broker_snapshot_fn=_broker_snapshot_empty)
        result = engine._normalize([{"name": "SOMESYMBOL", "qty": 7}])
        assert "SOMESYMBOL" in result

    def test_empty_symbol_skipped(self) -> None:
        engine = ReconciliationEngine(broker_snapshot_fn=_broker_snapshot_empty)
        result = engine._normalize([{"qty": 7}])  # no symbol key
        assert result == {}

    def test_empty_list(self) -> None:
        engine = ReconciliationEngine(broker_snapshot_fn=_broker_snapshot_empty)
        assert engine._normalize([]) == {}


class TestReconcilePositions:
    def test_empty_positions_ok(self) -> None:
        engine = ReconciliationEngine(broker_snapshot_fn=_broker_snapshot_empty)
        report = engine.reconcile_positions({})
        assert report.ok is True
        assert report.mismatches == 0
        assert len(report.items) == 0

    def test_matching_positions_ok(self) -> None:
        engine = ReconciliationEngine(
            broker_snapshot_fn=_broker_snapshot_nifty_qty_10,
        )
        report = engine.reconcile_positions({
            "NIFTY": {"qty": 10, "entry": 19500.0},
        })
        assert report.ok is True
        assert report.mismatches == 0
        assert len(report.items) == 1
        assert report.items[0].ok is True

    def test_qty_mismatch_detected(self) -> None:
        engine = ReconciliationEngine(
            broker_snapshot_fn=_broker_snapshot_nifty_qty_10,
        )
        report = engine.reconcile_positions({
            "NIFTY": {"qty": 5, "entry": 19500.0},
        })
        assert report.ok is False
        assert report.mismatches == 1
        assert report.items[0].has_qty_mismatch is True

    def test_price_mismatch_detected(self) -> None:
        engine = ReconciliationEngine(
            broker_snapshot_fn=lambda: {"NIFTY": {"qty": 10, "avg_price": 20000.0}},
            price_tolerance_pct=0.01,  # 1%
        )
        report = engine.reconcile_positions({
            "NIFTY": {"qty": 10, "entry": 19500.0},
        })
        assert report.ok is False
        assert report.mismatches == 1
        assert report.items[0].ok is False

    def test_price_tolerance_within_bounds(self) -> None:
        engine = ReconciliationEngine(
            broker_snapshot_fn=lambda: {"NIFTY": {"qty": 10, "avg_price": 19550.0}},
            price_tolerance_pct=0.05,  # 5% → 19500 ± 975
        )
        report = engine.reconcile_positions({
            "NIFTY": {"qty": 10, "entry": 19500.0},
        })
        assert report.ok is True  # 19550 is within 5% of 19500

    def test_broker_only_position_reported(self) -> None:
        engine = ReconciliationEngine(
            broker_snapshot_fn=_broker_snapshot_nifty_qty_10,
        )
        report = engine.reconcile_positions({
            "BANKNIFTY": {"qty": 5, "entry": 45000.0},
        })
        assert report.ok is False
        # Should have NIFTY as broker-only position
        nifty_items = [i for i in report.items if i.symbol == "NIFTY"]
        assert len(nifty_items) == 1
        assert nifty_items[0].local_qty == 0
        assert nifty_items[0].broker_qty == 10
        assert "broker-only" in nifty_items[0].note

    def test_broker_only_zero_qty_skipped(self) -> None:
        engine = ReconciliationEngine(
            broker_snapshot_fn=lambda: {"NIFTY": {"qty": 0}},
        )
        report = engine.reconcile_positions({})
        assert report.ok is True  # zero qty not reported as broker-only

    def test_qty_mismatch_halts_disabled_allows_report_ok(self) -> None:
        engine = ReconciliationEngine(
            broker_snapshot_fn=_broker_snapshot_nifty_qty_10,
            qty_mismatch_halts=False,
        )
        report = engine.reconcile_positions({
            "NIFTY": {"qty": 5, "entry": 19500.0},
        })
        # With qty_mismatch_halts=False and only qty mismatch → report ok
        assert report.ok is True
        assert report.mismatches == 1

    def test_report_broker_only_disabled(self) -> None:
        engine = ReconciliationEngine(
            broker_snapshot_fn=_broker_snapshot_nifty_qty_10,
            report_broker_only_positions=False,
        )
        report = engine.reconcile_positions({})
        assert report.ok is True  # no broker-only positions reported
        assert len(report.items) == 0

    def test_multiple_symbols(self) -> None:
        def broker_snapshot() -> dict:
            return {
                "NIFTY": {"qty": 10, "avg_price": 19500.0},
                "BANKNIFTY": {"qty": 5, "avg_price": 45000.0},
            }
        engine = ReconciliationEngine(broker_snapshot_fn=broker_snapshot)
        report = engine.reconcile_positions({
            "NIFTY": {"qty": 10, "entry": 19500.0},
            "BANKNIFTY": {"qty": 5, "entry": 45000.0},
        })
        assert report.ok is True
        assert len(report.items) == 2

    def test_zero_local_qty_handled(self) -> None:
        engine = ReconciliationEngine(
            broker_snapshot_fn=lambda: {"NIFTY": {"quantity": 10}},
        )
        report = engine.reconcile_positions({"NIFTY": {"qty": 0, "entry": 0.0}})
        assert report.ok is False
        assert report.items[0].local_qty == 0


class TestReconciliationItem:
    def test_dataclass(self) -> None:
        item = ReconciliationItem(
            symbol="NIFTY", ok=True, local_qty=10, broker_qty=10,
            local_price=19500.0, broker_price=19500.0,
        )
        assert item.symbol == "NIFTY"
        assert item.ok is True
        assert item.has_qty_mismatch is False


class TestReconciliationReport:
    def test_dataclass(self) -> None:
        items = [ReconciliationItem(
            symbol="NIFTY", ok=True, local_qty=10, broker_qty=10,
            local_price=19500.0, broker_price=19500.0,
        )]
        report = ReconciliationReport(ok=True, items=items, mismatches=0)
        assert report.ok is True
        assert len(report.items) == 1
        assert report.mismatches == 0
