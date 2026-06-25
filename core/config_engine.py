"""
Config Engine (deprecated).

WARNING: This module is deprecated. Use core.config_validator for config
validation and startup safety checks.

core.config_validator.validate_config() provides:
  - Required key presence checks
  - Execution mode validation
  - Risk mode validation
  - Tier boundary ordering
  - AI_THRESHOLD dead zone detection
  - TG_ALERT_MIN_SCORE alignment
  - VIX threshold sanity
  - SL/TP/RR consistency
  - Capital/risk limit validation
  - Structured block validation (instruments, indicator, market, financial)

This module will be removed in a future release.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Any

warnings.warn(
    "core.config_engine is DEPRECATED. Use core.config_validator.validate_config() instead.",
    DeprecationWarning,
    stacklevel=2,
)


@dataclass(frozen=True)
class ConfigIssue:
    level: str
    key: str
    message: str


@dataclass(frozen=True)
class ConfigValidationResult:
    errors: list[ConfigIssue]
    warnings: list[ConfigIssue]

    @property
    def ok(self) -> bool:
        return not self.errors


class ConfigValidator:
    """Small schema validator for startup safety checks."""

    def __init__(self, config: dict[str, Any]) -> None:
        self._cfg = dict(config or {})
        self._errors: list[ConfigIssue] = []
        self._warnings: list[ConfigIssue] = []

    def _error(self, key: str, message: str) -> None:
        self._errors.append(ConfigIssue("error", key, message))

    def _warn(self, key: str, message: str) -> None:
        self._warnings.append(ConfigIssue("warning", key, message))

    def _number_between(self, key: str, low: float, high: float, *, inclusive_low: bool = True, inclusive_high: bool = True) -> None:
        value = self._cfg.get(key)
        try:
            num = float(value)
        except (ValueError, TypeError):
            self._error(key, "must be a number")
            return
        low_ok = num >= low if inclusive_low else num > low
        high_ok = num <= high if inclusive_high else num < high
        if not (low_ok and high_ok):
            left = "[" if inclusive_low else "("
            right = "]" if inclusive_high else ")"
            self._error(key, f"must be in range {left}{low}, {high}{right}")

    def validate(self) -> ConfigValidationResult:
        mode = str(self._cfg.get("EXECUTION_MODE") or "MANUAL").upper()
        if mode not in ("MANUAL", "PAPER", "AUTO", "SIGNALS"):
            self._error("EXECUTION_MODE", "must be MANUAL, PAPER, AUTO, or SIGNALS")

        provider_priority = self._cfg.get("DATA_PROVIDER_PRIORITY", [])
        enabled = self._cfg.get("DATA_PROVIDER_ENABLED", {})
        if not isinstance(provider_priority, list) or not provider_priority:
            self._error("DATA_PROVIDER_PRIORITY", "must be a non-empty list")
        else:
            for idx, name in enumerate(provider_priority):
                if not isinstance(name, str) or not name.strip():
                    self._error("DATA_PROVIDER_PRIORITY", f"item {idx + 1} must be a non-empty text value")
        if not isinstance(enabled, dict):
            self._error("DATA_PROVIDER_ENABLED", "must be an object with provider flags")
        elif provider_priority and not any(bool(enabled.get(name)) for name in provider_priority if isinstance(name, str)):
            self._error("DATA_PROVIDER_ENABLED", "at least one preferred provider must be enabled")

        self._number_between("LATENCY_BUDGET_MS", 100.0, 10000.0)
        self._number_between("PORTFOLIO_MAX_SL_RISK_PCT", 0.05, 1.0, inclusive_low=False)
        self._number_between("AUDIT_RETENTION_DAYS", 1.0, 3650.0)
        self._number_between("RETENTION_REPORTS_MAX_FILES", 1.0, 500.0)
        self._number_between("RETENTION_LOGS_MAX_FILES", 1.0, 500.0)
        self._number_between("RETENTION_BACKUPS_MAX_FILES", 1.0, 500.0)

        broker_name = str(self._cfg.get("BROKER_NAME") or "").strip()
        if not broker_name:
            self._warn("BROKER_NAME", "broker name is empty; dashboard will show a generic label")

        broker_driver = str(self._cfg.get("BROKER_DRIVER") or "GENERIC").upper()
        custom_factory = str(self._cfg.get("BROKER_CUSTOM_FACTORY") or "").strip()
        if (
            broker_driver == "GENERIC"
            and mode == "AUTO"
            and bool(self._cfg.get("BROKER_API_ENABLED"))
            and not custom_factory
        ):
            self._warn("BROKER_DRIVER", "AUTO mode is enabled with a generic broker driver; confirm the live adapter is implemented before trading")

        if bool(self._cfg.get("AUDIT_LOG_ENABLED")) and not str(self._cfg.get("AUDIT_LOG_FILE") or "").strip():
            self._error("AUDIT_LOG_FILE", "must be set when audit logging is enabled")

        return ConfigValidationResult(errors=list(self._errors), warnings=list(self._warnings))


__all__ = [
    "ConfigIssue",
    "ConfigValidationResult",
    "ConfigValidator",
]

