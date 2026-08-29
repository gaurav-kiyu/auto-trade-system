"""
Tests for AIEngine — LLM-powered signal enrichment engine.

Covers:
- AIEngineConfig dataclass and factory
- AIDecision dataclass
- _parse_llm_json: JSON extraction from LLM responses with markdown fences
- _PROVIDER_FNS dispatch
- AIEngine: disabled mode, cooldown, regime/strength bias
- enrich_signal: verdict, score delta, veto, journal append
- get_ai_engine / reset_ai_engine singleton factory
- load_journal_stats
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from core.ai_engine import (
    AIDecision,
    AIEngine,
    AIEngineConfig,
    _parse_llm_json,
    ai_engine_config_from_cfg,
    get_ai_engine,
    reset_ai_engine,
)

# ── AIEngineConfig ────────────────────────────────────────────────────────


class TestAIEngineConfig:
    def test_defaults(self):
        cfg = AIEngineConfig()
        assert cfg.enabled is False
        assert cfg.provider == "anthropic"
        assert cfg.model == "claude-haiku-4-5-20251001"
        assert cfg.signal_boost_max == 5
        assert cfg.veto_enabled is True
        assert cfg.journal_enabled is True
        assert cfg.batch_cooldown_ms == 1200

    def test_custom_values(self):
        cfg = AIEngineConfig(
            enabled=True,
            provider="openai",
            model="gpt-4",
            signal_boost_max=10,
            veto_enabled=False,
        )
        assert cfg.enabled is True
        assert cfg.provider == "openai"
        assert cfg.model == "gpt-4"
        assert cfg.signal_boost_max == 10

    def test_regime_bias_default(self):
        cfg = AIEngineConfig()
        assert cfg.regime_bias["TRENDING"] == 1.10
        assert cfg.regime_bias["CHOPPY"] == 0.90

    def test_strength_bias_default(self):
        cfg = AIEngineConfig()
        assert cfg.strength_bias["STRONG"] == 1.05
        assert cfg.strength_bias["WEAK"] == 0.90


class TestAiEngineConfigFromCfg:
    def test_empty_cfg(self):
        cfg = ai_engine_config_from_cfg({})
        assert cfg.enabled is False
        assert cfg.provider == "anthropic"

    def test_partial_overrides(self):
        cfg = ai_engine_config_from_cfg({"AI_ENGINE_ENABLED": True, "AI_ENGINE_PROVIDER": "ollama"})
        assert cfg.enabled is True
        assert cfg.provider == "ollama"
        # Unset keys should have defaults
        assert cfg.model == "claude-haiku-4-5-20251001"
        assert cfg.signal_boost_max == 5

    def test_regime_bias_override(self):
        cfg = ai_engine_config_from_cfg({
            "AI_ENGINE_REGIME_BIAS": {"TRENDING": 1.5, "NEUTRAL": 1.0},
        })
        assert cfg.regime_bias["TRENDING"] == 1.5
        assert cfg.regime_bias["NEUTRAL"] == 1.0

    def test_strength_bias_override(self):
        cfg = ai_engine_config_from_cfg({
            "AI_ENGINE_STRENGTH_BIAS": {"STRONG": 1.2, "WEAK": 0.80},
        })
        assert cfg.strength_bias["STRONG"] == 1.2
        assert cfg.strength_bias["WEAK"] == 0.80


# ── AIDecision Dataclass ──────────────────────────────────────────────────


class TestAIDecision:
    def test_creation(self):
        d = AIDecision(
            symbol="NIFTY",
            verdict="TRADE",
            score_delta=3,
            reasoning="Strong momentum",
            provider="anthropic",
            model="claude-3",
            latency_ms=450,
            raw_signal_score=70,
            final_score=73,
        )
        assert d.verdict == "TRADE"
        assert d.score_delta == 3
        assert d.final_score == 73


# ── _parse_llm_json ──────────────────────────────────────────────────────


class TestParseLlmJson:
    def test_plain_json(self):
        result = _parse_llm_json('{"verdict": "TRADE", "score_delta": 2}')
        assert result == {"verdict": "TRADE", "score_delta": 2}

    def test_json_with_markdown_fences(self):
        raw = "```json\n{\"verdict\": \"SKIP\", \"score_delta\": -3}\n```"
        result = _parse_llm_json(raw)
        assert result == {"verdict": "SKIP", "score_delta": -3}

    def test_json_with_backtick_fences(self):
        raw = "```\n{\"verdict\": \"WATCH\", \"score_delta\": 0}\n```"
        result = _parse_llm_json(raw)
        assert result == {"verdict": "WATCH", "score_delta": 0}

    def test_text_before_json(self):
        raw = "Here is my analysis:\n{\"verdict\": \"TRADE\", \"score_delta\": 1}"
        result = _parse_llm_json(raw)
        assert result["verdict"] == "TRADE"

    def test_nested_json(self):
        raw = '{"verdict": "TRADE", "reasoning": "Strong {momentum}"}'
        result = _parse_llm_json(raw)
        assert result["verdict"] == "TRADE"

    def test_invalid_json_raises(self):
        with pytest.raises(json.JSONDecodeError):
            _parse_llm_json("not json at all")

    def test_empty_string_raises(self):
        with pytest.raises(json.JSONDecodeError):
            _parse_llm_json("")

    def test_fences_without_json_prefix(self):
        raw = "```{\"verdict\": \"TRADE\"}```"
        result = _parse_llm_json(raw)
        assert result["verdict"] == "TRADE"


# ── AIEngine Construction ─────────────────────────────────────────────────


class TestAIEngineConstruction:
    def test_disabled_by_default(self):
        cfg = AIEngineConfig(enabled=False)
        engine = AIEngine(cfg)
        assert engine._cfg.enabled is False

    def test_enabled_with_known_provider(self):
        cfg = AIEngineConfig(enabled=True, provider="anthropic")
        engine = AIEngine(cfg, log_fn=lambda msg: None)
        assert engine._cfg.enabled is True
        assert engine._call_fn is not None

    def test_unknown_provider_disables_engine(self):
        cfg = AIEngineConfig(enabled=True, provider="unknown_llm")
        engine = AIEngine(cfg, log_fn=lambda msg: None)
        assert engine._cfg.enabled is False  # auto-disabled

    def test_creates_journal_parent_dir(self, tmp_path: Path):
        journal = tmp_path / "sub" / "ai_decisions.jsonl"
        cfg = AIEngineConfig(enabled=False, journal_file=str(journal))
        AIEngine(cfg, log_fn=lambda msg: None)
        assert (tmp_path / "sub").exists()

    def test_custom_log_fn(self):
        msgs = []
        cfg = AIEngineConfig(enabled=False)
        engine = AIEngine(cfg, log_fn=lambda msg: msgs.append(msg))
        assert engine._log is not None


# ── enrich_signal — Disabled / Errors ─────────────────────────────────────


class TestEnrichSignalDisabled:
    @pytest.fixture
    def engine(self) -> AIEngine:
        return AIEngine(AIEngineConfig(enabled=False), log_fn=lambda msg: None)

    def test_disabled_returns_signal_unmodified(self, engine: AIEngine):
        signal = {"score": 70, "direction": "CALL"}
        result = engine.enrich_signal("NIFTY", signal)
        assert result == signal
        assert "ai_verdict" not in result

    def test_no_call_fn_returns_unmodified(self):
        cfg = AIEngineConfig(enabled=True, provider="unknown")
        engine = AIEngine(cfg, log_fn=lambda msg: None)
        signal = {"score": 60}
        result = engine.enrich_signal("NIFTY", signal)
        assert result == signal


# ── Helper: create engine with mocked _call_fn ───────────────────────────


def _make_engine(cfg_overrides: dict | None = None, return_value: str = '{"verdict": "WATCH", "score_delta": 0, "reasoning": ""}') -> AIEngine:
    """Create an AIEngine with a mocked _call_fn that returns the given JSON."""
    cfg_dict = {"AI_ENGINE_ENABLED": True, "AI_ENGINE_PROVIDER": "anthropic"}
    if cfg_overrides:
        cfg_dict.update(cfg_overrides)
    cfg = ai_engine_config_from_cfg(cfg_dict)
    engine = AIEngine(cfg, log_fn=lambda msg: None)
    engine._call_fn = MagicMock(return_value=return_value)
    return engine


# ── enrich_signal — Regime/Strength Bias ─────────────────────────────────


class TestEnrichSignalBias:
    def test_regime_bias_applied(self):
        """TRENDING regime gets 1.10 multiplier on score."""
        engine = _make_engine()
        result = engine.enrich_signal("NIFTY", {"score": 50, "mkt_regime": "TRENDING", "strength": "MODERATE"})
        # 50 * 1.10 (trending) * 1.00 (moderate) = 55, then delta 0 → 55
        assert result["score"] == 55

    def test_strength_bias_applied(self):
        engine = _make_engine()
        result = engine.enrich_signal("NIFTY", {"score": 50, "mkt_regime": "NEUTRAL", "strength": "STRONG"})
        # 50 * 1.00 (neutral) * 1.05 (strong) = 52, then delta 0 → 52
        assert result["score"] == 52

    def test_regime_and_strength_compound(self):
        engine = _make_engine()
        result = engine.enrich_signal("NIFTY", {"score": 50, "mkt_regime": "TRENDING", "strength": "STRONG"})
        # 50 * 1.10 (trending) * 1.05 (strong) = 57.75 → 58 (rounded)
        assert result["score"] == 58  # round(57.75) = 58


# ── enrich_signal — Verdict and Delta ────────────────────────────────────


class TestEnrichSignalVerdict:
    def test_trade_verdict_adds_delta(self):
        engine = _make_engine(return_value='{"verdict": "TRADE", "score_delta": 3, "reasoning": "Good setup"}')
        result = engine.enrich_signal("NIFTY", {"score": 50, "direction": "CALL"})
        assert result["ai_verdict"] == "TRADE"
        assert result["ai_score_delta"] == 3
        assert result["ai_vetoed"] is False

    def test_skip_verdict_with_veto(self):
        engine = _make_engine(
            {"AI_ENGINE_VETO_ENABLED": True},
            return_value='{"verdict": "SKIP", "score_delta": -5, "reasoning": "Too risky"}',
        )
        result = engine.enrich_signal("NIFTY", {"score": 50, "direction": "CALL"})
        assert result["ai_verdict"] == "SKIP"
        assert result["ai_vetoed"] is True
        assert result["score"] == 45  # 50 + (-5)

    def test_delta_clamped_to_boost_max(self):
        """Delta is clamped to signal_boost_max."""
        engine = _make_engine(
            {"AI_ENGINE_SIGNAL_BOOST_MAX": 5},
            return_value='{"verdict": "TRADE", "score_delta": 20, "reasoning": "Amazing"}',
        )
        result = engine.enrich_signal("NIFTY", {"score": 50, "direction": "CALL"})
        assert result["ai_score_delta"] == 5  # clamped to 5

    def test_veto_disabled_does_not_set_veto_flag(self):
        engine = _make_engine(
            {"AI_ENGINE_VETO_ENABLED": False},
            return_value='{"verdict": "SKIP", "score_delta": -3, "reasoning": "Skip"}',
        )
        result = engine.enrich_signal("NIFTY", {"score": 50})
        assert result["ai_vetoed"] is False

    def test_watch_verdict_preserves_score(self):
        engine = _make_engine(return_value='{"verdict": "WATCH", "score_delta": 0, "reasoning": "Borderline"}')
        result = engine.enrich_signal("NIFTY", {"score": 50})
        assert result["ai_verdict"] == "WATCH"
        assert result["ai_vetoed"] is False

    def test_llm_error_falls_back_gracefully(self):
        """LLM call failure returns signal unmodified."""
        engine = _make_engine(return_value='irrelevant')
        engine._call_fn = MagicMock(side_effect=ConnectionError("API timeout"))
        signal = {"score": 50, "direction": "CALL"}
        result = engine.enrich_signal("NIFTY", signal)
        assert "ai_verdict" not in result

    def test_invalid_llm_json_falls_back(self):
        """Unparseable LLM response returns signal unmodified."""
        engine = _make_engine(return_value="not valid json at all")
        signal = {"score": 50}
        result = engine.enrich_signal("NIFTY", signal)
        assert "ai_verdict" not in result


# ── enrich_signal — Journaling ────────────────────────────────────────────


class TestEnrichSignalJournal:
    def test_journal_appended_on_success(self, tmp_path: Path):
        journal = tmp_path / "journal.jsonl"
        engine = _make_engine(
            {"AI_ENGINE_JOURNAL_FILE": str(journal), "AI_ENGINE_JOURNAL_ENABLED": True},
            return_value='{"verdict": "TRADE", "score_delta": 2, "reasoning": "Good"}',
        )
        engine.enrich_signal("NIFTY", {"score": 50})
        assert journal.exists()
        data = json.loads(journal.read_text(encoding="utf-8"))
        assert data["symbol"] == "NIFTY"
        assert data["verdict"] == "TRADE"

    def test_journal_disabled_no_write(self, tmp_path: Path):
        journal = tmp_path / "journal.jsonl"
        engine = _make_engine(
            {"AI_ENGINE_JOURNAL_FILE": str(journal), "AI_ENGINE_JOURNAL_ENABLED": False},
            return_value='{"verdict": "TRADE", "score_delta": 1, "reasoning": "ok"}',
        )
        engine.enrich_signal("NIFTY", {"score": 50})
        assert not journal.exists()


# ── load_journal_stats ────────────────────────────────────────────────────


class TestLoadJournalStats:
    def test_no_journal_file(self, tmp_path: Path):
        cfg = AIEngineConfig(enabled=False, journal_file=str(tmp_path / "nonexistent.jsonl"))
        engine = AIEngine(cfg, log_fn=lambda msg: None)
        stats = engine.load_journal_stats(lookback=100)
        assert stats["count"] == 0

    def test_reads_entries(self, tmp_path: Path):
        journal = tmp_path / "journal.jsonl"
        journal.write_text(
            json.dumps({"verdict": "TRADE", "score_delta": 3}) + "\n"
            + json.dumps({"verdict": "SKIP", "score_delta": -2}) + "\n",
            encoding="utf-8",
        )
        cfg = AIEngineConfig(enabled=False, journal_file=str(journal))
        engine = AIEngine(cfg, log_fn=lambda msg: None)
        stats = engine.load_journal_stats(lookback=100)
        assert stats["count"] == 2
        assert stats["trade_pct"] == 50.0
        assert stats["skip_pct"] == 50.0
        assert stats["avg_delta"] == 0.5  # (3 + (-2)) / 2

    def test_lookback_limit(self, tmp_path: Path):
        journal = tmp_path / "journal.jsonl"
        lines = "\n".join(
            json.dumps({"verdict": "TRADE", "score_delta": 1}) for _ in range(10)
        )
        journal.write_text(lines + "\n", encoding="utf-8")
        cfg = AIEngineConfig(enabled=False, journal_file=str(journal))
        engine = AIEngine(cfg, log_fn=lambda msg: None)
        stats = engine.load_journal_stats(lookback=3)
        assert stats["count"] == 3  # limited to last 3


# ── Cooldown ──────────────────────────────────────────────────────────────


class TestCooldown:
    def test_cooldown_respected(self):
        """Cooldown between calls triggers sleep."""
        with patch("core.ai_engine.time.sleep") as mock_sleep:
            with patch("core.ai_engine.time.monotonic", return_value=100.0):
                cfg = ai_engine_config_from_cfg({
                    "AI_ENGINE_ENABLED": True,
                    "AI_ENGINE_PROVIDER": "anthropic",
                    "AI_ENGINE_BATCH_COOLDOWN_MS": 5000,
                })
                engine = AIEngine(cfg, log_fn=lambda msg: None)
                engine._call_fn = MagicMock(return_value='{"verdict": "WATCH"}')
                engine.enrich_signal("NIFTY", {"score": 50})
                engine.enrich_signal("NIFTY", {"score": 50})
                # Second call should have elapsed=0.0 (< 5s cooldown) → sleep triggered
                assert mock_sleep.called

    def test_first_call_no_cooldown(self):
        with patch("core.ai_engine.time.sleep") as mock_sleep:
            cfg = ai_engine_config_from_cfg({
                "AI_ENGINE_ENABLED": True,
                "AI_ENGINE_PROVIDER": "anthropic",
                "AI_ENGINE_BATCH_COOLDOWN_MS": 5000,
            })
            engine = AIEngine(cfg, log_fn=lambda msg: None)
            engine._last_call_ts = 0.0  # Ensure no recent call
            engine._wait_cooldown()
            assert not mock_sleep.called


# ── Singleton Factory ─────────────────────────────────────────────────────


class TestSingleton:
    def test_get_ai_engine_returns_instance(self):
        reset_ai_engine()
        engine = get_ai_engine({"AI_ENGINE_ENABLED": True, "AI_ENGINE_PROVIDER": "anthropic"})
        assert isinstance(engine, AIEngine)

    def test_get_ai_engine_singleton(self):
        reset_ai_engine()
        e1 = get_ai_engine({"AI_ENGINE_ENABLED": False})
        e2 = get_ai_engine({"AI_ENGINE_ENABLED": False})
        assert e1 is e2

    def test_reset_ai_engine_clears_singleton(self):
        reset_ai_engine()
        e1 = get_ai_engine({"AI_ENGINE_ENABLED": False})
        reset_ai_engine()
        e2 = get_ai_engine({"AI_ENGINE_ENABLED": False})
        assert e1 is not e2


# ── LLM Provider Dispatch ─────────────────────────────────────────────────


class TestProviderDispatch:
    def test_provider_fns_contains_known(self):
        from core.ai_engine import _PROVIDER_FNS
        assert "anthropic" in _PROVIDER_FNS
        assert "openai" in _PROVIDER_FNS
        assert "ollama" in _PROVIDER_FNS
        assert "http" in _PROVIDER_FNS

    def test_unknown_provider_returns_none(self):
        cfg = AIEngineConfig(enabled=True, provider="unknown")
        engine = AIEngine(cfg, log_fn=lambda msg: None)
        assert engine._call_fn is None


# ── Helper: mock urlopen response ──────────────────────────────────────────


class _MockUrlopenResponse:
    """A file-like object that mimics urllib.request.urlopen response.
    Supports the context manager protocol for use with 'with' statements."""
    def __init__(self, data: dict):
        self._body = json.dumps(data).encode()

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _MockUrlopenResponse:
        return self

    def __exit__(self, *args) -> None:
        pass


# ── Provider Functions (Direct Unit Tests) ───────────────────────────────


class TestProviderFunctions:
    """Tests for the 4 LLM provider functions using mocked HTTP."""

    def test_call_anthropic_mocked(self):
        """_call_anthropic extracts text from content blocks."""
        from core.ai_engine import _call_anthropic
        cfg = AIEngineConfig(api_key_env="ANTHROPIC_API_KEY")
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}):
            with patch("urllib.request.urlopen", return_value=_MockUrlopenResponse({
                "content": [{"type": "text", "text": '{"verdict": "TRADE"}'}]
            })):
                result = _call_anthropic("test prompt", cfg)
                assert "verdict" in result

    def test_call_anthropic_no_content_blocks(self):
        """_call_anthropic returns empty string when no text blocks."""
        from core.ai_engine import _call_anthropic
        cfg = AIEngineConfig(api_key_env="ANTHROPIC_API_KEY")
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}):
            with patch("urllib.request.urlopen", return_value=_MockUrlopenResponse({"content": []})):
                result = _call_anthropic("test prompt", cfg)
                assert result == ""

    def test_call_anthropic_empty_api_key_raises(self):
        """_call_anthropic raises RuntimeError when API key is empty."""
        from core.ai_engine import _call_anthropic
        cfg = AIEngineConfig(api_key_env="MISSING_KEY")
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(RuntimeError, match="API key env var"):
                _call_anthropic("test", cfg)

    def test_call_openai_mocked(self):
        """_call_openai extracts content from choices."""
        from core.ai_engine import _call_openai
        cfg = AIEngineConfig(api_key_env="OPENAI_API_KEY")
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            with patch("urllib.request.urlopen", return_value=_MockUrlopenResponse({
                "choices": [{"message": {"content": '{"verdict": "TRADE"}'}}]
            })):
                result = _call_openai("test prompt", cfg)
                assert "verdict" in result

    def test_call_openai_empty_api_key_raises(self):
        """_call_openai raises RuntimeError when API key is empty."""
        from core.ai_engine import _call_openai
        cfg = AIEngineConfig(api_key_env="MISSING_KEY")
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(RuntimeError, match="API key env var"):
                _call_openai("test", cfg)

    def test_call_ollama_mocked(self):
        """_call_ollama extracts response field."""
        from core.ai_engine import _call_ollama
        cfg = AIEngineConfig(api_key_env="")
        with patch("urllib.request.urlopen", return_value=_MockUrlopenResponse({
            "response": '{"verdict": "WATCH"}'
        })):
            result = _call_ollama("test prompt", cfg)
            assert "verdict" in result

    def test_call_ollama_default_base_url(self):
        """_call_ollama uses localhost:11434 when no base URL set."""
        from core.ai_engine import _call_ollama
        cfg = AIEngineConfig(api_key_env="")
        with patch("urllib.request.urlopen", return_value=_MockUrlopenResponse({"response": "ok"})) as mock_urlopen:
            _call_ollama("test", cfg)
            call_args = mock_urlopen.call_args[0][0].full_url
            assert "localhost:11434" in call_args

    def test_call_http_mocked(self):
        """_call_http extracts from text/content/response fields."""
        from core.ai_engine import _call_http
        cfg = AIEngineConfig(api_key_env="", api_base_url="http://custom:8080/api")
        with patch("urllib.request.urlopen", return_value=_MockUrlopenResponse({
            "text": '{"verdict": "SKIP"}'
        })):
            result = _call_http("test prompt", cfg)
            assert "verdict" in result

    def test_call_http_no_base_url_raises(self):
        """_call_http raises RuntimeError when no base URL set."""
        from core.ai_engine import _call_http
        cfg = AIEngineConfig(api_key_env="")
        with pytest.raises(RuntimeError, match="API_BASE_URL must be set"):
            _call_http("test", cfg)


# ── Journal Rotation ─────────────────────────────────────────────────────


class TestJournalRotation:
    def test_rotate_journal_when_large(self, tmp_path: Path):
        """Journal rotates when it exceeds max size."""
        journal = tmp_path / "journal.jsonl"
        # Create journal larger than 10 MB limit
        with open(journal, "wb") as f:
            f.write(b"x" * (11 * 1024 * 1024))  # 11 MB

        cfg = AIEngineConfig(
            enabled=True, provider="anthropic",
            journal_file=str(journal), journal_enabled=True,
        )
        engine = AIEngine(cfg, log_fn=lambda msg: None)
        engine._call_fn = MagicMock(return_value='{"verdict": "WATCH", "score_delta": 0}')

        engine.enrich_signal("NIFTY", {"score": 50})

        # After rotation + append:
        # - Old file was renamed to archive (timestamped)
        # - New file created at journal path (with the decision line)
        # So journal.exists() is True (the new file), but there should also be an archive
        assert journal.exists()
        assert journal.stat().st_size < 1024  # new file is small (just the decision line)
        # There should be at least one archive file (old 11MB data renamed)
        archives = [p for p in tmp_path.iterdir() if p.suffix == ".jsonl" and p != journal]
        assert len(archives) >= 1
        # Archive should be large (the old 11MB data)
        assert archives[0].stat().st_size >= 10 * 1024 * 1024

    def test_rotate_journal_small_no_rotation(self, tmp_path: Path):
        """Small journal is not rotated."""
        journal = tmp_path / "small.jsonl"
        journal.write_text('{"test": "data"}\n', encoding="utf-8")

        cfg = AIEngineConfig(
            enabled=True, provider="anthropic",
            journal_file=str(journal), journal_enabled=True,
        )
        engine = AIEngine(cfg, log_fn=lambda msg: None)
        engine._call_fn = MagicMock(return_value='{"verdict": "WATCH", "score_delta": 0}')

        engine.enrich_signal("NIFTY", {"score": 50})
        # Original should still exist
        assert journal.exists()

    def test_rotate_journal_oserror_caught(self, tmp_path: Path):
        """OSError during rotation is caught and logged."""
        msgs = []
        journal = tmp_path / "rotated.jsonl"
        journal.write_text("x" * (11 * 1024 * 1024), encoding="utf-8")  # > 10 MB

        cfg = AIEngineConfig(
            enabled=True, provider="anthropic",
            journal_file=str(journal), journal_enabled=True,
        )
        engine = AIEngine(cfg, log_fn=lambda msg: msgs.append(msg))
        engine._call_fn = MagicMock(return_value='{"verdict": "WATCH", "score_delta": 0}')

        # Patch the _journal_path.rename to fail
        with patch.object(Path, "rename", side_effect=OSError("Permission denied")):
            engine.enrich_signal("NIFTY", {"score": 50})
        # Should have logged the error
        assert any("failed" in m.lower() for m in msgs), msgs


# ── Enrich Signal Edge Cases ─────────────────────────────────────────────


class TestEnrichSignalEdgeCases:
    """Tests for edge cases in enrich_signal: CHOPPY regime, missing fields, etc."""

    def test_choppy_regime_lower_score(self):
        """CHOPPY regime reduces score via bias multiplier."""
        engine = _make_engine()
        result = engine.enrich_signal("NIFTY", {"score": 50, "mkt_regime": "CHOPPY", "strength": "WEAK"})
        # 50 * 0.90 (choppy) * 0.90 (weak) = 40.5 → 40
        assert result["score"] == 40

    def test_signal_missing_regime_and_strength(self):
        """Missing regime/strength defaults to NEUTRAL/MODERATE."""
        engine = _make_engine()
        result = engine.enrich_signal("NIFTY", {"score": 50})
        # 50 * 1.00 (NEUTRAL default) * 1.00 (MODERATE default) = 50
        assert result["score"] == 50

    def test_unknown_verdict_normalized_to_watch(self):
        """Unknown verdict from LLM is normalized to WATCH."""
        engine = _make_engine(return_value='{"verdict": "INVALID", "score_delta": 5}')
        result = engine.enrich_signal("NIFTY", {"score": 50, "direction": "CALL"})
        assert result["ai_verdict"] == "WATCH"
        assert result["ai_score_delta"] == 5

    def test_skip_verdict_no_veto_still_adds_delta(self):
        """Without veto, SKIP adds delta but doesn't set veto flag."""
        engine = _make_engine(
            {"AI_ENGINE_VETO_ENABLED": False},
            return_value='{"verdict": "SKIP", "score_delta": -3, "reasoning": "Not great"}',
        )
        result = engine.enrich_signal("NIFTY", {"score": 50, "direction": "CALL"})
        assert result["ai_verdict"] == "SKIP"
        assert result["ai_vetoed"] is False  # veto disabled
        assert result["ai_score_delta"] == -3

    def test_enrich_signal_logs_on_llm_error(self):
        """LLM call failure logs a warning without crashing."""
        msgs = []
        cfg = ai_engine_config_from_cfg({"AI_ENGINE_ENABLED": True, "AI_ENGINE_PROVIDER": "anthropic"})
        engine = AIEngine(cfg, log_fn=lambda msg: msgs.append(msg))
        engine._call_fn = MagicMock(side_effect=TimeoutError("timed out"))
        result = engine.enrich_signal("NIFTY", {"score": 50})
        assert "ai_verdict" not in result  # returns unmodified
        assert any("failed" in m.lower() for m in msgs), msgs

    def test_enrich_signal_negative_delta_clamped(self):
        """Negative delta is clamped to -signal_boost_max."""
        engine = _make_engine(
            {"AI_ENGINE_SIGNAL_BOOST_MAX": 3},
            return_value='{"verdict": "SKIP", "score_delta": -10, "reasoning": "Terrible"}',
        )
        result = engine.enrich_signal("NIFTY", {"score": 50, "direction": "CALL"})
        assert result["ai_score_delta"] == -3  # clamped to -3


# ── load_journal_stats Edge Cases ────────────────────────────────────────


class TestLoadJournalStatsEdgeCases:
    def test_journal_oserror_returns_empty(self, tmp_path: Path):
        """OSError during journal read returns count 0."""
        journal = tmp_path / "broken.jsonl"
        journal.write_text("data\n", encoding="utf-8")
        cfg = AIEngineConfig(enabled=False, journal_file=str(journal))
        engine = AIEngine(cfg, log_fn=lambda msg: None)
        with patch.object(Path, "read_text", side_effect=OSError("disk error")):
            stats = engine.load_journal_stats(lookback=100)
            assert stats["count"] == 0

    def test_journal_parse_errors_skipped(self, tmp_path: Path):
        """Malformed JSON lines in journal are skipped gracefully."""
        journal = tmp_path / "mixed.jsonl"
        journal.write_text(
            '{"verdict": "TRADE", "score_delta": 3}\n'
            + "not valid json\n"
            + '{"verdict": "SKIP", "score_delta": -2}\n',
            encoding="utf-8",
        )
        cfg = AIEngineConfig(enabled=False, journal_file=str(journal))
        engine = AIEngine(cfg, log_fn=lambda msg: None)
        stats = engine.load_journal_stats(lookback=100)
        assert stats["count"] == 2  # only valid lines counted
        assert stats["avg_delta"] == 0.5  # (3 + (-2)) / 2
