"""
Shared merged-config loading for index and stock entry scripts.
Updated to use SecureConfig for enhanced security.
"""

from __future__ import annotations

__all__ = [
    "CRITICAL_CONFIG_KEYS",
    "HIGH_RISK_CONFIG_KEYS",
    "CONFIG_B64_SECRET_KEYS_STOCK",
    "CONFIG_B64_SECRET_KEYS_INDEX",
    "CONFIG_DEFAULTS_PATH_INDEX",
    "ConfigChange",
    "classify_change_risk",
    "diff_configs",
    "write_config_changes_jsonl",
    "read_recent_config_changes",
    "get_effective_config",
    "initialize_secure_config",
    "get_secure_config",
    "get_config_value",
    "get_config_secret",
    "get_config_bool",
    "get_config_int",
    "get_config_float",
    "get_config_list",
    "get_config_dict",
    "apply_env_overrides",
    "merge_bot_config",
    "decode_secret_keys",
    "coerce_config_values_to_defaults_types",
]

import json
import logging
import os
import threading
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Import our new secure config system
from infrastructure.config.secure_config import SecureConfig

from core.config_helpers import deep_merge_dict

# Import IST datetime function for timestamps
from core.datetime_ist import now_ist

import warnings as _cw

_log = logging.getLogger(__name__)

# ── Config change audit (Item 6 - v2.44) ────────────────────────

CRITICAL_CONFIG_KEYS: frozenset[str] = frozenset({
    "MAX_DAILY_LOSS", "MAX_DRAWDOWN", "MAX_OPEN", "MAX_TRADES_DAY",
    "RISK_MODE", "EXECUTION_MODE", "VIX_HALT_THRESHOLD",
    "SL_PCT", "TARGET_PCT", "TRAIL_PCT",
})

HIGH_RISK_CONFIG_KEYS: frozenset[str] = frozenset({
    "SCAN_INTERVAL", "SIGNAL_THRESHOLD_STRONG",
    "SIGNAL_THRESHOLD_MODERATE", "BASE_LOTS",
    "BASE_CAPITAL", "PORTFOLIO_MAX_SL_RISK_PCT",
})

_SECRET_SUBSTRINGS = ("token", "key", "secret", "password", "credential", "access")


def classify_change_risk(key: str) -> str:
    """
    Classify the risk level of a configuration change based on the key.

    Args:
        key: Configuration key to classify

    Returns:
        Risk level: "CRITICAL", "HIGH", or "NORMAL"
    """
    key_upper = key.upper()
    if key_upper in CRITICAL_CONFIG_KEYS:
        return "CRITICAL"
    elif key_upper in HIGH_RISK_CONFIG_KEYS:
        return "HIGH"
    else:
        return "NORMAL"


def diff_configs(old_config: Mapping[str, Any], new_config: Mapping[str, Any], changed_by: str = "startup") -> list[ConfigChange]:
    """
    Compute differences between two configuration dictionaries.

    Args:
        old_config: Original configuration
        new_config: New configuration
        changed_by: Who/what caused the change

    Returns:
        List of ConfigChange objects representing the differences
    """
    changes = []

    # Get all keys from both configs
    all_keys = set(old_config.keys()) | set(new_config.keys())

    for key in all_keys:
        old_value = old_config.get(key, None)
        new_value = new_config.get(key, None)

        # Skip if values are the same
        if old_value == new_value:
            continue

        # Skip secret keys for security
        if any(substring in key.lower() for substring in _SECRET_SUBSTRINGS):
            continue

        # Skip if both values are None
        if old_value is None and new_value is None:
            continue

        changes.append(ConfigChange(
            key=key,
            old_value=old_value,
            new_value=new_value,
            changed_at=now_ist().isoformat(),
            changed_by=changed_by,
            risk_level=classify_change_risk(key)
        ))

    return changes


def write_config_changes_jsonl(changes: list[ConfigChange], log_path: str | Path) -> None:
    """
    Write configuration changes to a JSONL file.

    Args:
        changes: List of ConfigChange objects to write
        log_path: Path to the JSONL log file
    """
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "a", encoding="utf-8") as f:
        for change in changes:
            # Convert ConfigChange to dict for JSON serialization
            change_dict = {
                "key": change.key,
                "old_value": change.old_value,
                "new_value": change.new_value,
                "changed_at": change.changed_at,
                "changed_by": change.changed_by,
                "risk_level": change.risk_level
            }
            f.write(json.dumps(change_dict, default=str) + "\n")


def read_recent_config_changes(log_path: str | Path, limit: int | None = None) -> list[dict]:
    """
    Read recent configuration changes from a JSONL file.

    Args:
        log_path: Path to the JSONL log file
        limit: Maximum number of lines to read (None for all)

    Returns:
        List of dictionaries representing config changes
    """
    path = Path(log_path)
    if not path.exists():
        return []

    changes = []
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
        if limit is not None:
            lines = lines[-limit:]  # Get the last 'limit' lines

        for line in lines:
            line = line.strip()
            if line:
                try:
                    change_dict = json.loads(line)
                    changes.append(change_dict)
                except json.JSONDecodeError:
                    # Skip invalid JSON lines
                    continue

    return changes


def get_effective_config(
    defaults_path: str = "index_config.defaults.json",
    config_dir: str = ".",
) -> dict[str, Any]:
    """
    The authoritative configuration pipeline.
    Defaults -> config.json -> config.local.json -> Env Vars -> Secrets.
    """
    # 1. Initialize SecureConfig (handles the merge and secrets)
    secure_cfg = SecureConfig(
        defaults_path=defaults_path,
        config_dir=config_dir
    )

    # 2. Convert to dict for backward compatibility with legacy modules
    effective_dict = secure_cfg._merged_config

    # 3. Apply environment variable overrides (OPBUYING_* prefix)
    # This is needed because SecureConfig only handles secrets via CredentialStorage,
    # but general config keys (e.g. OPBUYING_BASE_CAPITAL) must be applied separately.
    applied = apply_env_overrides(effective_dict, secure_cfg._defaults, prefix="OPBUYING_")
    if applied:
        _log.info("Applied %d OPBUYING_* environment variable override(s)", applied)

    # 4. Validate the final result
    with _cw.catch_warnings():
        _cw.filterwarnings("ignore", message=".*DEPRECATED.*", category=DeprecationWarning)
        from core.config_engine import ConfigValidator
        validator = ConfigValidator(effective_dict)
    result = validator.validate()

    if not result.ok:
        error_msgs = [f"{err.key} - {err.message}" for err in result.errors]
        for msg in error_msgs:
            _log.error(f"CONFIG ERROR: {msg}")
        raise RuntimeError(
            f"Config validation FAILED - {len(result.errors)} error(s). "
            f"Fix config or set OPBUYING_SKIP_CONFIG_VALIDATION=1 to bypass.\n"
            + "\n".join(error_msgs)
        )

    # Freeze config to prevent runtime mutation by any module
    return _freeze_config(effective_dict)


def _check_config_drift(secure_cfg: SecureConfig) -> None:
    """
    Detect config drift: keys in defaults.json not in merged config (new features),
    and keys in merged config not in defaults (deprecated/removed keys).
    Logs WARNING for drift and CRITICAL for high-risk key changes.
    """
    try:
        merged = secure_cfg._merged_config
        defaults_raw = secure_cfg._defaults_path
        if not defaults_raw or not os.path.isfile(str(defaults_raw)):
            return
        with open(str(defaults_raw), encoding='utf-8') as _df:
            defaults_dict = json.load(_df)

        merged_keys = set(merged.keys())
        defaults_keys = set(defaults_dict.keys())

        # Keys in defaults but NOT in merged config (new features with safe defaults)
        missing_in_merged = defaults_keys - merged_keys
        for key in sorted(missing_in_merged):
            _log.warning(
                "CONFIG DRIFT: Key '%s' (from defaults) not found in merged config. "
                "Using safe default from defaults.json (value=%s). "
                "Add to config.json to control explicitly.",
                key, defaults_dict.get(key),
            )

        # Keys in merged config but NOT in defaults (deprecated/removed)
        extra_in_merged = merged_keys - defaults_keys
        for key in sorted(extra_in_merged):
            risk = classify_change_risk(key)
            _log.log(
                logging.CRITICAL if risk == "CRITICAL" else logging.WARNING,
                "CONFIG DRIFT: Key '%s' in merged config not found in defaults. "
                "May be deprecated or removed. Risk: %s. Value: %s",
                key, risk, merged.get(key),
            )
    except (OSError, json.JSONDecodeError, KeyError, AttributeError) as _ex:
        _log.warning("Config drift check skipped: %s", _ex)


def _freeze_config(cfg: dict[str, Any]) -> dict[str, Any]:
    """Recursively freeze a config dict to prevent runtime mutation."""
    frozen: dict[str, Any] = {}
    for k, v in cfg.items():
        if isinstance(v, dict):
            frozen[k] = types.MappingProxyType(_freeze_config(v))
        elif isinstance(v, list):
            frozen[k] = tuple(v)
        else:
            frozen[k] = v
    return types.MappingProxyType(frozen)  # type: ignore[return-value]


@dataclass(frozen=True)
class ConfigChange:
    key:        str
    old_value:  Any
    new_value:  Any
    changed_at: str     # ISO timestamp IST
    changed_by: str     # "hot_reload" | "env_override" | "startup"
    risk_level: str     # "CRITICAL" | "HIGH" | "NORMAL"


# Global secure config instance
_SECURE_CONFIG: SecureConfig | None = None
_CONFIG_LOCK: threading.Lock = threading.RLock()


def initialize_secure_config(
    defaults_path: str | Path | None = None,
    config_dir: str | Path | None = None
) -> SecureConfig:
    """
    Initialize the secure configuration system.

    CRITICAL FIX (C14/C16): Default paths now point to the actual project root
    files, not non-existent "configs/templates/" or "config/" directories.
    If the defaults file cannot be found, an empty config is returned with a
    warning instead of silently masking the failure.

    On every initialization, performs a config drift check against defaults
    to detect stale or missing keys (Audit Finding #12).

    Args:
        defaults_path: Path to defaults JSON file
        config_dir: Path to configuration directory

    Returns:
        Initialized SecureConfig instance
    """
    global _SECURE_CONFIG

    # Use provided paths or defaults
    if defaults_path is None:
        # CRITICAL FIX: Point to actual project root, not non-existent configs/templates/
        project_root = Path(__file__).parent.parent
        candidates = [
            project_root / "index_config.defaults.json",
            project_root / "stock_config.defaults.json",
            project_root / "configs" / "templates" / "index_config.defaults.json",
        ]
        defaults_path = None
        for c in candidates:
            if c.is_file():
                defaults_path = c
                break
        if defaults_path is None:
            _log.warning(
                "initialize_secure_config: defaults file not found at any candidate path. "
                "Checked: %s. Using empty config.",
                [str(c) for c in candidates],
            )
            # Return a config that won't crash but prints safe defaults
            # Use module-level SecureConfig (imported at top) to avoid local shadowing
            dummy = SecureConfig(defaults_path=project_root / "index_config.defaults.json", config_dir=str(project_root))
            # Override merged config to empty so caller gets {} instead of crashing
            dummy._merged_config = {}
            _SECURE_CONFIG = dummy
            return _SECURE_CONFIG

    if config_dir is None:
        config_dir = Path(__file__).parent.parent  # project root (config.json lives there)

    _SECURE_CONFIG = SecureConfig(
        defaults_path=defaults_path,
        config_dir=config_dir,
        env_prefix="OPBUYING_",
        enable_secret_redaction=True
    )

    # ── Config Drift Detection (Audit Finding #12) ────────────────
    # Compare merged config against defaults to detect stale/missing keys
    try:
        _check_config_drift(_SECURE_CONFIG)
    except (OSError, json.JSONDecodeError, AttributeError, KeyError) as _drift_err:
        _log.warning("Config drift check failed: %s", _drift_err)
    # ───────────────────────────────────────────────────────────────

    return _SECURE_CONFIG


def get_secure_config() -> SecureConfig:
    """
    Get the global secure config instance.
    Initializes it if not already done.
    """
    global _SECURE_CONFIG
    with _CONFIG_LOCK:
        if _SECURE_CONFIG is None:
            return initialize_secure_config()
        return _SECURE_CONFIG


def get_config_value(key: str, default: Any = None) -> Any:
    """
    Get a configuration value by key.

    Args:
        key: Configuration key
        default: Default value if key not found

    Returns:
        Configuration value
    """
    config = get_secure_config()
    return config.get(key, default)


def get_config_secret(key: str, default: Any = None) -> Any:
    """
    Get a secret configuration value by key. This method is intended for accessing
    sensitive values and includes additional security auditing.

    Args:
        key: Configuration key for the secret
        default: Default value if key not found

    Returns:
        Secret value

    Note:
        Access to secrets through this method is logged for audit purposes.
    """
    config = get_secure_config()
    return config.get_secret(key, default)


def get_config_bool(key: str, default: bool = False) -> bool:
    """Get a boolean configuration value."""
    config = get_secure_config()
    return config.get_bool(key, default)


def get_config_int(key: str, default: int = 0) -> int:
    """Get an integer configuration value."""
    config = get_secure_config()
    return config.get_int(key, default)


def get_config_float(key: str, default: float = 0.0) -> float:
    """Get a float configuration value."""
    config = get_secure_config()
    return config.get_float(key, default)


def get_config_list(key: str, default: list | None = None) -> list:
    """Get a list configuration value."""
    if default is None:
        default = []
    config = get_secure_config()
    return config.get_list(key, default)


def get_config_dict(key: str, default: dict | None = None) -> dict:
    """Get a dictionary configuration value."""
    if default is None:
        default = {}
    config = get_secure_config()
    return config.get_dict(key, default)


# Backward compatibility constants - these map to the secure config system
# Keep these for backward compatibility with existing code
CONFIG_B64_SECRET_KEYS_STOCK: frozenset[str] = frozenset({
    "KITE_API_KEY",
    "KITE_ACCESS_TOKEN",
    "KITE_USER_ID",
    "KITE_PASSWORD",
    "KITE_TOTP_KEY",
})

# For backward compatibility, we'll define these as empty frozensets
# since the secure config system handles secrets differently
CONFIG_B64_SECRET_KEYS_INDEX: frozenset[str] = frozenset()


def apply_env_overrides(
    cfg: dict[str, Any],
    defaults: Mapping[str, Any],
    prefix: str = "OPBUYING_",
) -> int:
    """Apply environment variable overrides to a config dict.

    Only environment variables with the specified prefix are considered.
    The target key is matched case-insensitively against the config dict.

    Returns the number of overrides applied.
    """
    if not prefix:
        return 0

    lower_keys = {key.lower(): key for key in cfg}
    applied = 0

    for env_key, env_value in os.environ.items():
        if not env_key.lower().startswith(prefix.lower()):
            continue

        raw_key = env_key[len(prefix) :]
        if not raw_key:
            continue

        target_key = lower_keys.get(raw_key.lower())
        if target_key is None:
            continue

        current_value = cfg.get(target_key)
        new_value: Any = env_value

        if isinstance(current_value, bool):
            new_value = env_value.strip().lower() in ("true", "1", "yes", "on")
        elif isinstance(current_value, int) and not isinstance(current_value, bool):
            try:
                new_value = int(env_value)
            except ValueError:
                _log.debug("Failed to coerce env %s=%s to int, keeping raw string", env_key, env_value)
        elif isinstance(current_value, float):
            try:
                new_value = float(env_value)
            except ValueError:
                _log.debug("Failed to coerce env %s=%s to float, keeping raw string", env_key, env_value)

        cfg[target_key] = new_value
        applied += 1

    return applied


def merge_bot_config(
    defaults: Mapping[str, Any],
    project_root: Path,
    overlay_path: str | None = None,
    local_overlay_relpath: str | None = None,
    secret_keys_to_decode: FrozenSet[str] | None = None,
    apply_hybrid_execution=None,
    env_prefix: str = "OPBUYING_",
    debug: bool = False,
) -> Dict[str, Any]:
    """Legacy function kept for compatibility - delegates to secure config.

    DEPRECATED: New callers should use get_effective_config() which routes through
    SecureConfig and freezes the result. This function is maintained for backward
    compatibility with existing callers in _reload_config_handler (now updated to
    use get_effective_config).
    """
    # For backward compatibility, we still accept the old signature
    # but internally use the secure config system

    # Start with defaults as base
    result = dict(defaults)

    # Apply any overlay file
    if overlay_path:
        overlay_file = project_root / overlay_path
        if overlay_file.exists():
            with open(overlay_file) as f:
                overlay_data = json.load(f)
                result = deep_merge_dict(result, overlay_data)

    # Apply local overlay if specified
    if local_overlay_relpath:
        local_overlay_file = project_root / local_overlay_relpath
        if local_overlay_file.exists():
            with open(local_overlay_file) as f:
                local_data = json.load(f)
                result = deep_merge_dict(result, local_data)

    # Apply environment overrides
    apply_env_overrides(result, defaults, prefix=env_prefix)

    # Apply type coercion
    result = coerce_config_values_to_defaults_types(result, defaults)

    # Handle secret decoding if needed
    if secret_keys_to_decode is not None:
        result = decode_secret_keys(result, secret_keys_to_decode)

    # Freeze config to prevent runtime mutation (same as get_effective_config)
    return _freeze_config(result)


# Legacy function for backward compatibility
def decode_secret_keys(legacy_dict: Mapping[str, Any], secret_keys: frozenset[str]) -> Dict[str, Any]:
    """Legacy function for backward compatibility."""
    # This is now handled automatically by SecureConfig
    # but we keep the function signature for compatibility
    return dict(legacy_dict)


# Additional backward compatibility functions that might be expected by existing code
def coerce_config_values_to_defaults_types(user_config: Mapping[str, Any], defaults: Mapping[str, Any], debug: bool = False) -> Dict[str, Any]:
    """
    Legacy function for backward compatibility.
    In the secure config system, type coercion is handled automatically.
    """
    # Simple implementation for backward compatibility - modify in place to match test expectations
    for key, value in user_config.items():
        if key in defaults:
            # Try to match the type of the default value
            default_value = defaults[key]
            if isinstance(default_value, bool) and isinstance(value, str):
                user_config[key] = value.lower() in ('true', '1', 'yes', 'on')
            elif isinstance(default_value, int) and isinstance(value, str):
                try:
                    user_config[key] = int(value)
                except ValueError as e:
                    # If conversion fails, keep original value
                    _log.debug("[CONFIG_BOOTSTRAP] non-critical error: %s", e)
            elif isinstance(default_value, float) and isinstance(value, str):
                try:
                    user_config[key] = float(value)
                except ValueError as e:
                    # If conversion fails, keep original value
                    _log.debug("[CONFIG_BOOTSTRAP] non-critical error: %s", e)
            # For other types or when types already match, keep as-is
    return user_config


# Additional legacy constants that might be referenced
CONFIG_DEFAULTS_PATH_INDEX: str | None = None  # Will be set by initialize_secure_config
