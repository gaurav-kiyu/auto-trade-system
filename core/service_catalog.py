"""Platform Engineering Service Catalog — Constitution v4.0: Internal Developer Platform.

Tracks all registered services/modules with metadata:
  - Service ownership, version, tech stack
  - Golden path checklists & maturity levels
  - Environment provisioning (dev/qa/staging/production)
  - Health, SLA, runbook integration
  - Dependency tracking (links to DependencyAnalyzer)

Usage:
    from core.service_catalog import get_service_catalog

    catalog = get_service_catalog()
    catalog.register_service(ServiceEntry(
        name="index_trader",
        domain="trading",
        owner="team-core",
        version="2.57.0",
        runbook_path="docs/runbooks/trader_outage.md",
        sla_pct=99.5,
    ))
    report = catalog.get_report()
    print(report.summary_text())
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

SERVICE_DATA_FILE = "service_catalog.json"


# ── Data Models ──────────────────────────────────────────────────────────────


@dataclass
class ServiceEntry:
    """A single service registered in the developer portal / service catalog."""

    name: str
    domain: str = ""                    # trading, risk, data, infrastructure, ai, governance
    owner: str = "unassigned"           # Team or individual owner
    version: str = "0.0.0"
    status: str = "ACTIVE"              # ACTIVE, DORMANT, DEPRECATED, RETIRED
    category: str = "core"              # core, infrastructure, app, script
    tech_stack: list[str] = field(default_factory=lambda: ["Python"])
    runbook_path: str = ""
    sla_pct: float = 99.0               # Target availability %
    environment: str = "production"     # dev, qa, staging, production
    maturity_level: str = "LEVEL_3"     # LEVEL_0 → LEVEL_4 (from golden path)
    description: str = ""
    tags: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)  # other service names
    registered_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    last_health_check: float = 0.0
    is_healthy: bool = True
    has_tests: bool = True
    has_documentation: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "domain": self.domain,
            "owner": self.owner,
            "version": self.version,
            "status": self.status,
            "category": self.category,
            "tech_stack": list(self.tech_stack),
            "runbook_path": self.runbook_path,
            "sla_pct": self.sla_pct,
            "environment": self.environment,
            "maturity_level": self.maturity_level,
            "description": self.description,
            "tags": list(self.tags),
            "dependencies": list(self.dependencies),
            "registered_at": self.registered_at,
            "updated_at": self.updated_at,
            "last_health_check": self.last_health_check,
            "is_healthy": self.is_healthy,
            "has_tests": self.has_tests,
            "has_documentation": self.has_documentation,
        }


@dataclass
class GoldenPath:
    """A golden path template defining a standardized service journey."""

    name: str
    description: str = ""
    steps: list[str] = field(default_factory=list)
    maturity_levels: list[str] = field(default_factory=lambda: [
        "LEVEL_0: Initial / Skeleton",
        "LEVEL_1: Core Functionality",
        "LEVEL_2: Testing & Monitoring",
        "LEVEL_3: Production Ready",
        "LEVEL_4: Optimized & Automated",
    ])
    required_checks: list[str] = field(default_factory=lambda: [
        "has_tests", "has_documentation", "has_runbook",
        "has_health_check", "has_metrics", "has_alerting",
    ])

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "steps": list(self.steps),
            "maturity_levels": list(self.maturity_levels),
            "required_checks": list(self.required_checks),
        }


@dataclass
class Environment:
    """A deployment environment tracked by the catalog."""

    name: str                        # dev, qa, staging, production
    services: list[str] = field(default_factory=list)
    is_healthy: bool = True
    version: str = ""
    last_deploy: float = 0.0
    deploy_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "services": list(self.services),
            "is_healthy": self.is_healthy,
            "version": self.version,
            "last_deploy": self.last_deploy,
            "deploy_count": self.deploy_count,
        }


@dataclass
class ServiceCatalogReport:
    """Aggregated report of the entire service catalog."""

    total_services: int = 0
    active_services: int = 0
    domains: dict[str, int] = field(default_factory=dict)
    maturity_distribution: dict[str, int] = field(default_factory=dict)
    healthy_count: int = 0
    unhealthy_services: list[str] = field(default_factory=list)
    owners: dict[str, list[str]] = field(default_factory=dict)
    average_sla: float = 0.0
    environment_summary: dict[str, dict] = field(default_factory=dict)
    services_missing_runbook: list[str] = field(default_factory=list)
    services_missing_tests: list[str] = field(default_factory=list)
    services_missing_docs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_services": self.total_services,
            "active_services": self.active_services,
            "domains": dict(self.domains),
            "maturity_distribution": dict(self.maturity_distribution),
            "healthy_count": self.healthy_count,
            "unhealthy_services": list(self.unhealthy_services),
            "owners": {k: list(v) for k, v in self.owners.items()},
            "average_sla": round(self.average_sla, 2),
            "environment_summary": dict(self.environment_summary),
            "services_missing_runbook": list(self.services_missing_runbook),
            "services_missing_tests": list(self.services_missing_tests),
            "services_missing_docs": list(self.services_missing_docs),
        }

    def summary_text(self) -> str:
        lines = [
            "═" * 60,
            "  SERVICE CATALOG REPORT  —  Platform Engineering",
            "═" * 60,
            f"  Total services: {self.total_services}",
            f"  Active: {self.active_services}   Healthy: {self.healthy_count}",
            f"  Avg SLA: {self.average_sla:.1f}%",
            "",
        ]
        if self.domains:
            lines.append("  By Domain:")
            for dom, count in sorted(self.domains.items(), key=lambda x: -x[1]):
                lines.append(f"    {dom}: {count}")
        if self.maturity_distribution:
            lines.append("")
            lines.append("  Maturity Levels:")
            for level, count in sorted(self.maturity_distribution.items()):
                lines.append(f"    {level}: {count}")
        if self.unhealthy_services:
            lines.append(f"  Unhealthy: {', '.join(self.unhealthy_services[:5])}")
        if self.services_missing_runbook:
            lines.append(f"  Missing runbooks ({len(self.services_missing_runbook)}): "
                         f"{', '.join(self.services_missing_runbook[:5])}")
        if self.services_missing_tests:
            lines.append(f"  Missing tests ({len(self.services_missing_tests)}): "
                         f"{', '.join(self.services_missing_tests[:5])}")
        if self.services_missing_docs:
            lines.append(f"  Missing docs ({len(self.services_missing_docs)}): "
                         f"{', '.join(self.services_missing_docs[:5])}")
        lines.append("═" * 60)
        return "\n".join(lines)


# ── Service Catalog ──────────────────────────────────────────────────────────


class ServiceCatalog:
    """Platform Engineering Service Catalog — tracks all system services.

    Thread-safe singleton. Persists to ``service_catalog.json``.
    """

    def __init__(self, storage_path: str = SERVICE_DATA_FILE) -> None:
        self._storage_path = storage_path
        self._services: dict[str, ServiceEntry] = {}
        self._golden_paths: dict[str, GoldenPath] = {}
        self._environments: dict[str, Environment] = {}
        self._lock = threading.RLock()
        self._load()

    # ── Registration ──────────────────────────────────────────────────────

    def register_service(self, entry: ServiceEntry) -> None:
        """Register or update a service in the catalog."""
        with self._lock:
            entry.updated_at = time.time()
            if entry.name in self._services:
                existing = self._services[entry.name]
                entry.registered_at = existing.registered_at
            self._services[entry.name] = entry
            self._save()
            _log.info("[SVC_CAT] Registered service: %s (%s)", entry.name, entry.domain)

    def unregister_service(self, name: str) -> bool:
        """Remove a service from the catalog. Returns False if not found."""
        with self._lock:
            if name in self._services:
                del self._services[name]
                self._save()
                _log.info("[SVC_CAT] Unregistered service: %s", name)
                return True
            return False

    def get_service(self, name: str) -> ServiceEntry | None:
        """Get a service by name."""
        with self._lock:
            return self._services.get(name)

    def list_services(self, domain: str = "", status: str = "",
                      environment: str = "") -> list[ServiceEntry]:
        """List services with optional filters."""
        with self._lock:
            result = list(self._services.values())
            if domain:
                result = [s for s in result if s.domain == domain]
            if status:
                result = [s for s in result if s.status == status]
            if environment:
                result = [s for s in result if s.environment == environment]
            return result

    def update_health(self, name: str, is_healthy: bool) -> bool:
        """Update the health status of a service."""
        with self._lock:
            entry = self._services.get(name)
            if not entry:
                return False
            entry.is_healthy = is_healthy
            entry.last_health_check = time.time()
            self._save()
            return True

    # ── Golden Paths ──────────────────────────────────────────────────────

    def register_golden_path(self, path: GoldenPath) -> None:
        """Register a golden path template."""
        with self._lock:
            self._golden_paths[path.name] = path
            self._save()

    def get_golden_paths(self) -> list[GoldenPath]:
        """Get all registered golden paths."""
        with self._lock:
            return list(self._golden_paths.values())

    def check_service_maturity(self, name: str) -> dict[str, Any]:
        """Check a service against the first golden path's required checks."""
        with self._lock:
            entry = self._services.get(name)
            if not entry:
                return {"service": name, "found": False}

            result: dict[str, Any] = {
                "service": name,
                "found": True,
                "maturity_level": entry.maturity_level,
                "checks": {},
            }

            # Default checks: has tests, docs, runbook
            result["checks"]["has_tests"] = entry.has_tests
            result["checks"]["has_documentation"] = entry.has_documentation
            result["checks"]["has_runbook"] = bool(entry.runbook_path)
            result["checks"]["is_healthy"] = entry.is_healthy

            # Compute pass count
            passed = sum(1 for v in result["checks"].values() if v)
            total = len(result["checks"])
            result["passed_checks"] = passed
            result["total_checks"] = total
            result["readiness_pct"] = round(passed / max(1, total) * 100, 1)
            return result

    # ── Environments ──────────────────────────────────────────────────────

    def register_environment(self, env: Environment) -> None:
        """Register or update an environment."""
        with self._lock:
            self._environments[env.name] = env
            self._save()

    def get_environments(self) -> list[Environment]:
        """Get all registered environments."""
        with self._lock:
            return list(self._environments.values())

    def deploy_to_environment(self, env_name: str, version: str) -> bool:
        """Record a deployment to an environment."""
        with self._lock:
            env = self._environments.get(env_name)
            if not env:
                return False
            env.version = version
            env.last_deploy = time.time()
            env.deploy_count += 1
            self._save()
            return True

    # ── Reports ───────────────────────────────────────────────────────────

    def get_report(self) -> ServiceCatalogReport:
        """Generate an aggregated report of the entire catalog."""
        with self._lock:
            report = ServiceCatalogReport()
            services = list(self._services.values())

            report.total_services = len(services)
            report.active_services = sum(1 for s in services if s.status == "ACTIVE")

            # Domain distribution
            dom_counts: dict[str, int] = {}
            for s in services:
                dom_counts[s.domain] = dom_counts.get(s.domain, 0) + 1
            report.domains = dom_counts

            # Maturity distribution
            mat_counts: dict[str, int] = {}
            for s in services:
                mat_counts[s.maturity_level] = mat_counts.get(s.maturity_level, 0) + 1
            report.maturity_distribution = mat_counts

            # Health
            report.healthy_count = sum(1 for s in services if s.is_healthy)
            report.unhealthy_services = [
                s.name for s in services if not s.is_healthy
            ]

            # Owners
            owner_map: dict[str, list[str]] = {}
            for s in services:
                if s.owner not in owner_map:
                    owner_map[s.owner] = []
                owner_map[s.owner].append(s.name)
            report.owners = owner_map

            # Avg SLA
            if services:
                report.average_sla = sum(s.sla_pct for s in services) / len(services)

            # Environment summary
            for env in self._environments.values():
                report.environment_summary[env.name] = {
                    "services": len(env.services),
                    "healthy": env.is_healthy,
                    "version": env.version,
                    "last_deploy": env.last_deploy,
                    "deploy_count": env.deploy_count,
                }

            # Missing artifacts
            report.services_missing_runbook = [
                s.name for s in services if not s.runbook_path
            ]
            report.services_missing_tests = [
                s.name for s in services if not s.has_tests
            ]
            report.services_missing_docs = [
                s.name for s in services if not s.has_documentation
            ]

            return report

    def get_stats(self) -> dict[str, Any]:
        """Get quick catalog statistics."""
        with self._lock:
            return {
                "total_services": len(self._services),
                "active_services": sum(1 for s in self._services.values() if s.status == "ACTIVE"),
                "golden_paths": len(self._golden_paths),
                "environments": len(self._environments),
                "domains": list(sorted(set(s.domain for s in self._services.values()))),
                "healthy_count": sum(1 for s in self._services.values() if s.is_healthy),
            }

    # ── Persistence ───────────────────────────────────────────────────────

    def _save(self) -> None:
        """Persist catalog state to JSON."""
        try:
            data = {
                "services": {name: svc.to_dict() for name, svc in self._services.items()},
                "golden_paths": {name: gp.to_dict() for name, gp in self._golden_paths.items()},
                "environments": {name: env.to_dict() for name, env in self._environments.items()},
            }
            Path(self._storage_path).write_text(
                json.dumps(data, indent=2, default=str), encoding="utf-8"
            )
        except OSError as exc:
            _log.warning("[SVC_CAT] Failed to save: %s", exc)

    def _load(self) -> None:
        """Load catalog state from JSON."""
        path = Path(self._storage_path)
        if not path.is_file():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            svcs = data.get("services", {})
            for name, sdata in svcs.items():
                self._services[name] = ServiceEntry(
                    name=sdata.get("name", name),
                    domain=sdata.get("domain", ""),
                    owner=sdata.get("owner", "unassigned"),
                    version=sdata.get("version", "0.0.0"),
                    status=sdata.get("status", "ACTIVE"),
                    category=sdata.get("category", "core"),
                    tech_stack=sdata.get("tech_stack", ["Python"]),
                    runbook_path=sdata.get("runbook_path", ""),
                    sla_pct=float(sdata.get("sla_pct", 99.0)),
                    environment=sdata.get("environment", "production"),
                    maturity_level=sdata.get("maturity_level", "LEVEL_3"),
                    description=sdata.get("description", ""),
                    tags=sdata.get("tags", []),
                    dependencies=sdata.get("dependencies", []),
                    registered_at=float(sdata.get("registered_at", 0)),
                    updated_at=float(sdata.get("updated_at", 0)),
                    last_health_check=float(sdata.get("last_health_check", 0)),
                    is_healthy=bool(sdata.get("is_healthy", True)),
                    has_tests=bool(sdata.get("has_tests", True)),
                    has_documentation=bool(sdata.get("has_documentation", True)),
                )
            gps = data.get("golden_paths", {})
            for name, gdata in gps.items():
                self._golden_paths[name] = GoldenPath(
                    name=gdata.get("name", name),
                    description=gdata.get("description", ""),
                    steps=gdata.get("steps", []),
                    maturity_levels=gdata.get("maturity_levels", []),
                    required_checks=gdata.get("required_checks", []),
                )
            envs = data.get("environments", {})
            for name, edata in envs.items():
                self._environments[name] = Environment(
                    name=edata.get("name", name),
                    services=edata.get("services", []),
                    is_healthy=bool(edata.get("is_healthy", True)),
                    version=edata.get("version", ""),
                    last_deploy=float(edata.get("last_deploy", 0)),
                    deploy_count=int(edata.get("deploy_count", 0)),
                )
        except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
            _log.warning("[SVC_CAT] Failed to load: %s", exc)


# ── Singleton ────────────────────────────────────────────────────────────────

_instance: ServiceCatalog | None = None
_instance_lock = threading.RLock()


def get_service_catalog(storage_path: str = SERVICE_DATA_FILE) -> ServiceCatalog:
    """Return the process-level ServiceCatalog singleton."""
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = ServiceCatalog(storage_path)
        return _instance


def reset_service_catalog() -> None:
    """Force-reset the singleton (for testing).
    Also clears the persisted storage file to prevent stale data loading.
    """
    global _instance
    with _instance_lock:
        _instance = None
    # Clear persisted file to prevent stale data on next init
    try:
        p = Path(SERVICE_DATA_FILE)
        if p.is_file():
            p.unlink()
    except OSError:
        pass


# ── CLI ───────────────────────────────────────────────────────────────────────

def _cli() -> None:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m core.service_catalog")
    ap.add_argument("--list", action="store_true", help="List all services")
    ap.add_argument("--report", action="store_true", help="Show aggregated report")
    ap.add_argument("--register", nargs=2, metavar=("name", "domain"), help="Register a service")
    ap.add_argument("--domain", type=str, help="Filter by domain")
    ap.add_argument("--json", action="store_true", help="Output JSON")
    args = ap.parse_args()

    catalog = get_service_catalog()

    if args.register:
        name, domain = args.register
        entry = ServiceEntry(name=name, domain=domain)
        catalog.register_service(entry)
        print(f"Registered: {name} ({domain})")
        return

    if args.report:
        report = catalog.get_report()
        if args.json:
            print(json.dumps(report.to_dict(), indent=2))
        else:
            print(report.summary_text())
        return

    if args.list:
        services = catalog.list_services(domain=args.domain or "")
        if args.json:
            print(json.dumps([s.to_dict() for s in services], indent=2))
        else:
            print(f"Services ({len(services)}):")
            for s in sorted(services, key=lambda x: x.name):
                health = "✓" if s.is_healthy else "✗"
                print(f"  [{health}] {s.name:30s}  {s.domain:15s}  {s.maturity_level}")
        return

    # Default: show stats
    stats = catalog.get_stats()
    if args.json:
        print(json.dumps(stats, indent=2))
    else:
        print(f"Service Catalog: {stats['total_services']} services, "
              f"{stats['active_services']} active, "
              f"{stats['healthy_count']} healthy, "
              f"{stats['golden_paths']} golden paths, "
              f"{stats['environments']} environments")
        if stats["domains"]:
            print(f"  Domains: {', '.join(stats['domains'])}")


if __name__ == "__main__":
    _cli()


__all__ = [
    "Environment",
    "GoldenPath",
    "ServiceCatalog",
    "ServiceCatalogReport",
    "ServiceEntry",
    "get_service_catalog",
    "reset_service_catalog",
]
