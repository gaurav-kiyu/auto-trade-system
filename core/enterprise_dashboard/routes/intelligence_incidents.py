"""Intelligence Incidents & Health routes — Incident Command, Constitution Health, Architecture Standards.

Extracted from register_intelligence_routes in intelligence.py for maintainability.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import Request

_log = logging.getLogger(__name__)


def register_incident_routes(app, dashboard, admin_only, operator_or_admin) -> None:  # type: ignore[no-untyped-def]
    """Register incident and health routes."""

    # ── Incident Command System (Constitution v4.0) ──────────────────

    @app.get("/api/intelligence/incidents/list")
    async def api_incidents_list(limit: int = 50, user: Any = operator_or_admin):
        """Get all incidents, most recent first."""
        try:
            from core.incident_command_system import get_incident_commander
            commander = get_incident_commander()
            incidents = commander.get_all_incidents(limit=max(1, min(200, limit)))
            stats = commander.get_stats()
            return {"status": "ok", "incidents": incidents, "stats": stats, "count": len(incidents), "timestamp": time.time()}
        except (ImportError, ValueError, TypeError, AttributeError, RuntimeError) as exc:
            _log.warning("[INTEL] Incidents list error: %s", exc)
            return {"status": "error", "detail": str(exc)}

    @app.get("/api/intelligence/incidents/open")
    async def api_incidents_open(user: Any = operator_or_admin):
        """Get all open incidents."""
        try:
            from core.incident_command_system import get_incident_commander
            commander = get_incident_commander()
            incidents = commander.get_open_incidents()
            stats = commander.get_stats()
            return {"status": "ok", "incidents": incidents, "stats": stats, "count": len(incidents), "timestamp": time.time()}
        except (ImportError, ValueError, TypeError, AttributeError, RuntimeError) as exc:
            _log.warning("[INTEL] Incidents open error: %s", exc)
            return {"status": "error", "detail": str(exc)}

    @app.post("/api/intelligence/incidents/create")
    async def api_incidents_create(request: Request, user: Any = operator_or_admin):
        """Create a new incident."""
        try:
            body = await request.json()
            from core.incident_command_system import get_incident_commander
            commander = get_incident_commander()
            incident = commander.create_incident(
                title=body.get("title", ""),
                description=body.get("description", ""),
                source=body.get("source", "api"),
                severity=body.get("severity", "MEDIUM"),
                detected_by=body.get("detected_by", "manual"),
                affected_modules=body.get("affected_modules", []),
                tags=body.get("tags", []),
            )
            if incident:
                return {"status": "ok", "incident": incident.to_dict(), "timestamp": time.time()}
            return {"status": "ok", "incident": None, "message": "Duplicate incident prevented", "timestamp": time.time()}
        except (ImportError, ValueError, TypeError, AttributeError, RuntimeError, OSError) as exc:
            _log.warning("[INTEL] Incidents create error: %s", exc)
            return {"status": "error", "detail": str(exc)}

    @app.get("/api/intelligence/incidents/get/{incident_id}")
    async def api_incidents_get(incident_id: str, user: Any = operator_or_admin):
        """Get a specific incident by ID."""
        try:
            from core.incident_command_system import get_incident_commander
            commander = get_incident_commander()
            incident = commander.get_incident(incident_id)
            return {"status": "ok", "incident": incident, "timestamp": time.time()}
        except (ImportError, ValueError, TypeError, AttributeError, RuntimeError) as exc:
            _log.warning("[INTEL] Incidents get error: %s", exc)
            return {"status": "error", "detail": str(exc)}

    @app.post("/api/intelligence/incidents/acknowledge/{incident_id}")
    async def api_incidents_acknowledge(incident_id: str, request: Request, user: Any = operator_or_admin):
        """Acknowledge an incident."""
        try:
            body = await request.json() if request.headers.get("content-type", "") else {}
            from core.incident_command_system import get_incident_commander
            commander = get_incident_commander()
            success = commander.acknowledge_incident(incident_id, body.get("notes", ""))
            return {"status": "ok", "success": success, "timestamp": time.time()}
        except (ImportError, ValueError, TypeError, AttributeError, RuntimeError) as exc:
            _log.warning("[INTEL] Incidents acknowledge error: %s", exc)
            return {"status": "error", "detail": str(exc)}

    @app.post("/api/intelligence/incidents/resolve/{incident_id}")
    async def api_incidents_resolve(incident_id: str, request: Request, user: Any = operator_or_admin):
        """Resolve an incident."""
        try:
            body = await request.json() if request.headers.get("content-type", "") else {}
            from core.incident_command_system import get_incident_commander
            commander = get_incident_commander()
            success = commander.resolve_incident(incident_id, body.get("notes", ""))
            return {"status": "ok", "success": success, "timestamp": time.time()}
        except (ImportError, ValueError, TypeError, AttributeError, RuntimeError) as exc:
            _log.warning("[INTEL] Incidents resolve error: %s", exc)
            return {"status": "error", "detail": str(exc)}

    @app.post("/api/intelligence/incidents/close/{incident_id}")
    async def api_incidents_close(incident_id: str, request: Request, user: Any = operator_or_admin):
        """Close a resolved incident."""
        try:
            body = await request.json() if request.headers.get("content-type", "") else {}
            from core.incident_command_system import get_incident_commander
            commander = get_incident_commander()
            success = commander.close_incident(incident_id, body.get("notes", ""))
            return {"status": "ok", "success": success, "timestamp": time.time()}
        except (ImportError, ValueError, TypeError, AttributeError, RuntimeError) as exc:
            _log.warning("[INTEL] Incidents close error: %s", exc)
            return {"status": "error", "detail": str(exc)}

    @app.post("/api/intelligence/incidents/detect")
    async def api_incidents_detect(user: Any = operator_or_admin):
        """Run a full incident detection cycle."""
        try:
            from core.incident_command_system import get_incident_commander
            commander = get_incident_commander()
            result = commander.run_detection_cycle()
            return {"status": "ok", "result": result, "timestamp": time.time()}
        except (ImportError, ValueError, TypeError, AttributeError, RuntimeError) as exc:
            _log.warning("[INTEL] Incidents detect error: %s", exc)
            return {"status": "error", "detail": str(exc)}

    # ── Constitution v4.0 System Health ────────────────────────────

    @app.get("/api/intelligence/health")
    async def api_constitution_health(user: Any = operator_or_admin):
        """Get real-time health status of all Constitution v4.0 modules."""
        _modules = [
            ("AI Security Gate",        "core.ai_security_gate",        "get_ai_security_gate"),
            ("Threat Modeler",          "core.threat_modeler",          "get_threat_modeler"),
            ("Postmortem Automator",    "core.postmortem_automator",    "get_postmortem_automator"),
            ("Decision Memory",         "core.decision_memory",         "get_decision_memory"),
            ("Digital Twin",            "core.digital_twin",            "get_digital_twin"),
            ("Runtime Security",        "core.runtime_security",        "get_runtime_security"),
            ("API Versioning",          "core.api_versioning",          "get_api_version_manager"),
            ("Executive Advisor",       "core.executive_advisor",       "get_executive_advisor"),
            ("Accessibility Gate",      "core.accessibility_gate",      "get_accessibility_gate"),
            ("Service Catalog",         "core.service_catalog",         "get_service_catalog"),
            ("Incident Commander",       "core.incident_command_system",  "get_incident_commander"),
            ("Continuous Intelligence",    "core.continuous_intelligence",   "get_intelligence_pipeline"),
            ("ICS → Telegram Bridge",     "core.ics_telegram_bridge",       "get_ics_telegram_bridge"),
            ("ICS → Self-Healing Bridge", "core.ics_self_healing_bridge",   "get_ics_self_healing_bridge"),
            ("Constitution Startup",       "core.startup",                   "startup_constitution_system"),
        ]

        _results = []
        _healthy = 0
        for _name, _import_path, _factory in _modules:
            try:
                _mod = __import__(_import_path, fromlist=[""])
                _fn = getattr(_mod, _factory, None)
                if _fn is None:
                    _results.append({"name": _name, "status": "DEGRADED", "reason": f"factory {_factory} not found"})
                    continue
                _instance = _fn()
                _stats = _instance.get_stats() if hasattr(_instance, "get_stats") else {}
                _results.append({"name": _name, "status": "HEALTHY", "stats": _stats})
                _healthy += 1
            except Exception as _exc:
                _results.append({"name": _name, "status": "UNHEALTHY", "reason": f"{type(_exc).__name__}: {_exc}"})

        _total = len(_modules)
        _score = round((_healthy / _total) * 100, 1) if _total > 0 else 0.0

        return {
            "status": "ok",
            "timestamp": time.time(),
            "overall_health_score": _score,
            "healthy_modules": _healthy,
            "total_modules": _total,
            "overall_status": "HEALTHY" if _score == 100.0 else "DEGRADED" if _score >= 70.0 else "CRITICAL",
            "modules": _results,
        }

    # ── Architecture Standards (v2.57) ─────────────────────────────────

    @app.get("/api/intelligence/architecture-standards")
    async def api_architecture_standards(user: Any = operator_or_admin):
        """Get health status of all Architecture Standard modules."""
        _arch_modules = [
            ("Feature Flags",        "core.feature_flags",        "get_feature_flag_manager"),
            ("Event Bus",            "core.event_bus",            "get_event_bus"),
            ("Plugin Registry",      "core.plugin_registry",      "get_plugin_registry"),
            ("Secrets Vault",        "core.secrets_vault",        "get_secrets_vault"),
            ("Enterprise Evolution", "core.enterprise_evolution", "get_evolution_engine"),
            ("Event Sourcing",       "core.event_sourcing",       "get_event_store"),
            ("CQRS Command Bus",     "core.cqrs.command_bus",     None),
            ("CQRS Query Bus",       "core.cqrs.query_bus",       None),
            ("Distributed Tracing",  "core.distributed_tracing",  "get_tracer"),
            ("Threat Intelligence",  "core.threat_intel",         "get_threat_intel"),
            ("Vulnerability Scanner", "core.vulnerability_scanner", "get_vulnerability_scanner"),
        ]

        _results = []
        _healthy = 0
        for _name, _import_path, _factory in _arch_modules:
            try:
                _mod = __import__(_import_path, fromlist=[""])
                if _factory is not None:
                    _fn = getattr(_mod, _factory, None)
                    if _fn is None:
                        _results.append({"name": _name, "status": "DEGRADED", "reason": f"factory {_factory} not found"})
                        continue
                    _instance = _fn()
                    _stats = _instance.get_stats() if hasattr(_instance, "get_stats") else {}
                    _results.append({"name": _name, "status": "HEALTHY", "stats": _stats})
                    _healthy += 1
                else:
                    _results.append({"name": _name, "status": "HEALTHY", "stats": {}})
                    _healthy += 1
            except Exception as _exc:
                _results.append({"name": _name, "status": "UNHEALTHY", "reason": f"{type(_exc).__name__}: {_exc}"})

        _total = len(_arch_modules)
        _score = round((_healthy / _total) * 100, 1) if _total > 0 else 0.0

        return {
            "status": "ok",
            "timestamp": time.time(),
            "overall_health_score": _score,
            "healthy_modules": _healthy,
            "total_modules": _total,
            "overall_status": "HEALTHY" if _score == 100.0 else "DEGRADED" if _score >= 70.0 else "CRITICAL",
            "modules": _results,
        }

    # ── v4.0 Comprehensive Health Check ──────────────────────────

    @app.get("/api/constitution/v4-health")
    async def api_constitution_v4_health(user: Any = operator_or_admin):
        """Get comprehensive v4.0 constitution health across all domains.

        Returns detailed health status for:
          - 55 total categories (31 classic + 12 layers + 12 gates)
          - 12 Enterprise Layers
          - 12 Quality Gates
          - 8 Success Metrics
          - 18 AI Specialist Roles
          - 10-step Definition of Done
          - 11-phase Continuous Lifecycle
          - 13 Engineering Principles
          - 13 Architecture Standards
          - 11 Security & Governance Standards
          - 6 Platform Engineering Standards
          - 9 SRE/Reliability Standards
        """
        try:
            from core.constitution import get_validator
            validator = get_validator()
            # Generate report once, reuse for health check AND category lists
            report_obj = validator.generate_report()
            report_dict = report_obj.to_dict()
            health = validator.comprehensive_health_check(reuse_report=report_obj)
            return {
                "status": "ok",
                "timestamp": time.time(),
                "version": "4.1.0",
                "overall_score": health["overall_score"],
                "total_categories": health["total_categories"],
                "total_evidence": health["total_evidence"],
                "open_regressions": health["open_regressions"],
                "domains": {
                    "enterprise_layers": health["enterprise_layers"],
                    "quality_gates": health["quality_gates"],
                    "success_metrics": health["success_metrics"],
                    "ai_specialist_roles": health["ai_specialist_roles"],
                    "definition_of_done": health["definition_of_done"],
                    "continuous_lifecycle": health["continuous_lifecycle"],
                    "engineering_principles": health["engineering_principles"],
                    "architecture_standards": health["architecture_standards"],
                    "security_governance": health["security_governance"],
                    "platform_engineering": health["platform_engineering"],
                    "sre_reliability": health["sre_reliability"],
                },
                "top_categories": [
                    {"id": cid, "score": cat["score"], "max_score": cat["max_score"]}
                    for cid, cat in sorted(
                        report_dict["categories"].items(),
                        key=lambda x: -x[1]["score"]
                    )[:10]
                ],
                "bottom_categories": [
                    {"id": cid, "score": cat["score"], "max_score": cat["max_score"]}
                    for cid, cat in sorted(
                        report_dict["categories"].items(),
                        key=lambda x: x[1]["score"]
                    )[:5]
                ],
            }
        except (ImportError, ValueError, TypeError, AttributeError, RuntimeError) as exc:
            _log.warning("[INTEL] v4.0 Health error: %s", exc)
            return {"status": "error", "detail": str(exc)}

    _log.info("[DASH] Incident & Health routes registered")
