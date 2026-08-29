"""Configuration Loader — extracted from index_trader.py ``_load_config()``.

Provides ConfigLoader class (canonical loading path), ConfigResult named
tuple (typed return), and convenience functions for backward compatibility
with legacy call sites.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading as _threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


# ── Typed result ──────────────────────────────────────────────────────────────


@dataclass
class ConfigResult:
    """Result of a config-loading operation."""

    cfg: dict[str, Any] = field(default_factory=dict)
    success: bool = True
    error_message: str = ""
    resolved_path: str = ""
    checksum_ok: bool = True


# ── Exceptions ────────────────────────────────────────────────────────────────


class ConfigLoadError(Exception):
    """Raised when configuration cannot be loaded from the designated source."""


class ConfigValidationError(Exception):
    """Raised when a loaded configuration fails validation."""


# ── Defaults ──────────────────────────────────────────────────────────────────


DEFAULT_SAFE_CONFIG: dict[str, Any] = {
    "MANUAL_SIGNALS_ONLY": True,
    "EXECUTION_MODE": "MANUAL",
    "BROKER_API_ENABLED": False,
}

_FAIL_SAFE_CONFIG: dict[str, Any] = {
    "MANUAL_SIGNALS_ONLY": True,
    "EXECUTION_MODE": "MANUAL",
    "BROKER_API_ENABLED": False,
}

# Runtime defaults that the bot reads WITHOUT inline fallbacks and that
# config.json may omit. Injected from index_config.defaults.json so the
# loaded config matches the documented defaults model (defaults <- config
# <- config.local <- OPBUYING_* env). Keep this list small and reviewable.
_DEFAULTS_INJECT_ALLOWLIST: frozenset[str] = frozenset({
    "trades_db",
    "trades_db_path",
    "DB_PATH",
    "web_dashboard_enabled",
    "web_dashboard_port",
})

_defaults_cache: dict[str, Any] | None = None


def _load_defaults_allowlist() -> dict[str, Any]:
    """Return all default values from ``index_config.defaults.json``.

    Cached after first read. Best-effort — returns ``{}`` on any error so
    defaults injection can never fail the load. Excludes documentation/metadata keys.
    """
    global _defaults_cache
    if _defaults_cache is not None:
        return _defaults_cache
    try:
        defaults_path = (
            Path(__file__).resolve().parent.parent.parent.parent
            / "json" / "index_config.defaults.json"
        )
        with open(defaults_path, encoding="utf-8-sig") as fh:
            defaults = json.load(fh)
        _defaults_cache = {
            k: v for k, v in defaults.items()
            if not k.startswith("_") and v is not None
        }
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        _defaults_cache = {}
    return _defaults_cache


def _apply_opbuying_env_overrides(cfg: dict[str, Any], project_root: str | Path | None = None) -> int:
    """Apply ``OPBUYING_*`` environment overrides to top-level config keys.

    Loads .env from project root with override=True so fresh credentials in .env
    always supersede stale shell session variables.
    """
    try:
        disable_dotenv = os.environ.get("OPBUYING_DISABLE_DOTENV", "").strip().lower() in {"1", "true", "yes", "on"}
        if not disable_dotenv:
            from dotenv import load_dotenv
            env_root = Path(project_root).resolve() if project_root else Path(__file__).resolve().parent.parent.parent.parent
            env_file = env_root / ".env"
            if env_file.exists():
                load_dotenv(env_file, override=True)
    except Exception:
        pass

    prefix = "OPBUYING_"
    lower_keys = {k.lower(): k for k in cfg}
    applied = 0
    for env_key, env_value in os.environ.items():
        if not env_key.lower().startswith(prefix.lower()):
            continue
        raw_key = env_key[len(prefix):]
        if not raw_key:
            continue
        target_key = lower_keys.get(raw_key.lower())
        if target_key is None:
            continue
        current = cfg.get(target_key)
        new_value: Any = env_value
        if isinstance(current, bool):
            new_value = env_value.strip().lower() in ("true", "1", "yes", "on")
        elif isinstance(current, int) and not isinstance(current, bool):
            try:
                new_value = int(env_value)
            except ValueError:
                log.debug("Failed to coerce env %s=%s to int", env_key, env_value)
        elif isinstance(current, float):
            try:
                new_value = float(env_value)
            except ValueError:
                log.debug("Failed to coerce env %s=%s to float", env_key, env_value)
        cfg[target_key] = new_value
        applied += 1
    if applied:
        log.info("Applied %d OPBUYING_* environment override(s)", applied)
    return applied


def _resolve_broker_config_env(cfg: dict[str, Any]) -> int:
    """Resolve ``BROKER_CONFIG.<field>_env`` -> ``BROKER_CONFIG.<field>``.

    ``config.json`` declares e.g. ``api_key_env: "OPBUYING_BROKER_API_KEY"``
    — the named environment variable supplies the secret. The plain field
    is only filled while empty so explicit values always win.
    """
    bc = cfg.get("BROKER_CONFIG")
    if not isinstance(bc, dict):
        return 0
    resolved = 0
    for env_key in list(bc.keys()):
        if not str(env_key).endswith("_env"):
            continue
        env_name = str(bc.get(env_key) or "")
        plain = str(env_key)[:-4]
        if not env_name or not plain:
            continue
        if bc.get(plain):
            continue  # explicit value wins over env
        value = os.environ.get(env_name, "")
        if value:
            bc[plain] = value
            resolved += 1
    if resolved:
        log.info("Resolved %d broker credential(s) from environment", resolved)
    return resolved


# ==============================================================================
# ConfigLoader — canonical config loading
# ==============================================================================


class ConfigLoader:
    """Loads, validates, and resolves the trading configuration.

    Responsibilities
    ----------------
    * Resolve config file path from ``OPBUYING_INDEX_CONFIG`` env var (default ``json/config.json``).
    * Guard against config paths that escape the project root.
    * SHA-256 checksum verification against an optional ``_checksum`` field.
    * Parse JSON, merge with defaults, and apply execution mode inference.
    * Run optional validation and secret-hygiene checks.

    Thread safety
    -------------
    The loader itself is stateless (all state is in the returned ``ConfigResult``).
    Callers are responsible for thread-safe assignment of module-level globals.
    """

    def __init__(
        self,
        project_root: str | Path | None = None,
        notifier: Callable[[str], None] | None = None,
    ) -> None:
        self._project_root = Path(project_root).resolve() if project_root else Path.cwd()
        self._notifier = notifier or (lambda msg: None)
        self._load_count: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(
        self,
        force: bool = False,
        env_var: str = "OPBUYING_INDEX_CONFIG",
        default_path: str = "json/config.json",
        strict: bool | None = None,
    ) -> ConfigResult:
        """Load configuration from the resolved path.

        Parameters
        ----------
        force:
            If ``True``, bypass any caller-side caching (increments an internal
            counter for observability but does **not** maintain a cache itself).
        env_var:
            Environment variable that may override *default_path*.
        default_path:
            Fallback path when *env_var* is not set.
        strict:
            If ``True``, schema violations block startup (``ConfigValidationError``
            raised). If ``False``, violations are only logged.
            If ``None`` (default), checks the ``CONFIG_STRICT_SCHEMA_ENFORCEMENT`` key
            in the loaded config (or the ``OPBUYING_CONFIG_STRICT_SCHEMA_ENFORCEMENT``
            env var). **Default is now True** for production safety.

        Returns
        -------
        ConfigResult with the parsed configuration or a safe default on failure.

        Raises
        ------
        ConfigValidationError
            When *strict* is ``True`` and JSON Schema violations are detected.
        """
        if force:
            self._load_count += 1

        cfg_path = os.environ.get(env_var, default_path)

        # ── Path-safety guard ────────────────────────────────────────────────
        try:
            resolved = Path(cfg_path).resolve()
            resolved.relative_to(self._project_root)
        except ValueError:
            log.warning(
                "Config path '%s' resolves outside project root '%s' — using defaults",
                cfg_path,
                self._project_root,
            )
            return ConfigResult(
                cfg=dict(DEFAULT_SAFE_CONFIG),
                success=True,
                error_message=f"Path '{cfg_path}' outside project root",
                resolved_path=str(resolved),
            )

        # ── Read raw bytes + checksum verification ───────────────────────────
        try:
            with open(resolved, "rb") as fh:
                raw_bytes = fh.read()
        except FileNotFoundError:
            template_path = resolved.parent / "config.template.json"
            if template_path.exists():
                log.info(
                    "Config file '%s' not found — bootstrapping from template '%s'",
                    resolved,
                    template_path,
                )
                try:
                    with open(template_path, "rb") as tfh:
                        raw_bytes = tfh.read()
                    # Write out the bootstrapped config.json for persistence
                    with open(resolved, "wb") as out_fh:
                        out_fh.write(raw_bytes)
                except OSError as _b_err:
                    log.warning("Could not persist bootstrapped config: %s", _b_err)
            else:
                log.warning("Config file '%s' not found — using safe defaults", resolved)
                self._notifier(f"Config file '{resolved}' not found — using safe defaults")
                return ConfigResult(
                    cfg=dict(_FAIL_SAFE_CONFIG),
                    success=False,
                    error_message=f"File not found: {resolved}",
                    resolved_path=str(resolved),
                )

        computed_checksum = hashlib.sha256(raw_bytes).hexdigest()

        try:
            raw_cfg: dict[str, Any] = json.loads(raw_bytes.decode("utf-8"))
        except json.JSONDecodeError as exc:
            log.error("Config file '%s' is not valid JSON: %s", resolved, exc)
            self._notifier(f"Config file '{resolved}' not valid JSON — using safe defaults")
            return ConfigResult(
                cfg=dict(_FAIL_SAFE_CONFIG),
                success=False,
                error_message=f"JSON decode error: {exc}",
                resolved_path=str(resolved),
            )

        cfg = dict(raw_cfg)
        stored_checksum = cfg.pop("_checksum", None)
        checksum_ok = True
        if stored_checksum:
            # Re-compute checksum on the content WITHOUT the _checksum field
            content_without_cs = json.dumps(cfg, sort_keys=True, default=str).encode("utf-8")
            computed_checksum = hashlib.sha256(content_without_cs).hexdigest()
            if computed_checksum != stored_checksum:
                log.error(
                    "Config checksum mismatch for '%s' — file may be corrupted. Using defaults.",
                    resolved,
                )
                checksum_ok = False
                cfg = dict(_FAIL_SAFE_CONFIG)
                return ConfigResult(
                    cfg=cfg,
                    success=False,
                    error_message="Checksum mismatch",
                    resolved_path=str(resolved),
                    checksum_ok=False,
                )

        log.info("Config loaded from %s", resolved)

        # ── Merge documented runtime defaults (allowlist) ────────────────────
        for _default_key, _default_value in _load_defaults_allowlist().items():
            if _default_key not in cfg:
                cfg[_default_key] = _default_value

        # ── OPBUYING_* env overrides + broker credential bridge ──────────────
        _apply_opbuying_env_overrides(cfg, project_root=self._project_root)
        _resolve_broker_config_env(cfg)

        # ── Post-load validation ─────────────────────────────────────────────
        schema_errors: list[str] = []
        self._run_post_load_checks(cfg, schema_errors)

        # ── Strict schema enforcement (DEBT-005) ───────────────────────────
        if strict is None:
            # Check config key (from the loaded config) or env var override
            # DEFAULT to True for fail-fast startup (DEBT-005 fix)
            strict = bool(
                cfg.get("CONFIG_STRICT_SCHEMA_ENFORCEMENT", True)
                or os.environ.get("OPBUYING_CONFIG_STRICT_SCHEMA_ENFORCEMENT", "")
                .strip().lower() in ("1", "true", "yes")
            )
        if strict and schema_errors:
            msg = (
                f"CONFIG SCHEMA VIOLATION: {len(schema_errors)} error(s) found. "
                f"Set CONFIG_STRICT_SCHEMA_ENFORCEMENT=false or "
                f"OPBUYING_CONFIG_STRICT_SCHEMA_ENFORCEMENT=0 to bypass.\n"
                + "\n".join(schema_errors)
            )
            log.critical(msg)
            raise ConfigValidationError(msg)

        return ConfigResult(
            cfg=cfg,
            success=True,
            resolved_path=str(resolved),
            checksum_ok=checksum_ok,
        )

    def make_fail_safe_config(self) -> dict[str, Any]:
        """Return a copy of the fail-safe configuration dict."""
        return dict(_FAIL_SAFE_CONFIG)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run_post_load_checks(self, cfg: dict[str, Any], schema_errors: list[str] | None = None) -> None:
        """Run config validation and secret-hygiene checks (best-effort).

        Appends JSON Schema violations to *schema_errors* when a list is
        provided (used by fail-fast strict mode).
        """
        # JSON Schema validation (uses committed schema file)
        try:
            from core.config_schema_validate import append_json_schema_errors
            _schema_errs: list[str] = []
            append_json_schema_errors(_schema_errs, cfg, flavour="index")
            if _schema_errs:
                for err in _schema_errs:
                    log.warning("[CONFIG_SCHEMA] %s", err)
                if schema_errors is not None:
                    schema_errors.extend(_schema_errs)
        except ImportError:
            pass
        except (ValueError, TypeError, KeyError, SystemExit) as exc:
            log.debug("JSON Schema validation skipped: %s", exc)

        # Config validation (legacy path)
        try:
            from core.config_validator import validate_and_log

            errors, warnings = validate_and_log(cfg)
            if errors:
                log.warning("Config validation: %d errors", len(errors))
            if warnings:
                log.warning("Config validation: %d warnings", len(warnings))
        except ImportError:
            pass
        except (ValueError, TypeError, KeyError, SystemExit) as exc:
            log.debug("Config validation skipped: %s", exc)

        # Secret-hygiene check
        try:
            from core.secret_hygiene import check_config_secrets

            result = check_config_secrets(cfg)
            if result.secrets_found:
                for s in result.secrets_found:
                    log.warning("[SECRET_HYGIENE] %s", s)
            if result.warnings:
                for w in result.warnings:
                    log.warning("[SECRET_HYGIENE] %s", w)
        except ImportError:
            pass
        except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError):
            log.debug("Secret-hygiene check skipped")

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def load_count(self) -> int:
        """Number of times ``load()`` has been called."""
        return self._load_count


# ==============================================================================
# Convenience functions (backward-compatible shims for legacy call sites)
# ==============================================================================

_shared_loader: ConfigLoader | None = None
_loader_lock = _threading.RLock()


def get_config_loader(
    project_root: str | Path | None = None,
    notifier: Callable[[str], None] | None = None,
) -> ConfigLoader:
    """Return the shared ``ConfigLoader`` singleton.

    Creates one on first call; subsequent calls return the same instance.
    Thread-safe via ``_loader_lock``.
    """
    global _shared_loader
    if _shared_loader is None:
        with _loader_lock:
            # Double-checked locking
            if _shared_loader is None:
                _shared_loader = ConfigLoader(
                    project_root=project_root or Path(__file__).resolve().parent.parent.parent.parent,
                    notifier=notifier,
                )
    return _shared_loader


def load_config(
    force: bool = False,
    env_var: str = "OPBUYING_INDEX_CONFIG",
    default_path: str = "json/config.json",
) -> ConfigResult:
    """Convenience: load config via the shared loader.

    Equivalent to ``get_config_loader().load(force, env_var, default_path)``.
    """
    return get_config_loader().load(force=force, env_var=env_var, default_path=default_path)


def make_fail_safe_config() -> dict[str, Any]:
    """Convenience: return fail-safe config dict."""
    return dict(_FAIL_SAFE_CONFIG)


__all__ = [
    "ConfigLoader",
    "ConfigLoadError",
    "ConfigResult",
    "ConfigValidationError",
    "get_config_loader",
    "load_config",
    "make_fail_safe_config",
]
