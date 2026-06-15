"""Tests for MorningChecklist — pre-session trading readiness checks."""

from __future__ import annotations

from unittest.mock import MagicMock

from core.morning_checklist import MorningChecklist, run_morning_checklist


class TestMorningChecklist:
    """MorningChecklist — pre-session trading readiness."""

    def test_default_init(self):
        checklist = MorningChecklist()
        assert checklist._running is False
        assert checklist._last_run_date is None

    def test_start_sets_running_flag(self):
        checklist = MorningChecklist()
        checklist.start()
        assert checklist._running is True
        checklist.stop()

    def test_stop_clears_running(self):
        checklist = MorningChecklist()
        checklist.start()
        checklist.stop()
        assert checklist._running is False

    def test_set_broker_port(self):
        checklist = MorningChecklist()
        bp = MagicMock()
        checklist.set_broker_port(bp)
        assert checklist._broker_port is bp

    def test_set_data_engine(self):
        checklist = MorningChecklist()
        de = MagicMock()
        checklist.set_data_engine(de)
        assert checklist._data_engine is de

    # ── Individual check methods ────────────────────────────────

    def test_check_token_validity_no_broker(self):
        checklist = MorningChecklist()
        ok, msg = checklist._check_token_validity()
        assert ok is True
        assert "no broker" in msg.lower()

    def test_check_token_validity_with_valid_broker(self):
        bp = MagicMock()
        bp._ensure_token_fresh.return_value = True
        checklist = MorningChecklist(broker_port=bp)
        ok, msg = checklist._check_token_validity()
        assert ok is True
        assert "valid" in msg.lower() or "fresh" in msg.lower()

    def test_check_token_validity_with_expired_broker(self):
        bp = MagicMock()
        bp._ensure_token_fresh.return_value = False
        checklist = MorningChecklist(broker_port=bp)
        ok, msg = checklist._check_token_validity()
        assert ok is False

    def test_check_broker_reachable_no_broker(self):
        checklist = MorningChecklist()
        ok, msg = checklist._check_broker_reachable()
        assert ok is True
        assert "paper" in msg.lower()

    def test_check_broker_reachable_healthy(self):
        bp = MagicMock()
        bp.health_check.return_value = {"status": "healthy"}
        checklist = MorningChecklist(broker_port=bp)
        ok, _ = checklist._check_broker_reachable()
        assert ok is True

    def test_check_broker_reachable_unhealthy(self):
        bp = MagicMock()
        bp.health_check.side_effect = ConnectionError("refused")
        checklist = MorningChecklist(broker_port=bp)
        ok, _ = checklist._check_broker_reachable()
        assert ok is False

    def test_check_capital_reconciled_positive(self):
        checklist = MorningChecklist()
        ok, msg = checklist._check_capital_reconciled()
        # Should gracefully handle missing state_manager
        assert isinstance(ok, bool)
        assert isinstance(msg, str)

    def test_check_db_writable_skipped_for_missing_db(self):
        checklist = MorningChecklist()
        ok, msg = checklist._check_db_writable()
        assert ok is True
        assert "writable" in msg

    def test_check_orphan_orders_no_store(self):
        checklist = MorningChecklist()
        ok, msg = checklist._check_no_orphan_orders()
        # Should gracefully handle missing durable_store
        assert isinstance(ok, bool)
        assert isinstance(msg, str)

    def test_check_market_calendar(self):
        checklist = MorningChecklist()
        ok, msg = checklist._check_market_calendar()
        # Should gracefully handle missing event_calendar
        assert isinstance(ok, bool)
        assert isinstance(msg, str)

    def test_check_lot_sizes(self):
        checklist = MorningChecklist()
        ok, msg = checklist._check_lot_sizes()
        # Should gracefully handle missing lot_size_validator
        assert isinstance(ok, bool)
        assert isinstance(msg, str)

    def test_check_circuit_breaker(self):
        checklist = MorningChecklist()
        ok, msg = checklist._check_circuit_breaker()
        # Should gracefully handle missing circuit_breaker_detector
        assert isinstance(ok, bool)
        assert isinstance(msg, str)

    def test_check_telegram_reachable(self):
        checklist = MorningChecklist()
        ok, msg = checklist._check_telegram_reachable()
        assert isinstance(ok, bool)
        assert isinstance(msg, str)

    def test_check_instrument_metadata(self):
        checklist = MorningChecklist()
        ok, msg = checklist._check_instrument_metadata()
        assert ok is True
        assert "OK" in msg

    def test_check_vix_loaded(self):
        checklist = MorningChecklist()
        ok, msg = checklist._check_vix_loaded()
        assert isinstance(ok, bool)
        assert isinstance(msg, str)

    # ── _run_checklist smoke test ───────────────────────────────

    def test_run_checklist_sends_report(self):
        sent_messages = []

        def fake_send(msg):
            sent_messages.append(msg)

        checklist = MorningChecklist(send_fn=fake_send)
        checklist._run_checklist()
        assert len(sent_messages) > 0
        report = sent_messages[0]
        assert "Morning Pre-Session" in report

    # ── Factory function ────────────────────────────────────────

    def test_run_morning_checklist_factory(self):
        checklist = run_morning_checklist(
            send_fn=lambda x: None,
            cfg={"test": True},
        )
        assert isinstance(checklist, MorningChecklist)
        assert checklist._cfg.get("test") is True
        checklist.stop()

    def test_run_morning_checklist_defaults(self):
        checklist = run_morning_checklist()
        assert isinstance(checklist, MorningChecklist)
        assert checklist._cfg == {}
        checklist.stop()
