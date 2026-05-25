"""
Tests for core/signal_autopsy.py (Step 3).

Covers:
  - load_autopsy_data() missing db, days filter, mode filter
  - compute_feature_breakdown() dimensions, win rate calculation
  - find_failure_patterns() sorting, empty losers
  - compute_edge_decay() window size, chronological rolling
  - run_autopsy() no-trades fallback, full pipeline
  - format_autopsy_report() string contract
  - AutopsyReport fields populated correctly
"""
import datetime
import sqlite3

from core.signal_autopsy import (
    AutopsyReport,
    compute_edge_decay,
    compute_feature_breakdown,
    find_failure_patterns,
    format_autopsy_report,
    load_autopsy_data,
    run_autopsy,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_db(tmp_path, trades):
    """Create a trades.db with the given trade dicts."""
    p = tmp_path / "trades.db"
    conn = sqlite3.connect(str(p))
    conn.execute("""
        CREATE TABLE trades (
            id INTEGER PRIMARY KEY,
            ts TEXT, index_name TEXT, direction TEXT, entry REAL,
            exit_price REAL, qty INTEGER, gross_pnl REAL, net_pnl REAL,
            reason TEXT, regime TEXT, score REAL, iv REAL, vix REAL,
            ltp_estimated INTEGER, partial INTEGER, sl_warned INTEGER,
            mode TEXT, version TEXT
        )
    """)
    for i, t in enumerate(trades):
        conn.execute("""
            INSERT INTO trades
              (ts, index_name, direction, net_pnl, regime, score, iv, vix, mode)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (
            t.get("ts", (datetime.datetime.utcnow() - datetime.timedelta(hours=i)).isoformat()),
            t.get("index_name", "NIFTY"),
            t.get("direction", "CALL"),
            t.get("net_pnl", 0.0),
            t.get("regime", "TRENDING"),
            t.get("score", 75.0),
            t.get("iv", 0.0),
            t.get("vix", 14.0),
            t.get("mode", "PAPER"),
        ))
    conn.commit()
    conn.close()
    return str(p)


def _sample_trades(n=20):
    import random
    rng = random.Random(42)
    now = datetime.datetime.utcnow()
    trades = []
    for i in range(n):
        pnl = rng.choice([100.0, 200.0, -80.0, -150.0, 50.0])
        trades.append({
            "ts":         (now - datetime.timedelta(hours=n - i)).isoformat(),
            "index_name": rng.choice(["NIFTY", "BANKNIFTY"]),
            "direction":  rng.choice(["CALL", "PUT"]),
            "net_pnl":    pnl,
            "regime":     rng.choice(["TRENDING", "RANGING", "VOLATILE"]),
            "score":      float(rng.randint(60, 95)),
            "mode":       "PAPER",
        })
    return trades


# ── load_autopsy_data ─────────────────────────────────────────────────────────

class TestLoadAutopsyData:
    def test_returns_empty_when_db_missing(self, tmp_path):
        result = load_autopsy_data(str(tmp_path / "no.db"))
        assert result == []

    def test_loads_correct_count(self, tmp_path):
        db = _make_db(tmp_path, _sample_trades(15))
        trades = load_autopsy_data(db, days=0)
        assert len(trades) == 15

    def test_is_winner_set_correctly(self, tmp_path):
        # Provide explicit ts so ORDER BY ts ASC order is predictable
        now = datetime.datetime.utcnow()
        items = [
            {"ts": (now - datetime.timedelta(hours=2)).isoformat(), "net_pnl":  100.0},
            {"ts": (now - datetime.timedelta(hours=1)).isoformat(), "net_pnl": -50.0},
        ]
        db = _make_db(tmp_path, items)
        trades = load_autopsy_data(db, days=0)
        assert trades[0]["is_winner"] == 1
        assert trades[1]["is_winner"] == 0

    def test_days_filter_excludes_old(self, tmp_path):
        old_ts = (datetime.datetime.utcnow() - datetime.timedelta(days=60)).isoformat()
        new_ts = (datetime.datetime.utcnow() - datetime.timedelta(hours=2)).isoformat()
        items = [
            {"ts": old_ts, "net_pnl": 999.0},
            {"ts": new_ts, "net_pnl": 100.0},
        ]
        db = _make_db(tmp_path, items)
        trades = load_autopsy_data(db, days=30)
        assert len(trades) == 1
        assert abs(trades[0]["net_pnl"] - 100.0) < 1e-6

    def test_mode_filter(self, tmp_path):
        items = [
            {"net_pnl": 100.0, "mode": "PAPER"},
            {"net_pnl": 200.0, "mode": "LIVE"},
        ]
        db = _make_db(tmp_path, items)
        trades = load_autopsy_data(db, days=0, mode="PAPER")
        assert len(trades) == 1
        assert trades[0]["mode"] == "PAPER"

    def test_score_bin_assigned(self, tmp_path):
        items = [{"net_pnl": 100.0, "score": 92.0}]
        db = _make_db(tmp_path, items)
        trades = load_autopsy_data(db, days=0)
        assert trades[0]["score_bin"] == "90+"


# ── compute_feature_breakdown ─────────────────────────────────────────────────

class TestComputeFeatureBreakdown:
    def test_empty_returns_empty(self):
        assert compute_feature_breakdown([]) == {}

    def test_has_score_bin_dimension(self):
        trades = [{"score_bin": "80-89", "is_winner": 1, "net_pnl": 100.0, "direction": "CALL",
                   "regime": "TRENDING", "index_name": "NIFTY"}]
        result = compute_feature_breakdown(trades)
        assert "score_bin" in result

    def test_win_rate_all_winners(self):
        trades = [
            {"score_bin": "70-79", "is_winner": 1, "net_pnl": 100.0,
             "direction": "CALL", "regime": "TRENDING", "index_name": "NIFTY"}
        ] * 4
        result = compute_feature_breakdown(trades)
        assert result["score_bin"]["70-79"]["win_rate"] == 100.0

    def test_win_rate_mixed(self):
        trades = [
            {"score_bin": "70-79", "is_winner": 1, "net_pnl":  100.0,
             "direction": "CALL", "regime": "TRENDING", "index_name": "NIFTY"},
            {"score_bin": "70-79", "is_winner": 0, "net_pnl": -100.0,
             "direction": "CALL", "regime": "TRENDING", "index_name": "NIFTY"},
        ]
        result = compute_feature_breakdown(trades)
        assert result["score_bin"]["70-79"]["win_rate"] == 50.0
        assert result["score_bin"]["70-79"]["trades"] == 2

    def test_all_dimensions_present(self):
        trades = [
            {"score_bin": "80-89", "is_winner": 1, "net_pnl": 50.0,
             "direction": "PUT", "regime": "RANGING", "index_name": "BANKNIFTY"}
        ]
        result = compute_feature_breakdown(trades)
        for dim in ["score_bin", "direction", "regime", "index_name"]:
            assert dim in result


# ── find_failure_patterns ─────────────────────────────────────────────────────

class TestFindFailurePatterns:
    def test_empty_losers_returns_empty(self):
        trades = [{"is_winner": 1, "net_pnl": 100.0, "direction": "CALL",
                   "regime": "TRENDING", "score_bin": "80-89"}]
        assert find_failure_patterns(trades) == []

    def test_returns_list_of_dicts(self):
        trades = [
            {"is_winner": 0, "net_pnl": -100.0, "direction": "PUT",
             "regime": "RANGING", "score_bin": "60-69"},
        ] * 3
        patterns = find_failure_patterns(trades)
        assert isinstance(patterns, list)
        for p in patterns:
            assert "direction" in p and "regime" in p and "count" in p

    def test_most_common_pattern_first(self):
        trades = (
            [{"is_winner": 0, "net_pnl": -100.0, "direction": "PUT",
              "regime": "RANGING", "score_bin": "60-69"}] * 4 +
            [{"is_winner": 0, "net_pnl": -50.0, "direction": "CALL",
              "regime": "VOLATILE", "score_bin": "70-79"}] * 2
        )
        patterns = find_failure_patterns(trades, top_n=5)
        assert patterns[0]["count"] == 4

    def test_top_n_respected(self):
        trades = []
        for i in range(10):
            trades.append({"is_winner": 0, "net_pnl": -50.0,
                           "direction": "CALL", "regime": f"REG_{i}", "score_bin": "70-79"})
        patterns = find_failure_patterns(trades, top_n=3)
        assert len(patterns) <= 3

    def test_pct_of_losses_sums_roughly_100(self):
        trades = [
            {"is_winner": 0, "net_pnl": -100.0, "direction": "CALL",
             "regime": "TRENDING", "score_bin": "80-89"},
            {"is_winner": 0, "net_pnl": -100.0, "direction": "PUT",
             "regime": "RANGING", "score_bin": "70-79"},
        ]
        patterns = find_failure_patterns(trades, top_n=10)
        total_pct = sum(p["pct_of_losses"] for p in patterns)
        assert abs(total_pct - 100.0) < 1.0


# ── compute_edge_decay ────────────────────────────────────────────────────────

class TestComputeEdgeDecay:
    def _make_trades(self, winners_pattern):
        return [
            {"is_winner": w, "net_pnl": 100.0 if w else -100.0}
            for w in winners_pattern
        ]

    def test_empty_when_fewer_than_window(self):
        trades = self._make_trades([1, 0, 1])
        decay = compute_edge_decay(trades, window=5)
        assert decay == []

    def test_length_is_n_minus_window_plus_1(self):
        trades = self._make_trades([1, 0, 1, 0, 1, 0, 1, 0, 1, 0])
        decay = compute_edge_decay(trades, window=3)
        assert len(decay) == 10 - 3 + 1

    def test_win_rate_100_all_winners(self):
        trades = self._make_trades([1] * 10)
        decay = compute_edge_decay(trades, window=5)
        for d in decay:
            assert d["win_rate"] == 100.0

    def test_win_rate_0_all_losers(self):
        trades = self._make_trades([0] * 10)
        decay = compute_edge_decay(trades, window=5)
        for d in decay:
            assert d["win_rate"] == 0.0

    def test_trade_index_ascending(self):
        trades = self._make_trades([1, 0] * 6)
        decay = compute_edge_decay(trades, window=3)
        indices = [d["trade_index"] for d in decay]
        assert indices == sorted(indices)

    def test_trades_in_window_correct(self):
        trades = self._make_trades([1, 0, 1, 0, 1])
        decay = compute_edge_decay(trades, window=3)
        for d in decay:
            assert d["trades_in_window"] == 3


# ── run_autopsy ───────────────────────────────────────────────────────────────

class TestRunAutopsy:
    def test_no_trades_returns_empty_report(self, tmp_path):
        db = str(tmp_path / "empty.db")
        report = run_autopsy(db, days=30)
        assert isinstance(report, AutopsyReport)
        assert report.n_trades == 0

    def test_full_pipeline(self, tmp_path):
        db = _make_db(tmp_path, _sample_trades(20))
        report = run_autopsy(db, days=0)
        assert report.n_trades == 20
        assert report.n_winners + report.n_losers == 20
        assert isinstance(report.feature_breakdown, dict)
        assert isinstance(report.failure_patterns, list)
        assert isinstance(report.edge_decay, list)

    def test_overall_win_rate_range(self, tmp_path):
        db = _make_db(tmp_path, _sample_trades(20))
        report = run_autopsy(db, days=0)
        assert 0.0 <= report.overall_win_rate <= 100.0

    def test_insights_is_list_of_strings(self, tmp_path):
        db = _make_db(tmp_path, _sample_trades(20))
        report = run_autopsy(db, days=0)
        assert isinstance(report.insights, list)
        for ins in report.insights:
            assert isinstance(ins, str)

    def test_cfg_overrides_days(self, tmp_path):
        old_ts = (datetime.datetime.utcnow() - datetime.timedelta(days=100)).isoformat()
        items = [{"ts": old_ts, "net_pnl": 999.0}]
        db = _make_db(tmp_path, items)
        report = run_autopsy(db, cfg={"signal_autopsy_days": 7, "trades_db": db})
        assert report.n_trades == 0


# ── format_autopsy_report ─────────────────────────────────────────────────────

class TestFormatAutopsyReport:
    def test_returns_string(self, tmp_path):
        db = _make_db(tmp_path, _sample_trades(10))
        report = run_autopsy(db, days=0)
        s = format_autopsy_report(report)
        assert isinstance(s, str) and len(s) > 20

    def test_contains_win_rate(self, tmp_path):
        db = _make_db(tmp_path, _sample_trades(10))
        report = run_autopsy(db, days=0)
        s = format_autopsy_report(report)
        assert "Win Rate" in s or "%" in s

    def test_empty_report_does_not_raise(self):
        report = AutopsyReport(n_trades=0, n_winners=0, n_losers=0, overall_win_rate=0.0)
        s = format_autopsy_report(report)
        assert isinstance(s, str)
