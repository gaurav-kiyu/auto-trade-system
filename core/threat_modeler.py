"""Threat Modeler — Automated STRIDE Threat Modeling (Constitution v4.0).

Performs automated security threat analysis using STRIDE methodology:
- Spoofing: Identity/authentication threats
- Tampering: Data integrity threats
- Repudiation: Non-repudiation threats
- Information Disclosure: Confidentiality threats
- Denial of Service: Availability threats
- Elevation of Privilege: Authorization threats

Analyzes codebase modules to identify threats, assign risk scores,
and map to MITRE ATT&CK techniques where applicable.

Integrates with:
- SecurityAuditor for vulnerability correlation
- DependencyAnalyzer for attack surface mapping
- BIDashboard for security posture trending

Usage:
    from core.threat_modeler import get_threat_modeler

    modeler = get_threat_modeler()
    report = modeler.analyze_all_modules()
    print(report.summary_text())
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent

EXCLUDED_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv",
                 ".egg-info", "dist", "build", "reports", "data", ".benchmarks"}

# STRIDE categories with descriptions
STRIDE_CATEGORIES: dict[str, dict[str, Any]] = {
    "Spoofing": {
        "description": "Impersonating a user, system, or component",
        "mitre_techniques": ["T1078", "T1550", "T1651"],
        "risk_multiplier": 1.0,
    },
    "Tampering": {
        "description": "Unauthorized modification of data or code",
        "mitre_techniques": ["T1565", "T1499", "T1574"],
        "risk_multiplier": 1.2,
    },
    "Repudiation": {
        "description": "Denying an action without proof",
        "mitre_techniques": ["T1546", "T1072"],
        "risk_multiplier": 0.8,
    },
    "Information Disclosure": {
        "description": "Exposure of sensitive data to unauthorized parties",
        "mitre_techniques": ["T1040", "T1530", "T1213"],
        "risk_multiplier": 1.3,
    },
    "Denial of Service": {
        "description": "Disrupting service availability",
        "mitre_techniques": ["T1499", "T1498", "T0814"],
        "risk_multiplier": 0.9,
    },
    "Elevation of Privilege": {
        "description": "Gaining unauthorized access or permissions",
        "mitre_techniques": ["T1068", "T1548", "T1611"],
        "risk_multiplier": 1.4,
    },
}

# Module type → threat keyword mappings
MODULE_THREAT_PATTERNS: dict[str, list[tuple[str, str, float]]] = {
    "auth": [
        ("Spoofing", "Authentication logic — verify session handling, token validation, credential storage", 0.9),
        ("Elevation of Privilege", "Authorization boundaries — check role escalation paths", 0.85),
        ("Information Disclosure", "Credential exposure through logging or error messages", 0.7),
    ],
    "broker": [
        ("Spoofing", "Broker API communication — verify TLS/mTLS, API key handling", 0.85),
        ("Tampering", "Order data integrity — validate order parameters before submission", 0.8),
        ("Denial of Service", "Broker API rate limiting and connection reliability", 0.75),
    ],
    "risk": [
        ("Tampering", "Risk limit data integrity — corruption could disable protections", 0.95),
        ("Denial of Service", "Risk calculation blocking in high-volume conditions", 0.6),
    ],
    "execution": [
        ("Tampering", "Execution state integrity — ensure exactly-once semantics", 0.9),
        ("Repudiation", "Execution audit trail — non-repudiation of order placement", 0.8),
    ],
    "database": [
        ("Tampering", "SQL injection via dynamically constructed queries", 0.85),
        ("Information Disclosure", "Database connection strings and credentials in source", 0.8),
        ("Denial of Service", "Connection pool exhaustion under load", 0.7),
    ],
    "api": [
        ("Spoofing", "API authentication bypass via missing or weak auth checks", 0.85),
        ("Information Disclosure", "Sensitive data in API responses (PII, tokens, keys)", 0.8),
        ("Denial of Service", "API rate limiting gaps causing resource exhaustion", 0.75),
    ],
    "config": [
        ("Tampering", "Configuration file integrity — unauthorized modification", 0.8),
        ("Information Disclosure", "Secrets/keys stored in readable config files", 0.85),
    ],
    "telegram": [
        ("Spoofing", "Telegram bot token theft or misuse", 0.85),
        ("Information Disclosure", "Trade/P&L data leaked through notification channel", 0.7),
        ("Tampering", "Command injection via Telegram message processing", 0.8),
    ],
    "general": [
        ("Information Disclosure", "Hardcoded secrets detected in source code", 0.7),
        ("Tampering", "Pickle/unsafe deserialization in module", 0.75),
        ("Elevation of Privilege", "eval/exec usage allowing arbitrary code execution", 0.9),
    ],
}


# ── Data Models ────────────────────────────────────────────────────────────


@dataclass
class ThreatFinding:
    """A single identified threat."""

    stride_category: str = ""  # Spoofing, Tampering, Repudiation, Information Disclosure, DoS, Elevation of Privilege
    description: str = ""
    risk_score: float = 0.0  # 0.0 to 1.0
    mitre_techniques: list[str] = field(default_factory=list)
    affected_component: str = ""
    recommendation: str = ""
    severity: str = "MEDIUM"

    def to_dict(self) -> dict[str, Any]:
        return {
            "stride_category": self.stride_category,
            "description": self.description,
            "risk_score": round(self.risk_score, 3),
            "mitre_techniques": self.mitre_techniques,
            "affected_component": self.affected_component,
            "recommendation": self.recommendation,
            "severity": self.severity,
        }


@dataclass
class ModuleThreatProfile:
    """Threat assessment for a single module."""

    module_path: str = ""
    module_type: str = "general"
    total_threats: int = 0
    threats: list[ThreatFinding] = field(default_factory=list)
    max_risk_score: float = 0.0
    avg_risk_score: float = 0.0
    covered_categories: list[str] = field(default_factory=list)
    missing_categories: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "module_path": self.module_path,
            "module_type": self.module_type,
            "total_threats": self.total_threats,
            "threats": [t.to_dict() for t in self.threats],
            "max_risk_score": round(self.max_risk_score, 3),
            "avg_risk_score": round(self.avg_risk_score, 3),
            "covered_categories": self.covered_categories,
            "missing_categories": self.missing_categories,
        }


@dataclass
class ThreatModelReport:
    """Complete threat modeling report."""

    timestamp: float = 0.0
    total_modules_analyzed: int = 0
    total_threats_found: int = 0
    modules: list[ModuleThreatProfile] = field(default_factory=list)
    top_threats: list[ThreatFinding] = field(default_factory=list)
    stride_distribution: dict[str, int] = field(default_factory=dict)
    risk_level: str = "LOW"
    overall_risk_score: float = 0.0
    recommendations: list[str] = field(default_factory=list)
    mitre_mapping: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "date": datetime.fromtimestamp(self.timestamp).isoformat() if self.timestamp else "",
            "total_modules_analyzed": self.total_modules_analyzed,
            "total_threats_found": self.total_threats_found,
            "modules": [m.to_dict() for m in self.modules],
            "top_threats": [t.to_dict() for t in self.top_threats[:20]],
            "stride_distribution": self.stride_distribution,
            "risk_level": self.risk_level,
            "overall_risk_score": round(self.overall_risk_score, 3),
            "recommendations": self.recommendations,
            "mitre_mapping": self.mitre_mapping,
        }

    def summary_text(self) -> str:
        lines = [
            "═" * 60,
            "  THREAT MODEL REPORT (STRIDE)",
            "═" * 60,
            f"  Modules Analyzed: {self.total_modules_analyzed}",
            f"  Threats Found: {self.total_threats_found}",
            f"  Risk Level: {self.risk_level}",
            f"  Overall Risk Score: {self.overall_risk_score:.3f}",
            "",
        ]
        if self.stride_distribution:
            lines.append("  STRIDE Distribution:")
            for cat, count in sorted(self.stride_distribution.items(), key=lambda x: x[1], reverse=True):
                lines.append(f"    {cat}: {count}")
        if self.top_threats:
            lines.append("\n  Top Threats:")
            for t in self.top_threats[:5]:
                lines.append(f"    ⚠ [{t.severity}] {t.stride_category}: {t.description[:80]}")
                lines.append(f"       → {t.affected_component}")
        if self.recommendations:
            lines.append("\n  Recommendations:")
            for r in self.recommendations:
                lines.append(f"    → {r}")
        lines.append("═" * 60)
        return "\n".join(lines)


# ── Threat Modeler ────────────────────────────────────────────────────────


class ThreatModeler:
    """Automated STRIDE Threat Modeling engine.

    Analyzes codebase modules to identify potential security threats
    using the STRIDE methodology, assigns risk scores, and maps
    findings to MITRE ATT&CK techniques.

    Thread-safe.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._history: list[ThreatModelReport] = []
        self._last_report: ThreatModelReport | None = None
        self._total_analyses = 0
        self._persist_path = Path("json/threat_model_history.json")
        self._load_history()

    @property
    def last_report(self) -> ThreatModelReport | None:
        return self._last_report

    # ── Public API ────────────────────────────────────────────────────────

    def analyze_all_modules(self) -> ThreatModelReport:
        """Analyze all modules in the codebase for STRIDE threats.

        Scans core/, index_app/, scripts/, infrastructure/ directories
        and builds threat profiles per module.

        Returns:
            ThreatModelReport with findings and recommendations.
        """
        report = ThreatModelReport(timestamp=time.time())
        src_dirs = [ROOT / "core", ROOT / "index_app"]
        module_profiles: list[ModuleThreatProfile] = []

        for src_dir in src_dirs:
            if not src_dir.is_dir():
                continue
            for file_path in sorted(src_dir.rglob("*.py")):
                if "__pycache__" in str(file_path) or any(
                    ex in str(file_path) for ex in EXCLUDED_DIRS
                ):
                    continue
                rel_path = str(file_path.relative_to(ROOT))
                profile = self._analyze_module(str(file_path), rel_path)
                module_profiles.append(profile)

        report.modules = module_profiles
        report.total_modules_analyzed = len(module_profiles)
        report.total_threats_found = sum(m.total_threats for m in module_profiles)

        # Collect all threats
        all_threats: list[ThreatFinding] = []
        for m in module_profiles:
            all_threats.extend(m.threats)

        # Top threats (sorted by risk score)
        all_threats.sort(key=lambda t: t.risk_score, reverse=True)
        report.top_threats = all_threats[:20]

        # STRIDE distribution
        stride_dist: dict[str, int] = {}
        for t in all_threats:
            stride_dist[t.stride_category] = stride_dist.get(t.stride_category, 0) + 1
        report.stride_distribution = stride_dist

        # MITRE mapping
        mitre_map: dict[str, list[str]] = {}
        for t in all_threats:
            for technique in t.mitre_techniques:
                if technique not in mitre_map:
                    mitre_map[technique] = []
                mitre_map[technique].append(t.affected_component)
        report.mitre_mapping = mitre_map

        # Overall risk score (weighted by STRIDE risk multipliers)
        total_weighted = 0.0
        total_weight = 0.0
        for t in all_threats:
            multiplier = STRIDE_CATEGORIES.get(t.stride_category, {}).get("risk_multiplier", 1.0)
            total_weighted += t.risk_score * multiplier
            total_weight += multiplier
        report.overall_risk_score = total_weighted / max(total_weight, 1.0)

        # Risk level
        report.risk_level = self._risk_level(report.overall_risk_score)

        # Recommendations
        report.recommendations = self._generate_recommendations(report)

        with self._lock:
            self._history.append(report)
            self._last_report = report
            self._total_analyses += 1
            self._persist()

        return report

    def analyze_single_module(self, module_path: str) -> ModuleThreatProfile | None:
        """Analyze a single module for threats.

        Args:
            module_path: Relative path to the module (e.g., 'core/risk_service.py').

        Returns:
            ModuleThreatProfile or None if file not found.
        """
        abs_path = ROOT / module_path
        if not abs_path.is_file():
            return None
        return self._analyze_module(str(abs_path), module_path)

    def get_stats(self) -> dict[str, Any]:
        """Get threat modeler statistics."""
        with self._lock:
            last = self._last_report
            return {
                "total_analyses": self._total_analyses,
                "history_length": len(self._history),
                "last_analysis_ts": last.timestamp if last else 0,
                "last_threats_found": last.total_threats_found if last else 0,
                "last_risk_level": last.risk_level if last else "UNKNOWN",
                "last_risk_score": round(last.overall_risk_score, 3) if last else 0.0,
            }

    # ── Module Analysis ──────────────────────────────────────────────────

    def _analyze_module(self, abs_path: str, rel_path: str) -> ModuleThreatProfile:
        """Analyze a single module file for STRIDE threats."""
        try:
            content = Path(abs_path).read_text(encoding="utf-8", errors="ignore")
        except (OSError, UnicodeDecodeError):
            return ModuleThreatProfile(module_path=rel_path)

        # Determine module type from path
        module_type = self._classify_module(rel_path)
        profile = ModuleThreatProfile(module_path=rel_path, module_type=module_type)
        threats: list[ThreatFinding] = []

        # 1. Apply type-specific threat patterns
        type_patterns = MODULE_THREAT_PATTERNS.get(module_type, [])
        type_patterns.extend(MODULE_THREAT_PATTERNS.get("general", []))

        for stride_cat, description, base_risk in type_patterns:
            # Check if the module actually contains relevant code
            relevance_keywords = self._get_relevance_keywords(stride_cat, module_type)
            is_relevant = any(kw.lower() in content.lower() for kw in relevance_keywords)

            risk_score = base_risk
            if not is_relevant:
                risk_score *= 0.5  # Less relevant = lower risk

            threat = ThreatFinding(
                stride_category=stride_cat,
                description=description,
                risk_score=risk_score,
                mitre_techniques=STRIDE_CATEGORIES.get(stride_cat, {}).get("mitre_techniques", []),
                affected_component=rel_path,
                recommendation=self._generate_threat_recommendation(stride_cat, module_type),
                severity=self._risk_level(risk_score),
            )
            threats.append(threat)

        # 2. Scan for hardcoded secrets (Information Disclosure)
        secret_patterns = [
            r"(?i)password\s*[:=]\s*['\"][^'\"]{6,}['\"]",
            r"(?i)(api[_-]?key|apikey)\s*[:=]\s*['\"][A-Za-z0-9_\-]{16,}['\"]",
            r"-----BEGIN\s+(RSA |EC |DSA )?PRIVATE KEY-----",
        ]
        for pattern in secret_patterns:
            if re.search(pattern, content):
                threats.append(ThreatFinding(
                    stride_category="Information Disclosure",
                    description="Hardcoded secret/credential detected in source",
                    risk_score=0.85,
                    mitre_techniques=["T1552", "T1081"],
                    affected_component=rel_path,
                    recommendation="Move secrets to environment variables or a vault service",
                    severity="HIGH",
                ))

        # 3. Scan for dangerous APIs (Elevation of Privilege + Tampering)
        if re.search(r"eval\(|exec\(|compile\(", content):
            threats.append(ThreatFinding(
                stride_category="Elevation of Privilege",
                description="Arbitrary code execution via eval/exec — allows privilege escalation",
                risk_score=0.9,
                mitre_techniques=["T1068"],
                affected_component=rel_path,
                recommendation="Replace eval/exec with safer alternatives (ast.literal_eval, restricted Python)",
                severity="CRITICAL",
            ))

        if "subprocess" in content and "shell=True" in content:
            threats.append(ThreatFinding(
                stride_category="Elevation of Privilege",
                description="Shell injection risk via subprocess with shell=True",
                risk_score=0.85,
                mitre_techniques=["T1059"],
                affected_component=rel_path,
                recommendation="Use subprocess with explicit argument lists instead of shell=True",
                severity="HIGH",
            ))

        if "pickle.load" in content or "pickle.loads" in content:
            threats.append(ThreatFinding(
                stride_category="Tampering",
                description="Unsafe deserialization via pickle — code execution risk",
                risk_score=0.8,
                mitre_techniques=["T1055"],
                affected_component=rel_path,
                recommendation="Replace pickle with safe serialization (JSON, msgpack, or verify authenticity)",
                severity="HIGH",
            ))

        # 4. Deduplicate threats by category
        seen_categories: set[str] = set()
        unique_threats: list[ThreatFinding] = []
        for t in sorted(threats, key=lambda x: x.risk_score, reverse=True):
            if t.stride_category not in seen_categories:
                unique_threats.append(t)
                seen_categories.add(t.stride_category)

        profile.threats = unique_threats
        profile.total_threats = len(unique_threats)

        # Stats
        if unique_threats:
            profile.max_risk_score = max(t.risk_score for t in unique_threats)
            profile.avg_risk_score = sum(t.risk_score for t in unique_threats) / len(unique_threats)

        # Covered/missing STRIDE categories
        for cat in STRIDE_CATEGORIES:
            if any(t.stride_category == cat for t in unique_threats):
                profile.covered_categories.append(cat)
            else:
                profile.missing_categories.append(cat)

        return profile

    def _classify_module(self, rel_path: str) -> str:
        """Classify a module by its path to determine threat patterns."""
        path_lower = rel_path.lower()

        if "auth" in path_lower or "login" in path_lower or "session" in path_lower:
            return "auth"
        if "broker" in path_lower or "kite" in path_lower or "angel" in path_lower:
            return "broker"
        if "risk" in path_lower or "safety" in path_lower or "halt" in path_lower:
            return "risk"
        if "execution" in path_lower or "order" in path_lower or "trade" in path_lower:
            return "execution"
        if "db" in path_lower or "database" in path_lower or "sqlite" in path_lower or "postgres" in path_lower:
            return "database"
        if "api" in path_lower or "web" in path_lower or "dashboard" in path_lower or "endpoint" in path_lower:
            return "api"
        if "config" in path_lower:
            return "config"
        if "telegram" in path_lower or "notification" in path_lower:
            return "telegram"

        return "general"

    def _get_relevance_keywords(self, stride_cat: str, module_type: str) -> list[str]:
        """Get keywords that indicate relevance of a threat category to a module."""
        keyword_map: dict[str, list[str]] = {
            "Spoofing": ["auth", "token", "session", "login", "verify", "authenticate", "credential"],
            "Tampering": ["write", "update", "modify", "save", "store", "insert", "delete", "patch"],
            "Repudiation": ["log", "audit", "journal", "record", "trail", "event"],
            "Information Disclosure": ["secret", "password", "key", "token", "credential", "pii", "config"],
            "Denial of Service": ["rate", "limit", "timeout", "throttle", "queue", "pool", "retry"],
            "Elevation of Privilege": ["admin", "role", "permission", "sudo", "root", "privilege", "exec"],
        }
        return keyword_map.get(stride_cat, [stride_cat.lower()])

    def _generate_threat_recommendation(self, stride_cat: str, module_type: str) -> str:
        """Generate a recommendation for mitigating a threat category."""
        recs: dict[str, str] = {
            "Spoofing": "Implement strong authentication — verify all identities, use short-lived tokens, rotate credentials",
            "Tampering": "Implement data integrity checks — use checksums, signed payloads, and input validation",
            "Repudiation": "Implement non-repudiation — capture detailed audit logs with timestamps and user/process identity",
            "Information Disclosure": "Apply least privilege — encrypt sensitive data, avoid logging secrets, use vaults",
            "Denial of Service": "Implement rate limiting, connection pooling, timeouts, and graceful degradation",
            "Elevation of Privilege": "Apply principle of least privilege — validate all authorization checks, avoid eval/exec",
        }
        return recs.get(stride_cat, "Apply security best practices for this threat category")

    # ── Utilities ─────────────────────────────────────────────────────────

    def _risk_level(self, score: float) -> str:
        """Convert numeric score to risk level."""
        if score >= 0.75:
            return "CRITICAL"
        if score >= 0.5:
            return "HIGH"
        if score >= 0.25:
            return "MEDIUM"
        return "LOW"

    def _generate_recommendations(self, report: ThreatModelReport) -> list[str]:
        """Generate actionable recommendations based on findings."""
        recs: list[str] = []

        if report.total_threats_found == 0:
            recs.append("No threats identified — maintain current security practices")
            return recs

        # Critical/High threats
        critical = [t for t in report.top_threats if t.severity == "CRITICAL"]
        high = [t for t in report.top_threats if t.severity == "HIGH"]
        if critical:
            recs.append(f"Address {len(critical)} critical threats immediately — see top threats list")
        if high:
            recs.append(f"Review and mitigate {len(high)} high-risk threats in next sprint")

        # STRIDE gaps
        for cat, count in report.stride_distribution.items():
            if count == 0:
                recs.append(f"No threats identified in '{cat}' category — verify threat coverage completeness")

        # Modules with highest risk
        high_risk_modules = sorted(
            [m for m in report.modules if m.max_risk_score > 0.7],
            key=lambda m: m.max_risk_score, reverse=True,
        )
        if high_risk_modules:
            recs.append(f"Prioritize review of {len(high_risk_modules)} high-risk modules: "
                        f"{', '.join(m.module_path for m in high_risk_modules[:5])}")

        # MITRE coverage
        if report.mitre_mapping:
            recs.append(f"Threats mapped to {len(report.mitre_mapping)} MITRE ATT&CK techniques — "
                        f"integrate with SIEM for detection coverage")

        if not recs:
            recs.append("Threat model complete — no additional recommendations")

        return recs[:8]

    # ── Persistence ──────────────────────────────────────────────────────

    def _persist(self) -> None:
        """Persist analysis history to disk."""
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            data = [r.to_dict() for r in self._history[-50:]]
            self._persist_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except (OSError, ValueError) as exc:
            _log.debug("[THREAT] Persist: %s", exc)

    def _load_history(self) -> None:
        """Load analysis history from disk."""
        try:
            if self._persist_path.is_file():
                data = json.loads(self._persist_path.read_text(encoding="utf-8"))
                for item in data:
                    try:
                        report = ThreatModelReport(**{k: v for k, v in item.items()
                                                      if k in ThreatModelReport.__dataclass_fields__})
                        self._history.append(report)
                    except (TypeError, ValueError) as exc:
                        _log.debug("[THREAT] Load skip: %s", exc)
                self._total_analyses = len(self._history)
                if self._history:
                    self._last_report = self._history[-1]
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            _log.debug("[THREAT] Load failed: %s", exc)


# ── CLI ────────────────────────────────────────────────────────────────────


def _cli() -> None:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m core.threat_modeler",
        description="STRIDE Threat Modeler — Analyze codebase for security threats",
    )
    ap.add_argument("--analyze", action="store_true", help="Run STRIDE analysis on all modules")
    ap.add_argument("--module", type=str, help="Analyze a single module (path relative to project root)")
    ap.add_argument("--stats", action="store_true", help="Show statistics")
    ap.add_argument("--json", action="store_true", help="Output as JSON")
    args = ap.parse_args()

    modeler = get_threat_modeler()

    if args.module:
        profile = modeler.analyze_single_module(args.module)
        if profile is None:
            print(f"Module not found: {args.module}")
            return
        if args.json:
            import json
            print(json.dumps(profile.to_dict(), indent=2))
        else:
            print(f"Module: {profile.module_path}")
            print(f"Type: {profile.module_type}")
            print(f"Total Threats: {profile.total_threats}")
            print(f"Max Risk: {profile.max_risk_score:.3f}")
            for t in profile.threats:
                print(f"  [{t.severity}] {t.stride_category}: {t.description[:80]}")
        return

    if args.analyze:
        report = modeler.analyze_all_modules()
        if args.json:
            import json
            print(json.dumps(report.to_dict(), indent=2))
        else:
            print(report.summary_text())
        return

    if args.stats:
        stats = modeler.get_stats()
        if args.json:
            import json
            print(json.dumps(stats, indent=2))
        else:
            print(f"Total Analyses: {stats['total_analyses']}")
            print(f"Last Threats Found: {stats['last_threats_found']}")
            print(f"Last Risk Level: {stats['last_risk_level']}")
        return

    ap.print_help()


if __name__ == "__main__":
    _cli()

# ── Singleton ──────────────────────────────────────────────────────────────

_modeler: ThreatModeler | None = None
_modeler_lock = threading.RLock()


def get_threat_modeler() -> ThreatModeler:
    """Get the singleton ThreatModeler instance."""
    global _modeler
    with _modeler_lock:
        if _modeler is None:
            _modeler = ThreatModeler()
        return _modeler


def reset_threat_modeler() -> None:
    """Force-reset singleton (for testing)."""
    global _modeler
    with _modeler_lock:
        _modeler = None


__all__ = [
    "ModuleThreatProfile",
    "ThreatFinding",
    "ThreatModelReport",
    "ThreatModeler",
    "get_threat_modeler",
    "reset_threat_modeler",
]
