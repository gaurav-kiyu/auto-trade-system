"""Environment separation — validates deployment environment, prevents misconfiguration."""

import logging
import os
import sys
from enum import Enum
from typing import Optional

log = logging.getLogger(__name__)


class Environment(Enum):
    DEV = "dev"
    QA = "qa"
    PAPER = "paper"
    SHADOW = "shadow"
    STAGING = "staging"
    PRODUCTION = "production"

    @classmethod
    def from_str(cls, value: str) -> "Environment":
        normalized = value.strip().lower().replace("-", "_")
        for env in cls:
            if env.value == normalized:
                return env
        raise ValueError(f"Unknown environment: {value!r}. Valid: {[e.value for e in cls]}")


def current_environment() -> Environment:
    """Detect environment from OPBUYING_ENVIRONMENT env var (default: DEV).

    Note: This does not read the ENVIRONMENT config key. For full resolution
    that checks both env var and config with proper precedence, use
    validate_environment(cfg) instead.
    """
    raw = os.environ.get("OPBUYING_ENVIRONMENT", "").strip()
    if not raw:
        return Environment.DEV
    return Environment.from_str(raw)


def guard_dev_config_in_production(cfg: dict) -> None:
    """Warn if env=PRODUCTION but config looks dev-like (low capital, defaults token)."""
    try:
        env = Environment.from_str(str(cfg.get("ENVIRONMENT", "dev")))
    except ValueError:
        return
    if env != Environment.PRODUCTION:
        return
    warnings: list[str] = []
    if str(cfg.get("BOT_TOKEN", "")).startswith("YOUR_") or str(cfg.get("CHAT_ID", "")).startswith("YOUR_"):
        warnings.append("BOT_TOKEN/CHAT_ID still have placeholder values")
    if float(cfg.get("BASE_CAPITAL", 0)) < 10000:
        warnings.append(f"BASE_CAPITAL ({cfg.get('BASE_CAPITAL')}) is below 10,000 — suspiciously low for production")
    if cfg.get("admin_control_plane_auth_token") in ("", "change_me"):
        warnings.append("admin_control_plane_auth_token is empty — admin API is unprotected")
    if cfg.get("web_dashboard_enabled") and not cfg.get("web_dashboard_auth_token"):
        warnings.append("web_dashboard is enabled without auth token")
    if warnings:
        for w in warnings:
            log.warning("PRODUCTION ENV GUARD: %s", w)
        if cfg.get("environment_block_on_violation", True):
            log.critical("PRODUCTION ENV GUARD: Blocking startup due to %d violations", len(warnings))
            sys.exit(88)


def guard_mode_env_compatibility(execution_mode: str | None, env: Environment) -> None:
    """Prevent running FULL_AUTO or LIVE_MANUAL_CONFIRM in non-production environments.
    Does nothing if execution_mode is None.
    """
    if execution_mode is None:
        return
    mode_upper = execution_mode.strip().upper()
    if mode_upper in ("FULL_AUTO", "LIVE_MANUAL_CONFIRM") and env not in (
        Environment.PRODUCTION, Environment.STAGING, Environment.SHADOW
    ):
        log.critical(
            "Execution mode %s requires environment STAGING, SHADOW, or PRODUCTION (current: %s). "
            "Refusing to start.", execution_mode, env.value,
        )
        sys.exit(88)


def validate_environment(cfg: dict) -> Environment:
    """Validate environment setting at startup. Returns resolved Environment.

    Precedence: OPBUYING_ENVIRONMENT env var > ENVIRONMENT config key.
    Logs a warning if both are set to different values.
    """
    env_var = os.environ.get("OPBUYING_ENVIRONMENT", "").strip()
    cfg_raw = str(cfg.get("ENVIRONMENT", "dev"))

    # env var takes precedence over config key
    if env_var:
        try:
            env = Environment.from_str(env_var)
            if env_var.lower() != cfg_raw.strip().lower():
                log.warning(
                    "Environment mismatch: OPBUYING_ENVIRONMENT env var=%r but "
                    "config ENVIRONMENT=%r. Using env var value: %s",
                    env_var, cfg_raw, env.value,
                )
        except ValueError:
            log.critical("Invalid OPBUYING_ENVIRONMENT=%r. Must be one of: %s", env_var, [e.value for e in Environment])
            sys.exit(88)
    else:
        try:
            env = Environment.from_str(cfg_raw)
        except ValueError:
            log.critical("Invalid ENVIRONMENT=%r. Must be one of: %s", cfg_raw, [e.value for e in Environment])
            sys.exit(88)

    log.info("Environment: %s", env.value)
    if env == Environment.DEV:
        log.warning("Running in DEV mode — this is NOT suitable for production trading")
    guard_dev_config_in_production(cfg)
    execution_mode = str(cfg.get("EXECUTION_MODE", "SIGNAL_ONLY"))
    guard_mode_env_compatibility(execution_mode, env)
    return env
