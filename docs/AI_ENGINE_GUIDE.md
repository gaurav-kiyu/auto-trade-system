# AI Engine & Auto-Learner — Configuration Guide (v1.2)

## Overview

Two fully configurable optional modules:
- `core/ai_engine.py` — LLM-powered signal enrichment
- `core/auto_learner.py` — self-tuning adaptive threshold learner

Both are **disabled by default** (`AI_ENGINE_ENABLED: false`, `AUTO_LEARNER_ENABLED: false`).
Both have zero hard-coded values — every knob is in `config.json`.

> **Current system state:** These modules are available in code but not activated.
> The system operates in MANUAL mode with static scoring (`ADAPTIVE_THRESHOLD_ENABLED: false`,
> `AUTO_TUNE_ENABLED: false`). To enable, add the keys below to `config.json`.

---

## AI Engine (`AI_ENGINE_*`)

### Enabling
```json
"AI_ENGINE_ENABLED": true,
"AI_ENGINE_PROVIDER": "anthropic",
"AI_ENGINE_MODEL": "claude-haiku-4-5-20251001",
"AI_ENGINE_API_KEY_ENV": "ANTHROPIC_API_KEY"
```
Set the env var before launching:
```
set ANTHROPIC_API_KEY=sk-ant-...         (Windows)
export ANTHROPIC_API_KEY=sk-ant-...      (Linux/Mac)
```

### Supported Providers
| `AI_ENGINE_PROVIDER` | Notes |
|---|---|
| `anthropic` | Claude models — default |
| `openai` | GPT models — set `AI_ENGINE_MODEL` to e.g. `gpt-4o-mini` |
| `ollama` | Local — set `AI_ENGINE_API_BASE_URL` to `http://localhost:11434` |
| `http` | Any REST endpoint that accepts `{"prompt":...}` and returns `{"text":...}` |

### What the AI does
1. Receives a compact signal dict (no PII, just score/regime/indicators)
2. Returns `TRADE`, `SKIP`, or `WATCH` + a score delta (−5..+5)
3. If `AI_ENGINE_VETO_ENABLED: true` and verdict is `SKIP`, the signal score is penalized
4. All decisions are logged to `AI_ENGINE_JOURNAL_FILE`

### Full config keys
```json
"AI_ENGINE_ENABLED": false,
"AI_ENGINE_PROVIDER": "anthropic",
"AI_ENGINE_MODEL": "claude-haiku-4-5-20251001",
"AI_ENGINE_API_KEY_ENV": "ANTHROPIC_API_KEY",
"AI_ENGINE_API_BASE_URL": "",
"AI_ENGINE_MAX_TOKENS": 256,
"AI_ENGINE_TIMEOUT_SEC": 8.0,
"AI_ENGINE_SIGNAL_BOOST_MAX": 5,
"AI_ENGINE_VETO_ENABLED": true,
"AI_ENGINE_PROMPT_TEMPLATE": "",
"AI_ENGINE_JOURNAL_FILE": "reports/ai_decisions.jsonl",
"AI_ENGINE_JOURNAL_ENABLED": true,
"AI_ENGINE_BATCH_COOLDOWN_MS": 1200,
"AI_ENGINE_REGIME_BIAS": {
    "TRENDING": 1.10,
    "NEUTRAL": 1.00,
    "CHOPPY": 0.90,
    "EVENT": 0.75
},
"AI_ENGINE_STRENGTH_BIAS": {
    "STRONG": 1.05,
    "MODERATE": 1.00,
    "WEAK": 0.90
}
```

---

## Auto-Learner (`AUTO_LEARNER_*`)

The auto-learner is **disabled by default** (`AUTO_LEARNER_ENABLED: false`). When enabled, it replaces the fixed-rate adaptive_learning nudges with fully configurable ones and feeds back AI journal skip-rate into threshold tuning.

### Full config keys
```json
"AUTO_LEARNER_ENABLED": false,
"AUTO_LEARNER_STATE_FILE": "backups/learner_state.json",
"AUTO_LEARNER_LOOKBACK": 40,
"AUTO_LEARNER_WIN_SCORE_DECAY": 2.0,
"AUTO_LEARNER_LOSS_SCORE_INC": 3.0,
"AUTO_LEARNER_CONFIDENCE_WIN_INC": 1.0,
"AUTO_LEARNER_CONFIDENCE_LOSS_DEC": 1.0,
"AUTO_LEARNER_STREAK_BOOST_AT": 3,
"AUTO_LEARNER_LOSS_STREAK_HALT": 3,
"AUTO_LEARNER_MAX_BONUS": 8,
"AUTO_LEARNER_MAX_DISCOUNT": 3,
"AUTO_LEARNER_AI_JOURNAL_WEIGHT": 0.3,
"AUTO_LEARNER_REGIME_DECAY": 0.98,
"AUTO_LEARNER_PER_SYMBOL": false,
"AUTO_LEARNER_CSV_EXPORT_FILE": ""
```

### What is learned automatically
| Data Source | Effect |
|---|---|
| Recent trade WIN/LOSS history | Adjusts AI_THRESHOLD up (cautious) or down (confident) |
| Loss streaks | Raises threshold progressively |
| Regime/strength win-rates | Weights future signals by historical performance in same regime |
| AI journal skip-rate | Adds extra threshold bonus when LLM is flagging many signals |

---

## Integration into your bots (index_trader / STOCK app)

Both bots will auto-detect and use these modules when the config keys are present. 
To manually wire them into a custom bot:

```python
from core.ai_engine import get_ai_engine
from core.auto_learner import get_auto_learner

ai = get_ai_engine(cfg, log_fn=log_msg)
learner = get_auto_learner(cfg, log_fn=log_msg,
                           ai_journal_file=cfg.get("AI_ENGINE_JOURNAL_FILE",""))

# In signal generation:
enriched_signal = ai.enrich_signal(symbol, raw_signal)
delta, reason = learner.threshold_adjustment(symbol, regime, strength, trade_history)
effective_threshold = base_threshold + delta

# After trade exit:
learner.record_exit(symbol, "WIN", regime, strength, net_pnl)
learner.save()
```

---

## Graceful degradation

If `AI_ENGINE_ENABLED: false` (default), or if the LLM call fails for any reason:
- `enrich_signal()` returns the original signal dict unchanged
- Trading continues exactly as before v1.2
- No exceptions propagate to the main loop
