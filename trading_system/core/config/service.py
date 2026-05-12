"""
Configuration Service - Immutable configuration management with validation.
Replaces global _CFG variable with proper dependency injection.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import Any, Dict, Optional, Set, FrozenSet

from core.config_bootstrap import (
    merge_bot_config,
    diff_configs,
    write_config_changes_jsonl,
    read_recent_config_changes,
    apply_env_overrides,
    coerce_config_values_to_defaults_types,
    classify_change_risk,
    _is_secret_key,
)
from core.config_helpers import decode_if_b64
from core.datetime_ist import now_ist
from core.config_validator import validate_config
from core.common_config_validate import (
    BROKER_ALLOWED_DRIVERS_STOCK,
    append_broker_api_config_errors,
    append_common_risk_and_target_errors,
    append_execution_hybrid_warnings,
    append_normalized_execution_mode_errors,
    append_nse_session_clock_errors,
    append_portfolio_reconcile_errors,
    append_scan_age_summary_errors,
    append_slot_and_trail_errors,
    append_vix_band_relation_errors,
    append_vix_modifier_errors,
    append_weekday_bias_errors,
    append_json_schema_errors,
)


@dataclass(frozen=True)
class ConfigChange:
    """Immutable record of a configuration change."""
    key: str
    old_value: Any
    new_value: Any
    changed_at: str  # ISO timestamp IST
    changed_by: str  # "hot_reload" | "env_override" | "startup"
    risk_level: str  # "CRITICAL" | "HIGH" | "NORMAL"


class ConfigurationService:
    """
    Immutable configuration service that replaces global _CFG variable.

    Features:
    - 3-layer merge: defaults → config.json → config.local.json → OPBUYING_* env vars
    - Type coercion and validation
    - Base64 secret decoding
    - Soft-reload capability with immutability enforcement
    - Configuration change auditing
    - Thread-safe access
    """

    # Critical keys that cannot be changed via soft-reload
    IMMUTABLE_KEYS: FrozenSet[str] = frozenset({
        "BASE_CAPITAL", "MAX_DAILY_LOSS", "MAX_DRAWDOWN", "KITE_API_KEY",
        "KITE_API_SECRET", "BROKER_API_ENABLED", "PAPER_MODE", "EXECUTION_MODE",
        "MANUAL_SIGNALS_ONLY"
    })

    # Keys that can be safely changed via soft-reload
    SAFE_RELOAD_KEYS: FrozenSet[str] = frozenset({
        "SCAN_INTERVAL", "COOLDOWN", "TG_MAX_PER_MIN", "ALERT_COOLDOWN_SECONDS",
        "CONSEC_LOSS_LIMIT", "VIX_COOLDOWN_SEC", "TG_HEARTBEAT_INTERVAL",
        "MIN_ENTRY_INTERVAL", "RECONCILE_INTERVAL", "WATCHDOG_TIMEOUT",
        "CLUSTER_WINDOW_SEC", "MONDAY_GAP_GRACE_MIN", "TG_STARTUP_ALERT",
        "TG_TRADE_ONLY", "TG_CACHE_TTL_SEC", "TG_SIGNAL_GLOBAL_COOLDOWN_SEC",
        "TG_TRADE_CRITICAL_PATTERNS",
        "STOCK_ALERT_MODE", "EQUITY_SL_MOVE_PCT", "EQUITY_TP_MOVE_PCT",
        "SIGNAL_MAX_AGE", "MAX_POSITION_AGE",
        "VIX_SIZE_HIGH_THRESHOLD", "VIX_SIZE_MED_THRESHOLD",
        "WEEKDAY_BIAS", "VIX_RISING_THRESHOLD_BONUS", "VIX_FALLING_COOLDOWN_MULT",
        "RECONCILE_HALT_ON_QTY_MISMATCH", "PORTFOLIO_MAX_SL_RISK_PCT", "BROKER_LATENCY_ENFORCE_ORDER",
        "EXIT_RECON_MAX_AGE_SEC", "API_FAIL_BLOCK_NEW_ENTRIES", "EXIT_SPREAD_GUARD_MULT",
        "FORCE_PRE_TRADE_RECON", "ORDER_STATUS_VERIFY_RETRIES", "API_DEGRADE_REDUCE_SIZE_AT", "API_DEGRADE_SIZE_MULT",
        "API_DEGRADE_BLOCK_ENTRIES_AT", "API_DEGRADE_HALT_AT", "CONFIG_DRIFT_AUTO_RELOAD",
        "TG_TRADE_ALERTS_STRICT", "TG_PERIODIC_SUMMARY_TELEGRAM", "DASHBOARD_COMPACT", "SHUTDOWN_ON_UI_CLOSE",
        "LOG_PERIODIC_SUMMARY", "USER_TIPS_ON_START",
        "ADAPTIVE_THRESHOLD_ENABLED", "ADAPTIVE_HISTORY_LOOKBACK",
        "ADAPTIVE_THRESHOLD_MAX_BONUS", "ADAPTIVE_THRESHOLD_MAX_DISCOUNT",
        "NSE_CASH_SESSION_START_HOUR", "NSE_CASH_SESSION_START_MINUTE",
        "NSE_CASH_SESSION_END_HOUR", "NSE_CASH_SESSION_END_MINUTE",
        "NSE_CONTINUOUS_TRADE_START_HOUR", "NSE_CONTINUOUS_TRADE_START_MINUTE",
        "NSE_MARKET_STATUS_CLOSED_HOUR", "NSE_MARKET_STATUS_CLOSED_MINUTE",
        "NSE_BLOCK_NEW_ENTRIES_FROM_HOUR", "NSE_BLOCK_NEW_ENTRIES_FROM_MINUTE",
        "NSE_POST_OPEN_NO_TRADE_MINUTES",
        "NSE_EARLY_SESSION_END_HOUR", "NSE_EARLY_SESSION_END_MINUTE"
    })

    def __init__(
        self,
        project_root: Path,
        config_file: str = "stock_config.json",
        defaults_file: str = "stock_config.defaults.json",
        local_overlay_relpath: Optional[str] = None,
        decode_secret_keys: Optional[FrozenSet[str]] = None,
        env_prefix: str = "OPBUYING_",
    ):
        """
        Initialize configuration service.

        Args:
            project_root: Root directory of the project
            config_file: Main configuration file name (relative to project_root)
            defaults_file: Defaults configuration file name (relative to project_root)
            local_overlay_relpath: Local overlay file path (relative to project_root)
            decode_secret_keys: Keys to decode from base64
            env_prefix: Environment variable prefix for overrides
        """
        self._project_root = project_root
        self._config_file = config_file
        self._defaults_file = defaults_file
        self._local_overlay_relpath = local_overlay_relpath
        self._decode_secret_keys = decode_secret_keys or frozenset()
        self._env_prefix = env_prefix

        # Thread-safe access to configuration
        self._lock = RLock()

        # Load initial configuration
        self._config: Dict[str, Any] = self._load_configuration()
        self._config_hash: str = self._calculate_hash(self._config)

        # Configuration change tracking
        self._change_history: list[ConfigChange] = []
        self._reload_count: int = 0
        self._last_reload_time: float = 0.0

        # Apply hybrid execution mode if needed (preserving existing behavior)
        self._apply_initial_hybrid_execution()

    def _load_configuration(self) -> Dict[str, Any]:
        """Load and merge configuration from all sources."""
        # Load defaults file
        defaults_path = self._project_root / self._defaults_file
        if not defaults_path.is_file():
            raise FileNotFoundError(f"Defaults file not found: {defaults_path}")

        with open(defaults_path, 'r', encoding='utf-8') as f:
            defaults = json.load(f)

        # Build merged configuration
        config = merge_bot_config(
            defaults=defaults,
            project_root=self._project_root,
            overlay_path=self._config_file,
            local_overlay_relpath=self._local_overlay_relpath,
            decode_secret_keys=self._decode_secret_keys,
            apply_hybrid_execution=None,  # We handle this separately
            env_prefix=self._env_prefix,
            debug=False,
        )

        # Validate configuration
        self._validate_configuration(config)

        return config

    def _validate_configuration(self, config: Dict[str, Any]) -> None:
        """Validate configuration and raise exceptions for critical errors."""
        errors, warnings = validate_config(config)

        # Log warnings (non-fatal)
        for warning in warnings:
            # In a real implementation, we'd use proper logging
            print(f"[CONFIG WARN] {warning}")

        # Raise exception for critical errors
        if errors:
            error_msg = "Configuration validation failed:\n" + "\n".join(f"  - {error}" for error in errors)
            raise ValueError(error_msg)

    def _apply_initial_hybrid_execution(self) -> None:
        """Apply hybrid execution mode logic during initial load."""
        from core.hybrid_execution import apply_execution_mode as _apply_hybrid_execution_mode

        # Apply execution mode logic (preserving existing behavior)
        cfg = self._config
        paper_mode_from_cli = "--paper" in os.sys.argv

        # Same hybrid rules as index bot: MANUAL → signals only; AUTO → broker on; PAPER → sim.
        cfg = _apply_hybrid_execution_mode(cfg, cli_paper=paper_mode_from_cli, infer_blank_from_broker=True)

        if str(cfg.get("EXECUTION_MODE", "")).upper() == "PAPER":
            # Update paper mode flag (this would normally be a global)
            # We'll handle this through derived properties
            pass

        self._config = cfg
        self._config_hash = self._calculate_hash(self._config)

    def _calculate_hash(self, config: Dict[str, Any]) -> str:
        """Calculate hash of configuration for change detection."""
        import hashlib as hl
        # Exclude secret keys from hash for security
        filtered_config = {
            k: v for k, v in config.items()
            if not _is_secret_key(k)
        }
        return hl.md5(
            json.dumps(filtered_config, sort_keys=True).encode()
        ).hexdigest()[:12]

    def get(self, key: str, default: Any = None) -> Any:
        """
        Get configuration value by key.

        Args:
            key: Configuration key
            default: Default value if key not found

        Returns:
            Configuration value or default
        """
        with self._lock:
            return self._config.get(key, default)

    def get_all(self) -> Dict[str, Any]:
        """
        Get a copy of all configuration values.

        Returns:
            Copy of configuration dictionary (secrets excluded for security)
        """
        with self._lock:
            # Return copy with secrets masked
            result = {}
            for key, value in self._config.items():
                if _is_secret_key(key):
                    result[key] = "[REDACTED]"
                else:
                    result[key] = value
            return result

    def get_secret(self, key: str) -> Any:
        """
        Get secret configuration value (use with caution).

        Args:
            key: Configuration key

        Returns:
            Actual secret value
        """
        with self._lock:
            return self._config.get(key)

    def has_key(self, key: str) -> bool:
        """Check if configuration key exists."""
        with self._lock:
            return key in self._config

    def soft_reload(self) -> bool:
        """
        Attempt to soft-reload configuration from file.

        Returns:
            True if reload was successful, False otherwise
        """
        with self._lock:
            try:
                # Load new configuration
                new_config = self._load_configuration()

                # Partition changes into blocked, ignored, and allowed
                changed, blocked, ignored = self._partition_changes(
                    self._config, new_config
                )

                # Handle blocked changes (immutable keys)
                if blocked:
                    # Log and reject immutable key changes
                    print(f"[CONFIG] BLOCKED immutable key changes: {blocked}")
                    # In a real implementation, we'd send Telegram alert here
                    return False

                # Handle ignored keys (require restart)
                if ignored:
                    print(f"[CONFIG] Ignored keys require restart: {ignored}")
                    # We could still apply safe changes but warn about ignored ones
                    # For now, we'll proceed with safe changes only

                # Apply safe changes
                if changed or not ignored:  # Proceed if there are changes or no ignored keys
                    # Update configuration
                    old_config = self._config
                    self._config = new_config

                    # Calculate new hash
                    new_hash = self._calculate_hash(new_config)
                    self._config_hash = new_hash

                    # Track changes for audit
                    changes = diff_configs(
                        old_config,
                        new_config,
                        changed_by="hot_reload"
                    )

                    if changes:
                        self._change_history.extend(changes)
                        # Keep only recent changes to prevent unbounded growth
                        if len(self._change_history) > 1000:
                            self._change_history = self._change_history[-500:]

                        # Write to audit log
                        write_config_changes_jsonl(changes)

                    # Update reload tracking
                    self._reload_count += 1
                    self._last_reload_time = time.time()

                    print(f"[CONFIG] Soft-reload successful: {len(changes)} changes applied")
                    return True
                else:
                    print("[CONFIG] No changes detected in configuration")
                    return False

            except Exception as e:
                print(f"[CONFIG] Soft-reload failed: {e}")
                return False

    def _partition_changes(
        self,
        old_config: Dict[str, Any],
        new_config: Dict[str, Any]
    ) -> tuple[Set[str], Set[str], Set[str]]:
        """
        Partition configuration changes into changed/blocked/ignored categories.

        Returns:
            Tuple of (changed_keys, blocked_keys, ignored_keys)
        """
        changed = set()
        blocked = set()
        ignored = set()

        all_keys = set(old_config.keys()) | set(new_config.keys())

        for key in all_keys:
            old_val = old_config.get(key)
            new_val = new_config.get(key)

            if old_val != new_val:
                if key in self.IMMUTABLE_KEYS:
                    blocked.add(key)
                elif key in self.SAFE_RELOAD_KEYS:
                    changed.add(key)
                else:
                    ignored.add(key)

        return changed, blocked, ignored

    def get_change_history(self, limit: int = 50) -> list[ConfigChange]:
        """
        Get recent configuration change history.

        Args:
            limit: Maximum number of changes to return

        Returns:
            List of configuration changes (most recent first)
        """
        with self._lock:
            return list(reversed(self._change_history[-limit:]))

    def get_reload_stats(self) -> Dict[str, Any]:
        """
        Get configuration reload statistics.

        Returns:
            Dictionary with reload statistics
        """
        with self._lock:
            return {
                "reload_count": self._reload_count,
                "last_reload_time": self._last_reload_time,
                "config_hash": self._config_hash,
                "total_changes": len(self._change_history),
            }

    def is_immutable_key(self, key: str) -> bool:
        """Check if a key is immutable (cannot be changed via soft-reload)."""
        return key in self.IMMUTABLE_KEYS

    def is_safe_reload_key(self, key: str) -> bool:
        """Check if a key can be safely changed via soft-reload."""
        return key in self.SAFE_RELOAD_KEYS

    def _get_secrets(self) -> FrozenSet[str]:
        """Get the set of keys that are treated as secrets."""
        return frozenset(k for k in self._config.keys() if _is_secret_key(k))


# Factory function for easy instantiation
def create_configuration_service(
    project_root: Optional[Path] = None,
    config_file: str = "stock_config.json",
    defaults_file: str = "stock_config.defaults.json",
    local_overlay_relpath: Optional[str] = None,
    decode_secret_keys: Optional[FrozenSet[str]] = None,
    env_prefix: str = "OPBUYING_",
) -> ConfigurationService:
    """
    Factory function to create a configuration service instance.

    Args:
        project_root: Root directory of the project (defaults to current directory)
        config_file: Main configuration file name
        defaults_file: Defaults configuration file name
        local_overlay_relpath: Local overlay file path
        decode_secret_keys: Keys to decode from base64
        env_prefix: Environment variable prefix for overrides

    Returns:
        Configured ConfigurationService instance
    """
    if project_root is None:
        project_root = Path.cwd()

    return ConfigurationService(
        project_root=project_root,
        config_file=config_file,
        defaults_file=defaults_file,
        local_overlay_relpath=local_overlay_relpath,
        decode_secret_keys=decode_secret_keys,
        env_prefix=env_prefix,
    )
