"""Feature Flags — Toggle Management System (Constitution v4.0 Architecture Standard).

Provides a lightweight feature toggle system for gradual rollouts, A/B testing,
kill-switches, and environment-specific feature gating. Supports multiple
toggle backends (in-memory for development, JSON config for production).

Architecture Standard: Feature Flags
Constitution Principle: Continuous Improvement, Backward Compatibility

Usage:
    from core.feature_flags import get_feature_flag_manager

    fm = get_feature_flag_manager()
    fm.register_flag("new_dashboard", default=False, description="New dashboard UI")
    fm.register_flag("ml_v2", default=True, owners=["ml-team"], description="ML v2 model")

    if fm.is_enabled("new_dashboard", user_id="abc123"):
        # Show new dashboard
        pass

    # Gradual rollout: 25% of users
    fm.set_rollout("new_dashboard", 25)
    if fm.is_enabled("new_dashboard", user_id="user_42"):
        pass  # Only 25% of users get this
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from hashlib import md5
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)


# ── Data Models ──────────────────────────────────────────────────────────────


@dataclass
class FeatureFlag:
    """A single feature flag definition."""

    key: str = ""
    default: bool = False
    description: str = ""
    owners: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    rollout_pct: float = 100.0  # 0.0 to 100.0
    environment_overrides: dict[str, bool] = field(default_factory=dict)
    created_at: float = 0.0
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "default": self.default,
            "description": self.description,
            "owners": self.owners,
            "tags": self.tags,
            "rollout_pct": self.rollout_pct,
            "environment_overrides": self.environment_overrides,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class FlagEvaluation:
    """Result of evaluating a feature flag."""

    key: str = ""
    enabled: bool = False
    reason: str = ""  # default | override | rollout | environment
    source: str = "default"
    user_id: str = ""


# ── Feature Flag Manager ────────────────────────────────────────────────────


class FeatureFlagManager:
    """Manages feature flags with gradual rollout, environment overrides.

    Thread-safe. Supports JSON persistence.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._flags: dict[str, FeatureFlag] = {}
        self._persist_path = Path("json/feature_flags.json")
        self._environment: str = "development"
        self._load_flags()

    # ── Registration ──────────────────────────────────────────────────────

    def register_flag(
        self,
        key: str,
        default: bool = False,
        description: str = "",
        owners: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> FeatureFlag:
        """Register a new feature flag.

        Args:
            key: Unique flag identifier (e.g., 'new_dashboard', 'ml_v2').
            default: Default enabled/disabled state.
            description: Human-readable description.
            owners: Team or individual responsible for the flag.
            tags: Freeform tags for grouping/filtering.

        Returns:
            The registered FeatureFlag.
        """
        now = time.time()
        flag = FeatureFlag(
            key=key.strip(),
            default=default,
            description=description.strip(),
            owners=[o.strip() for o in (owners or []) if o.strip()],
            tags=[t.strip().lower() for t in (tags or []) if t.strip()],
            rollout_pct=100.0 if default else 0.0,
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._flags[key] = flag
            self._persist()
        _log.info("[FEATURE_FLAGS] Registered flag '%s' (default=%s)", key, default)
        return flag

    def unregister_flag(self, key: str) -> bool:
        """Remove a feature flag.

        Returns True if the flag was removed, False if not found.
        """
        with self._lock:
            if key in self._flags:
                del self._flags[key]
                self._persist()
                return True
            return False

    def get_flag(self, key: str) -> FeatureFlag | None:
        """Get a specific flag definition."""
        with self._lock:
            return self._flags.get(key)

    def list_flags(self, tag: str = "") -> list[FeatureFlag]:
        """List all registered flags, optionally filtered by tag."""
        with self._lock:
            flags = list(self._flags.values())
        if tag:
            clean_tag = tag.lower()
            flags = [f for f in flags if clean_tag in f.tags]
        return sorted(flags, key=lambda f: f.key)

    # ── Toggle Control ────────────────────────────────────────────────────

    def set_enabled(self, key: str, enabled: bool) -> bool:
        """Set a flag's default state.

        Returns True if updated, False if flag not found.
        """
        with self._lock:
            flag = self._flags.get(key)
            if flag is None:
                return False
            flag.default = enabled
            flag.updated_at = time.time()
            if enabled:
                flag.rollout_pct = 100.0
            else:
                flag.rollout_pct = 0.0
            self._persist()
            return True

    def set_rollout(self, key: str, percentage: float) -> bool:
        """Set gradual rollout percentage (0.0 to 100.0).

        Args:
            key: Flag key.
            percentage: 0.0 (disabled for all) to 100.0 (enabled for all).

        Returns:
            True if updated, False if flag not found.
        """
        pct = max(0.0, min(100.0, percentage))
        with self._lock:
            flag = self._flags.get(key)
            if flag is None:
                return False
            flag.rollout_pct = pct
            flag.default = pct > 0
            if pct > 0:
                flag.default = True  # May still be rolled out
            else:
                flag.default = False
            flag.updated_at = time.time()
            self._persist()
            return True

    def set_environment_override(self, key: str, environment: str, enabled: bool) -> bool:
        """Override a flag's state for a specific environment.

        Args:
            key: Flag key.
            environment: Environment name (production, staging, development).
            enabled: Override state.

        Returns:
            True if updated, False if flag not found.
        """
        with self._lock:
            flag = self._flags.get(key)
            if flag is None:
                return False
            flag.environment_overrides[environment] = enabled
            flag.updated_at = time.time()
            self._persist()
            return True

    def set_environment(self, environment: str) -> None:
        """Set the current environment name.

        Environment overrides take precedence over defaults.
        """
        with self._lock:
            self._environment = environment.strip().lower()

    # ── Evaluation ────────────────────────────────────────────────────────

    def is_enabled(self, key: str, user_id: str = "", context: dict[str, Any] | None = None) -> bool:
        """Check if a feature flag is enabled.

        Evaluation order:
        1. Environment override (if set for current environment)
        2. User-level kill switch (context.get('force_disable'))
        3. Gradual rollout check (based on user_id hash)
        4. Default state

        Args:
            key: Flag key.
            user_id: Optional user identifier for gradual rollout bucketing.
            context: Optional context dict (supports 'force_disable', 'force_enable').

        Returns:
            True if the feature is enabled for this user/context.
        """
        ctx = context or {}

        # Force enable/disable from context
        if ctx.get("force_disable"):
            return False
        if ctx.get("force_enable"):
            return True

        with self._lock:
            flag = self._flags.get(key)
            if flag is None:
                _log.debug("[FEATURE_FLAGS] Unknown flag '%s', returning False", key)
                return False

            # Environment override
            env = self._environment
            if env in flag.environment_overrides:
                return flag.environment_overrides[env]

            # Gradual rollout
            if flag.rollout_pct < 100.0 and user_id:
                bucket = self._bucket_user(key, user_id)
                if bucket > flag.rollout_pct:
                    return False

            return flag.default

    def evaluate(self, key: str, user_id: str = "", context: dict[str, Any] | None = None) -> FlagEvaluation:
        """Evaluate a flag and return detailed evaluation info.

        Useful for debugging flag states.
        """
        ctx = context or {}
        env = self._environment

        with self._lock:
            flag = self._flags.get(key)

            if flag is None:
                return FlagEvaluation(key=key, enabled=False, reason="unknown_flag", source="none")

            # Environment override
            if env in flag.environment_overrides:
                val = flag.environment_overrides[env]
                return FlagEvaluation(key=key, enabled=val, reason="environment_override", source=f"env:{env}")

            # Force context
            if ctx.get("force_disable"):
                return FlagEvaluation(key=key, enabled=False, reason="force_disabled", source="context")
            if ctx.get("force_enable"):
                return FlagEvaluation(key=key, enabled=True, reason="force_enabled", source="context")

            # Gradual rollout
            if flag.rollout_pct < 100.0 and user_id:
                bucket = self._bucket_user(key, user_id)
                if bucket > flag.rollout_pct:
                    return FlagEvaluation(
                        key=key,
                        enabled=False,
                        reason="rollout_excluded",
                        source=f"rollout:{flag.rollout_pct}%",
                    )

            # Default
            return FlagEvaluation(
                key=key,
                enabled=flag.default,
                reason="default",
                source=f"default:{flag.default}",
            )

    def get_stats(self) -> dict[str, Any]:
        """Get feature flag statistics."""
        with self._lock:
            total = len(self._flags)
            enabled = sum(1 for f in self._flags.values() if f.default)
            partial = sum(1 for f in self._flags.values() if 0 < f.rollout_pct < 100)
            overridden = sum(1 for f in self._flags.values() if f.environment_overrides)
            return {
                "total_flags": total,
                "enabled": enabled,
                "disabled": total - enabled,
                "partial_rollouts": partial,
                "environment_overrides": overridden,
                "environment": self._environment,
                "persisted": self._persist_path.is_file(),
            }

    # ── Internal ──────────────────────────────────────────────────────────

    def _bucket_user(self, flag_key: str, user_id: str) -> float:
        """Compute a deterministic bucket (0-100) for a user/flag pair.

        Same user + same flag = same bucket always (consistent experience).
        """
        # MD5 here is used ONLY for deterministic rollout bucketing (never for
        # security/crypto), so mark it non-security to stay FIPS-compatible.
        hash_input = f"{flag_key}:{user_id}".encode()
        hash_hex = md5(hash_input, usedforsecurity=False).hexdigest()
        # Convert first 8 hex chars to a number 0-100
        return (int(hash_hex[:8], 16) % 10000) / 100.0

    # ── Persistence ───────────────────────────────────────────────────────

    def _persist(self) -> None:
        """Persist flags to JSON."""
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "environment": self._environment,
                "flags": {k: v.to_dict() for k, v in self._flags.items()},
            }
            self._persist_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except (OSError, ValueError) as exc:
            _log.debug("[FEATURE_FLAGS] Persist error: %s", exc)

    def _load_flags(self) -> None:
        """Load flags from JSON."""
        try:
            if self._persist_path.is_file():
                data = json.loads(self._persist_path.read_text(encoding="utf-8"))
                self._environment = data.get("environment", "development")
                for key, item in data.get("flags", {}).items():
                    self._flags[key] = FeatureFlag(
                        **{k: v for k, v in item.items() if k in FeatureFlag.__dataclass_fields__}
                    )
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            _log.debug("[FEATURE_FLAGS] Load error: %s", exc)

    def clear_all(self) -> None:
        """Clear all flags (for testing)."""
        with self._lock:
            self._flags.clear()
            if self._persist_path.exists():
                self._persist_path.unlink()


# ── CLI ────────────────────────────────────────────────────────────────────


def _cli() -> None:
    import argparse

    ap = argparse.ArgumentParser(
        prog="python -m core.feature_flags",
        description="Feature Flags — Toggle management and gradual rollout system",
    )
    ap.add_argument("--list", action="store_true", help="List all flags")
    ap.add_argument("--register", type=str, metavar="KEY", help="Register a new flag (default=false)")
    ap.add_argument("--enable", type=str, metavar="KEY", help="Enable a flag")
    ap.add_argument("--disable", type=str, metavar="KEY", help="Disable a flag")
    ap.add_argument("--rollout", type=str, metavar="KEY:PCT", help="Set rollout percentage (e.g., 'new_feat:25')")
    ap.add_argument("--stats", action="store_true", help="Show statistics")
    ap.add_argument("--json", action="store_true", help="Output as JSON")
    args = ap.parse_args()

    fm = get_feature_flag_manager()

    if args.register:
        flag = fm.register_flag(key=args.register, default=False)
        if args.json:
            import json

            print(json.dumps(flag.to_dict(), indent=2))
        else:
            print(f"Registered flag: {flag.key}")
        return

    if args.list:
        flags = fm.list_flags()
        if args.json:
            import json

            print(json.dumps([f.to_dict() for f in flags], indent=2))
        else:
            print(f"{'Flag':<30} {'Default':<10} {'Rollout':<10} {'Owners':<20}")
            print("-" * 70)
            for f in flags:
                print(f"{f.key:<30} {str(f.default):<10} {f.rollout_pct:<10.1f} {', '.join(f.owners):<20}")
        return

    if args.enable:
        ok = fm.set_enabled(args.enable, True)
        print(f"{'Updated' if ok else 'Not found'}: {args.enable}")
        return

    if args.disable:
        ok = fm.set_enabled(args.disable, False)
        print(f"{'Updated' if ok else 'Not found'}: {args.disable}")
        return

    if args.rollout:
        parts = args.rollout.split(":")
        if len(parts) == 2:
            key, pct_str = parts
            try:
                pct = float(pct_str)
                ok = fm.set_rollout(key, pct)
                print(f"{'Updated' if ok else 'Not found'}: {key} -> {pct}%")
            except ValueError:
                print("Invalid percentage")
        else:
            print("Usage: --rollout KEY:PCT")
        return

    if args.stats:
        stats = fm.get_stats()
        if args.json:
            import json

            print(json.dumps(stats, indent=2))
        else:
            print("Feature Flag Stats:")
            for k, v in stats.items():
                print(f"  {k}: {v}")
        return

    ap.print_help()


if __name__ == "__main__":
    _cli()


# ── Singleton ──────────────────────────────────────────────────────────────

_instance: FeatureFlagManager | None = None
_instance_lock = threading.RLock()


def get_feature_flag_manager() -> FeatureFlagManager:
    """Get the singleton FeatureFlagManager instance."""
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = FeatureFlagManager()
        return _instance


def reset_feature_flag_manager() -> None:
    """Force-reset singleton (for testing)."""
    global _instance
    with _instance_lock:
        _instance = None


__all__ = [
    "FeatureFlag",
    "FeatureFlagManager",
    "FlagEvaluation",
    "get_feature_flag_manager",
    "reset_feature_flag_manager",
]
