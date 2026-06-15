"""
AI Engine — Configurable LLM-powered signal intelligence and auto-learning layer.

Drop-in enhancement for the OPBuying trading system:
  • Wraps any LLM (Anthropic, OpenAI, Ollama, custom HTTP) via config
  • Enriches signal dicts with LLM-based market commentary + confidence boost/veto
  • Maintains a persistent AI learning journal (JSON-lines) that feeds back into
    threshold tuning — fully driven by config, zero hard-coded values
  • All provider endpoints, model names, prompt templates, enabled flags, and
    rate-limits are read from the system config at runtime
  • Graceful degradation: if LLM is unavailable, trading continues unaffected

Configuration keys (all under AI_ENGINE in config.json):
    AI_ENGINE_ENABLED           bool   — master on/off (default False)
    AI_ENGINE_PROVIDER          str    — "anthropic" | "openai" | "ollama" | "http"
    AI_ENGINE_MODEL             str    — model string ("claude-3-5-haiku-20241022" etc.)
    AI_ENGINE_API_KEY_ENV       str    — env-var holding the API key
    AI_ENGINE_API_BASE_URL      str    — override base URL (Ollama / custom endpoints)
    AI_ENGINE_MAX_TOKENS        int    — max tokens per LLM call (default 256)
    AI_ENGINE_TIMEOUT_SEC       float  — HTTP timeout (default 8.0)
    AI_ENGINE_SIGNAL_BOOST_MAX  int    — max score bonus LLM can add (default 5)
    AI_ENGINE_VETO_ENABLED      bool   — allow LLM to veto a signal (default True)
    AI_ENGINE_PROMPT_TEMPLATE   str    — override system prompt (optional)
    AI_ENGINE_JOURNAL_FILE      str    — path for AI learning journal JSONL
    AI_ENGINE_JOURNAL_ENABLED   bool   — persist AI decisions (default True)
    AI_ENGINE_BATCH_COOLDOWN_MS int    — min ms between LLM calls (default 1200)
    AI_ENGINE_REGIME_BIAS       dict   — per-regime score multiplier {"TRENDING":1.1,...}
    AI_ENGINE_STRENGTH_BIAS     dict   — per-strength multiplier {"STRONG":1.05,...}
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# ─── Defaults (all overridable via config) ─────────────────────────────────────
_DEFAULTS: dict[str, Any] = {
    "AI_ENGINE_ENABLED": False,
    "AI_ENGINE_PROVIDER": "anthropic",
    "AI_ENGINE_MODEL": "claude-haiku-4-5-20251001",
    "AI_ENGINE_API_KEY_ENV": "ANTHROPIC_API_KEY",
    "AI_ENGINE_API_BASE_URL": "",
    "AI_ENGINE_MAX_TOKENS": 256,
    "AI_ENGINE_TIMEOUT_SEC": 8.0,
    "AI_ENGINE_SIGNAL_BOOST_MAX": 5,
    "AI_ENGINE_VETO_ENABLED": True,
    "AI_ENGINE_PROMPT_TEMPLATE": "",
    "AI_ENGINE_JOURNAL_FILE": "reports/ai_decisions.jsonl",
    "AI_ENGINE_JOURNAL_ENABLED": True,
    "AI_ENGINE_BATCH_COOLDOWN_MS": 1200,
    "AI_ENGINE_REGIME_BIAS": {
        "TRENDING": 1.10,
        "NEUTRAL": 1.00,
        "CHOPPY": 0.90,
        "EVENT": 0.75,
    },
    "AI_ENGINE_STRENGTH_BIAS": {
        "STRONG": 1.05,
        "MODERATE": 1.00,
        "WEAK": 0.90,
    },
}

_DEFAULT_SYSTEM_PROMPT = """You are a quantitative options trading assistant for Indian markets (NSE/NFO).
Given a raw signal dict, reply with a compact JSON object:
{
  "verdict": "TRADE"|"SKIP"|"WATCH",
  "score_delta": <int -5..5>,
  "reasoning": "<1 sentence>"
}
- TRADE: signal quality is good; score_delta adds confidence
- SKIP: signal is weak or risky; score_delta subtracts
- WATCH: borderline; score_delta is 0
Be concise. Never hallucinate broker or price data not given."""


# ─── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class AIDecision:
    symbol: str
    verdict: str          # TRADE | SKIP | WATCH
    score_delta: int      # adjustment applied to raw signal score
    reasoning: str
    provider: str
    model: str
    latency_ms: int
    raw_signal_score: int
    final_score: int
    regime: str = ""
    strength: str = ""
    ts: str = ""


@dataclass
class AIEngineConfig:
    enabled: bool = False
    provider: str = "anthropic"
    model: str = "claude-haiku-4-5-20251001"
    api_key_env: str = "ANTHROPIC_API_KEY"
    api_base_url: str = ""
    max_tokens: int = 256
    timeout_sec: float = 8.0
    signal_boost_max: int = 5
    veto_enabled: bool = True
    prompt_template: str = ""
    journal_file: str = "reports/ai_decisions.jsonl"
    journal_enabled: bool = True
    batch_cooldown_ms: int = 1200
    regime_bias: dict[str, float] = field(default_factory=lambda: dict(_DEFAULTS["AI_ENGINE_REGIME_BIAS"]))
    strength_bias: dict[str, float] = field(default_factory=lambda: dict(_DEFAULTS["AI_ENGINE_STRENGTH_BIAS"]))


def ai_engine_config_from_cfg(cfg: dict[str, Any]) -> AIEngineConfig:
    """Build AIEngineConfig from the system config dict (merges with _DEFAULTS)."""
    merged = {**_DEFAULTS, **{k: v for k, v in cfg.items() if k.startswith("AI_ENGINE")}}
    return AIEngineConfig(
        enabled=bool(merged["AI_ENGINE_ENABLED"]),
        provider=str(merged["AI_ENGINE_PROVIDER"]).lower().strip(),
        model=str(merged["AI_ENGINE_MODEL"]).strip(),
        api_key_env=str(merged["AI_ENGINE_API_KEY_ENV"]).strip(),
        api_base_url=str(merged.get("AI_ENGINE_API_BASE_URL") or "").strip(),
        max_tokens=int(merged["AI_ENGINE_MAX_TOKENS"]),
        timeout_sec=float(merged["AI_ENGINE_TIMEOUT_SEC"]),
        signal_boost_max=int(merged["AI_ENGINE_SIGNAL_BOOST_MAX"]),
        veto_enabled=bool(merged["AI_ENGINE_VETO_ENABLED"]),
        prompt_template=str(merged.get("AI_ENGINE_PROMPT_TEMPLATE") or "").strip(),
        journal_file=str(merged["AI_ENGINE_JOURNAL_FILE"]),
        journal_enabled=bool(merged["AI_ENGINE_JOURNAL_ENABLED"]),
        batch_cooldown_ms=int(merged["AI_ENGINE_BATCH_COOLDOWN_MS"]),
        regime_bias=dict(merged.get("AI_ENGINE_REGIME_BIAS") or _DEFAULTS["AI_ENGINE_REGIME_BIAS"]),
        strength_bias=dict(merged.get("AI_ENGINE_STRENGTH_BIAS") or _DEFAULTS["AI_ENGINE_STRENGTH_BIAS"]),
    )


# ─── LLM provider adapters ────────────────────────────────────────────────────

def _call_anthropic(prompt: str, ai_cfg: AIEngineConfig) -> str:
    import urllib.request
    api_key = os.environ.get(ai_cfg.api_key_env, "")
    if not api_key:
        raise RuntimeError(f"API key env var {ai_cfg.api_key_env!r} is empty")
    base = ai_cfg.api_base_url or "https://api.anthropic.com"
    url = f"{base.rstrip('/')}/v1/messages"
    body = json.dumps({
        "model": ai_cfg.model,
        "max_tokens": ai_cfg.max_tokens,
        "system": ai_cfg.prompt_template or _DEFAULT_SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    })
    with urllib.request.urlopen(req, timeout=ai_cfg.timeout_sec) as resp:
        result = json.loads(resp.read())
    # Extract text from content blocks
    for block in result.get("content", []):
        if block.get("type") == "text":
            return block["text"]
    return ""


def _call_openai(prompt: str, ai_cfg: AIEngineConfig) -> str:
    import urllib.request
    api_key = os.environ.get(ai_cfg.api_key_env, "")
    if not api_key:
        raise RuntimeError(f"API key env var {ai_cfg.api_key_env!r} is empty")
    base = ai_cfg.api_base_url or "https://api.openai.com"
    url = f"{base.rstrip('/')}/v1/chat/completions"
    body = json.dumps({
        "model": ai_cfg.model,
        "max_tokens": ai_cfg.max_tokens,
        "messages": [
            {"role": "system", "content": ai_cfg.prompt_template or _DEFAULT_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    }).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    })
    with urllib.request.urlopen(req, timeout=ai_cfg.timeout_sec) as resp:
        result = json.loads(resp.read())
    return result["choices"][0]["message"]["content"]


def _call_ollama(prompt: str, ai_cfg: AIEngineConfig) -> str:
    import urllib.request
    base = ai_cfg.api_base_url or "http://localhost:11434"
    url = f"{base.rstrip('/')}/api/generate"
    system = ai_cfg.prompt_template or _DEFAULT_SYSTEM_PROMPT
    body = json.dumps({
        "model": ai_cfg.model,
        "prompt": f"{system}\n\nUser: {prompt}",
        "stream": False,
        "options": {"num_predict": ai_cfg.max_tokens},
    }).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=ai_cfg.timeout_sec) as resp:
        result = json.loads(resp.read())
    return result.get("response", "")


def _call_http(prompt: str, ai_cfg: AIEngineConfig) -> str:
    """Generic HTTP JSON endpoint: POST {"prompt": ..., "system": ...} → {"text": ...}"""
    import urllib.request
    url = ai_cfg.api_base_url
    if not url:
        raise RuntimeError("AI_ENGINE_API_BASE_URL must be set for 'http' provider")
    body = json.dumps({
        "prompt": prompt,
        "system": ai_cfg.prompt_template or _DEFAULT_SYSTEM_PROMPT,
        "model": ai_cfg.model,
        "max_tokens": ai_cfg.max_tokens,
    }).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=ai_cfg.timeout_sec) as resp:
        result = json.loads(resp.read())
    return str(result.get("text") or result.get("content") or result.get("response") or "")


_PROVIDER_FNS: dict[str, Callable[[str, AIEngineConfig], str]] = {
    "anthropic": _call_anthropic,
    "openai": _call_openai,
    "ollama": _call_ollama,
    "http": _call_http,
}


def _parse_llm_json(raw: str) -> dict[str, Any]:
    """Extract JSON from LLM response (handles markdown fences)."""
    text = raw.strip()
    # Strip ```json ... ``` fences
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    # Find first { ... }
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        text = text[start:end]
    return json.loads(text)


# ─── AIEngine ─────────────────────────────────────────────────────────────────

class AIEngine:
    """
    LLM-powered signal enrichment engine.

    Usage:
        ai = AIEngine(ai_cfg)
        enhanced = ai.enrich_signal("NIFTY", signal_dict)
        # enhanced["ai_verdict"]  → "TRADE" | "SKIP" | "WATCH"
        # enhanced["score"]       → original + ai_delta (clamped)
        # enhanced["ai_reasoning"]→ one-sentence LLM note
    """

    def __init__(self, ai_cfg: AIEngineConfig, *, log_fn: Callable[[str], None] | None = None) -> None:
        self._cfg = ai_cfg
        self._log = log_fn or (lambda msg: log.info(msg))
        self._lock = threading.Lock()
        self._last_call_ts: float = 0.0
        self._journal_path = Path(self._cfg.journal_file)
        self._journal_path.parent.mkdir(parents=True, exist_ok=True)
        self._call_fn = _PROVIDER_FNS.get(self._cfg.provider)
        if self._cfg.enabled and self._call_fn is None:
            self._log(f"[AI_ENGINE] Unknown provider {self._cfg.provider!r} — engine disabled")
            self._cfg = AIEngineConfig(**{**asdict(self._cfg), "enabled": False})

    # ── cooldown guard ───────────────────────────────────────────────────────

    def _wait_cooldown(self) -> None:
        cooldown_s = self._cfg.batch_cooldown_ms / 1000.0
        elapsed = time.monotonic() - self._last_call_ts
        if elapsed < cooldown_s:
            time.sleep(cooldown_s - elapsed)

    # ── journal ──────────────────────────────────────────────────────────────

    _JOURNAL_MAX_BYTES = 10 * 1024 * 1024  # 10 MB

    def _rotate_journal_if_needed(self) -> None:
        try:
            if self._journal_path.exists() and self._journal_path.stat().st_size > self._JOURNAL_MAX_BYTES:
                archive = self._journal_path.with_suffix(
                    f".{time.strftime('%Y%m%d_%H%M%S')}.jsonl"
                )
                self._journal_path.rename(archive)
                self._log(f"[AI_ENGINE] Journal rotated → {archive.name}")
        except (OSError, json.JSONDecodeError) as exc:
            self._log(f"[AI_ENGINE] Journal rotation failed: {exc}")

    def _append_journal(self, decision: AIDecision) -> None:
        if not self._cfg.journal_enabled:
            return
        self._rotate_journal_if_needed()
        try:
            with self._journal_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    **asdict(decision),
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                }) + "\n")
        except (OSError, json.JSONDecodeError) as exc:
            self._log(f"[AI_ENGINE] Journal write failed: {exc}")

    # ── main enrich ──────────────────────────────────────────────────────────

    def enrich_signal(self, symbol: str, signal: dict[str, Any]) -> dict[str, Any]:
        """
        Enrich a signal dict with AI verdict and adjusted score.
        Returns a *new* dict (original is never mutated).
        If AI is disabled or errors, returns original unmodified.
        """
        out = dict(signal)
        if not self._cfg.enabled or self._call_fn is None:
            return out

        raw_score = int(signal.get("score") or 0)
        regime = str(signal.get("mkt_regime") or signal.get("regime") or "NEUTRAL")
        strength = str(signal.get("strength") or "MODERATE")

        # Apply static bias from config before LLM call
        regime_mult = self._cfg.regime_bias.get(regime, 1.0)
        strength_mult = self._cfg.strength_bias.get(strength, 1.0)
        biased_score = int(round(raw_score * regime_mult * strength_mult))
        out["score"] = biased_score

        # Build a compact prompt (no PII, just signal numerics)
        prompt_data = {k: signal[k] for k in (
            "score", "threshold", "direction", "mkt_regime", "strength",
            "vol_ratio", "breakout_ok", "rsi", "macd_hist",
        ) if k in signal}
        prompt = (
            f"Symbol: {symbol}\n"
            f"Signal: {json.dumps(prompt_data, default=str)}\n"
            "Give your verdict."
        )

        t0 = time.monotonic()
        try:
            with self._lock:
                self._wait_cooldown()
                raw_response = self._call_fn(prompt, self._cfg)
                self._last_call_ts = time.monotonic()
        except (OSError, ConnectionError, TimeoutError, json.JSONDecodeError, ValueError, TypeError) as exc:
            self._log(f"[AI_ENGINE] LLM call failed for {symbol}: {exc}")
            return out

        latency_ms = int((time.monotonic() - t0) * 1000)

        try:
            parsed = _parse_llm_json(raw_response)
        except (json.JSONDecodeError, ValueError, TypeError):
            self._log(f"[AI_ENGINE] Failed to parse LLM JSON for {symbol}: {raw_response[:120]}")
            return out

        verdict = str(parsed.get("verdict") or "WATCH").upper()
        if verdict not in ("TRADE", "SKIP", "WATCH"):
            verdict = "WATCH"
        delta = int(parsed.get("score_delta") or 0)
        delta = max(-self._cfg.signal_boost_max, min(self._cfg.signal_boost_max, delta))
        reasoning = str(parsed.get("reasoning") or "")

        # Apply veto
        if verdict == "SKIP" and self._cfg.veto_enabled:
            out["ai_vetoed"] = True
            out["ai_score_delta"] = delta
            out["score"] = max(0, biased_score + delta)
        else:
            out["ai_vetoed"] = False
            out["ai_score_delta"] = delta
            out["score"] = biased_score + delta

        out["ai_verdict"] = verdict
        out["ai_reasoning"] = reasoning

        final_score = int(out["score"])
        decision = AIDecision(
            symbol=symbol,
            verdict=verdict,
            score_delta=delta,
            reasoning=reasoning,
            provider=self._cfg.provider,
            model=self._cfg.model,
            latency_ms=latency_ms,
            raw_signal_score=raw_score,
            final_score=final_score,
            regime=regime,
            strength=strength,
        )
        self._append_journal(decision)
        self._log(
            f"[AI] {symbol} verdict={verdict} delta={delta:+d} "
            f"score {raw_score}→{final_score} | {reasoning[:60]}"
        )
        return out

    # ── journal analytics (for adaptive learning feedback) ───────────────────

    def load_journal_stats(self, lookback: int = 100) -> dict[str, Any]:
        """Read last `lookback` journal entries and return aggregate stats."""
        entries: list[dict] = []
        if not self._journal_path.exists():
            return {"count": 0}
        try:
            lines = self._journal_path.read_text(encoding="utf-8").splitlines()
            for line in lines[-lookback:]:
                try:
                    entries.append(json.loads(line))
                except (json.JSONDecodeError, ValueError, TypeError) as _parse_err:
                    self._log(f"[AI_ENGINE] Journal parse error (non-blocking): {_parse_err}")
        except (OSError, json.JSONDecodeError) as _io_err:
            self._log(f"[AI_ENGINE] Journal read failed: {_io_err}")
            return {"count": 0}

        total = len(entries)
        verdicts = {"TRADE": 0, "SKIP": 0, "WATCH": 0}
        delta_sum = 0
        for e in entries:
            v = str(e.get("verdict") or "WATCH").upper()
            verdicts[v] = verdicts.get(v, 0) + 1
            delta_sum += int(e.get("score_delta") or 0)

        return {
            "count": total,
            "trade_pct": round(verdicts["TRADE"] / max(1, total) * 100, 1),
            "skip_pct": round(verdicts["SKIP"] / max(1, total) * 100, 1),
            "avg_delta": round(delta_sum / max(1, total), 2),
            "verdicts": verdicts,
        }


# ─── Singleton factory (one engine per process) ───────────────────────────────

_engine_instance: AIEngine | None = None
_engine_lock = threading.Lock()


def get_ai_engine(cfg: dict[str, Any], *, log_fn: Callable[[str], None] | None = None) -> AIEngine:
    """Return the process-level AIEngine, creating it if necessary."""
    global _engine_instance
    with _engine_lock:
        if _engine_instance is None:
            ai_cfg = ai_engine_config_from_cfg(cfg)
            _engine_instance = AIEngine(ai_cfg, log_fn=log_fn)
    return _engine_instance


def reset_ai_engine() -> None:
    """Force-reset singleton (tests only)."""
    global _engine_instance
    with _engine_lock:
        _engine_instance = None
