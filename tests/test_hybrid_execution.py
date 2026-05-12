"""Unit tests for core.hybrid_execution (shared index + stock hybrid rules)."""

from __future__ import annotations

import pytest

from core.hybrid_execution import apply_execution_mode, normalize_execution_mode


@pytest.mark.confidence_gate
def test_normalize_aliases_and_fallback():
    assert normalize_execution_mode("manual") == "MANUAL"
    assert normalize_execution_mode("live") == "AUTO"
    assert normalize_execution_mode("paper_mode") == "PAPER"
    assert normalize_execution_mode("bogus") == "MANUAL"


@pytest.mark.confidence_gate
def test_apply_index_style_no_infer():
    cfg = {"EXECUTION_MODE": "AUTO", "MANUAL_SIGNALS_ONLY": True, "BROKER_API_ENABLED": False}
    apply_execution_mode(cfg, cli_paper=False, infer_blank_from_broker=False)
    assert cfg["EXECUTION_MODE"] == "AUTO"
    assert cfg["MANUAL_SIGNALS_ONLY"] is False
    assert cfg["BROKER_API_ENABLED"] is True


def test_apply_stock_blank_infers_from_broker():
    cfg: dict = {"EXECUTION_MODE": "", "MANUAL_SIGNALS_ONLY": False, "BROKER_API_ENABLED": True}
    apply_execution_mode(cfg, cli_paper=False, infer_blank_from_broker=True)
    assert cfg["EXECUTION_MODE"] == "AUTO"


def test_apply_stock_blank_infers_manual_when_broker_off():
    cfg: dict = {"EXECUTION_MODE": None, "MANUAL_SIGNALS_ONLY": False, "BROKER_API_ENABLED": False}
    apply_execution_mode(cfg, cli_paper=False, infer_blank_from_broker=True)
    assert cfg["EXECUTION_MODE"] == "MANUAL"
    assert cfg["MANUAL_SIGNALS_ONLY"] is True


@pytest.mark.confidence_gate
def test_cli_paper_wins():
    cfg = {"EXECUTION_MODE": "AUTO", "MANUAL_SIGNALS_ONLY": False, "BROKER_API_ENABLED": True}
    apply_execution_mode(cfg, cli_paper=True, infer_blank_from_broker=False)
    assert cfg["EXECUTION_MODE"] == "PAPER"
    assert cfg["BROKER_API_ENABLED"] is False


# ---------------------------------------------------------------------------
# MANUAL alias tests with infer_blank_from_broker=True (stock app path)
# ---------------------------------------------------------------------------

def test_manual_only_alias_infer_blank_broker_off():
    """MANUAL_ONLY with infer_blank=True and broker off → MANUAL + MSO=True."""
    cfg = {"EXECUTION_MODE": "MANUAL_ONLY", "MANUAL_SIGNALS_ONLY": False, "BROKER_API_ENABLED": False}
    apply_execution_mode(cfg, cli_paper=False, infer_blank_from_broker=True)
    assert cfg["EXECUTION_MODE"] == "MANUAL"
    assert cfg["MANUAL_SIGNALS_ONLY"] is True
    assert cfg["BROKER_API_ENABLED"] is False


def test_signals_only_alias_infer_blank_broker_off():
    """SIGNALS_ONLY with infer_blank=True and broker off → MANUAL + MSO=True."""
    cfg = {"EXECUTION_MODE": "SIGNALS_ONLY", "MANUAL_SIGNALS_ONLY": False, "BROKER_API_ENABLED": False}
    apply_execution_mode(cfg, cli_paper=False, infer_blank_from_broker=True)
    assert cfg["EXECUTION_MODE"] == "MANUAL"
    assert cfg["MANUAL_SIGNALS_ONLY"] is True
    assert cfg["BROKER_API_ENABLED"] is False


def test_manual_only_alias_infer_blank_broker_on():
    """MANUAL_ONLY overrides broker=True — alias wins; broker flag must be cleared."""
    cfg = {"EXECUTION_MODE": "MANUAL_ONLY", "MANUAL_SIGNALS_ONLY": False, "BROKER_API_ENABLED": True}
    apply_execution_mode(cfg, cli_paper=False, infer_blank_from_broker=True)
    # MANUAL_ONLY is NOT blank so infer step is skipped; normalize → MANUAL
    assert cfg["EXECUTION_MODE"] == "MANUAL"
    assert cfg["MANUAL_SIGNALS_ONLY"] is True
    assert cfg["BROKER_API_ENABLED"] is False


def test_signals_only_alias_infer_blank_broker_on():
    """SIGNALS_ONLY is not blank — infer step skipped; alias → MANUAL regardless of broker flag."""
    cfg = {"EXECUTION_MODE": "SIGNALS_ONLY", "MANUAL_SIGNALS_ONLY": False, "BROKER_API_ENABLED": True}
    apply_execution_mode(cfg, cli_paper=False, infer_blank_from_broker=True)
    assert cfg["EXECUTION_MODE"] == "MANUAL"
    assert cfg["MANUAL_SIGNALS_ONLY"] is True
    assert cfg["BROKER_API_ENABLED"] is False


def test_infer_blank_preserves_explicit_manual():
    """Explicit MANUAL (not an alias, not blank) with infer_blank → MANUAL unchanged."""
    cfg = {"EXECUTION_MODE": "MANUAL", "MANUAL_SIGNALS_ONLY": False, "BROKER_API_ENABLED": True}
    apply_execution_mode(cfg, cli_paper=False, infer_blank_from_broker=True)
    assert cfg["EXECUTION_MODE"] == "MANUAL"
    assert cfg["MANUAL_SIGNALS_ONLY"] is True
    assert cfg["BROKER_API_ENABLED"] is False


def test_infer_blank_with_none_and_broker_off_gives_manual():
    """None EXECUTION_MODE + infer_blank=True + broker off → MANUAL (already tested base; verify MSO)."""
    cfg = {"EXECUTION_MODE": None, "BROKER_API_ENABLED": False}
    apply_execution_mode(cfg, cli_paper=False, infer_blank_from_broker=True)
    assert cfg["EXECUTION_MODE"] == "MANUAL"
    assert cfg["MANUAL_SIGNALS_ONLY"] is True


def test_cli_paper_wins_over_manual_alias_with_infer():
    """cli_paper=True always forces PAPER regardless of MANUAL_ONLY alias or infer flag."""
    cfg = {"EXECUTION_MODE": "MANUAL_ONLY", "MANUAL_SIGNALS_ONLY": True, "BROKER_API_ENABLED": False}
    apply_execution_mode(cfg, cli_paper=True, infer_blank_from_broker=True)
    assert cfg["EXECUTION_MODE"] == "PAPER"
    assert cfg["MANUAL_SIGNALS_ONLY"] is False
    assert cfg["BROKER_API_ENABLED"] is False
