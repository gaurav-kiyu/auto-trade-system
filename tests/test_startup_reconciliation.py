"""Tests for core.startup_reconciliation — startup broker reconciliation."""

from __future__ import annotations

from unittest.mock import MagicMock

from core.startup_reconciliation import (
    ReconciliationResult,
    StartupReconciler,
    run_startup_reconciliation,
)


# ── ReconciliationResult ─────────────────────────────────────────────────

def test_reconciliation_result_default() -> None:
    result = ReconciliationResult(
        is_clean=False, broker_reachable=False, auth_valid=False,
        orders_reconciled=False, positions_reconciled=False,
    )
    assert result.is_clean is False
    assert result.errors == []
    assert result.warnings == []


def test_reconciliation_result_clean() -> None:
    result = ReconciliationResult(
        is_clean=True, broker_reachable=True, auth_valid=True,
        orders_reconciled=True, positions_reconciled=True,
    )
    assert result.is_clean is True


def test_reconciliation_result_with_errors() -> None:
    result = ReconciliationResult(
        is_clean=False, broker_reachable=False, auth_valid=False,
        orders_reconciled=False, positions_reconciled=False,
        errors=["Broker not reachable", "Auth token invalid"],
    )
    assert len(result.errors) == 2
    assert "Broker not reachable" in result.errors


# ── StartupReconciler construction ───────────────────────────────────────

def test_reconciler_no_broker() -> None:
    reconciler = StartupReconciler()
    result = reconciler.reconcile()
    assert result.is_clean is False
    assert "No broker port configured" in result.warnings


def test_reconciler_set_broker_port() -> None:
    reconciler = StartupReconciler()
    broker = MagicMock()
    reconciler.set_broker_port(broker)
    assert reconciler._broker_port is broker


def test_reconciler_set_durable_store() -> None:
    reconciler = StartupReconciler()
    store = MagicMock()
    reconciler.set_durable_store(store)
    assert reconciler._durable_store is store


# ── Broker reachability ──────────────────────────────────────────────────

def test_reconciler_broker_reachable_healthy() -> None:
    broker = MagicMock()
    broker.health_check.return_value = {"status": "healthy"}
    reconciler = StartupReconciler(broker_port=broker)
    result = reconciler.reconcile()
    assert result.broker_reachable is True


def test_reconciler_broker_reachable_unhealthy() -> None:
    broker = MagicMock()
    broker.health_check.return_value = {"status": "down"}
    reconciler = StartupReconciler(broker_port=broker)
    result = reconciler.reconcile()
    # health_check returns status != "healthy" -> False
    assert result.broker_reachable is False
    assert "Broker not reachable" in result.errors


def test_reconciler_broker_no_health_check() -> None:
    broker = MagicMock(spec=[])
    reconciler = StartupReconciler(broker_port=broker)
    result = reconciler.reconcile()
    # No health_check method -> defaults to True
    assert result.broker_reachable is True


# ── Auth validation ──────────────────────────────────────────────────────

def test_reconciler_auth_valid() -> None:
    broker = MagicMock()
    broker.health_check.return_value = {"status": "healthy"}
    broker._ensure_token_fresh.return_value = True
    reconciler = StartupReconciler(broker_port=broker)
    result = reconciler.reconcile()
    assert result.auth_valid is True


def test_reconciler_auth_invalid() -> None:
    broker = MagicMock()
    broker.health_check.return_value = {"status": "healthy"}
    broker._ensure_token_fresh.return_value = False
    reconciler = StartupReconciler(broker_port=broker)
    result = reconciler.reconcile()
    assert result.auth_valid is False


# ── Order reconciliation ─────────────────────────────────────────────────

def test_reconciler_orders_no_pending() -> None:
    broker = MagicMock()
    broker.health_check.return_value = {"status": "healthy"}
    broker._ensure_token_fresh.return_value = True
    store = MagicMock()
    store.get_non_terminal_executions.return_value = []
    reconciler = StartupReconciler(broker_port=broker, durable_store=store)
    result = reconciler.reconcile()
    assert result.orders_reconciled is True


def test_reconciler_orders_no_durable_store() -> None:
    broker = MagicMock()
    broker.health_check.return_value = {"status": "healthy"}
    broker._ensure_token_fresh.return_value = True
    reconciler = StartupReconciler(broker_port=broker)
    result = reconciler.reconcile()
    assert result.orders_reconciled is True


# ── Position reconciliation ──────────────────────────────────────────────

def test_reconciler_positions_no_broker_get_positions() -> None:
    broker = MagicMock(spec=["health_check", "_ensure_token_fresh"])
    broker.health_check.return_value = {"status": "healthy"}
    broker._ensure_token_fresh.return_value = True
    reconciler = StartupReconciler(broker_port=broker)
    result = reconciler.reconcile()
    assert result.positions_reconciled is True  # No get_positions -> True


def test_reconciler_positions_with_broker() -> None:
    broker = MagicMock()
    broker.health_check.return_value = {"status": "healthy"}
    broker._ensure_token_fresh.return_value = True
    broker.get_positions.return_value = [{"symbol": "NIFTY", "qty": 1}]
    reconciler = StartupReconciler(broker_port=broker)
    result = reconciler.reconcile()
    assert result.positions_reconciled is True


# ── run_startup_reconciliation convenience ──────────────────────────────

def test_run_startup_reconciliation() -> None:
    broker = MagicMock()
    broker.health_check.return_value = {"status": "healthy"}
    broker._ensure_token_fresh.return_value = True
    result = run_startup_reconciliation(broker_port=broker)
    assert isinstance(result, ReconciliationResult)
    assert result.broker_reachable is True


def test_run_startup_reconciliation_no_broker() -> None:
    result = run_startup_reconciliation()
    assert result.is_clean is False
