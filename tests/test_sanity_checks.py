from pathlib import Path

from core.sanity_checks import ltp_sane, ohlcv_bar_sane, spread_sane, volume_sane


def test_ltp_sane_accepts_mid_range():
    assert ltp_sane(100.0) is True


def test_ltp_sane_rejects_and_logs():
    msgs: list[str] = []

    def lg(m: str) -> None:
        msgs.append(m)

    assert ltp_sane(0.1, name="X", log_fn=lg) is False
    assert any("X" in m and "LTP" in m for m in msgs)


def test_volume_sane():
    assert volume_sane(1_000) is True
    assert volume_sane(-1) is False


def test_spread_sane_rejects_inverted():
    assert spread_sane(100, 99) is True
    assert spread_sane(99, 100) is False


def test_ohlcv_bar_sane():
    assert ohlcv_bar_sane(100, 105, 99, 102, 1_000_000) is True
    assert ohlcv_bar_sane(100, 99, 100, 100, 100) is False


def test_verify_release_bundle_script(tmp_path):
    import subprocess
    import sys

    (tmp_path / "README.txt").write_text("x", encoding="utf-8")
    script = Path(__file__).resolve().parent.parent / "scripts" / "verify_release_bundle.py"
    r = subprocess.run(
        [sys.executable, str(script), "--root", str(tmp_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    assert r.returncode == 0, r.stderr
    (tmp_path / ".env").write_text("SECRET=1", encoding="utf-8")
    r2 = subprocess.run(
        [sys.executable, str(script), "--root", str(tmp_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    assert r2.returncode == 1
