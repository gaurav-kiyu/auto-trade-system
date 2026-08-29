"""Tests for core.signals.signal_tracker's SignalTracker singleton.

Covers:
- get_instance() default path (unchanged behavior)
- get_instance(db_path=...) redirects the singleton on first construction
  (regression: previously get_instance() took no path override at all,
  so any test exercising a call site like core/auth/routes.py or
  core/all_nse_scanner.py had no way to avoid the real db/signals_history.db)
- reset_instance() allows a fresh singleton with a different path
"""
from __future__ import annotations

import pytest
from core.signals.signal_tracker import SignalTracker


@pytest.fixture(autouse=True)
def _reset_singleton():
    SignalTracker.reset_instance()
    yield
    SignalTracker.reset_instance()


class TestGetInstance:
    def test_returns_same_instance_on_repeated_calls(self):
        a = SignalTracker.get_instance()
        b = SignalTracker.get_instance()
        assert a is b

    def test_db_path_override_redirects_on_first_construction(self, tmp_path):
        custom_path = tmp_path / "isolated_signals.db"
        tracker = SignalTracker.get_instance(db_path=custom_path)
        assert tracker._db_path == custom_path
        assert custom_path.is_file()

    def test_later_db_path_argument_is_ignored_once_constructed(self, tmp_path):
        first_path = tmp_path / "first.db"
        second_path = tmp_path / "second.db"
        first = SignalTracker.get_instance(db_path=first_path)
        second = SignalTracker.get_instance(db_path=second_path)
        assert first is second
        assert second._db_path == first_path  # second_path never took effect


class TestResetInstance:
    def test_reset_allows_a_fresh_instance_with_a_new_path(self, tmp_path):
        path_a = tmp_path / "a.db"
        path_b = tmp_path / "b.db"
        a = SignalTracker.get_instance(db_path=path_a)
        SignalTracker.reset_instance()
        b = SignalTracker.get_instance(db_path=path_b)
        assert a is not b
        assert b._db_path == path_b


# =============================================================================
# update_active_signal_outcomes() - closes the "signals stay ACTIVE forever"
# gap so get_admin_signal_analytics()'s win_rate/t1_hit_rate can ever move
# off zero, including while running purely SIGNAL_ONLY (no real fills).
# =============================================================================

class TestUpdateActiveSignalOutcomes:
    def _tracker(self, tmp_path):
        from core.signals.signal_tracker import SignalTracker as _ST
        tracker = _ST(db_path=tmp_path / "signals.db")
        # _init_db() seeds ~12 hardcoded demo signals on first construction
        # (one of them, "IDEA", is itself status=ACTIVE) - clear all seed
        # rows so these tests start from a genuinely clean slate rather than
        # depending on the seed data's exact contents.
        conn = tracker._get_conn()
        conn.execute("DELETE FROM system_signals")
        conn.execute("DELETE FROM user_deliveries")
        conn.commit()
        conn.close()
        return tracker

    def _insert_active(self, tracker, symbol="NIFTY", direction="CALL", entry=100.0, sl=92.0, t1=130.0, t2=180.0, created_date=None):
        signal = {
            "symbol": symbol, "direction": direction, "price": entry,
            "stop_loss": sl, "target_1": t1, "target_2": t2,
            "score": 85, "tier": "STRONG", "category": "INDEX_OPTIONS",
        }
        sig_id = tracker.record_generated_signal(signal)
        if created_date is not None:
            conn = tracker._get_conn()
            conn.execute("UPDATE system_signals SET created_date = ? WHERE signal_id = ?", (created_date, sig_id))
            conn.commit()
            conn.close()
        return sig_id

    def test_no_active_signals_is_a_noop(self, tmp_path):
        tracker = self._tracker(tmp_path)
        result = tracker.update_active_signal_outcomes(lambda sym: 100.0)
        assert result == {"checked": 0, "resolved": 0, "expired": 0}

    def test_target_1_hit_for_call(self, tmp_path):
        tracker = self._tracker(tmp_path)
        self._insert_active(tracker, direction="CALL", entry=100.0, sl=92.0, t1=130.0, t2=180.0)
        result = tracker.update_active_signal_outcomes(lambda sym: 135.0)
        assert result == {"checked": 1, "resolved": 1, "expired": 0}
        rows = tracker.get_admin_signal_analytics()["signals"]
        assert rows[0]["status"] == "TARGET_1_HIT"
        assert rows[0]["current_price"] == 135.0
        assert rows[0]["pnl_pct"] == 35.0

    def test_simultaneous_barrier_hits_are_marked_ambiguous(self, tmp_path):
        tracker = self._tracker(tmp_path)
        self._insert_active(tracker, direction="CALL", entry=100.0, sl=92.0, t1=130.0, t2=180.0)
        tracker.update_active_signal_outcomes(lambda sym: 190.0)
        rows = tracker.get_admin_signal_analytics()["signals"]
        assert rows[0]["status"] == "AMBIGUOUS"

    def test_stop_loss_hit_for_call(self, tmp_path):
        tracker = self._tracker(tmp_path)
        self._insert_active(tracker, direction="CALL", entry=100.0, sl=92.0, t1=130.0, t2=180.0)
        tracker.update_active_signal_outcomes(lambda sym: 90.0)
        rows = tracker.get_admin_signal_analytics()["signals"]
        assert rows[0]["status"] == "SL_HIT"
        assert rows[0]["pnl_pct"] == -10.0

    def test_put_direction_uses_inverted_comparisons(self, tmp_path):
        tracker = self._tracker(tmp_path)
        self._insert_active(tracker, direction="PUT", entry=100.0, sl=108.0, t1=70.0, t2=20.0)
        tracker.update_active_signal_outcomes(lambda sym: 65.0)
        rows = tracker.get_admin_signal_analytics()["signals"]
        assert rows[0]["status"] == "TARGET_1_HIT"
        assert rows[0]["pnl_pct"] == 35.0

    def test_still_pending_today_stays_active(self, tmp_path):
        tracker = self._tracker(tmp_path)
        self._insert_active(tracker, direction="CALL", entry=100.0, sl=92.0, t1=130.0, t2=180.0)
        result = tracker.update_active_signal_outcomes(lambda sym: 105.0)  # between SL and T1
        assert result == {"checked": 1, "resolved": 0, "expired": 0}
        rows = tracker.get_admin_signal_analytics()["signals"]
        assert rows[0]["status"] == "ACTIVE"
        assert rows[0]["current_price"] == 105.0

    def test_stale_prior_day_signal_expires_without_hitting_either(self, tmp_path):
        tracker = self._tracker(tmp_path)
        self._insert_active(tracker, direction="CALL", entry=100.0, sl=92.0, t1=130.0, t2=180.0, created_date="2000-01-01")
        result = tracker.update_active_signal_outcomes(lambda sym: 105.0)
        assert result == {"checked": 1, "resolved": 0, "expired": 1}
        rows = tracker.get_admin_signal_analytics()["signals"]
        assert rows[0]["status"] == "EXPIRED"

    def test_price_lookup_returning_none_skips_without_crashing(self, tmp_path):
        tracker = self._tracker(tmp_path)
        self._insert_active(tracker)
        result = tracker.update_active_signal_outcomes(lambda sym: None)
        assert result == {"checked": 1, "resolved": 0, "expired": 0}
        rows = tracker.get_admin_signal_analytics()["signals"]
        assert rows[0]["status"] == "ACTIVE"

    def test_price_lookup_raising_is_swallowed(self, tmp_path):
        tracker = self._tracker(tmp_path)
        self._insert_active(tracker)

        def _boom(sym):
            raise ValueError("boom")

        result = tracker.update_active_signal_outcomes(_boom)  # must not raise
        assert result == {"checked": 1, "resolved": 0, "expired": 0}

    def test_win_rate_moves_off_zero_after_resolution(self, tmp_path):
        """The exact gap this closes: get_admin_signal_analytics()'s
        win_rate_pct used to be permanently stuck at 0 (or a misleading
        default) because nothing ever transitioned a signal off ACTIVE."""
        tracker = self._tracker(tmp_path)
        self._insert_active(tracker, direction="CALL", entry=100.0, sl=92.0, t1=130.0, t2=180.0)
        before = tracker.get_admin_signal_analytics()["win_rate_pct"]
        tracker.update_active_signal_outcomes(lambda sym: 135.0)
        after = tracker.get_admin_signal_analytics()["win_rate_pct"]
        assert before == 0.0
        assert after == 100.0

    def test_multiple_active_signals_all_checked(self, tmp_path):
        tracker = self._tracker(tmp_path)
        self._insert_active(tracker, symbol="NIFTY", entry=100.0, sl=92.0, t1=130.0, t2=180.0)
        self._insert_active(tracker, symbol="BANKNIFTY", entry=200.0, sl=184.0, t1=260.0, t2=360.0)
        result = tracker.update_active_signal_outcomes(lambda sym: 135.0 if sym == "NIFTY" else 270.0)
        assert result["checked"] == 2
        assert result["resolved"] == 2


# =============================================================================
# mark_order_placed() - admin's own "I actually traded this signal" marker,
# for the historical/report view (templates/enterprise/admin_signals.html).
# =============================================================================

class TestMarkOrderPlaced:
    def _tracker(self, tmp_path):
        from core.signals.signal_tracker import SignalTracker as _ST
        tracker = _ST(db_path=tmp_path / "signals.db")
        conn = tracker._get_conn()
        conn.execute("DELETE FROM system_signals")
        conn.execute("DELETE FROM user_deliveries")
        conn.commit()
        conn.close()
        return tracker

    def test_unknown_signal_id_returns_false(self, tmp_path):
        tracker = self._tracker(tmp_path)
        assert tracker.mark_order_placed("SIG-DOES-NOT-EXIST", True, "admin") is False

    def test_marking_placed_persists_who_and_when(self, tmp_path):
        tracker = self._tracker(tmp_path)
        sig_id = tracker.record_generated_signal({"symbol": "NIFTY", "direction": "CALL", "price": 100.0})
        ok = tracker.mark_order_placed(sig_id, True, "gaurav")
        assert ok is True
        row = next(r for r in tracker.get_admin_signal_analytics()["signals"] if r["signal_id"] == sig_id)
        assert row["order_placed"] == 1
        assert row["order_placed_by"] == "gaurav"
        assert row["order_placed_at"] != ""

    def test_unmarking_clears_who_and_when(self, tmp_path):
        tracker = self._tracker(tmp_path)
        sig_id = tracker.record_generated_signal({"symbol": "NIFTY", "direction": "CALL", "price": 100.0})
        tracker.mark_order_placed(sig_id, True, "gaurav")
        tracker.mark_order_placed(sig_id, False, "gaurav")
        row = next(r for r in tracker.get_admin_signal_analytics()["signals"] if r["signal_id"] == sig_id)
        assert row["order_placed"] == 0
        assert row["order_placed_by"] == ""
        assert row["order_placed_at"] == ""

    def test_defaults_to_not_placed_for_a_fresh_signal(self, tmp_path):
        tracker = self._tracker(tmp_path)
        sig_id = tracker.record_generated_signal({"symbol": "NIFTY", "direction": "CALL", "price": 100.0})
        row = next(r for r in tracker.get_admin_signal_analytics()["signals"] if r["signal_id"] == sig_id)
        assert row["order_placed"] == 0

    def test_orders_placed_count_reflects_marked_signals(self, tmp_path):
        tracker = self._tracker(tmp_path)
        sig_a = tracker.record_generated_signal({"symbol": "NIFTY", "direction": "CALL", "price": 100.0})
        tracker.record_generated_signal({"symbol": "BANKNIFTY", "direction": "CALL", "price": 200.0})
        tracker.mark_order_placed(sig_a, True, "gaurav")
        assert tracker.get_admin_signal_analytics()["orders_placed_count"] == 1


# =============================================================================
# prune_old_signals() - SQLite row-level retention for db/signals_history.db.
# core/data_governance.py's file-glob categories can't reach into a database,
# and all_nse_scanner.py's 2,500+ stock universe scan means this table would
# otherwise grow unbounded. Every aged-out row is archived to a .zip before
# deletion - never delete without a confirmed backup on disk.
# =============================================================================

class TestPruneOldSignals:
    def _tracker(self, tmp_path):
        from core.signals.signal_tracker import SignalTracker as _ST
        tracker = _ST(db_path=tmp_path / "signals.db")
        conn = tracker._get_conn()
        conn.execute("DELETE FROM system_signals")
        conn.execute("DELETE FROM user_deliveries")
        conn.commit()
        conn.close()
        return tracker

    def _insert_resolved(self, tracker, status="TARGET_1_HIT", created_date="2000-01-01", symbol="NIFTY"):
        sig_id = tracker.record_generated_signal({"symbol": symbol, "direction": "CALL", "price": 100.0})
        conn = tracker._get_conn()
        conn.execute(
            "UPDATE system_signals SET status = ?, created_date = ? WHERE signal_id = ?",
            (status, created_date, sig_id),
        )
        conn.commit()
        conn.close()
        return sig_id

    def test_zero_or_negative_max_age_is_a_noop(self, tmp_path):
        tracker = self._tracker(tmp_path)
        self._insert_resolved(tracker)
        assert tracker.prune_old_signals(0, archive_dir=tmp_path / "archive") == 0
        assert tracker.prune_old_signals(-5, archive_dir=tmp_path / "archive") == 0
        assert not (tmp_path / "archive").exists()

    def test_no_eligible_signals_returns_zero_without_creating_archive(self, tmp_path):
        tracker = self._tracker(tmp_path)
        archive_dir = tmp_path / "archive"
        assert tracker.prune_old_signals(30, archive_dir=archive_dir) == 0
        assert not archive_dir.exists() or not list(archive_dir.glob("*.zip"))

    def test_old_resolved_signal_is_archived_and_removed(self, tmp_path):
        tracker = self._tracker(tmp_path)
        sig_id = self._insert_resolved(tracker, status="TARGET_1_HIT", created_date="2000-01-01")
        archive_dir = tmp_path / "archive"

        removed = tracker.prune_old_signals(30, archive_dir=archive_dir)

        assert removed == 1
        rows = [r for r in tracker.get_admin_signal_analytics()["signals"] if r["signal_id"] == sig_id]
        assert rows == []
        zips = list(archive_dir.glob("*.zip"))
        assert len(zips) == 1

    def test_archive_zip_contains_the_pruned_signal(self, tmp_path):
        import json
        import zipfile

        tracker = self._tracker(tmp_path)
        sig_id = self._insert_resolved(tracker, status="SL_HIT", created_date="2000-01-01", symbol="BANKNIFTY")
        archive_dir = tmp_path / "archive"

        tracker.prune_old_signals(30, archive_dir=archive_dir)

        zip_path = next(archive_dir.glob("*.zip"))
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            assert len(names) == 1
            payload = json.loads(zf.read(names[0]))
        archived_ids = [row["signal_id"] for row in payload["system_signals"]]
        assert sig_id in archived_ids
        assert any(row["symbol"] == "BANKNIFTY" for row in payload["system_signals"])

    def test_active_signal_is_never_pruned_regardless_of_age(self, tmp_path):
        tracker = self._tracker(tmp_path)
        sig_id = self._insert_resolved(tracker, status="ACTIVE", created_date="2000-01-01")
        archive_dir = tmp_path / "archive"

        removed = tracker.prune_old_signals(30, archive_dir=archive_dir)

        assert removed == 0
        rows = [r for r in tracker.get_admin_signal_analytics()["signals"] if r["signal_id"] == sig_id]
        assert len(rows) == 1

    def test_recent_resolved_signal_is_kept(self, tmp_path):
        from core.datetime_ist import now_ist
        tracker = self._tracker(tmp_path)
        today_str = now_ist().date().isoformat()
        sig_id = self._insert_resolved(tracker, status="TARGET_1_HIT", created_date=today_str)
        archive_dir = tmp_path / "archive"

        removed = tracker.prune_old_signals(30, archive_dir=archive_dir)

        assert removed == 0
        rows = [r for r in tracker.get_admin_signal_analytics()["signals"] if r["signal_id"] == sig_id]
        assert len(rows) == 1

    def test_linked_user_deliveries_are_archived_and_removed_too(self, tmp_path):
        tracker = self._tracker(tmp_path)
        sig_id = tracker.record_generated_signal(
            {"symbol": "NIFTY", "direction": "CALL", "price": 100.0},
            eligible_users=[type("U", (), {"username": "gaurav"})()],
        )
        conn = tracker._get_conn()
        conn.execute(
            "UPDATE system_signals SET status = 'TARGET_1_HIT', created_date = '2000-01-01' WHERE signal_id = ?",
            (sig_id,),
        )
        conn.commit()
        delivery_count_before = conn.execute(
            "SELECT COUNT(*) as c FROM user_deliveries WHERE signal_id = ?", (sig_id,)
        ).fetchone()["c"]
        conn.close()
        assert delivery_count_before >= 1

        archive_dir = tmp_path / "archive"
        tracker.prune_old_signals(30, archive_dir=archive_dir)

        conn = tracker._get_conn()
        delivery_count_after = conn.execute(
            "SELECT COUNT(*) as c FROM user_deliveries WHERE signal_id = ?", (sig_id,)
        ).fetchone()["c"]
        conn.close()
        assert delivery_count_after == 0

    def test_archive_write_failure_leaves_rows_in_place(self, tmp_path, monkeypatch):
        """If the archive can't be written, the live rows must NOT be
        deleted - never delete a signal without a confirmed backup on disk."""
        tracker = self._tracker(tmp_path)
        sig_id = self._insert_resolved(tracker, status="TARGET_1_HIT", created_date="2000-01-01")

        monkeypatch.setattr(
            tracker, "_archive_signals",
            lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")),
        )

        removed = tracker.prune_old_signals(30, archive_dir=tmp_path / "archive")

        assert removed == 0
        rows = [r for r in tracker.get_admin_signal_analytics()["signals"] if r["signal_id"] == sig_id]
        assert len(rows) == 1

# =============================================================================
# V174 ? chronological first-hit lifecycle contract
# =============================================================================


# =============================================================================
# V174 ? chronological first-hit lifecycle contract
# =============================================================================

class TestFirstHitLifecycleV174:
    """
    The first independently observed barrier hit is immutable.

    A later SL/T1/T2 observation must be recorded as subsequent evidence,
    but must never rewrite first_touch.
    """

    def _tracker(self, tmp_path):
        from core.signals.signal_tracker import SignalTracker as _ST

        tracker = _ST(db_path=tmp_path / "signals.db")

        conn = tracker._get_conn()
        conn.execute("DELETE FROM system_signals")
        conn.execute("DELETE FROM user_deliveries")
        conn.execute("DELETE FROM signal_outcome_events")
        conn.commit()
        conn.close()

        return tracker

    def _insert_active(
        self,
        tracker,
        *,
        direction="CALL",
        entry=100.0,
        sl=90.0,
        t1=110.0,
        t2=120.0,
    ):
        signal = {
            "symbol": "V174TEST",
            "company_name": "V174 Test",
            "category": "INDEX_OPTIONS",
            "direction": direction,
            "score": 95,
            "tier": "STRONG",
            "entry_price": entry,
            "stop_loss": sl,
            "target_1": t1,
            "target_2": t2,
            "price": entry,
        }

        sig_id = tracker.record_generated_signal(signal)

        assert sig_id

        return sig_id

    def _row(self, tracker, sig_id):
        conn = tracker._get_conn()
        row = conn.execute(
            "SELECT * FROM system_signals WHERE signal_id = ?",
            (sig_id,),
        ).fetchone()
        conn.close()

        assert row is not None
        return dict(row)

    def _events(self, tracker, sig_id):
        conn = tracker._get_conn()

        rows = conn.execute(
            """
            SELECT event_id, observed_price, hit_sl, hit_t1, hit_t2
            FROM signal_outcome_events
            WHERE signal_id = ?
            ORDER BY event_id
            """,
            (sig_id,),
        ).fetchall()

        conn.close()

        return [dict(r) for r in rows]

    def test_t1_first_then_sl_keeps_t1_as_first_touch(self, tmp_path):
        tracker = self._tracker(tmp_path)

        sig_id = self._insert_active(tracker)

        # First observation: T1.
        tracker.update_active_signal_outcomes(
            lambda sym: 110.0
        )

        first = self._row(tracker, sig_id)

        assert first["first_touch"] == "T1"
        assert first["first_touch_at"]

        # Later observation: SL.
        tracker.update_active_signal_outcomes(
            lambda sym: 90.0
        )

        second = self._row(tracker, sig_id)

        assert second["first_touch"] == "T1"
        assert second["first_touch_at"] == first["first_touch_at"]

        events = self._events(tracker, sig_id)

        assert len(events) >= 2
        assert events[0]["hit_t1"] == 1
        assert events[0]["hit_sl"] == 0
        assert events[1]["hit_sl"] == 1

    def test_sl_first_then_t1_keeps_sl_as_first_touch(self, tmp_path):
        tracker = self._tracker(tmp_path)

        sig_id = self._insert_active(tracker)

        # First observation: SL.
        tracker.update_active_signal_outcomes(
            lambda sym: 90.0
        )

        first = self._row(tracker, sig_id)

        assert first["first_touch"] == "SL"
        assert first["first_touch_at"]

        # Later observation: T1.
        tracker.update_active_signal_outcomes(
            lambda sym: 110.0
        )

        second = self._row(tracker, sig_id)

        assert second["first_touch"] == "SL"
        assert second["first_touch_at"] == first["first_touch_at"]

        events = self._events(tracker, sig_id)

        assert len(events) >= 2
        assert events[0]["hit_sl"] == 1
        assert events[0]["hit_t1"] == 0
        assert events[1]["hit_t1"] == 1

    def test_t1_then_t2_preserves_t1_first_touch(self, tmp_path):
        tracker = self._tracker(tmp_path)

        sig_id = self._insert_active(tracker)

        tracker.update_active_signal_outcomes(
            lambda sym: 110.0
        )

        first = self._row(tracker, sig_id)

        assert first["first_touch"] == "T1"

        tracker.update_active_signal_outcomes(
            lambda sym: 120.0
        )

        second = self._row(tracker, sig_id)

        assert second["first_touch"] == "T1"
        assert second["first_touch_at"] == first["first_touch_at"]

        events = self._events(tracker, sig_id)

        assert len(events) >= 2
        assert events[0]["hit_t1"] == 1
        assert events[1]["hit_t2"] == 1

    def test_same_observation_multiple_barriers_is_ambiguous(self, tmp_path):
        tracker = self._tracker(tmp_path)

        sig_id = self._insert_active(tracker)

        # 120 crosses T1 and T2 for this CALL.
        tracker.update_active_signal_outcomes(
            lambda sym: 120.0
        )

        row = self._row(tracker, sig_id)

        assert row["first_touch"] == "AMBIGUOUS_SAME_OBSERVATION"
        assert row["outcome_confidence"] == "AMBIGUOUS"

        events = self._events(tracker, sig_id)

        assert len(events) == 1
        assert events[0]["hit_t1"] == 1
        assert events[0]["hit_t2"] == 1

    def test_repeated_polling_does_not_create_fake_first_touch_changes(self, tmp_path):
        tracker = self._tracker(tmp_path)

        sig_id = self._insert_active(tracker)

        # First observation: T1.
        tracker.update_active_signal_outcomes(
            lambda sym: 110.0
        )

        first = self._row(tracker, sig_id)

        # Same barrier remains crossed.
        tracker.update_active_signal_outcomes(
            lambda sym: 112.0
        )

        second = self._row(tracker, sig_id)

        assert second["first_touch"] == "T1"
        assert second["first_touch_at"] == first["first_touch_at"]

        events = self._events(tracker, sig_id)

        # Repeated polling of the same barrier state must not create
        # duplicate lifecycle events.
        assert len(events) == 1
        assert events[0]["hit_t1"] == 1
        assert events[0]["hit_sl"] == 0
        assert events[0]["hit_t2"] == 0
