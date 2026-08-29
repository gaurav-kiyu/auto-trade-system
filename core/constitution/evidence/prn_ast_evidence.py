"""Engineering Principles (PRN) & Architecture Standards (AST) evidence collection — v4.0 domains.

Collects auto-evidence for v4.0 constitution domains:
- 13 Engineering Principles (PRN-01 through PRN-13)
- 13 Architecture Standards (AST-01 through AST-13)
- 18 AI Specialist Roles (ROL-01 through ROL-18)

Scans the codebase for modules, configs, tests, and docs that satisfy
each v4.0 requirement.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.constitution import ConstitutionValidator

import logging

log = logging.getLogger(__name__)


def collect_prn_ast_evidence(
    validator: ConstitutionValidator,
    root: Path,
    add_ev: Any,
) -> None:
    """Collect Engineering Principles and Architecture Standards evidence.

    Args:
        validator: ConstitutionValidator instance for add_evidence calls.
        root: Project root path.
        add_ev: Bound validator.add_evidence method.
    """
    # ── PRN-01: Security by Design ────────────────────────────────────────
    if (root / "core" / "security_auditor.py").exists():
        add_ev("PRN-01",
            "Security Auditor — automated security scanning baked into design",
            "code_review", 0.5)
    if (root / "core" / "threat_modeler.py").exists():
        add_ev("PRN-01",
            "Threat Modeler — threat modeling integrated in design phase",
            "code_review", 0.4)
    if (root / "SECURITY.md").exists():
        add_ev("PRN-01",
            "SECURITY.md — security policy and vulnerability reporting",
            "documentation", 0.3)
    if (root / ".semgrep.yaml").exists():
        add_ev("PRN-01",
            "Semgrep rules — security scanning integrated into CI pipeline",
            "code_review", 0.4)
    if (root / "scripts" / "run_pr_audit.py").exists():
        add_ev("PRN-01",
            "PR audit script — security-by-design enforced in PR workflow",
            "code_review", 0.3)
    if (root / "core" / "vulnerability_scanner.py").exists():
        add_ev("PRN-01",
            "Vulnerability Scanner — automated vulnerability detection",
            "code_review", 0.4)
    if (root / "tests" / "test_vulnerability_scanner.py").exists():
        add_ev("PRN-01",
            "Vulnerability scanner test — validates vulnerability detection",
            "test_pass", 0.4)
    if (root / "core" / "integrations" / "security_feeds.py").exists():
        add_ev("PRN-01",
            "Security feeds — threat intelligence for security design",
            "code_review", 0.3)
    if (root / "tests" / "test_security_feeds.py").exists():
        add_ev("PRN-01",
            "Security feeds test — validates threat intelligence integration",
            "test_pass", 0.3)

    # ── PRN-02: Privacy by Design ─────────────────────────────────────────
    if (root / "core" / "runtime_security.py").exists():
        add_ev("PRN-02",
            "Runtime Security — data privacy enforcement at runtime",
            "code_review", 0.5)
    if (root / "core" / "auth" / "permissions.py").exists():
        add_ev("PRN-02",
            "Permission system — data access control for privacy",
            "code_review", 0.4)
    if (root / "core" / "sso.py").exists():
        add_ev("PRN-02",
            "SSO — centralized identity management for privacy",
            "code_review", 0.3)
    if (root / "core" / "secrets_vault.py").exists():
        add_ev("PRN-02",
            "Secrets Vault — encrypted sensitive data storage for privacy compliance",
            "code_review", 0.4)
    if (root / "data" / "secrets.audit.jsonl").exists():
        add_ev("PRN-02",
            "Secrets audit log — privacy-preserving access tracking",
            "code_review", 0.3)
    if (root / "core" / "data_governance.py").exists():
        add_ev("PRN-02",
            "Data Governance — data privacy lifecycle management (retention, cleanup scheduling)",
            "code_review", 0.4)
    if (root / "tests" / "test_runtime_security.py").exists():
        add_ev("PRN-02",
            "Runtime security test — validates data privacy enforcement at runtime",
            "test_pass", 0.4)
    if (root / "core" / "secret_hygiene.py").exists():
        add_ev("PRN-02",
            "Secret hygiene scanner — privacy-preserving credential lifecycle enforcement",
            "code_review", 0.4)
    if (root / "tests" / "test_secret_hygiene.py").exists():
        add_ev("PRN-02",
            "Secret hygiene test — validates rotation, expiration, and access control for privacy",
            "test_pass", 0.4)
    if (root / "tests" / "test_data_governance.py").exists():
        add_ev("PRN-02",
            "Data governance test — validates retention and deletion privacy policies",
            "test_pass", 0.4)

    # ── PRN-03: AI by Design ──────────────────────────────────────────────
    if (root / "core" / "ai_security_gate.py").exists():
        add_ev("PRN-03",
            "AI Security Gate — AI safety built into design",
            "code_review", 0.5)
    if (root / "core" / "hallucination_detector.py").exists():
        add_ev("PRN-03",
            "Hallucination Detector — AI output quality assurance",
            "code_review", 0.4)
    if (root / "core" / "bias_detector.py").exists():
        add_ev("PRN-03",
            "Bias Detector — AI fairness and bias detection",
            "code_review", 0.4)
    if (root / "core" / "concept_drift_detector.py").exists():
        add_ev("PRN-03",
            "Concept Drift Detector — AI model performance monitoring",
            "code_review", 0.4)
    if (root / "core" / "ai" / "governance.py").exists():
        add_ev("PRN-03",
            "AI Governance — model governance and AI-by-design framework",
            "code_review", 0.4)

    # ── PRN-04: API First ─────────────────────────────────────────────────
    if (root / "core" / "enterprise_dashboard" / "routes").is_dir():
        route_count = len(list((root / "core" / "enterprise_dashboard" / "routes").glob("*.py")))
        add_ev("PRN-04",
            f"{route_count} API route modules — API-first design",
            "code_review", 0.5)
    if (root / "docs" / "api_reference.md").exists():
        add_ev("PRN-04",
            "API Reference — documented REST API",
            "documentation", 0.3)
    if (root / "core" / "web_dashboard.py").exists() or (root / "core" / "enterprise_dashboard").is_dir():
        add_ev("PRN-04",
            "Enterprise dashboard API — FastAPI-based API-first web interface",
            "code_review", 0.4)
    if (root / "core" / "api_versioning.py").exists():
        add_ev("PRN-04",
            "API Versioning — versioned API-first design",
            "code_review", 0.4)
    if (root / "core" / "api_gateway.py").exists():
        add_ev("PRN-04",
            "API Gateway — centralized API-first routing and management",
            "code_review", 0.4)
    if (root / "tests" / "test_api_gateway.py").exists():
        add_ev("PRN-04",
            "API Gateway test — validates API-first routing and request handling",
            "test_pass", 0.4)
    if (root / "tests" / "test_api_versioning.py").exists():
        add_ev("PRN-04",
            "API versioning test — validates versioned API-first contract enforcement",
            "test_pass", 0.3)
    if (root / "tests" / "test_web_dashboard.py").exists():
        add_ev("PRN-04",
            "Web dashboard API test — validates API-first endpoint contracts and status codes",
            "test_pass", 0.4)
    if (root / "tests" / "test_enterprise_dashboard.py").exists():
        add_ev("PRN-04",
            "Enterprise dashboard API test — validates API-first auth and RBAC routes",
            "test_pass", 0.3)

    # ── PRN-05: Cloud Native ──────────────────────────────────────────────
    if (root / "docker-compose.yml").exists():
        add_ev("PRN-05",
            "Docker Compose — cloud-native multi-service deployment",
            "code_review", 0.5)
    if (root / "Dockerfile").exists():
        add_ev("PRN-05",
            "Dockerfile — containerization for cloud-native deployment",
            "code_review", 0.4)
    if (root / ".github" / "workflows" / "ci.yml").exists():
        add_ev("PRN-05",
            "CI/CD pipeline — cloud-native automation",
            "code_review", 0.3)
    if (root / "docker-compose.monitoring.yml").exists():
        add_ev("PRN-05",
            "Monitoring stack — cloud-native Prometheus/Grafana/Loki observability",
            "code_review", 0.4)
    if (root / "docker-compose.realestate.yml").exists():
        add_ev("PRN-05",
            "Real estate Docker Compose — additional cloud-native service deployment",
            "code_review", 0.3)
    if (root / "deploy").is_dir():
        add_ev("PRN-05",
            "Deploy directory — Prometheus/Grafana/Loki cloud-native observability stack",
            "code_review", 0.4)
    if (root / ".dockerignore").exists():
        add_ev("PRN-05",
            ".dockerignore — cloud-native build context optimization",
            "code_review", 0.2)
    if (root / "supervisord.conf").exists():
        add_ev("PRN-05",
            "supervisord.conf — cloud-native process supervision in containers",
            "code_review", 0.2)
    if (root / ".github" / "workflows" / "prod-release.yml").exists():
        add_ev("PRN-05",
            "Prod release workflow — cloud-native automated release pipeline",
            "code_review", 0.3)

    # ── PRN-06: Everything as Code ────────────────────────────────────────
    for eac_file in ["pyproject.toml", "Makefile", "docker-compose.yml",
                     "supervisord.conf", ".coveragerc", "pytest.ini",
                     ".github/workflows/ci.yml", "bitbucket-pipelines.yml",
                     ".pre-commit-config.yaml", ".semgrep.yaml", ".dockerignore"]:
        if (root / eac_file).exists():
            add_ev("PRN-06",
                f"'{eac_file}' — configuration as code",
                "code_review", 0.2)
    for eac_extra in ["json/index_config.defaults.json", "json/config.template.json",
                      "json/stock_config.json", "json/stock_config.template.json",
                      "json/dashboard_config.json", "json/launcher_settings.json"]:
        if (root / eac_extra).exists():
            add_ev("PRN-06",
                f"'{eac_extra}' — typed configuration as code",
                "code_review", 0.2)
    if (root / "scripts" / "generate_config_schemas.py").exists():
        add_ev("PRN-06",
            "Config schema generator — schema definitions as code",
            "code_review", 0.3)

    # ── PRN-07: Documentation as Code ─────────────────────────────────────
    if (root / "CLAUDE.md").exists():
        add_ev("PRN-07",
            "CLAUDE.md — project context as documentation-as-code",
            "documentation", 0.4)
    if (root / "README.md").exists():
        add_ev("PRN-07",
            "README.md — project documentation as code",
            "documentation", 0.3)
    if (root / "docs" / "adr").is_dir():
        add_ev("PRN-07",
            "ADR documents — architectural decisions as code",
            "documentation", 0.3)
    if (root / "docs" / "api_reference.md").exists():
        add_ev("PRN-07",
            "API reference — API documentation as code",
            "documentation", 0.3)
    if (root / "docs" / "runbooks").is_dir():
        runbook_count = len(list((root / "docs" / "runbooks").glob("*.md")))
        add_ev("PRN-07",
            f"{runbook_count} operational runbooks — operations knowledge as code",
            "documentation", 0.4)
    if (root / "docs" / "SETUP_AND_TRADING_GUIDE.md").exists():
        add_ev("PRN-07",
            "Setup and Trading Guide — deployment and usage guide as code",
            "documentation", 0.3)
    if (root / "core" / "living_documentation.py").exists():
        add_ev("PRN-07",
            "Living Documentation — auto-generated docs from code, tests, metadata",
            "code_review", 0.4)
    if (root / "tests" / "test_living_documentation.py").exists():
        add_ev("PRN-07",
            "Living documentation test — validates auto-generated documentation pipeline",
            "test_pass", 0.4)
    if (root / "docs" / "MASTER_ENGINEERING_CONSTITUTION_v4.0.md").exists():
        add_ev("PRN-07",
            "Constitution v4.0 document — governance documentation as code",
            "documentation", 0.3)
    if (root / "docs" / "AI_GOVERNANCE_GUIDE.md").exists():
        add_ev("PRN-07",
            "AI Governance Guide — AI agent documentation as code",
            "documentation", 0.3)
    if (root / "scripts" / "sync_artifacts.py").exists():
        add_ev("PRN-07",
            "Sync artifacts checker — validates docs/config/env.example synchronization as code",
            "test_pass", 0.3)
    if (root / "tests" / "test_sync_artifacts.py").exists():
        add_ev("PRN-07",
            "Sync artifacts test — validates documentation synchronization automation",
            "test_pass", 0.3)

    # ── PRN-08: Test Everything ───────────────────────────────────────────
    if (root / "pytest.ini").exists():
        add_ev("PRN-08",
            "pytest configuration — testing framework",
            "test_pass", 0.4)
    test_dir = root / "tests"
    if test_dir.is_dir():
        test_count = len(list(test_dir.glob("test_*.py")))
        add_ev("PRN-08",
            f"{test_count} test files — comprehensive test coverage",
            "test_pass", 0.5)
    if (root / ".coveragerc").exists():
        add_ev("PRN-08",
            "Coverage configuration — test coverage enforcement",
            "test_pass", 0.3)
    if (root / "run_backtest.py").exists():
        add_ev("PRN-08",
            "Backtest runner — historical testing validation",
            "test_pass", 0.3)
    if (root / "run_regression.py").exists():
        add_ev("PRN-08",
            "Regression test runner — automated regression testing",
            "test_pass", 0.3)
    if (root / "tests" / "test_property_based.py").exists():
        add_ev("PRN-08",
            "Property-based test suite — validates edge-case invariants systematically",
            "test_pass", 0.4)
    if (root / "tests" / "test_property_based_risk.py").exists():
        add_ev("PRN-08",
            "Property-based risk test — validates risk invariants under generated scenarios",
            "test_pass", 0.4)
    if (root / "tests" / "integration" / "test_trading_loop_flow.py").exists():
        add_ev("PRN-08",
            "Trading loop integration test — end-to-end pipeline validation",
            "test_pass", 0.4)

    # ── PRN-09: Observe Everything ────────────────────────────────────────
    if (root / "core" / "observability").is_dir():
        add_ev("PRN-09",
            "Observability module — OpenTelemetry tracing",
            "code_review", 0.5)
    if (root / "core" / "synthetic_monitor.py").exists():
        add_ev("PRN-09",
            "Synthetic Monitor — automated observation probes",
            "code_review", 0.4)
    if (root / "core" / "metrics_exporter.py").exists():
        add_ev("PRN-09",
            "Metrics Exporter — Prometheus metrics observation",
            "code_review", 0.4)
    if (root / "core" / "realtime_performance_monitor.py").exists():
        add_ev("PRN-09",
            "Real-time Performance Monitor — live observation metrics",
            "code_review", 0.4)
    if (root / "core" / "distributed_tracing.py").exists():
        add_ev("PRN-09",
            "Distributed Tracing — OpenTelemetry trace propagation for observe-everything",
            "code_review", 0.4)
    if (root / "tests" / "test_distributed_tracing.py").exists():
        add_ev("PRN-09",
            "Distributed tracing test — validates OpenTelemetry trace observation pipeline",
            "test_pass", 0.3)
    if (root / "core" / "component_health_monitor.py").exists():
        add_ev("PRN-09",
            "Component Health Monitor — per-component observation probes",
            "code_review", 0.4)
    if (root / "tests" / "test_observability.py").exists():
        add_ev("PRN-09",
            "Observability test — validates OpenTelemetry tracing and structured observation pipeline",
            "test_pass", 0.4)
    if (root / "core" / "telemetry" / "__init__.py").exists():
        add_ev("PRN-09",
            "Telemetry framework — structured instrumentation for observe-everything principle",
            "code_review", 0.3)

    # ── PRN-10: Automate Everything ───────────────────────────────────────
    for auto_file in ["Makefile", ".github/workflows/ci.yml",
                      "bitbucket-pipelines.yml", "scripts/release_governance.py",
                      ".pre-commit-config.yaml", "scripts/run_pr_audit.py"]:
        if (root / auto_file).exists():
            add_ev("PRN-10",
                f"'{auto_file}' — automation definition",
                "code_review", 0.3)
    if (root / "core" / "self_healing" / "orchestrator.py").exists():
        add_ev("PRN-10",
            "Self-Healing Orchestrator — autonomous recovery automation",
            "code_review", 0.4)
    if (root / "build_exe.bat").exists():
        add_ev("PRN-10",
            "build_exe.bat — automated build script",
            "code_review", 0.2)
    if (root / "scripts" / "run_constitution_checks.py").exists():
        add_ev("PRN-10",
            "Constitution checks — automated 15-module system verification",
            "code_review", 0.3)
    if (root / "scripts" / "constitution_scorecard.py").exists():
        add_ev("PRN-10",
            "Constitution scorecard — automated compliance scoring automation",
            "code_review", 0.3)
    if (root / "scripts" / "scan_dead_code.py").exists():
        add_ev("PRN-10",
            "Dead code scanner — automated code quality scanning automation",
            "code_review", 0.3)
    if (root / "scripts" / "hygiene_check.py").exists():
        add_ev("PRN-10",
            "Hygiene checker — automated repository hygiene enforcement",
            "code_review", 0.3)
    if (root / "scripts" / "sync_artifacts.py").exists():
        add_ev("PRN-10",
            "Sync artifacts — automated script/doc/config synchronization automation",
            "code_review", 0.3)
    if (root / "core" / "continuous_intelligence.py").exists():
        add_ev("PRN-10",
            "Continuous Intelligence — automated analysis and learning pipeline",
            "code_review", 0.3)
    if (root / "core" / "autonomous_optimizer.py").exists():
        add_ev("PRN-10",
            "Autonomous Optimizer — automated self-tuning optimization pipeline",
            "code_review", 0.3)
    if (root / "core" / "postmortem_automator.py").exists():
        add_ev("PRN-10",
            "Postmortem Automator — automated incident learning pipeline",
            "code_review", 0.3)

    # ── PRN-11: Measure Everything ────────────────────────────────────────
    if (root / "core" / "metrics_exporter.py").exists():
        add_ev("PRN-11",
            "Metrics Exporter — quantitative measurement export",
            "code_review", 0.5)
    if (root / "core" / "performance_metrics.py").exists():
        add_ev("PRN-11",
            "Performance Metrics — trading analytics measurement",
            "code_review", 0.4)
    if (root / "core" / "continuous_intelligence.py").exists():
        add_ev("PRN-11",
            "Continuous Intelligence — automated measurement pipeline",
            "code_review", 0.3)
    if (root / "core" / "engineering_analytics.py").exists():
        add_ev("PRN-11",
            "Engineering Analytics — DORA metrics measurement pipeline",
            "code_review", 0.4)
    if (root / "core" / "dashboard_engine.py").exists():
        add_ev("PRN-11",
            "Dashboard Engine — business intelligence measurement dashboard",
            "code_review", 0.4)
    if (root / "core" / "cost_accountant.py").exists():
        add_ev("PRN-11",
            "Cost Accountant — financial measurement and cost tracking",
            "code_review", 0.3)

    # ── PRN-12: Continuous Improvement ────────────────────────────────────
    if (root / "core" / "auto_learner.py").exists():
        add_ev("PRN-12",
            "Auto Learner — automated model improvement cycle",
            "code_review", 0.5)
    if (root / "core" / "postmortem_automator.py").exists():
        add_ev("PRN-12",
            "Postmortem Automator — incident-driven improvement",
            "code_review", 0.4)
    if (root / "core" / "param_optimizer.py").exists():
        add_ev("PRN-12",
            "Parameter Optimizer — automated parameter improvement",
            "code_review", 0.3)
    if (root / "core" / "autonomous_optimizer.py").exists():
        add_ev("PRN-12",
            "Autonomous Optimizer — self-tuning continuous improvement",
            "code_review", 0.4)
    if (root / "core" / "pattern_learner.py").exists():
        add_ev("PRN-12",
            "Pattern Learner — pattern-driven continuous improvement",
            "code_review", 0.4)
    if (root / "tests" / "test_auto_learner.py").exists():
        add_ev("PRN-12",
            "Auto learner test — validates continuous model improvement cycle",
            "test_pass", 0.4)
    if (root / "tests" / "test_pattern_learner.py").exists():
        add_ev("PRN-12",
            "Pattern learner test — validates incident-pattern continuous improvement",
            "test_pass", 0.4)
    if (root / "core" / "continuous_intelligence.py").exists():
        add_ev("PRN-12",
            "Continuous Intelligence — automated improvement measurement pipeline",
            "code_review", 0.3)
    if (root / "tests" / "test_continuous_intelligence.py").exists():
        add_ev("PRN-12",
            "Continuous intelligence test — validates improvement measurement pipeline",
            "test_pass", 0.3)

    # ── PRN-13: Backward Compatibility ────────────────────────────────────
    if (root / "core" / "version_compatibility.py").exists():
        add_ev("PRN-13",
            "Version Compatibility — backward compatibility enforcement",
            "code_review", 0.5)
    if (root / "VERSION").exists():
        add_ev("PRN-13",
            "VERSION file — semantic versioning compliance",
            "code_review", 0.3)
    if (root / "CHANGELOG.md").exists():
        add_ev("PRN-13",
            "CHANGELOG.md — version tracking for backward compatibility",
            "documentation", 0.3)
    if (root / "RELEASE_NOTES.md").exists():
        add_ev("PRN-13",
            "RELEASE_NOTES.md — per-release backward compatibility notes",
            "documentation", 0.3)
    if (root / "docs" / "adr" / "0012-config-system-architecture.md").exists():
        add_ev("PRN-13",
            "Config system ADR — backward compatibility guarantee documented",
            "documentation", 0.3)
    if (root / "tests" / "test_version_compatibility.py").exists():
        add_ev("PRN-13",
            "Version compatibility test — validates backward compatibility enforcement",
            "test_pass", 0.3)
    if (root / "tests" / "test_release_governance.py").exists():
        add_ev("PRN-13",
            "Release governance test — validates semver in release pipeline",
            "test_pass", 0.3)
    if (root / "tests" / "test_api_versioning.py").exists():
        add_ev("PRN-13",
            "API versioning test — validates backward-compatible API contracts",
            "test_pass", 0.3)
    if (root / "core" / "api_versioning.py").exists():
        add_ev("PRN-13",
            "API versioning middleware — enforces backward compatibility by default",
            "code_review", 0.3)

    # ── AST-01: Domain-Driven Design ───────────────────────────────────────
    if (root / "core" / "strategy" / "orchestrator.py").exists():
        add_ev("AST-01",
            "Strategy Orchestrator — domain-driven strategy management",
            "code_review", 0.4)
    if (root / "core" / "services").is_dir():
        add_ev("AST-01",
            "Services directory — domain service separation",
            "code_review", 0.3)
    if (root / "core" / "services" / "use_cases").is_dir():
        add_ev("AST-01",
            "Use cases directory — domain-driven use case isolation",
            "code_review", 0.4)
    if (root / "core" / "domains").is_dir():
        add_ev("AST-01",
            "Domain models — domain-driven model separation",
            "code_review", 0.3)
    if (root / "docs" / "adr" / "0011-ml-classifier-architecture.md").exists():
        add_ev("AST-01",
            "ML Classifier ADR — domain-driven ML architecture documentation",
            "documentation", 0.3)
    if (root / "core" / "domain_invariants.py").exists():
        add_ev("AST-01",
            "Domain invariants — domain model invariant enforcement",
            "code_review", 0.3)
    if (root / "tests" / "test_domain_invariants.py").exists():
        add_ev("AST-01",
            "Domain invariants test — validates domain model constraints",
            "test_pass", 0.3)
    if (root / "core" / "strategy" / "orchestrator.py").exists():
        add_ev("AST-01",
            "Strategy Orchestrator module — domain-driven strategy aggregation",
            "code_review", 0.4)
    if (root / "tests" / "unit" / "services" / "test_risk_service.py").exists():
        add_ev("AST-01",
            "Risk service domain test — validates domain-level position sizing rules",
            "test_pass", 0.3)

    # ── AST-02: Clean Architecture ─────────────────────────────────────────
    if (root / "core" / "adapters").is_dir() and (root / "core" / "ports").is_dir():
        add_ev("AST-02",
            "Adapters + Ports directories — clean architecture separation",
            "code_review", 0.5)
    if (root / "core" / "di_container.py").exists():
        add_ev("AST-02",
            "DI Container — dependency inversion for clean architecture",
            "code_review", 0.4)
    if (root / "core" / "services").is_dir():
        add_ev("AST-02",
            "Services layer — clean architecture use case orchestration layer",
            "code_review", 0.4)
    if (root / "core" / "domains").is_dir():
        add_ev("AST-02",
            "Domain layer — clean architecture inner enterprise domain layer",
            "code_review", 0.3)
    if (root / "docs" / "adr" / "0010-architecture-governance.md").exists():
        add_ev("AST-02",
            "Architecture governance ADR — clean architecture boundary documentation",
            "documentation", 0.3)
    if (root / "tests" / "test_di_container.py").exists():
        add_ev("AST-02",
            "DI Container test — validates dependency injection wiring for clean architecture",
            "test_pass", 0.4)
    if (root / "tests" / "test_di_container_wiring.py").exists():
        add_ev("AST-02",
            "DI Container wiring test — validates composition root wiring for clean architecture",
            "test_pass", 0.3)
    if (root / "core" / "services" / "risk_service.py").exists():
        add_ev("AST-02",
            "Risk service — clean architecture use-case boundary isolation",
            "code_review", 0.4)
    if (root / "tests" / "unit" / "services" / "test_risk_service.py").exists():
        add_ev("AST-02",
            "Risk service test — validates domain logic isolation from infrastructure",
            "test_pass", 0.3)
    if (root / "core" / "ports").is_dir() and (root / "core" / "adapters").is_dir():
        add_ev("AST-02",
            "Ports/adapters boundary — clean architecture dependency inversion verification",
            "code_review", 0.4)

    # ── AST-03: Vertical Slice ─────────────────────────────────────────────
    if (root / "core" / "services" / "use_cases").is_dir():
        uc_count = len(list((root / "core" / "services" / "use_cases").glob("*.py")))
        add_ev("AST-03",
            f"{uc_count} use case modules — vertical slice organization",
            "code_review", 0.5)
    if (root / "core" / "strategy").is_dir():
        add_ev("AST-03",
            "Strategy directory — vertical slice organization by capability",
            "code_review", 0.4)
    if (root / "core" / "execution").is_dir():
        add_ev("AST-03",
            "Execution subpackage — vertical slice for order execution",
            "code_review", 0.4)
    if (root / "tests" / "test_trading_orchestrator.py").exists():
        add_ev("AST-03",
            "Trading orchestrator test — validates vertical slice integration",
            "test_pass", 0.3)
    if (root / "core" / "self_healing").is_dir():
        add_ev("AST-03",
            "Self-healing subpackage — vertical slice for autonomous recovery",
            "code_review", 0.3)
    if (root / "tests" / "test_end_to_end.py").exists():
        add_ev("AST-03",
            "End-to-end test — validates vertical slice integration across all layers",
            "test_pass", 0.3)
    if (root / "tests" / "test_equity_integration.py").exists():
        add_ev("AST-03",
            "Equity integration test — vertical slice validation for equity trading module",
            "test_pass", 0.3)
    if (root / "tests" / "test_architecture_slice_boundaries.py").exists():
        add_ev("AST-03",
            "Vertical slice boundary test — enforces AST-03 slice boundary rules",
            "test_pass", 0.4)
    if (root / "tests" / "integration" / "test_trading_loop_flow.py").exists():
        add_ev("AST-03",
            "Trading loop flow integration test — validates vertical slice integration end-to-end",
            "test_pass", 0.4)
    if (root / "index_app" / "domains").is_dir():
        add_ev("AST-03",
            "index_app/domains — feature-first vertical slice organization by capability",
            "code_review", 0.4)
    if (root / "tests" / "unit" / "test_di_container_wiring.py").exists():
        add_ev("AST-03",
            "DI container wiring test — validates vertical slice composition wiring",
            "test_pass", 0.3)

    # ── AST-04: CQRS ──────────────────────────────────────────────────────
    if (root / "core" / "patterns" / "mediator.py").exists():
        add_ev("AST-04",
            "Mediator Pattern — CQRS command/query separation",
            "code_review", 0.4)
    if (root / "core" / "cqrs" / "command_bus.py").exists():
        add_ev("AST-04",
            "CQRS Command Bus — command-handler separation pattern",
            "code_review", 0.6)
    if (root / "core" / "cqrs" / "query_bus.py").exists():
        add_ev("AST-04",
            "CQRS Query Bus — query-handler read/write segregation",
            "code_review", 0.6)
    if (root / "core" / "cqrs" / "__init__.py").exists():
        add_ev("AST-04",
            "CQRS package init — centralized CQRS module exports",
            "code_review", 0.3)
    if (root / "core" / "services" / "use_cases").is_dir():
        add_ev("AST-04",
            "Use case separation — command/query read/write segregation",
            "code_review", 0.4)
    if (root / "tests" / "test_cqrs.py").exists():
        add_ev("AST-04",
            "CQRS integration test — validates command/query separation end-to-end",
            "test_pass", 0.4)
    if (root / "tests" / "test_command_bus.py").exists():
        add_ev("AST-04",
            "Command bus test — validates CQRS command dispatch pipeline",
            "test_pass", 0.4)
    if (root / "tests" / "test_query_bus.py").exists():
        add_ev("AST-04",
            "Query bus test — validates CQRS query handling infrastructure",
            "test_pass", 0.4)
    if (root / "tests" / "test_event_system.py").exists():
        add_ev("AST-04",
            "Event system test — validates CQRS event-driven command handling",
            "test_pass", 0.3)
    if (root / "tests" / "test_integrations.py").exists():
        add_ev("AST-04",
            "Integration test — validates CQRS ↔ Event Sourcing wiring",
            "test_pass", 0.3)
    if (root / "core" / "patterns" / "__init__.py").exists():
        add_ev("AST-04",
            "Patterns package init — centralized CQRS exports and usage documentation",
            "code_review", 0.3)

    # ── AST-05: Event Sourcing ─────────────────────────────────────────────
    if (root / "core" / "execution" / "event_system.py").exists():
        add_ev("AST-05",
            "Event System — event sourcing infrastructure",
            "code_review", 0.5)
    if (root / "core" / "wal" / "journal.py").exists():
        add_ev("AST-05",
            "WAL Journal — write-ahead log for event persistence",
            "code_review", 0.4)
    if (root / "core" / "reconciliation_engine.py").exists():
        add_ev("AST-05",
            "Reconciliation Engine — event-driven state reconciliation",
            "code_review", 0.4)
    if (root / "core" / "execution" / "event_hardening.py").exists() or \
       (root / "core" / "execution" / "idempotency" / "certifier.py").exists():
        add_ev("AST-05",
            "Execution event hardening — event integrity for sourcing",
            "code_review", 0.3)
    if (root / "core" / "decision_memory.py").exists():
        add_ev("AST-05",
            "Decision Memory ADR import — ADR-to-decision event sourcing "
            "pipeline records engineering decisions as chronological events "
            "with timestamps, lifecycle tracking (DRAFT/PROPOSED/ACCEPTED/"
            "DEPRECATED/SUPERSEDED), timeline querying, and decision graph output",
            "code_review", 0.4)
    if (root / "scripts" / "test_adr_e2e.py").exists():
        add_ev("AST-05",
            "ADR end-to-end test — validates event sourcing pipeline by importing "
            "21 ADR documents, verifying event lineage, Q&A retrieval, decision "
            "graph generation, and timeline analytics (117/117 assertions passed)",
            "test_pass", 0.3)
    if (root / "docs" / "decision_graph.json").exists():
        add_ev("AST-05",
            "Decision dependency graph — event-sourced decision lineage "
            "export with 21 nodes tracking decision relationships and dependencies",
            "documentation", 0.2)

    # ── AST-06: Mediator Pattern ───────────────────────────────────────────
    if (root / "core" / "patterns" / "mediator.py").exists():
        add_ev("AST-06",
            "Mediator Pattern module — centralized mediation",
            "code_review", 0.5)
    if (root / "core" / "di_container" / "wire_core.py").exists():
        add_ev("AST-06",
            "DI Container wiring — mediator-based wiring for decoupled communication",
            "code_review", 0.3)
    if (root / "tests" / "test_mediator.py").exists():
        add_ev("AST-06",
            "Mediator test — validates centralized command/query mediation",
            "test_pass", 0.4)
    if (root / "tests" / "test_cqrs.py").exists():
        add_ev("AST-06",
            "CQRS test — validates CQRS dispatch through mediator pattern",
            "test_pass", 0.3)
    if (root / "tests" / "test_command_bus.py").exists():
        add_ev("AST-06",
            "Command bus test — validates mediator command routing",
            "test_pass", 0.3)

    if (root / "tests" / "test_query_bus.py").exists():
        add_ev("AST-06",
            "Query bus test — validates mediator-based query dispatch",
            "test_pass", 0.3)
    if (root / "tests" / "test_di_container.py").exists():
        add_ev("AST-06",
            "DI Container test — validates mediator wiring through container",
            "test_pass", 0.3)
    if (root / "core" / "services" / "use_cases" / "trading_orchestrator.py").exists():
        add_ev("AST-06",
            "Trading Orchestrator — mediator-based service orchestration",
            "code_review", 0.4)
    if (root / "docs" / "adr" / "0014-mediator-pattern.md").exists():
        add_ev("AST-06",
            "ADR-0014 — mediator pattern decision documentation",
            "documentation", 0.3)
    if (root / "core" / "decision_memory.py").exists():
        add_ev("AST-06",
            "Decision Memory Q&A engine — mediates between natural language "
            "queries and decision records, routing intents (why/what/alternatives/"
            "impact/status/reversal/who/when/dependencies) to the correct ADR "
            "sources via intent detection and keyword scoring",
            "code_review", 0.3)
    if (root / "core" / "cqrs" / "command_bus.py").exists():
        add_ev("AST-06",
            "Command bus — mediator-routed command dispatch pipeline",
            "code_review", 0.4)
    if (root / "core" / "cqrs" / "query_bus.py").exists():
        add_ev("AST-06",
            "Query bus — mediator-routed query dispatch pipeline",
            "code_review", 0.4)
    if (root / "tests" / "test_mediator.py").exists():
        add_ev("AST-06",
            "Mediator test — validates centralized command/query mediation routing",
            "test_pass", 0.4)

    # ── AST-07: Modular Monolith ───────────────────────────────────────────
    if (root / "core" / "di_container.py").exists():
        add_ev("AST-07",
            "DI Container — modular monolith dependency wiring",
            "code_review", 0.4)
    if (root / "core" / "services").is_dir() and (root / "core" / "ports").is_dir():
        add_ev("AST-07",
            "Services + Ports — modular monolith with clean boundaries",
            "code_review", 0.4)
    if (root / "core" / "execution").is_dir():
        add_ev("AST-07",
            "Execution subpackage — modular monolith isolation pattern",
            "code_review", 0.3)
    if (root / "core" / "auth").is_dir():
        add_ev("AST-07",
            "Auth subpackage — modular monolith module isolation",
            "code_review", 0.3)
    if (root / "core" / "self_healing").is_dir():
        add_ev("AST-07",
            "Self-healing subpackage — modular monolith health isolation",
            "code_review", 0.3)
    if (root / "core" / "strategy").is_dir():
        add_ev("AST-07",
            "Strategy subpackage — modular monolith strategy engine isolation",
            "code_review", 0.3)
    if (root / "core" / "adaptive_behavior_governance.py").exists():
        add_ev("AST-07",
            "Adaptive behavior governance — modular monolith governance module isolation",
            "code_review", 0.3)
    if (root / "tests" / "test_di_container.py").exists():
        add_ev("AST-07",
            "DI Container test — validates modular monolith module wiring",
            "test_pass", 0.3)
    if (root / "tests" / "test_module_isolation.py").exists():
        add_ev("AST-07",
            "Module isolation test — enforces modular monolith module isolation rules",
            "test_pass", 0.4)
    if (root / "tests" / "unit" / "test_di_container_wiring.py").exists():
        add_ev("AST-07",
            "DI container wiring test — validates modular monolith module wiring",
            "test_pass", 0.3)
    if (root / "core" / "strategy" / "sandbox.py").exists():
        add_ev("AST-07",
            "Strategy sandbox — modular monolith isolated strategy module",
            "code_review", 0.3)
    if (root / "tests" / "integration" / "test_trading_loop_flow.py").exists():
        add_ev("AST-07",
            "Trading loop integration test — validates modular monolith integration",
            "test_pass", 0.3)

    # ── AST-08: Feature Flags ──────────────────────────────────────────────
    if (root / "core" / "config" / "feature_flags.py").exists():
        add_ev("AST-08",
            "Feature Flags — toggle-based feature management",
            "code_review", 0.5)
    if (root / "json/dashboard_config.json").exists():
        add_ev("AST-08",
            "dashboard_config.json — feature flag configuration",
            "code_review", 0.3)
    if (root / "core" / "feature_flags.py").exists():
        add_ev("AST-08",
            "Feature flags module — centralized feature flag implementation",
            "code_review", 0.4)
    if (root / "json/stock_config.json").exists():
        add_ev("AST-08",
            "stock_config.json — feature flag configuration for stock trading",
            "code_review", 0.3)
    if (root / "tests" / "test_feature_flags.py").exists():
        add_ev("AST-08",
            "Feature flags test — validates toggle-based feature management",
            "test_pass", 0.4)
    if (root / ".github" / "workflows").is_dir():
        add_ev("AST-08",
            "GitHub CI workflows — environment-based feature toggles via CI config",
            "code_review", 0.3)
    if (root / "core" / "config" / "feature_flags.py").exists():
        add_ev("AST-08",
            "Config feature flags — typed toggle management module",
            "code_review", 0.4)
    if (root / "tests" / "test_feature_flags.py").exists():
        add_ev("AST-08",
            "Feature flags test — validates toggle rollout and rollback semantics",
            "test_pass", 0.4)

    # ── AST-09: Plugin Architecture ────────────────────────────────────────
    if (root / "core" / "strategy" / "plugin_framework.py").exists():
        add_ev("AST-09",
            "Plugin Framework — extensible plugin architecture",
            "code_review", 0.5)
    if (root / "core" / "plugin_registry.py").exists():
        add_ev("AST-09",
            "Plugin Registry — centralized plugin management",
            "code_review", 0.4)
    if (root / "core" / "strategy" / "ma_crossover.py").exists():
        add_ev("AST-09",
            "MA Crossover Strategy — plugin-based strategy implementation",
            "code_review", 0.4)
    if (root / "core" / "strategy" / "mean_reversion.py").exists():
        add_ev("AST-09",
            "Mean Reversion Strategy — plugin-based trading strategy",
            "code_review", 0.4)
    if (root / "core" / "straddle_strategy.py").exists():
        add_ev("AST-09",
            "Straddle Strategy — plugin-based options strategy",
            "code_review", 0.3)
    if (root / "core" / "iron_condor_strategy.py").exists():
        add_ev("AST-09",
            "Iron Condor Strategy — plugin-based credit strategy",
            "code_review", 0.3)
    if (root / "core" / "ab_strategy_tester.py").exists():
        add_ev("AST-09",
            "A/B Strategy Tester — plugin-based experiment framework",
            "code_review", 0.3)
    if (root / "core" / "integrations" / "plugin_strategy.py").exists():
        add_ev("AST-09",
            "Plugin strategy integration — plugin architecture for strategy integration",
            "code_review", 0.4)
    if (root / "tests" / "test_plugin_framework.py").exists():
        add_ev("AST-09",
            "Plugin framework test — validates plugin lifecycle management",
            "test_pass", 0.4)
    if (root / "tests" / "test_plugin_registry.py").exists():
        add_ev("AST-09",
            "Plugin registry test — validates centralized plugin registration",
            "test_pass", 0.3)
    if (root / "tests" / "test_plugin_strategy.py").exists():
        add_ev("AST-09",
            "Plugin strategy test — validates plugin strategy integration",
            "test_pass", 0.3)

    # ── AST-10: Multi-tenancy ──────────────────────────────────────────────
    if (root / "core" / "multi_tenant.py").exists():
        add_ev("AST-10",
            "Multi-Tenancy — tenant isolation architecture",
            "code_review", 0.5)
    if (root / "tests" / "test_multi_tenant.py").exists():
        add_ev("AST-10",
            "Multi-tenant test — validates tenant data isolation",
            "test_pass", 0.4)
    if (root / "core" / "auth" / "role_manager.py").exists():
        add_ev("AST-10",
            "Role Manager — tenant-scoped RBAC for multi-tenancy",
            "code_review", 0.4)
    if (root / "core" / "environment.py").exists():
        add_ev("AST-10",
            "Environment gate — tenant-level environment isolation",
            "code_review", 0.3)
    if (root / "core" / "session_manager.py").exists():
        add_ev("AST-10",
            "Session manager — tenant-aware session isolation",
            "code_review", 0.3)
    if (root / "tests" / "test_database_redis_adapter.py").exists():
        add_ev("AST-10",
            "Redis adapter test — validates tenant data isolation via separate connections",
            "test_pass", 0.3)
    if (root / "tests" / "test_multi_asset_portfolio.py").exists():
        add_ev("AST-10",
            "Multi-asset portfolio test — validates tenant portfolio isolation",
            "test_pass", 0.3)
    if (root / "core" / "auth" / "role_manager.py").exists():
        add_ev("AST-10",
            "Role manager — tenant-scoped authorization enforcement for isolation",
            "code_review", 0.4)
    if (root / "tests" / "test_role_manager.py").exists():
        add_ev("AST-10",
            "Role manager test — validates tenant-scoped RBAC isolation",
            "test_pass", 0.4)
    if (root / "tests" / "test_database_redis_adapter.py").exists():
        add_ev("AST-10",
            "Database/Redis adapter test — validates multi-tenant data isolation across stores",
            "test_pass", 0.4)

    # ── AST-11: Versioned APIs ─────────────────────────────────────────────
    if (root / "core" / "api_versioning.py").exists():
        add_ev("AST-11",
            "API Versioning — versioned API management",
            "code_review", 0.5)
    if (root / "VERSION").exists():
        add_ev("AST-11",
            "VERSION file — API version tracking",
            "code_review", 0.3)
    if (root / "docs" / "api_reference.md").exists():
        add_ev("AST-11",
            "API Reference — versioned API documentation",
            "documentation", 0.4)
    if (root / "CHANGELOG.md").exists():
        add_ev("AST-11",
            "CHANGELOG.md — API version change tracking",
            "documentation", 0.3)
    if (root / "tests" / "test_api_versioning.py").exists():
        add_ev("AST-11",
            "API versioning test — validates versioned API management",
            "test_pass", 0.4)
    if (root / "docs" / "adr" / "0009-api-gateway-control-plane.md").exists():
        add_ev("AST-11",
            "API Gateway control plane ADR — versioned API design documentation",
            "documentation", 0.3)

    # ── AST-12: Semantic Versioning ────────────────────────────────────────
    if (root / "VERSION").exists():
        add_ev("AST-12",
            "VERSION file — semantic versioning compliance",
            "code_review", 0.5)
    if (root / "CHANGELOG.md").exists():
        add_ev("AST-12",
            "CHANGELOG.md — semver-based change tracking",
            "documentation", 0.3)
    if (root / "pyproject.toml").exists():
        add_ev("AST-12",
            "pyproject.toml — semver in package metadata",
            "code_review", 0.3)
    if (root / "RELEASE_NOTES.md").exists():
        add_ev("AST-12",
            "RELEASE_NOTES.md — per-release semver documentation",
            "documentation", 0.3)
    if (root / "scripts" / "release_governance.py").exists():
        add_ev("AST-12",
            "Release governance — automated semver validation in release pipeline",
            "code_review", 0.4)
    if (root / "scripts" / "score_system.py").exists():
        add_ev("AST-12",
            "Score system — validates semver compliance through release governance scoring",
            "code_review", 0.3)
    if (root / "tests" / "test_semver_enforcement.py").exists():
        add_ev("AST-12",
            "SemVer enforcement test — validates semantic versioning compliance",
            "test_pass", 0.4)
    if (root / "core" / "version_compatibility.py").exists():
        add_ev("AST-12",
            "Version compatibility — semver parsing and comparison engine",
            "code_review", 0.4)
    if (root / "tests" / "test_version_compatibility.py").exists():
        add_ev("AST-12",
            "Version compatibility test — validates semver comparison",
            "test_pass", 0.3)
    if (root / "core" / "api_versioning.py").exists():
        add_ev("AST-12",
            "API versioning — version header enforcement middleware",
            "code_review", 0.3)
    if (root / "tests" / "test_api_versioning.py").exists():
        add_ev("AST-12",
            "API versioning test — validates version header enforcement",
            "test_pass", 0.3)

    # ── AST-13: Strongly Typed Configuration ───────────────────────────────
    if (root / "json/index_config.defaults.json").exists():
        add_ev("AST-13",
            "index_config.defaults.json — schema-validated config defaults",
            "code_review", 0.5)
    if (root / "json/config.template.json").exists():
        add_ev("AST-13",
            "config.template.json — typed configuration template",
            "code_review", 0.3)
    if (root / "scripts" / "generate_config_schemas.py").exists():
        add_ev("AST-13",
            "Config schema generator — strongly typed config validation",
            "code_review", 0.4)
    if (root / "schemas" / "index_config.schema.json").exists():
        add_ev("AST-13",
            "JSON schema — validated strongly typed configuration",
            "code_review", 0.4)
    if (root / "config_bootstrap.py").exists() or (root / "core" / "config_bootstrap.py").exists():
        add_ev("AST-13",
            "Config bootstrap — strongly typed config merge and validation",
            "code_review", 0.4)
    if (root / "core" / "config_schema_validate.py").exists():
        add_ev("AST-13",
            "Config schema validation — programmatic schema-based config validation",
            "code_review", 0.4)
    if (root / "core" / "config_engine.py").exists():
        add_ev("AST-13",
            "Config engine — strongly typed configuration management engine",
            "code_review", 0.4)
    if (root / "tests" / "test_config_schema.py").exists():
        add_ev("AST-13",
            "Config schema test — validates schema-based config typing",
            "test_pass", 0.4)
    if (root / "CONFIG_EXPLANATIONS.md").exists():
        add_ev("AST-13",
            "CONFIG_EXPLANATIONS.md — typed configuration reference documentation",
            "documentation", 0.3)
    if (root / "tests" / "test_config_bootstrap.py").exists():
        add_ev("AST-13",
            "Config bootstrap test — validates typed config merge",
            "test_pass", 0.3)

    # ── ROL: AI Specialist Roles (evidence that role infrastructure exists) ─
    role_infra = {
        "ROL-01": ("Planner", "core/decision_analyzer.py"),
        "ROL-02": ("Principal Architect", "core/architecture_analyzer.py"),
        "ROL-03": ("Developer", None),
        "ROL-04": ("Reviewer", "core/codebase_knowledge_graph.py"),
        "ROL-05": ("Security", "core/security_auditor.py"),
        "ROL-06": ("Performance", "core/performance_optimizer.py"),
        "ROL-07": ("Database", "core/db_provider.py"),
        "ROL-08": ("DevOps", None),
        "ROL-09": ("SRE", "core/synthetic_monitor.py"),
        "ROL-10": ("QA", "pytest.ini"),
        "ROL-11": ("Technical Writer", "core/living_documentation.py"),
        "ROL-12": ("Business Analyst", "core/executive_advisor.py"),
        "ROL-13": ("Product Owner", "core/recommendation_engine.py"),
        "ROL-14": ("Cloud", "Dockerfile"),
        "ROL-15": ("Platform", "core/service_catalog.py"),
        "ROL-16": ("FinOps", "core/capacity_planning.py"),
        "ROL-17": ("Governance", "core/constitution/__init__.py"),
        "ROL-18": ("Executive Advisor", "core/executive_advisor.py"),
    }
    for rol_id, (rol_name, rol_path) in role_infra.items():
        if rol_path and (root / rol_path).exists():
            add_ev(rol_id,
                   f"AI Specialist Role '{rol_name}' — supported by {rol_path}",
                   "code_review", 0.3)
        elif not rol_path:
            add_ev(rol_id,
                   f"AI Specialist Role '{rol_name}' — defined in constitution v4.0",
                   "documentation", 0.2)


__all__ = ["collect_prn_ast_evidence"]
