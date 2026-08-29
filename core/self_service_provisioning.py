"""Self-Service Infrastructure Provisioning — Constitution v4.0 PLS-06.

Provides developer self-service provisioning of environments without ops tickets:

  - Blueprint catalog: available environments (dev/qa/staging/production/monitoring)
    with their IaC artifacts (Dockerfile / docker-compose / supervisord configs)
  - Provisioning requests: request, approve, track, and audit environment provisioning
  - Environment state: record and report which environments are provisioned
  - Audit trail: every provisioning action is recorded with actor + timestamp

Safety: this module NEVER executes docker/system commands itself. It manages the
provisioning *workflow and state* (the self-service layer). The actual IaC apply is
left to the operator's configured pipeline (Makefile / docker compose / release
scripts), which is the correct division of responsibility for a self-service portal.

Usage:
    from core.self_service_provisioning import get_provisioner

    prov = get_provisioner()
    for bp in prov.list_blueprints():
        print(bp.name, bp.environment)
    req = prov.request_provisioning("monitoring", actor="dev@example.com")
    print(req.status)
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

PROVISIONING_STATE_FILE = "json/provisioning_requests.json"

# Environments this platform can self-serve provision (from repo IaC artifacts).
_BLUEPRINT_DEFS: list[dict[str, Any]] = [
    {
        "name": "main_app",
        "environment": "production",
        "description": "Core trading application environment (Dockerfile + docker-compose)",
        "artifacts": ["Dockerfile", "docker-compose.yml", "supervisord.conf"],
        "kind": "app",
    },
    {
        "name": "monitoring_stack",
        "environment": "monitoring",
        "description": "Prometheus / Loki / Grafana observability stack",
        "artifacts": ["docker-compose.monitoring.yml", "deploy/prometheus/prometheus.yml", "deploy/grafana/dashboards.yml"],
        "kind": "observability",
    },
    {
        "name": "realestate_app",
        "environment": "production",
        "description": "Real estate services environment (Dockerfile.realestate + compose)",
        "artifacts": ["Dockerfile.realestate", "docker-compose.realestate.yml"],
        "kind": "app",
    },
    {
        "name": "postgres_db",
        "environment": "production",
        "description": "Postgres database environment for persistence services",
        "artifacts": ["deploy/docker-compose.postgres.yml"],
        "kind": "data",
    },
    {
        "name": "dev_env",
        "environment": "dev",
        "description": "Local development environment (config.local.json + launcher)",
        "artifacts": ["json/config.template.json", "json/launcher_settings.json"],
        "kind": "dev",
    },
]


# ── Data Models ──────────────────────────────────────────────────────────────


@dataclass
class ProvisioningBlueprint:
    """A self-service environment blueprint that can be provisioned."""

    name: str
    environment: str
    description: str = ""
    artifacts: list[str] = field(default_factory=list)
    kind: str = "app"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "environment": self.environment,
            "description": self.description,
            "artifacts": list(self.artifacts),
            "kind": self.kind,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProvisioningBlueprint:
        return cls(
            name=data.get("name", ""),
            environment=data.get("environment", ""),
            description=data.get("description", ""),
            artifacts=list(data.get("artifacts", [])),
            kind=data.get("kind", "app"),
        )


@dataclass
class ProvisioningRequest:
    """A single self-service provisioning request (workflow + audit record)."""

    request_id: str
    blueprint: str
    environment: str
    actor: str
    status: str = "PENDING"          # PENDING → APPROVED → PROVISIONED | REJECTED | FAILED
    requested_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "blueprint": self.blueprint,
            "environment": self.environment,
            "actor": self.actor,
            "status": self.status,
            "requested_at": self.requested_at,
            "updated_at": self.updated_at,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProvisioningRequest:
        return cls(
            request_id=data.get("request_id", ""),
            blueprint=data.get("blueprint", ""),
            environment=data.get("environment", ""),
            actor=data.get("actor", ""),
            status=data.get("status", "PENDING"),
            requested_at=float(data.get("requested_at", 0)),
            updated_at=float(data.get("updated_at", 0)),
            note=data.get("note", ""),
        )


# ── Provisioner ──────────────────────────────────────────────────────────────


class SelfServiceProvisioner:
    """Self-service infrastructure provisioning manager.

    Thread-safe. Persists provisioning requests to ``json/provisioning_requests.json``.
    Never executes system commands — this is the workflow/state layer only.
    """

    def __init__(self, storage_path: str = PROVISIONING_STATE_FILE) -> None:
        self._storage_path = storage_path
        self._lock = threading.RLock()
        self._blueprints: dict[str, ProvisioningBlueprint] = {
            bp["name"]: ProvisioningBlueprint(**bp) for bp in _BLUEPRINT_DEFS
        }
        self._requests: dict[str, ProvisioningRequest] = {}
        self._load()

    # ── Blueprints ────────────────────────────────────────────────────────

    def list_blueprints(self, environment: str = "") -> list[ProvisioningBlueprint]:
        """List available self-service provisioning blueprints."""
        with self._lock:
            items = list(self._blueprints.values())
            if environment:
                items = [b for b in items if b.environment == environment]
            return items

    def get_blueprint(self, name: str) -> ProvisioningBlueprint | None:
        """Get a blueprint by name."""
        with self._lock:
            return self._blueprints.get(name)

    def blueprint_artifacts_exist(self, name: str) -> dict[str, bool]:
        """Check whether the blueprint's IaC artifacts are present in the repo."""
        bp = self.get_blueprint(name)
        if not bp:
            return {}
        root = Path(__file__).resolve().parent.parent
        return {art: (root / art).exists() for art in bp.artifacts}

    # ── Provisioning workflow ─────────────────────────────────────────────

    def request_provisioning(
        self,
        blueprint: str,
        actor: str = "self-service",
        environment: str = "",
    ) -> ProvisioningRequest | None:
        """Request provisioning of a blueprint (self-service, no ops ticket).

        Creates a PENDING request that flows through the approval workflow.
        Returns None if the blueprint is unknown.
        """
        bp = self.get_blueprint(blueprint)
        if not bp:
            _log.warning("[PROV] Unknown blueprint requested: %s", blueprint)
            return None

        with self._lock:
            req = ProvisioningRequest(
                request_id=uuid.uuid4().hex[:12],
                blueprint=bp.name,
                environment=environment or bp.environment,
                actor=actor,
            )
            self._requests[req.request_id] = req
            self._save()
            _log.info("[PROV] Request %s: %s env=%s actor=%s",
                      req.request_id, req.blueprint, req.environment, req.actor)
            return req

    def approve_provisioning(
        self,
        request_id: str,
        approver: str = "admin",
        note: str = "",
    ) -> ProvisioningRequest | None:
        """Approve a pending provisioning request (status PENDING → APPROVED)."""
        with self._lock:
            req = self._requests.get(request_id)
            if not req or req.status != "PENDING":
                return req
            req.status = "APPROVED"
            req.updated_at = time.time()
            req.note = note or f"approved by {approver}"
            self._save()
            return req

    def mark_provisioned(
        self,
        request_id: str,
        note: str = "",
    ) -> ProvisioningRequest | None:
        """Mark an approved request as provisioned (APPROVED → PROVISIONED)."""
        with self._lock:
            req = self._requests.get(request_id)
            if not req or req.status != "APPROVED":
                return req
            req.status = "PROVISIONED"
            req.updated_at = time.time()
            req.note = note or "provisioned"
            self._save()
            return req

    def reject_provisioning(
        self,
        request_id: str,
        reason: str = "rejected by approver",
    ) -> ProvisioningRequest | None:
        """Reject a pending request (PENDING → REJECTED)."""
        with self._lock:
            req = self._requests.get(request_id)
            if not req or req.status != "PENDING":
                return req
            req.status = "REJECTED"
            req.updated_at = time.time()
            req.note = reason
            self._save()
            return req

    # ── Queries ───────────────────────────────────────────────────────────

    def list_requests(
        self,
        status: str = "",
        environment: str = "",
    ) -> list[ProvisioningRequest]:
        """List provisioning requests with optional filters."""
        with self._lock:
            items = list(self._requests.values())
            if status:
                items = [r for r in items if r.status == status]
            if environment:
                items = [r for r in items if r.environment == environment]
            return sorted(items, key=lambda r: r.requested_at, reverse=True)

    def get_request(self, request_id: str) -> ProvisioningRequest | None:
        """Get a provisioning request by ID."""
        with self._lock:
            return self._requests.get(request_id)

    def get_stats(self) -> dict[str, Any]:
        """Get quick provisioning statistics."""
        with self._lock:
            reqs = list(self._requests.values())
            return {
                "blueprints": len(self._blueprints),
                "requests": len(reqs),
                "pending": sum(1 for r in reqs if r.status == "PENDING"),
                "approved": sum(1 for r in reqs if r.status == "APPROVED"),
                "provisioned": sum(1 for r in reqs if r.status == "PROVISIONED"),
                "rejected": sum(1 for r in reqs if r.status == "REJECTED"),
                "environments": sorted({b.environment for b in self._blueprints.values()}),
            }

    def get_report(self) -> dict[str, Any]:
        """Get a full self-service provisioning report."""
        with self._lock:
            return {
                "blueprints": [b.to_dict() for b in self.list_blueprints()],
                "requests": [r.to_dict() for r in self.list_requests()],
                "stats": self.get_stats(),
                "timestamp": time.time(),
            }

    # ── Persistence ───────────────────────────────────────────────────────

    def _save(self) -> None:
        """Persist provisioning requests to JSON."""
        try:
            path = Path(self._storage_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "requests": {rid: r.to_dict() for rid, r in self._requests.items()},
            }
            path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        except OSError as exc:
            _log.warning("[PROV] Failed to save: %s", exc)

    def _load(self) -> None:
        """Load provisioning requests from JSON (if present)."""
        path = Path(self._storage_path)
        if not path.is_file():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for rid, rdata in data.get("requests", {}).items():
                self._requests[rid] = ProvisioningRequest.from_dict(rdata)
        except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
            _log.warning("[PROV] Failed to load: %s", exc)


# ── Singleton ────────────────────────────────────────────────────────────────

_instance: SelfServiceProvisioner | None = None
_instance_lock = threading.RLock()


def get_provisioner(storage_path: str = PROVISIONING_STATE_FILE) -> SelfServiceProvisioner:
    """Return the process-level SelfServiceProvisioner singleton."""
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = SelfServiceProvisioner(storage_path)
        return _instance


def reset_provisioner() -> None:
    """Force-reset the singleton (for testing). Also clears persisted state."""
    global _instance
    with _instance_lock:
        _instance = None
    try:
        p = Path(PROVISIONING_STATE_FILE)
        if p.is_file():
            p.unlink()
    except OSError:
        pass


# ── CLI ──────────────────────────────────────────────────────────────────────


def _cli() -> None:
    import argparse

    ap = argparse.ArgumentParser(prog="python -m core.self_service_provisioning")
    ap.add_argument("--list-blueprints", action="store_true", help="List available blueprints")
    ap.add_argument("--request", nargs="?", metavar="BLUEPRINT", help="Request provisioning of a blueprint")
    ap.add_argument("--actor", type=str, default="self-service", help="Actor for the request")
    ap.add_argument("--report", action="store_true", help="Show full provisioning report")
    ap.add_argument("--json", action="store_true", help="Output JSON")
    args = ap.parse_args()

    prov = get_provisioner()

    if args.request:
        req = prov.request_provisioning(args.request, actor=args.actor)
        if req is None:
            print(f"Unknown blueprint: {args.request}")
            return
        print(f"Request {req.request_id}: {req.blueprint} [{req.status}]")
        return

    if args.report:
        report = prov.get_report()
        if args.json:
            print(json.dumps(report, indent=2, default=str))
        else:
            print(f"Self-Service Provisioning: {report['stats']['blueprints']} blueprints, "
                  f"{report['stats']['requests']} requests, "
                  f"{report['stats']['provisioned']} provisioned")
            for bp in report["blueprints"]:
                print(f"  - {bp['name']:20s} {bp['environment']:12s} {bp['kind']}")
        return

    if args.list_blueprints or args.json:
        data = [b.to_dict() for b in prov.list_blueprints()]
        if args.json:
            print(json.dumps(data, indent=2))
        else:
            print(f"Blueprints ({len(data)}):")
            for b in data:
                print(f"  - {b['name']:20s} {b['environment']:12s} {b['kind']}")
        return

    stats = prov.get_stats()
    print(f"Self-Service Provisioning: {stats['blueprints']} blueprints, "
          f"{stats['requests']} requests, "
          f"{stats['pending']} pending, {stats['provisioned']} provisioned")


if __name__ == "__main__":
    _cli()


__all__ = [
    "PROVISIONING_STATE_FILE",
    "ProvisioningBlueprint",
    "ProvisioningRequest",
    "SelfServiceProvisioner",
    "get_provisioner",
    "reset_provisioner",
]
