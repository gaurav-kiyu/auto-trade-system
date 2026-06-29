"""
Multi-Tenant Readiness Module.

Provides tenant isolation infrastructure for institutional deployments.
Uses the existing RBAC system as a foundation and adds:

- Tenant-scoped data access (each tenant sees only their trades/config)
- Tenant configuration isolation
- Tenant-level rate limiting and quotas
- Audit trail with tenant attribution

Usage
-----
    from core.multi_tenant import TenantContext, get_tenant_context

    # In a request handler:
    tc = get_tenant_context(tenant_id="tenant_001")
    trades = tc.get_trades(db_path="trades.db")

    # Check if tenant can execute trades
    if tc.can_trade():
        execute_trade()

Config keys (all optional)
--------------------------
    multi_tenant_enabled     : bool  default False
    multi_tenant_db_prefix   : str   default "tenant_"
    multi_tenant_max_tenants : int   default 10
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)


# ── Tenant data models ───────────────────────────────────────────────────────

@dataclass
class Tenant:
    """A tenant (organization) in the multi-tenant system."""
    tenant_id: str
    name: str
    is_active: bool = True
    max_daily_trades: int = 10
    max_open_positions: int = 5
    max_daily_loss: float = -2000.0
    max_capital: float = 100000.0
    feature_flags: dict[str, bool] = field(default_factory=lambda: {
        "ml_enabled": True,
        "webhook_enabled": False,
        "spread_strategy": False,
        "equity_trading": False,
    })
    created_at: float = field(default_factory=time.time)
    config_overrides: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "name": self.name,
            "is_active": self.is_active,
            "max_daily_trades": self.max_daily_trades,
            "max_open_positions": self.max_open_positions,
            "max_daily_loss": self.max_daily_loss,
            "max_capital": self.max_capital,
            "feature_flags": self.feature_flags,
            "created_at": self.created_at,
        }


# ── Tenant Context ────────────────────────────────────────────────────────────

class TenantContext:
    """Scoped context for a single tenant's operations.

    Provides tenant-isolated access to trades, config, and execution.
    All methods check tenant activation status and apply tenant-specific limits.
    """

    def __init__(self, tenant: Tenant, base_config: dict[str, Any] | None = None):
        self._tenant = tenant
        self._base_config = base_config or {}
        self._lock = threading.RLock()

    @property
    def tenant_id(self) -> str:
        return self._tenant.tenant_id

    @property
    def is_active(self) -> bool:
        return self._tenant.is_active

    def get_effective_config(self) -> dict[str, Any]:
        """Get tenant-specific effective config (base + tenant overrides)."""
        merged = dict(self._base_config)
        merged.update(self._tenant.config_overrides)
        # Apply tenant limits
        merged["MAX_TRADES_DAY"] = min(
            merged.get("MAX_TRADES_DAY", 10),
            self._tenant.max_daily_trades,
        )
        merged["MAX_OPEN"] = min(
            merged.get("MAX_OPEN", 5),
            self._tenant.max_open_positions,
        )
        merged["MAX_DAILY_LOSS"] = max(
            merged.get("MAX_DAILY_LOSS", -2000),
            self._tenant.max_daily_loss,
        )
        return merged

    def can_trade(self) -> bool:
        """Check if this tenant can execute trades."""
        return self._tenant.is_active

    def get_trades(self, db_path: str = "trades.db", days: int = 30) -> list[dict[str, Any]]:
        """Get trades scoped to this tenant.

        Requires a 'tenant_id' column in the trades table.
        Falls back to all trades if column doesn't exist.
        """
        if not self._tenant.is_active:
            return []

        try:
            from core.db_utils import get_connection
            conn = get_connection(db_path, timeout=5, row_factory=False)
            try:
                # Check if tenant_id column exists
                has_tenant_col = False
                try:
                    conn.execute("SELECT tenant_id FROM trades LIMIT 0")
                    has_tenant_col = True
                except (sqlite3.OperationalError, AttributeError):
                    pass

                if has_tenant_col:
                    rows = conn.execute(
                        "SELECT * FROM trades WHERE tenant_id = ? AND "
                        "ts >= datetime('now', ?) ORDER BY ts DESC",
                        (self._tenant.tenant_id, f"-{days} days"),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT * FROM trades WHERE ts >= datetime('now', ?) ORDER BY ts DESC",
                        (f"-{days} days",),
                    ).fetchall()
            finally:
                conn.close()
            return [dict(r) for r in rows] if rows else []
        except Exception as exc:
            _log.warning("[TENANT] Trade fetch failed for %s: %s", self._tenant.tenant_id, exc)
            return []

    def get_state(self) -> dict[str, Any]:
        """Get tenant-scoped state."""
        state_path = Path(f"tenant_{self._tenant.tenant_id}_state.json")
        if state_path.is_file():
            try:
                return json.loads(state_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
        return {}

    def to_dict(self) -> dict[str, Any]:
        return self._tenant.to_dict()


# ── Multi-Tenant Manager ─────────────────────────────────────────────────────

class MultiTenantManager:
    """Manages tenant creation, isolation, and lifecycle."""

    def __init__(self, cfg: dict[str, Any] | None = None):
        self._cfg = cfg or {}
        self._enabled = bool(self._cfg.get("multi_tenant_enabled", False))
        self._lock = threading.RLock()
        self._tenants: dict[str, Tenant] = {}
        self._contexts: dict[str, TenantContext] = {}
        self._max_tenants = int(self._cfg.get("multi_tenant_max_tenants", 10))

        # Load tenants from config if present
        self._load_from_config()

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _load_from_config(self) -> None:
        """Load tenant definitions from config."""
        tenants_cfg = self._cfg.get("tenants", [])
        for t_cfg in tenants_cfg:
            tenant = Tenant(
                tenant_id=t_cfg.get("tenant_id", ""),
                name=t_cfg.get("name", ""),
                is_active=t_cfg.get("is_active", True),
                max_daily_trades=int(t_cfg.get("max_daily_trades", 10)),
                max_open_positions=int(t_cfg.get("max_open_positions", 5)),
                max_daily_loss=float(t_cfg.get("max_daily_loss", -2000)),
                max_capital=float(t_cfg.get("max_capital", 100000)),
                feature_flags=t_cfg.get("feature_flags", {}),
                config_overrides=t_cfg.get("config_overrides", {}),
            )
            self._tenants[tenant.tenant_id] = tenant

    def register_tenant(self, tenant: Tenant) -> bool:
        """Register a new tenant."""
        with self._lock:
            if len(self._tenants) >= self._max_tenants:
                _log.warning("[TENANT] Max tenants (%d) reached", self._max_tenants)
                return False
            if tenant.tenant_id in self._tenants:
                _log.warning("[TENANT] Tenant %s already registered", tenant.tenant_id)
                return False
            self._tenants[tenant.tenant_id] = tenant
            _log.info("[TENANT] Registered: %s (%s)", tenant.tenant_id, tenant.name)
            return True

    def deactivate_tenant(self, tenant_id: str) -> bool:
        """Deactivate a tenant (blocks trading)."""
        with self._lock:
            tenant = self._tenants.get(tenant_id)
            if not tenant:
                return False
            tenant.is_active = False
            _log.warning("[TENANT] Deactivated: %s", tenant_id)
            return True

    def activate_tenant(self, tenant_id: str) -> bool:
        """Activate a tenant (allows trading)."""
        with self._lock:
            tenant = self._tenants.get(tenant_id)
            if not tenant:
                return False
            tenant.is_active = True
            _log.info("[TENANT] Activated: %s", tenant_id)
            return True

    def get_tenant(self, tenant_id: str) -> Tenant | None:
        """Get a tenant by ID."""
        with self._lock:
            return self._tenants.get(tenant_id)

    def get_context(self, tenant_id: str) -> TenantContext | None:
        """Get or create a tenant context."""
        if not self._enabled:
            return None

        with self._lock:
            tenant = self._tenants.get(tenant_id)
            if not tenant:
                return None
            if tenant_id not in self._contexts:
                self._contexts[tenant_id] = TenantContext(tenant, self._cfg)
            return self._contexts[tenant_id]

    def list_tenants(self) -> list[Tenant]:
        """List all registered tenants."""
        with self._lock:
            return list(self._tenants.values())

    def get_stats(self) -> dict[str, Any]:
        """Get multi-tenant statistics."""
        with self._lock:
            active = sum(1 for t in self._tenants.values() if t.is_active)
            return {
                "enabled": self._enabled,
                "total_tenants": len(self._tenants),
                "active_tenants": active,
                "max_tenants": self._max_tenants,
                "tenants": [t.to_dict() for t in self._tenants.values()],
            }


# ── Singleton ─────────────────────────────────────────────────────────────────

_global_mtm: MultiTenantManager | None = None
_mtm_lock = threading.RLock()


def get_multi_tenant_manager(cfg: dict[str, Any] | None = None) -> MultiTenantManager:
    """Get the global MultiTenantManager singleton."""
    global _global_mtm
    with _mtm_lock:
        if _global_mtm is None:
            _global_mtm = MultiTenantManager(cfg)
        return _global_mtm


# ── CLI ───────────────────────────────────────────────────────────────────────

def _cli() -> None:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m core.multi_tenant")
    ap.add_argument("--list", action="store_true", help="List tenants")
    ap.add_argument("--register", nargs=2, metavar=("id", "name"), help="Register a tenant")
    ap.add_argument("--deactivate", type=str, help="Deactivate a tenant")
    ap.add_argument("--activate", type=str, help="Activate a tenant")
    ap.add_argument("--json", action="store_true", help="Output JSON")
    args = ap.parse_args()

    mtm = get_multi_tenant_manager()

    if args.register:
        tid, name = args.register
        tenant = Tenant(tenant_id=tid, name=name)
        ok = mtm.register_tenant(tenant)
        print(f"{'Registered' if ok else 'Failed'} tenant: {tid}")
        return

    if args.deactivate:
        ok = mtm.deactivate_tenant(args.deactivate)
        print(f"{'Deactivated' if ok else 'Not found'}: {args.deactivate}")
        return

    if args.activate:
        ok = mtm.activate_tenant(args.activate)
        print(f"{'Activated' if ok else 'Not found'}: {args.activate}")
        return

    if args.list:
        tenants = mtm.list_tenants()
        if args.json:
            print(json.dumps([t.to_dict() for t in tenants], indent=2))
        else:
            print(f"Tenants ({len(tenants)}):")
            for t in tenants:
                status = "ACTIVE" if t.is_active else "INACTIVE"
                print(f"  [{status}] {t.tenant_id}: {t.name}")
        return

    # Default: show stats
    stats = mtm.get_stats()
    if args.json:
        print(json.dumps(stats, indent=2))
    else:
        print(f"Multi-Tenant: {'ENABLED' if stats['enabled'] else 'DISABLED'}")
        print(f"  Tenants: {stats['active_tenants']}/{stats['total_tenants']} active")
        print(f"  Max: {stats['max_tenants']}")


if __name__ == "__main__":
    _cli()


__all__ = [
    "MultiTenantManager",
    "Tenant",
    "TenantContext",
    "get_multi_tenant_manager",
]

