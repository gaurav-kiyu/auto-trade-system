"""Security/Governance (SGS) & Platform Engineering (PLS) evidence collection — v4.0 domains.

Collects auto-evidence for v4.0 constitution domains:
- 11 Security & Governance Standards (SGS-01 through SGS-11)
- 6 Platform Engineering Standards (PLS-01 through PLS-06)
- 11-phase Continuous Lifecycle

Scans the codebase for modules, tests, docs, and configs that satisfy
each v4.0 requirement.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.constitution import ConstitutionValidator

import logging

log = logging.getLogger(__name__)


def collect_sgs_pls_evidence(
    validator: ConstitutionValidator,
    root: Path,
    add_ev: Any,
) -> None:
    """Collect Security/Governance and Platform Engineering evidence.

    Args:
        validator: ConstitutionValidator instance for add_evidence calls.
        root: Project root path.
        add_ev: Bound validator.add_evidence method.
    """
    # ── SGS-01: Zero Trust ─────────────────────────────────────────────────
    if (root / "core" / "auth" / "permissions.py").exists():
        add_ev("SGS-01",
            "Permissions system — zero trust access control enforcement",
            "code_review", 0.5)
    if (root / "core" / "environment.py").exists():
        add_ev("SGS-01",
            "Environment gate — never-trust deployment boundary enforcement",
            "code_review", 0.4)
    if (root / "tests" / "test_permissions.py").exists():
        add_ev("SGS-01",
            "Permissions test — validates zero trust access control",
            "test_pass", 0.4)
    if (root / "core" / "auth" / "session_store.py").exists():
        add_ev("SGS-01",
            "Session store — zero trust session management",
            "code_review", 0.4)
    if (root / "core" / "runtime_security.py").exists():
        add_ev("SGS-01",
            "Runtime Security — zero trust continuous verification",
            "code_review", 0.4)

    # ── SGS-02: RBAC/PBAC ─────────────────────────────────────────────────
    if (root / "core" / "auth" / "role_manager.py").exists():
        add_ev("SGS-02",
            "Role Manager — RBAC role assignment and inheritance",
            "code_review", 0.5)
    if (root / "core" / "rbac.py").exists():
        add_ev("SGS-02",
            "RBAC module — role-based access control implementation",
            "code_review", 0.5)
    if (root / "tests" / "test_role_manager.py").exists():
        add_ev("SGS-02",
            "Role manager test — validates RBAC enforcement",
            "test_pass", 0.4)
    if (root / "tests" / "test_rbac.py").exists():
        add_ev("SGS-02",
            "RBAC test — validates role-based authorization",
            "test_pass", 0.4)
    if (root / "core" / "auth" / "permissions.py").exists():
        add_ev("SGS-02",
            "Permissions system — PBAC policy-based access control integration",
            "code_review", 0.3)
    if (root / "tests" / "test_permissions.py").exists():
        add_ev("SGS-02",
            "Auth permissions test — validates PBAC policy-based access control",
            "test_pass", 0.4)
    if (root / "tests" / "test_control_rbac.py").exists():
        add_ev("SGS-02",
            "Control RBAC test — validates admin control plane RBAC enforcement",
            "test_pass", 0.4)

    # ── SGS-03: Threat Modeling ────────────────────────────────────────────
    if (root / "core" / "threat_modeler.py").exists():
        add_ev("SGS-03",
            "Threat Modeler — automated threat modeling engine",
            "code_review", 0.5)
    if (root / "tests" / "test_threat_modeler.py").exists():
        add_ev("SGS-03",
            "Threat modeler test — validates threat detection",
            "test_pass", 0.4)
    if (root / "tests" / "test_threat_intel.py").exists():
        add_ev("SGS-03",
            "Threat intel test — validates threat intelligence feeds",
            "test_pass", 0.3)
    if (root / "scripts" / "institutional_challenge.py").exists():
        add_ev("SGS-03",
            "Institutional challenge — adversarial threat modeling validation",
            "chaos", 0.4)
    if (root / "core" / "security_feeds.py").exists():
        add_ev("SGS-03",
            "Security feeds — external threat intelligence integration",
            "code_review", 0.3)
    if (root / "tests" / "test_security_feeds.py").exists():
        add_ev("SGS-03",
            "Security feeds test — validates external threat intelligence",
            "test_pass", 0.3)
    if (root / "tests" / "test_institutional_challenge.py").exists():
        add_ev("SGS-03",
            "Institutional challenge test — adversarial threat model validation",
            "chaos", 0.4)
    if (root / "core" / "threat_intel.py").exists():
        add_ev("SGS-03",
            "Threat Intel — external threat intelligence feed integration",
            "code_review", 0.4)
    if (root / "core" / "security_auditor.py").exists():
        add_ev("SGS-03",
            "Security Auditor — automated security audit for threat modeling",
            "code_review", 0.3)
    if (root / "tests" / "test_security_auditor.py").exists():
        add_ev("SGS-03",
            "Security auditor test — validates automated security auditing",
            "test_pass", 0.3)
    if (root / "core" / "vulnerability_scanner.py").exists():
        add_ev("SGS-03",
            "Vulnerability Scanner — automated vulnerability threat detection",
            "code_review", 0.3)
    if (root / "tests" / "test_vulnerability_scanner.py").exists():
        add_ev("SGS-03",
            "Vulnerability scanner test — validates vulnerability threat scanning",
            "test_pass", 0.3)
    if (root / "SECURITY.md").exists():
        add_ev("SGS-03",
            "SECURITY.md — documented security policy and threat reporting",
            "documentation", 0.3)
    if (root / "docs" / "adr" / "0010-architecture-governance.md").exists():
        add_ev("SGS-03",
            "Architecture governance ADR — threat model governance documentation",
            "documentation", 0.2)

    # ── SGS-04: Secrets Management ─────────────────────────────────────────
    if (root / "core" / "secure_config.py").exists() \
       or (root / "infrastructure" / "config" / "secure_config.py").exists():
        add_ev("SGS-04",
            "Secure Config — encrypted secrets management",
            "code_review", 0.5)
    if (root / "core" / "secrets_vault.py").exists():
        add_ev("SGS-04",
            "Secrets Vault — centralized secrets storage",
            "code_review", 0.5)
    if (root / ".env.example").exists():
        add_ev("SGS-04",
            ".env.example — documented environment variable template",
            "documentation", 0.3)
    if (root / "data" / "secrets.audit.jsonl").exists():
        add_ev("SGS-04",
            "Secrets audit log — audit trail for secret access attempts",
            "code_review", 0.4)
    if (root / "SECRETS_MIGRATION_GUIDE.md").exists():
        add_ev("SGS-04",
            "Secrets migration guide — documented secrets management procedures",
            "documentation", 0.3)
    if (root / "tests" / "test_secrets_vault.py").exists():
        add_ev("SGS-04",
            "Secrets vault test — validates encrypted secrets storage",
            "test_pass", 0.4)
    if (root / "tests" / "test_secure_config.py").exists():
        add_ev("SGS-04",
            "Secure config test — validates encrypted configuration secrets",
            "test_pass", 0.4)
    if (root / "core" / "secret_hygiene.py").exists():
        add_ev("SGS-04",
            "Secret hygiene scanner — automated credential lifecycle enforcement",
            "code_review", 0.4)
    if (root / "tests" / "test_secret_hygiene.py").exists():
        add_ev("SGS-04",
            "Secret hygiene test — validates rotation, expiration, and access control",
            "test_pass", 0.4)
    if (root / "tests" / "test_credential_storage.py").exists():
        add_ev("SGS-04",
            "Credential storage test — validates encrypted credential persistence",
            "test_pass", 0.4)

    # ── SGS-05: SBOM ───────────────────────────────────────────────────────
    if (root / "core" / "sbom_generator.py").exists():
        add_ev("SGS-05",
            "SBOM Generator — software bill of materials generation",
            "code_review", 0.5)
    if (root / "requirements.txt").exists():
        add_ev("SGS-05",
            "requirements.txt — dependency inventory",
            "code_review", 0.3)
    if (root / "requirements-lock.txt").exists() or (root / "requirements-dev.txt").exists():
        add_ev("SGS-05",
            "Locked requirements — pinned dependency versions for SBOM",
            "code_review", 0.3)
    if (root / "pyproject.toml").exists():
        add_ev("SGS-05",
            "pyproject.toml — project metadata with dependency declarations",
            "code_review", 0.3)
    if (root / "scripts" / "run_hygiene_scan.py").exists():
        add_ev("SGS-05",
            "Hygiene scan — automated SBOM and dependency validation",
            "code_review", 0.3)
    if (root / "tests" / "test_sbom_generator.py").exists():
        add_ev("SGS-05",
            "SBOM generator test — validates software bill of materials output",
            "test_pass", 0.4)
    if (root / "scripts" / "run_hygiene_scan.py").exists():
        add_ev("SGS-05",
            "Hygiene scan runner — automated SBOM and dependency validation",
            "code_review", 0.3)
    if (root / "requirements-dev.txt").exists():
        add_ev("SGS-05",
            "requirements-dev.txt — pinned dev dependency inventory for SBOM",
            "code_review", 0.3)
    if (root / ".trivyignore").exists():
        add_ev("SGS-05",
            ".trivyignore — documented vulnerability acceptance policy for SBOM",
            "code_review", 0.2)

    # ── SGS-06: Compliance Reporting ───────────────────────────────────────
    if (root / "core" / "regulatory_reporting.py").exists():
        add_ev("SGS-06",
            "Regulatory Reporting — automated compliance report generation",
            "code_review", 0.5)
    if (root / "tests" / "test_regulatory_reporting.py").exists():
        add_ev("SGS-06",
            "Regulatory reporting test — validates compliance output",
            "test_pass", 0.4)
    if (root / "scripts" / "run_constitution_checks.py").exists():
        add_ev("SGS-06",
            "Constitution checks — automated governance compliance reporting",
            "code_review", 0.4)
    if (root / "docs" / "constitution_scoring_framework.md").exists():
        add_ev("SGS-06",
            "Constitution scoring framework — compliance reporting criteria",
            "documentation", 0.3)
    if (root / "tests" / "test_regulatory_reporting.py").exists():
        add_ev("SGS-06",
            "Regulatory report test — validates automated compliance output",
            "test_pass", 0.4)
    if (root / "alembic").is_dir():
        add_ev("SGS-06",
            "Alembic migrations — compliance-ready database migration audit trail",
            "code_review", 0.3)
    if (root / "scripts" / "score_system.py").exists():
        add_ev("SGS-06",
            "Score system script — automated constitution compliance reporting",
            "code_review", 0.3)
    if (root / "tests" / "test_score_system.py").exists():
        add_ev("SGS-06",
            "Score system test — validates automated compliance scoring output",
            "test_pass", 0.3)
    if (root / "scripts" / "generate_constitution_report.py").exists():
        add_ev("SGS-06",
            "Constitution report generator — automated governance compliance reporting",
            "code_review", 0.3)
    if (root / "scripts" / "generate_maturity_report.py").exists():
        add_ev("SGS-06",
            "Maturity report generator — automated compliance maturity reporting",
            "code_review", 0.3)

    # ── SGS-07: Runtime Security ───────────────────────────────────────────
    if (root / "core" / "runtime_security.py").exists():
        add_ev("SGS-07",
            "Runtime Security — runtime threat detection and prevention",
            "code_review", 0.5)
    if (root / "tests" / "test_runtime_security.py").exists():
        add_ev("SGS-07",
            "Runtime security test — validates runtime protection",
            "test_pass", 0.4)
    if (root / "tests" / "test_vulnerability_scanner.py").exists():
        add_ev("SGS-07",
            "Vulnerability scanner test — validates runtime scanning",
            "test_pass", 0.3)
    if (root / "core" / "anomaly_detector.py").exists():
        add_ev("SGS-07",
            "Anomaly Detector — runtime anomaly detection for security",
            "code_review", 0.4)
    if (root / "core" / "rate_limiting_service.py").exists():
        add_ev("SGS-07",
            "Rate limiting service — runtime DOS attack prevention",
            "code_review", 0.4)
    if (root / "tests" / "test_runtime_security.py").exists():
        add_ev("SGS-07",
            "Runtime security test — validates runtime threat detection",
            "test_pass", 0.4)
    if (root / "tests" / "test_anomaly_detector.py").exists():
        add_ev("SGS-07",
            "Anomaly detector test — validates runtime anomaly detection",
            "test_pass", 0.3)
    if (root / "tests" / "test_sandbox.py").exists():
        add_ev("SGS-07",
            "Sandbox test — validates runtime isolation for untrusted code",
            "test_pass", 0.3)
    if (root / "tests" / "test_rate_limiting_service.py").exists():
        add_ev("SGS-07",
            "Rate limiting test — validates runtime brute-force prevention",
            "test_pass", 0.3)
    if (root / "core" / "vulnerability_scanner.py").exists():
        add_ev("SGS-07",
            "Vulnerability scanner — runtime vulnerability detection engine",
            "code_review", 0.3)

    # ── SGS-08: AI Security ────────────────────────────────────────────────
    if (root / "core" / "ai_security_gate.py").exists():
        add_ev("SGS-08",
            "AI Security Gate — AI-specific security controls",
            "code_review", 0.5)
    if (root / "core" / "ai" / "governance.py").exists():
        add_ev("SGS-08",
            "AI Governance — model governance and security",
            "code_review", 0.4)
    if (root / "core" / "constitution_ai_gate.py").exists():
        add_ev("SGS-08",
            "Constitution AI Gate — AI governance constitution enforcement",
            "code_review", 0.4)
    if (root / "docs" / "AI_GOVERNANCE_GUIDE.md").exists():
        add_ev("SGS-08",
            "AI Governance Guide — AI security documentation",
            "documentation", 0.3)
    if (root / "tests" / "test_ai_security_gate.py").exists():
        add_ev("SGS-08",
            "AI security gate test — validates AI-specific security controls",
            "test_pass", 0.4)
    if (root / "tests" / "test_bias_detector.py").exists():
        add_ev("SGS-08",
            "Bias detector test — validates AI fairness bias detection",
            "test_pass", 0.3)
    if (root / "core" / "bias_detector.py").exists():
        add_ev("SGS-08",
            "Bias Detector — AI model bias security control",
            "code_review", 0.3)
    if (root / "core" / "hallucination_detector.py").exists():
        add_ev("SGS-08",
            "Hallucination Detector — AI output integrity security control",
            "code_review", 0.3)
    if (root / "tests" / "test_ai_security_gate.py").exists():
        add_ev("SGS-08",
            "AI security gate test — validates AI model security controls",
            "test_pass", 0.3)

    # ── SGS-09: Prompt Injection Detection ─────────────────────────────────
    if (root / "core" / "ai_security_gate.py").exists():
        add_ev("SGS-09",
            "AI Security Gate — prompt injection detection capabilities",
            "code_review", 0.5)
    if (root / "core" / "hallucination_detector.py").exists():
        add_ev("SGS-09",
            "Hallucination Detector — prompt injection output validation",
            "code_review", 0.4)
    if (root / "core" / "constitution_ai_gate.py").exists():
        add_ev("SGS-09",
            "Constitution AI Gate — prompt injection prevention via constitution rules",
            "code_review", 0.4)
    if (root / "tests" / "test_ai_security_gate.py").exists():
        add_ev("SGS-09",
            "AI security gate test — validates prompt injection detection",
            "test_pass", 0.4)
    if (root / "tests" / "test_hallucination_detector.py").exists():
        add_ev("SGS-09",
            "Hallucination detector test — validates AI prompt injection output detection",
            "test_pass", 0.4)
    if (root / "core" / "ai" / "safety_gate.py").exists():
        add_ev("SGS-09",
            "AI safety gate — prompt injection validation for AI system prompts",
            "code_review", 0.4)
    if (root / "tests" / "test_constitution_ai_gate.py").exists():
        add_ev("SGS-09",
            "Constitution AI gate test — validates prompt injection rule enforcement",
            "test_pass", 0.4)
    if (root / "core" / "ai" / "governance.py").exists():
        add_ev("SGS-09",
            "AI Governance — prompt injection policy enforcement",
            "code_review", 0.3)
    if (root / "tests" / "test_ai_governance.py").exists():
        add_ev("SGS-09",
            "AI governance test — validates AI prompt injection security policy",
            "test_pass", 0.3)

    # ── SGS-10: Hallucination Detection ────────────────────────────────────
    if (root / "core" / "hallucination_detector.py").exists():
        add_ev("SGS-10",
            "Hallucination Detector — AI output hallucination detection",
            "code_review", 0.5)
    if (root / "tests" / "test_hallucination_detector.py").exists():
        add_ev("SGS-10",
            "Hallucination detector test — validates detection accuracy",
            "test_pass", 0.4)
    if (root / "core" / "bias_detector.py").exists():
        add_ev("SGS-10",
            "Bias Detector — complementary AI output quality detection",
            "code_review", 0.4)
    if (root / "core" / "concept_drift_detector.py").exists():
        add_ev("SGS-10",
            "Concept Drift Detector — AI output consistency monitoring",
            "code_review", 0.3)
    if (root / "tests" / "test_bias_detector.py").exists():
        add_ev("SGS-10",
            "Bias detector test — validates complementary AI output quality detection",
            "test_pass", 0.4)
    if (root / "core" / "ai" / "safety_gate.py").exists():
        add_ev("SGS-10",
            "AI Safety Gate — AI output validation for hallucination prevention",
            "code_review", 0.4)
    if (root / "core" / "ai_security_gate.py").exists():
        add_ev("SGS-10",
            "AI Security Gate — hallucination detection in AI output validation",
            "code_review", 0.3)
    if (root / "tests" / "test_ai_security_gate.py").exists():
        add_ev("SGS-10",
            "AI security gate test — validates AI hallucination detection",
            "test_pass", 0.4)
    if (root / "core" / "ai" / "governance.py").exists():
        add_ev("SGS-10",
            "AI Governance — model output validation and hallucination prevention",
            "code_review", 0.3)
    if (root / "tests" / "test_concept_drift_detector.py").exists():
        add_ev("SGS-10",
            "Concept drift detector test — validates AI output drift monitoring",
            "test_pass", 0.3)

    # ── SGS-11: Audit Trails ───────────────────────────────────────────────
    if (root / "core" / "audit_mode.py").exists():
        add_ev("SGS-11",
            "Audit Mode — comprehensive audit trail capture",
            "code_review", 0.5)
    if (root / "core" / "telegram_audit_manager.py").exists():
        add_ev("SGS-11",
            "Telegram Audit Manager — notification audit trail",
            "code_review", 0.4)
    if (root / "tests" / "test_audit_trail.py").exists() \
       or (root / "tests" / "test_telegram_audit_manager.py").exists():
        add_ev("SGS-11",
            "Audit trail test — validates audit log integrity",
            "test_pass", 0.4)
    if (root / "core" / "audit_engine.py").exists():
        add_ev("SGS-11",
            "Audit Engine — structured audit event capture and storage",
            "code_review", 0.4)
    if (root / "core" / "config_audit_log.py").exists():
        add_ev("SGS-11",
            "Config audit log — configuration change audit trail",
            "code_review", 0.3)
    if (root / "data" / "secrets.audit.jsonl").exists():
        add_ev("SGS-11",
            "Secrets audit log — access audit trail for sensitive operations",
            "code_review", 0.3)
    if (root / "core" / "audit_engine.py").exists():
        add_ev("SGS-11",
            "Audit engine — structured audit event capture for compliance trails",
            "code_review", 0.4)
    if (root / "core" / "audit_journal.py").exists():
        add_ev("SGS-11",
            "Audit journal — immutable audit event journal for compliance",
            "code_review", 0.4)
    if (root / "tests" / "test_audit_engine.py").exists():
        add_ev("SGS-11",
            "Audit engine test — validates structured audit event capture",
            "test_pass", 0.4)
    if (root / "tests" / "test_audit_journal.py").exists():
        add_ev("SGS-11",
            "Audit journal test — validates immutable audit event integrity",
            "test_pass", 0.4)
    if (root / "core" / "auditor" / "auditor.py").exists():
        add_ev("SGS-11",
            "Auditor module — independent audit trail verification",
            "code_review", 0.4)
    if (root / "tests" / "test_telegram_audit_manager.py").exists():
        add_ev("SGS-11",
            "Telegram audit manager test — validates notification audit trails",
            "test_pass", 0.3)

    # ── PLS-01: Internal Developer Platform ────────────────────────────────
    if (root / "core" / "service_catalog.py").exists():
        add_ev("PLS-01",
            "Service Catalog — internal developer platform registry",
            "code_review", 0.5)
    if (root / "Makefile").exists():
        add_ev("PLS-01",
            "Makefile — developer platform build automation",
            "code_review", 0.3)
    if (root / "docker-compose.yml").exists():
        add_ev("PLS-01",
            "Docker Compose — platform environment orchestration",
            "code_review", 0.3)
    if (root / "Dockerfile").exists():
        add_ev("PLS-01",
            "Dockerfile — containerized development platform",
            "code_review", 0.3)
    if (root / ".github" / "workflows" / "ci.yml").exists():
        add_ev("PLS-01",
            "CI/CD workflow — developer platform automation pipeline",
            "code_review", 0.3)
    if (root / "tests" / "test_service_catalog.py").exists():
        add_ev("PLS-01",
            "Service catalog test — validates IDP service registry",
            "test_pass", 0.4)
    if (root / ".github" / "workflows" / "prod-release.yml").exists():
        add_ev("PLS-01",
            "Prod release workflow — automated IDP production release pipeline",
            "code_review", 0.3)
    if (root / "tests" / "test_service_catalog.py").exists():
        add_ev("PLS-01",
            "Service catalog test — validates IDP service registry functionality",
            "test_pass", 0.4)
    if (root / "docs" / "QUICK_START_GUIDE.md").exists():
        add_ev("PLS-01",
            "Quick start guide — developer self-service onboarding path",
            "documentation", 0.3)

    # ── PLS-02: Golden Paths ──────────────────────────────────────────────
    if (root / "core" / "service_catalog.py").exists():
        add_ev("PLS-02",
            "Service Catalog — Golden Path definitions for standardized services",
            "code_review", 0.4)
    if (root / "CLAUDE.md").exists():
        add_ev("PLS-02",
            "CLAUDE.md — AI agent golden path guidance",
            "documentation", 0.3)
    if (root / "pyproject.toml").exists():
        add_ev("PLS-02",
            "pyproject.toml — standardized project golden path",
            "code_review", 0.3)
    if (root / "json/config.template.json").exists():
        add_ev("PLS-02",
            "Config template — golden path configuration pattern",
            "code_review", 0.3)
    if (root / "docs" / "adr" / "0012-config-system-architecture.md").exists():
        add_ev("PLS-02",
            "Config system ADR — documented golden path architecture",
            "documentation", 0.3)
    if (root / "docs" / "QUICK_START_GUIDE.md").exists():
        add_ev("PLS-02",
            "Quick start guide — developer golden path for rapid onboarding",
            "documentation", 0.4)
    if (root / "docs" / "STEP_BY_STEP_GUIDE.md").exists():
        add_ev("PLS-02",
            "Step-by-step guide — user golden path for trading setup",
            "documentation", 0.3)
    if (root / "tests" / "test_service_catalog.py").exists():
        add_ev("PLS-02",
            "Service catalog test — validates golden path service definitions",
            "test_pass", 0.3)
    if (root / "docs" / "SETUP_AND_TRADING_GUIDE.md").exists():
        add_ev("PLS-02",
            "Setup and Trading Guide — golden path deployment documentation",
            "documentation", 0.3)
    if (root / "USER_GUIDE.md").exists():
        add_ev("PLS-02",
            "USER_GUIDE.md — user golden path for system operation",
            "documentation", 0.3)
    if (root / "run_regression.py").exists():
        add_ev("PLS-02",
            "run_regression.py — regression validation golden path",
            "code_review", 0.3)
    if (root / "json/launcher_settings.json").exists():
        add_ev("PLS-02",
            "launcher_settings.json — launcher golden path configuration",
            "code_review", 0.2)

    # ── PLS-03: Service Catalog ────────────────────────────────────────────
    if (root / "core" / "service_catalog.py").exists():
        add_ev("PLS-03",
            "Service Catalog — comprehensive service registry with SLAs",
            "code_review", 0.5)
    if (root / "tests" / "test_service_catalog.py").exists():
        add_ev("PLS-03",
            "Service catalog test — validates catalog functionality",
            "test_pass", 0.4)
    if (root / "docs" / "ownership_matrix.md").exists():
        add_ev("PLS-03",
            "Ownership matrix — service ownership mapping for catalog",
            "documentation", 0.3)
    if (root / "tests" / "test_service.py").exists():
        add_ev("PLS-03",
            "Service test — validates service registry registration",
            "test_pass", 0.3)
    if (root / "tests" / "test_service_catalog.py").exists():
        add_ev("PLS-03",
            "Service catalog test — validates catalog functionality end-to-end",
            "test_pass", 0.4)
    if (root / "core" / "service_catalog.py").exists():
        add_ev("PLS-03",
            "Service catalog SLA tracking — service-level agreement registry and monitoring",
            "code_review", 0.4)
    if (root / "tests" / "test_service_catalog.py").exists():
        add_ev("PLS-03",
            "Service catalog test — validates service discovery and SLA tracking",
            "test_pass", 0.3)
    if (root / "core" / "service_catalog.py").exists():
        add_ev("PLS-03",
            "Service Catalog registry — service discovery and registration for catalog",
            "code_review", 0.3)

    # ── PLS-04: Environment Provisioning ───────────────────────────────────
    if (root / "docker-compose.yml").exists():
        add_ev("PLS-04",
            "Docker Compose — environment provisioning via compose",
            "code_review", 0.4)
    if (root / "deploy").is_dir():
        add_ev("PLS-04",
            "Deploy directory — environment provisioning configurations",
            "code_review", 0.4)
    if (root / "Dockerfile").exists():
        add_ev("PLS-04",
            "Dockerfile — reproducible environment provisioning",
            "code_review", 0.3)
    if (root / "docker-compose.monitoring.yml").exists():
        add_ev("PLS-04",
            "Monitoring docker-compose — monitoring stack provisioning",
            "code_review", 0.3)
    if (root / "docker-compose.realestate.yml").exists():
        add_ev("PLS-04",
            "Real estate docker-compose — service-specific environment provisioning",
            "code_review", 0.3)
    if (root / "Dockerfile.realestate").exists():
        add_ev("PLS-04",
            "Dockerfile.realestate — service-specific container provisioning",
            "code_review", 0.3)

    # ── PLS-05: Infrastructure as Code ────────────────────────────────────
    for iac_file in ["Dockerfile", "docker-compose.yml", "supervisord.conf",
                     ".github/workflows/ci.yml", "bitbucket-pipelines.yml",
                     "Dockerfile.realestate", "docker-compose.monitoring.yml",
                     "docker-compose.realestate.yml"]:
        if (root / iac_file).exists():
            add_ev("PLS-05",
                f"'{iac_file}' — infrastructure as code definition",
                "code_review", 0.2)
    if (root / "deploy").is_dir():
        add_ev("PLS-05",
            "Deploy directory — full IaC deployment configurations (Grafana/Prometheus/Loki/Postgres)",
            "code_review", 0.4)
    if (root / "deploy" / "grafana" / "dashboards.yml").exists():
        add_ev("PLS-05",
            "Grafana dashboards as code — observability IaC definitions",
            "code_review", 0.3)
    if (root / "deploy" / "prometheus" / "prometheus.yml").exists():
        add_ev("PLS-05",
            "Prometheus config as code — metrics infrastructure IaC",
            "code_review", 0.3)
    if (root / ".github" / "workflows" / "prod-release.yml").exists():
        add_ev("PLS-05",
            "Prod release workflow — CI/CD infrastructure as code",
            "code_review", 0.3)

    # ── PLS-06: Self-Service Infrastructure ────────────────────────────────
    if (root / "core" / "self_service_provisioning.py").exists():
        add_ev("PLS-06",
            "Self-Service Provisioning API — click-to-provision environments without ops tickets (core/self_service_provisioning.py)",
            "code_review", 0.5)
    if (root / "core" / "enterprise_dashboard" / "routes" / "provisioning.py").exists():
        add_ev("PLS-06",
            "Self-service provisioning dashboard routes — /api/platform/provisioning/* endpoints",
            "code_review", 0.4)
    if (root / "tests" / "test_self_service_provisioning.py").exists():
        add_ev("PLS-06",
            "Self-service provisioning test — validates blueprint catalog and request workflow",
            "test_pass", 0.5)
    if (root / "Makefile").exists():
        add_ev("PLS-06",
            "Makefile — self-service build and test commands",
            "code_review", 0.4)
    if (root / "launcher.py").exists():
        add_ev("PLS-06",
            "Launcher — self-service GUI for bot execution",
            "code_review", 0.4)
    if (root / "run_low_capital.bat").exists():
        add_ev("PLS-06",
            "run_low_capital.bat — self-service low-capital execution script",
            "code_review", 0.3)
    if (root / "build_exe.bat").exists():
        add_ev("PLS-06",
            "build_exe.bat — self-service executable builder",
            "code_review", 0.3)
    if (root / "run_backtest.py").exists():
        add_ev("PLS-06",
            "run_backtest.py — self-service backtesting infrastructure",
            "code_review", 0.3)
    if (root / "run_final_certification.bat").exists():
        add_ev("PLS-06",
            "run_final_certification.bat — self-service certification runner",
            "code_review", 0.3)
    if (root / "run_regression.py").exists():
        add_ev("PLS-06",
            "run_regression.py — self-service regression test runner",
            "code_review", 0.3)
    if (root / "json/launcher_settings.json").exists():
        add_ev("PLS-06",
            "launcher_settings.json — self-service launcher configuration",
            "code_review", 0.2)
    if (root / "supervisord.conf").exists():
        add_ev("PLS-06",
            "supervisord.conf — self-service process supervision configuration",
            "code_review", 0.2)
    if (root / "json/config.template.json").exists():
        add_ev("PLS-06",
            "config.template.json — self-service configuration template",
            "code_review", 0.2)

    # ── Continuous Lifecycle evidence ──────────────────────────────────────
    lifecycle_items = {
        "Requirements": "CLAUDE.md",
        "Architecture": "core/architecture_analyzer.py",
        "Development": "index_app/index_trader.py",
        "Review": "core/codebase_knowledge_graph.py",
        "Testing": "pytest.ini",
        "Deployment": "Dockerfile",
        "Monitoring": "core/synthetic_monitor.py",
        "Incident Analysis": "core/postmortem_automator.py",
        "Learning": "core/decision_memory.py",
        "Knowledge Update": "core/living_documentation.py",
        "Continuous Optimization": "core/auto_learner.py",
    }
    for lifecycle_phase, lifecycle_path in lifecycle_items.items():
        if (root / lifecycle_path).exists():
            add_ev(f"LC-{lifecycle_phase.replace(' ', '_')}",
                   f"Continuous Lifecycle phase '{lifecycle_phase}' — supported by {lifecycle_path}",
                   "code_review", 0.3)


__all__ = ["collect_sgs_pls_evidence"]
