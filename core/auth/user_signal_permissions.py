"""User Signal Permissions & Multi-Timeframe Quota Manager (v3.0).

Provides granular role-based signal dispatch controls for the Super Admin:
- Master Signal Toggle (Allow / Block per user)
- Granular Asset Category Subscriptions (Index Options, Large-Cap, Mid/Small, Penny/SME, Commodities, Currencies, Futures, ETFs)
- Conviction Tier Filtering (STRONG >= 80 vs MODERATE >= 68)
- Multi-Timeframe Quotas (Daily, Weekly, Monthly, Yearly limits) with automated boundary resets
- Dedicated Channel Routing (User-specific Telegram Chat ID & Email address)
- Full Audit Trail & Pre-Guard Safety Enforcement
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from core.datetime_ist import now_ist

_log = logging.getLogger("USER_PERMISSIONS")
_ROOT = Path(__file__).resolve().parent.parent.parent
_PERMISSIONS_STORE_PATH = _ROOT / "json" / "user_signal_permissions.json"

ALL_CATEGORIES: list[str] = [
    "INDEX_OPTIONS",
    "STOCK_OPTIONS",
    "EQUITY_SWING_DELIVERY",
    "LARGE_CAP_EQUITY",
    "MID_SMALL_CAP",
    "PENNY_SME",
    "COMMODITIES",
    "CURRENCIES",
    "FUTURES",
    "ETFS_REITS",
]


@dataclass
class UserSignalPermission:
    username: str
    display_name: str = ""
    role: str = "viewer"  # super_admin, admin, operator, viewer, observer, developer

    # Optional per-user RBAC overrides. Empty lists mean role defaults.
    # `allowed_permissions` may add capabilities; `denied_permissions` may remove them.
    allowed_permissions: list[str] = field(default_factory=list)
    denied_permissions: list[str] = field(default_factory=list)
    is_active: bool = True

    # Master Signal Switch
    signals_enabled: bool = True

    # Granular Category Permissions
    allowed_categories: list[str] = field(default_factory=lambda: list(ALL_CATEGORIES))

    # Minimum Conviction Tier
    min_signal_tier: str = "MODERATE_AND_STRONG"  # STRONG_ONLY, MODERATE_AND_STRONG, ALL

    # Custom Channel Routing
    telegram_enabled: bool = True
    telegram_chat_id: str = ""
    email_enabled: bool = True
    email: str = ""

    # Multi-Timeframe Quotas (0 = Unlimited)
    max_signals_daily: int = 15
    max_signals_weekly: int = 75
    max_signals_monthly: int = 300
    max_signals_yearly: int = 3600

    # Quota Usage Tracking
    daily_signals_used: int = 0
    weekly_signals_used: int = 0
    monthly_signals_used: int = 0
    yearly_signals_used: int = 0

    # Reset Timestamps (ISO format)
    last_daily_reset: str = field(default_factory=lambda: now_ist().date().isoformat())
    last_weekly_reset: str = field(default_factory=lambda: f"{now_ist().year}-W{now_ist().isocalendar()[1]}")
    last_monthly_reset: str = field(default_factory=lambda: f"{now_ist().year}-{now_ist().month:02d}")
    last_yearly_reset: str = field(default_factory=lambda: str(now_ist().year))

    updated_at: str = field(default_factory=lambda: now_ist().isoformat())
    updated_by: str = "system"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class UserPermissionManager:
    """Thread-safe Singleton Manager for User Signal Permissions & Quotas."""

    _instance: UserPermissionManager | None = None
    _lock = threading.Lock()

    def __init__(self, store_path: Path | None = None) -> None:
        self._path = store_path or _PERMISSIONS_STORE_PATH
        self._permissions: dict[str, UserSignalPermission] = {}
        self._io_lock = threading.Lock()
        self._load()

    @classmethod
    def get_instance(cls) -> UserPermissionManager:
        with cls._lock:
            if cls._instance is None:
                cls._instance = UserPermissionManager()
            return cls._instance

    def _load(self) -> None:
        """Load permissions from JSON store or seed defaults."""
        with self._io_lock:
            if self._path.exists():
                try:
                    with open(self._path, encoding="utf-8") as f:
                        data = json.load(f)
                    for uname, udata in data.items():
                        # Migrate missing fields gracefully
                        valid_fields = UserSignalPermission.__dataclass_fields__.keys()
                        filtered = {k: v for k, v in udata.items() if k in valid_fields}
                        self._permissions[uname] = UserSignalPermission(**filtered)
                    _log.info("Loaded %d user signal permissions from %s", len(self._permissions), self._path)
                    return
                except Exception as ex:
                    _log.warning("Failed to load permissions store: %s. Seeding defaults.", ex)

            # Seed default admin user
            self._seed_default_users()

    def _seed_default_users(self) -> None:
        """Seed initial super admin & default users."""
        # Notification destinations are runtime configuration. Never embed
        # credentials or personal routing identifiers in source code.
        cfg: dict[str, Any] = {}
        try:
            cfg_path = _ROOT / "json" / "config.json"
            if cfg_path.exists():
                cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception as exc:
            _log.warning("Failed to load admin notification defaults: %s", exc)
        admin_email = str(os.getenv("OPBUYING_EMAIL_TO") or cfg.get("EMAIL_TO") or "").strip()
        admin_chat = str(
            os.getenv("OPBUYING_CHAT_ID")
            or os.getenv("OPBUYING_TELEGRAM_CHAT_ID")
            or cfg.get("CHAT_ID")
            or ""
        ).strip()
        default_admin = UserSignalPermission(
            username="admin",
            display_name="Super Admin",
            role="admin",
            is_active=True,
            signals_enabled=True,
            allowed_categories=list(ALL_CATEGORIES),
            min_signal_tier="STRONG_ONLY",
            telegram_enabled=bool(admin_chat),
            telegram_chat_id=admin_chat,
            email_enabled=bool(admin_email),
            email=admin_email,
            max_signals_daily=0,  # Unlimited
            max_signals_weekly=0,
            max_signals_monthly=0,
            max_signals_yearly=0,
            updated_by="system",
        )
        self._permissions["admin"] = default_admin
        self._save_unlocked()

    def _save_unlocked(self) -> None:
        """Write in-memory permissions to disk."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            serializable = {uname: u.to_dict() for uname, u in self._permissions.items()}
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(serializable, f, indent=4, sort_keys=True)
        except Exception as ex:
            _log.error("Failed to persist user permissions: %s", ex)

    def _check_and_reset_quotas(self, perm: UserSignalPermission) -> bool:
        """Check and reset daily, weekly, monthly counters if boundaries crossed."""
        now = now_ist()
        today_str = now.date().isoformat()
        current_week_str = f"{now.year}-W{now.isocalendar()[1]}"
        current_month_str = f"{now.year}-{now.month:02d}"
        current_year_str = str(now.year)
        modified = False

        if perm.last_daily_reset != today_str:
            perm.daily_signals_used = 0
            perm.last_daily_reset = today_str
            modified = True

        if perm.last_weekly_reset != current_week_str:
            perm.weekly_signals_used = 0
            perm.last_weekly_reset = current_week_str
            modified = True

        if perm.last_monthly_reset != current_month_str:
            perm.monthly_signals_used = 0
            perm.last_monthly_reset = current_month_str
            modified = True

        if perm.last_yearly_reset != current_year_str:
            perm.yearly_signals_used = 0
            perm.last_yearly_reset = current_year_str
            modified = True

        return modified

    def get_user_permissions(self, username: str) -> UserSignalPermission | None:
        self._load()
        with self._io_lock:
            perm = self._permissions.get(username)
            if perm:
                if self._check_and_reset_quotas(perm):
                    self._save_unlocked()
            return perm

    def list_all_permissions(self) -> list[dict[str, Any]]:
        self._load()
        with self._io_lock:
            results = []
            modified = False
            for perm in self._permissions.values():
                if self._check_and_reset_quotas(perm):
                    modified = True
                results.append(perm.to_dict())
            if modified:
                self._save_unlocked()
            return results

    def update_user_permissions(
        self,
        username: str,
        data: dict[str, Any],
        admin_username: str = "admin",
    ) -> tuple[bool, str, dict[str, Any] | None]:
        """Update or register permissions for a user."""
        with self._io_lock:
            existing = self._permissions.get(username)
            if existing is None:
                # Create new entry
                valid_fields = UserSignalPermission.__dataclass_fields__.keys()
                filtered = {k: v for k, v in data.items() if k in valid_fields}
                filtered["username"] = username
                filtered["updated_by"] = admin_username
                filtered["updated_at"] = now_ist().isoformat()
                new_perm = UserSignalPermission(**filtered)
                self._permissions[username] = new_perm
                self._save_unlocked()
                _log.info("[ADMIN] SuperAdmin %s created permissions for user %s", admin_username, username)
                return True, f"Permissions created for user {username}", new_perm.to_dict()

            # Update existing entry
            for k, v in data.items():
                if hasattr(existing, k) and k not in ("username", "daily_signals_used", "weekly_signals_used", "monthly_signals_used", "yearly_signals_used", "last_daily_reset", "last_weekly_reset", "last_monthly_reset", "last_yearly_reset"):
                    setattr(existing, k, v)

            existing.updated_by = admin_username
            existing.updated_at = now_ist().isoformat()
            self._save_unlocked()
            _log.info("[ADMIN] SuperAdmin %s updated permissions for user %s", admin_username, username)
            return True, f"Permissions updated for user {username}", existing.to_dict()


    def get_effective_permissions(self, username: str, base_role: str | None = None) -> set[str]:
        """Return effective permissions after applying per-user overrides.

        Super Admin remains unrestricted. Unknown/invalid override names are ignored.
        The role is the baseline; explicit denies win over allows.
        """
        from core.auth.permissions import get_role_permissions
        perm = self.get_user_permissions(username)
        if perm is None:
            return set()
        # Auth DB role is authoritative; permission-record role is metadata only.
        role_name = str(base_role or perm.role or "viewer").lower()
        if role_name == "super_admin":
            return {p.value for p in get_role_permissions("super_admin")}
        effective = {p.value for p in get_role_permissions(role_name)}
        valid = {p.value for p in __import__("core.auth.permissions", fromlist=["Permission"]).Permission}
        effective.update(str(p).lower() for p in perm.allowed_permissions if str(p).lower() in valid)
        effective.difference_update(str(p).lower() for p in perm.denied_permissions)
        return effective

    def user_has_permission(self, username: str, permission: str, base_role: str | None = None) -> bool:
        return str(permission).lower() in self.get_effective_permissions(username, base_role=base_role)

    def delete_user_permissions(self, username: str) -> bool:
        """Permanently delete user signal permissions from store."""
        with self._io_lock:
            if username in self._permissions:
                del self._permissions[username]
                self._save_unlocked()
                _log.info("[ADMIN] Deleted user permissions for %s", username)
                return True
            return False

    def prune_stale_users(self, active_usernames: set[str]) -> int:
        """Remove permission entries for users that no longer exist in auth DB."""
        with self._io_lock:
            stale = [uname for uname in self._permissions if uname not in active_usernames and uname != "admin"]
            for uname in stale:
                del self._permissions[uname]
            if stale:
                self._save_unlocked()
                _log.info("[ADMIN] Pruned %d stale user permissions: %s", len(stale), stale)
            return len(stale)

    def toggle_user_signals(self, username: str, admin_username: str = "admin") -> tuple[bool, str, bool]:
        """One-click toggle master signal switch for a user."""
        with self._io_lock:
            perm = self._permissions.get(username)
            if not perm:
                return False, f"User {username} not found", False

            perm.signals_enabled = not perm.signals_enabled
            perm.updated_by = admin_username
            perm.updated_at = now_ist().isoformat()
            self._save_unlocked()
            _log.info("[ADMIN] SuperAdmin %s toggled signals for %s -> %s",
                      admin_username, username, perm.signals_enabled)
            return True, f"Signals {'ENABLED' if perm.signals_enabled else 'BLOCKED'} for {username}", perm.signals_enabled

    def get_eligible_recipients(
        self,
        category: str,
        tier: str,
        symbol: str = "",
    ) -> list[UserSignalPermission]:
        """Pre-guard evaluation: returns all users authorized to receive this signal.

        Evaluates:
        1. User is active and signals_enabled == True.
        2. Category is in user's allowed_categories.
        3. Signal tier satisfies user's min_signal_tier.
        4. User has not exceeded daily, weekly, monthly, or yearly quota.
        """
        eligible: list[UserSignalPermission] = []
        tier_upper = tier.upper()
        cat_upper = category.upper()

        self._load()

        with self._io_lock:
            modified = False
            for perm in self._permissions.values():
                self._check_and_reset_quotas(perm)

                if not perm.is_active or not perm.signals_enabled:
                    continue

                # Category check
                if cat_upper not in [c.upper() for c in perm.allowed_categories]:
                    continue

                # Tier check
                if perm.min_signal_tier == "STRONG_ONLY" and tier_upper != "STRONG":
                    continue
                if perm.min_signal_tier == "MODERATE_AND_STRONG" and tier_upper not in ("STRONG", "MODERATE"):
                    continue

                # Quota checks (0 = unlimited)
                if perm.max_signals_daily > 0 and perm.daily_signals_used >= perm.max_signals_daily:
                    _log.debug("User %s daily signal quota reached (%d/%d)",
                              perm.username, perm.daily_signals_used, perm.max_signals_daily)
                    continue

                if perm.max_signals_weekly > 0 and perm.weekly_signals_used >= perm.max_signals_weekly:
                    _log.debug("User %s weekly signal quota reached (%d/%d)",
                              perm.username, perm.weekly_signals_used, perm.max_signals_weekly)
                    continue

                if perm.max_signals_monthly > 0 and perm.monthly_signals_used >= perm.max_signals_monthly:
                    _log.debug("User %s monthly signal quota reached (%d/%d)",
                              perm.username, perm.monthly_signals_used, perm.max_signals_monthly)
                    continue

                if perm.max_signals_yearly > 0 and perm.yearly_signals_used >= perm.max_signals_yearly:
                    _log.debug("User %s yearly signal quota reached (%d/%d)",
                              perm.username, perm.yearly_signals_used, perm.max_signals_yearly)
                    continue

                # Increment quota usage
                perm.daily_signals_used += 1
                perm.weekly_signals_used += 1
                perm.monthly_signals_used += 1
                perm.yearly_signals_used += 1
                modified = True
                eligible.append(perm)

            if modified:
                self._save_unlocked()

        return eligible
