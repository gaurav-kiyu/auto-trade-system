"""Tests for scripts/paper_session_review.py completion alert.

Covers:
- Telegram credential resolution (env → config.local.json → config.json,
  placeholder detection)
- Completion message formatting (success/failure)
- send_completion_alert(): send success, graceful skips, never-raises
- --no-alert / OPBUYING_TG_COMPLETION_ALERT disable paths
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "paper_session_review", ROOT / "scripts" / "paper_session_review.py"
)
assert SPEC is not None and SPEC.loader is not None
psr = importlib.util.module_from_spec(SPEC)
sys.modules["paper_session_review"] = psr
SPEC.loader.exec_module(psr)


# ── Fixtures / helpers ───────────────────────────────────────────────────────

def _write_config(tmp_path: Path, name: str, data: dict) -> Path:
    # Config files live under the json/ folder in the new layout
    cfg_dir = tmp_path / "json"
    cfg_dir.mkdir(exist_ok=True)
    cfg = cfg_dir / name
    cfg.write_text(json.dumps(data), encoding="utf-8")
    return cfg


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch, tmp_path):
    """Ensure no ambient Telegram credentials leak into tests and config
    lookups point at an empty temp dir by default."""
    monkeypatch.delenv(psr.TG_ENV_TOKEN, raising=False)
    monkeypatch.delenv(psr.TG_ENV_CHAT_ID, raising=False)
    monkeypatch.delenv(psr.TG_ALERT_DISABLE_ENV, raising=False)
    monkeypatch.setattr(psr, "ROOT", tmp_path)


# ── _is_real_credential ──────────────────────────────────────────────────────

class TestIsRealCredential:
    @pytest.mark.parametrize("value", [
        "", None, "YOUR_TELEGRAM_BOT_TOKEN", "your_telegram_bot_token",
        "YOUR_TELEGRAM_CHAT_ID", "your_telegram_chat_id", "YOUR_CHAT_ID",
    ])
    def test_placeholders_rejected(self, value):
        assert psr._is_real_credential(value) is False

    def test_real_value_accepted(self):
        assert psr._is_real_credential("123456:ABC-DEF_xyz") is True
        assert psr._is_real_credential("-1001234567890") is True


# ── _load_tg_credentials ─────────────────────────────────────────────────────

class TestLoadTgCredentials:
    def test_env_wins(self, monkeypatch):
        monkeypatch.setenv(psr.TG_ENV_TOKEN, "env_token")
        monkeypatch.setenv(psr.TG_ENV_CHAT_ID, "-100env")
        token, chat = psr._load_tg_credentials()
        assert (token, chat) == ("env_token", "-100env")

    def test_placeholder_env_falls_back_to_config(self, monkeypatch, tmp_path):
        monkeypatch.setenv(psr.TG_ENV_TOKEN, "YOUR_TELEGRAM_BOT_TOKEN")
        cfg = _write_config(tmp_path, "config.local.json", {
            "BOT_TOKEN": "cfg_token", "TG_CHAT_ID": "-100cfg",
        })
        monkeypatch.setattr(psr, "ROOT", tmp_path)
        token, chat = psr._load_tg_credentials()
        assert (token, chat) == ("cfg_token", "-100cfg")
        assert cfg.exists()

    def test_local_overrides_base(self, monkeypatch, tmp_path):
        _write_config(tmp_path, "config.json", {
            "BOT_TOKEN": "base_token", "TG_CHAT_ID": "-100base",
        })
        _write_config(tmp_path, "config.local.json", {
            "BOT_TOKEN": "local_token", "TG_CHAT_ID": "-100local",
        })
        monkeypatch.setattr(psr, "ROOT", tmp_path)
        token, chat = psr._load_tg_credentials()
        assert (token, chat) == ("local_token", "-100local")

    def test_chat_id_fallback_to_chat_id_key(self, monkeypatch, tmp_path):
        _write_config(tmp_path, "config.json", {
            "BOT_TOKEN": "tok", "CHAT_ID": "-100direct",
        })
        monkeypatch.setattr(psr, "ROOT", tmp_path)
        token, chat = psr._load_tg_credentials()
        assert (token, chat) == ("tok", "-100direct")

    def test_nothing_configured(self, monkeypatch, tmp_path):
        monkeypatch.setattr(psr, "ROOT", tmp_path)
        assert psr._load_tg_credentials() == ("", "")


# ── _extract_json ────────────────────────────────────────────────────────────

class TestExtractJson:
    def test_clean_json(self):
        payload = '{"overall_status": "OK", "checks": [1, 2, 3]}'
        assert psr._extract_json(payload) == {"overall_status": "OK", "checks": [1, 2, 3]}

    def test_log_line_prepended(self):
        # Regression: health_checker interleaves log lines before the JSON payload
        raw = (
            '2026-08-10 16:54:57 [INFO] core.news_sentinel: [NEWS] NewsSentinel started\r\n'
            '{"overall_status": "FAIL", "results": [{"name": "trades.db size", "status": "OK"}]}'
        )
        assert psr._extract_json(raw) == {
            "overall_status": "FAIL",
            "results": [{"name": "trades.db size", "status": "OK"}],
        }

    def test_log_line_appended(self):
        raw = '{"ok": true}\r\n[INFO] trailing log noise'
        assert psr._extract_json(raw) == {"ok": True}

    def test_braces_inside_strings(self):
        raw = 'prefix noise {"msg": "curly { brace", "n": 1} suffix'
        assert psr._extract_json(raw) == {"msg": "curly { brace", "n": 1}

    def test_no_json_returns_none(self):
        assert psr._extract_json("") is None
        assert psr._extract_json(None) is None
        assert psr._extract_json("just some log text with no braces") is None

    def test_nested_object(self):
        raw = 'noise\n{"a": {"b": {"c": [1, 2]}}, "d": "e"}\nmore noise'
        assert psr._extract_json(raw) == {"a": {"b": {"c": [1, 2]}}, "d": "e"}


# ── _build_completion_message ────────────────────────────────────────────────

class TestBuildCompletionMessage:
    def test_success(self):
        msg = psr._build_completion_message({
            "date": "20260811", "mode": "PAPER", "exit_code": 0,
            "duration_min": 380.5, "stop_reason": "scheduled stop at 15:25 IST",
            "log_file": "logs/paper_session_20260811.log",
            "summary_file": "reports/paper_trading/session_20260811.json",
        })
        assert "PAPER SESSION COMPLETE" in msg
        assert "SUCCESS" in msg and "exit 0" in msg
        assert "380.5 min" in msg
        assert "scheduled stop at 15:25 IST" in msg
        assert "session_20260811.json" in msg

    def test_failure(self):
        msg = psr._build_completion_message({
            "date": "20260811", "mode": "PAPER", "exit_code": 1,
            "duration_min": 5, "stop_reason": "test mode", "log_file": "x", "summary_file": "y",
        })
        assert "FAILED" in msg and "exit 1" in msg

    def test_defaults_when_missing(self):
        msg = psr._build_completion_message({"exit_code": 0})
        assert "PAPER SESSION COMPLETE" in msg
        assert "Date      : ?" in msg


# ── send_completion_alert ────────────────────────────────────────────────────

class _FakeClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.sent = []
        self.closed = False

    def send_raw(self, text, chat_id=None, critical=False):
        self.sent.append((text, chat_id, critical))
        return True

    def close(self):
        self.closed = True


class _FailingClient(_FakeClient):
    def send_raw(self, text, chat_id=None, critical=False):
        raise ConnectionError("simulated network failure")


class TestSendCompletionAlert:
    def test_disabled_via_env(self, monkeypatch):
        monkeypatch.setenv(psr.TG_ALERT_DISABLE_ENV, "false")
        result = psr.send_completion_alert({"exit_code": 0})
        assert result["sent"] is False
        assert "disabled" in result["detail"].lower()

    def test_not_configured_graceful(self):
        # autouse fixture points ROOT at an empty temp dir - no config files
        result = psr.send_completion_alert({"exit_code": 0})
        assert result["sent"] is False
        assert "not configured" in result["detail"]

    def test_send_success(self, monkeypatch, tmp_path):
        _write_config(tmp_path, "config.local.json", {
            "BOT_TOKEN": "tok123:abc", "TG_CHAT_ID": "-100cfg",
        })
        import infrastructure.adapters.notifications.telegram_adapter as tg_mod
        monkeypatch.setattr(tg_mod, "_TelegramClient", _FakeClient)
        result = psr.send_completion_alert({
            "date": "20260811", "mode": "PAPER", "exit_code": 0,
            "duration_min": 10, "stop_reason": "test", "log_file": "l", "summary_file": "s",
        })
        assert result == {"sent": True, "detail": "sent"}

    def test_send_failure_reported_not_raised(self, monkeypatch, tmp_path):
        _write_config(tmp_path, "config.local.json", {
            "BOT_TOKEN": "tok", "TG_CHAT_ID": "-100x",
        })
        import infrastructure.adapters.notifications.telegram_adapter as tg_mod
        monkeypatch.setattr(tg_mod, "_TelegramClient", _FailingClient)
        result = psr.send_completion_alert({"exit_code": 0})
        assert result["sent"] is False
        assert "simulated network failure" in result["detail"]

    def test_send_api_rejected(self, monkeypatch, tmp_path):
        class _RejectClient(_FakeClient):
            def send_raw(self, text, chat_id=None, critical=False):
                return False

        _write_config(tmp_path, "config.local.json", {
            "BOT_TOKEN": "tok", "TG_CHAT_ID": "-100x",
        })
        import infrastructure.adapters.notifications.telegram_adapter as tg_mod
        monkeypatch.setattr(tg_mod, "_TelegramClient", _RejectClient)
        result = psr.send_completion_alert({"exit_code": 0})
        assert result["sent"] is False
        assert "rejected" in result["detail"]


# ── main() --no-alert flag acceptance ────────────────────────────────────────

class TestNoAlertFlag:
    def test_no_alert_wired_in_source(self):
        """Drift guard: the real module must register --no-alert and the env
        disable hook so --no-alert/OPBUYING_TG_COMPLETION_ALERT actually work."""
        src = (ROOT / "scripts" / "paper_session_review.py").read_text(encoding="utf-8")
        assert 'add_argument("--no-alert"' in src
        assert "OPBUYING_TG_COMPLETION_ALERT" in src


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
