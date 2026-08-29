import numpy as np
import pandas as pd

from index_app.domains.signal.evaluator import SignalEvaluator


def _frame():
    n = 120
    close = np.linspace(100.0, 140.0, n)

    return pd.DataFrame(
        {
            "Open": close - 0.1,
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Volume": np.full(n, 100000.0),
        }
    )


def _frames():
    return {
        "df1m": _frame(),
        "df5m": _frame(),
        "df15m": _frame(),
    }


def test_valid_ohlcv_reaches_evaluator(monkeypatch):
    called = {"yes": False}

    def fake_eval(**kwargs):
        called["yes"] = True
        return None, "test"

    monkeypatch.setattr(
        "index_app.domains.signal.evaluator._eval_v2",
        fake_eval,
    )

    svc = SignalEvaluator({})
    svc.evaluate("NIFTY", _frames(), 12.0)

    assert called["yes"] is True


def test_negative_volume_blocks_before_scoring(monkeypatch):
    frames = _frames()
    frames["df1m"].loc[50, "Volume"] = -100.0

    called = {"yes": False}

    def fake_eval(**kwargs):
        called["yes"] = True
        return None, "test"

    monkeypatch.setattr(
        "index_app.domains.signal.evaluator._eval_v2",
        fake_eval,
    )

    svc = SignalEvaluator({})
    result, reason = svc.evaluate("NIFTY", frames, 12.0)

    assert result is None
    assert "invalid_ohlcv" in reason
    assert called["yes"] is False


def test_nan_volume_blocks_before_scoring(monkeypatch):
    frames = _frames()
    frames["df5m"].loc[50, "Volume"] = np.nan

    called = {"yes": False}

    def fake_eval(**kwargs):
        called["yes"] = True
        return None, "test"

    monkeypatch.setattr(
        "index_app.domains.signal.evaluator._eval_v2",
        fake_eval,
    )

    svc = SignalEvaluator({})
    result, reason = svc.evaluate("NIFTY", frames, 12.0)

    assert result is None
    assert "invalid_ohlcv" in reason
    assert called["yes"] is False


def test_inf_close_blocks_before_scoring(monkeypatch):
    frames = _frames()
    frames["df15m"].loc[50, "Close"] = np.inf

    called = {"yes": False}

    def fake_eval(**kwargs):
        called["yes"] = True
        return None, "test"

    monkeypatch.setattr(
        "index_app.domains.signal.evaluator._eval_v2",
        fake_eval,
    )

    svc = SignalEvaluator({})
    result, reason = svc.evaluate("NIFTY", frames, 12.0)

    assert result is None
    assert "invalid_ohlcv" in reason
    assert called["yes"] is False


def test_missing_volume_blocks_before_scoring(monkeypatch):
    frames = _frames()
    frames["df1m"] = frames["df1m"].drop(columns=["Volume"])

    called = {"yes": False}

    def fake_eval(**kwargs):
        called["yes"] = True
        return None, "test"

    monkeypatch.setattr(
        "index_app.domains.signal.evaluator._eval_v2",
        fake_eval,
    )

    svc = SignalEvaluator({})
    result, reason = svc.evaluate("NIFTY", frames, 12.0)

    assert result is None
    assert "invalid_ohlcv" in reason
    assert called["yes"] is False
