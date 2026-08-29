"""Root Cause Analysis Engine (Pillar 5).

When an issue occurs, automatically collects:
- Stack traces and error details
- Related commits (git log)
- Recent deployments
- Configuration changes
- Database changes
- Infrastructure events
- Dependency updates
- Similar historical incidents

Produces:
- Probable root cause with confidence level
- Recommended fix
- Impacted modules
- Suggested rollback if necessary

Integrates with: ExecutionErrorClassifier, AnomalyDetector, IncidentAlerting,
ChangeManager, DataLineageEngine.

Usage:
    from core.root_cause_analyzer import RootCauseAnalyzer

    analyzer = RootCauseAnalyzer()
    result = analyzer.investigate(
        error_type="broker_disconnect",
        error_message="Connection refused: broker.zerodha.com:443",
        stack_trace="...",
    )
    print(result.probable_cause)
    print(result.confidence)
    print(result.recommended_fix)
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

# ── Constants ───────────────────────────────────────────────────────────────

KNOWN_INCIDENT_PATTERNS: dict[str, dict[str, Any]] = {
    "broker_disconnect": {
        "description": "Broker connection lost",
        "common_causes": [
            "Network outage or firewall blocking outbound connections",
            "Broker API endpoint changed or deprecated",
            "Authentication token expired and not refreshed",
            "Rate limit exceeded at broker side",
            "Broker maintenance window",
        ],
        "recovery_actions": [
            "Check network connectivity to broker endpoint",
            "Verify API token validity and refresh if needed",
            "Review broker status page for outages",
            "Check if failover broker is available",
        ],
        "severity": "CRITICAL",
    },
    "reconciliation_mismatch": {
        "description": "Internal state does not match broker state",
        "common_causes": [
            "Order acknowledgement lost during network interruption",
            "Partial fill not processed correctly",
            "Duplicate order submission due to retry",
            "Order cancellation not confirmed by broker",
            "State corruption after unexpected restart",
        ],
        "recovery_actions": [
            "Run full reconciliation with broker",
            "Identify mismatched orders and resolve each one",
            "Check order history for duplicate submissions",
            "Verify position sizes match across systems",
        ],
        "severity": "HIGH",
    },
    "stale_quote": {
        "description": "Market data feed not updating",
        "common_causes": [
            "Yahoo Finance rate limiting or IP ban",
            "WebSocket connection dropped and not reconnected",
            "Data provider API changed format",
            "Network latency spike causing timeout cascade",
            "Disk I/O bottleneck preventing writes",
        ],
        "recovery_actions": [
            "Check data provider status and rate limits",
            "Restart WebSocket feed connection",
            "Fall back to alternative data provider",
            "Verify LTP cache is being refreshed",
        ],
        "severity": "NORMAL",
    },
    "risk_breach": {
        "description": "Risk limit exceeded",
        "common_causes": [
            "Configuration change accidently relaxed limits",
            "Market gap move exceeded VaR assumptions",
            "Position sizing calculation error",
            "Capital tracking desync between sessions",
            "Multiple concurrent entries bypassed limits",
        ],
        "recovery_actions": [
            "Verify current risk configuration",
            "Check capital tracking accuracy",
            "Review recent configuration changes",
            "Consider if limits need adjustment for current volatility",
        ],
        "severity": "CRITICAL",
    },
    "circuit_breaker": {
        "description": "Circuit breaker triggered (repeated failures)",
        "common_causes": [
            "Dependency (broker/data provider) is in failure state",
            "Transient failures not handled properly creating cascade",
            "Configuration change reduced failure tolerance",
            "Network instability causing intermittent failures",
            "Resource exhaustion (memory/disk) causing failures",
        ],
        "recovery_actions": [
            "Check if downstream dependency is healthy",
            "Review failure logs to identify the triggering pattern",
            "Verify circuit breaker configuration thresholds",
            "Consider manual reset after confirming dependency health",
        ],
        "severity": "HIGH",
    },
    "db_failure": {
        "description": "Database operation failed",
        "common_causes": [
            "Disk full or inode exhaustion",
            "WAL file size exceeded and checkpoint failed",
            "Database file corruption from unclean shutdown",
            "SQLite lock contention from concurrent writes",
            "Schema migration applied incorrectly",
        ],
        "recovery_actions": [
            "Check disk space and inode usage",
            "Run integrity check on affected database",
            "Restore from most recent backup",
            "Verify schema version matches expected migration",
        ],
        "severity": "HIGH",
    },
    "capacity_critical": {
        "description": "Resource capacity threshold breached",
        "common_causes": [
            "Database growth exceeding projections",
            "Log rotation not running or misconfigured",
            "Historical data accumulation without purge",
            "Backup accumulation consuming disk space",
            "Memory leak in long-running process",
        ],
        "recovery_actions": [
            "Run disk cleanup to free space",
            "Verify log rotation is working",
            "Check database growth rates and archive old data",
            "Review capacity forecasts for scaling needs",
        ],
        "severity": "HIGH",
    },
    "auth_expiry": {
        "description": "Authentication token expired or invalid",
        "common_causes": [
            "Broker API token expired beyond refresh window",
            "Refresh token rotated without updating stored secret",
            "System clock drift causing JWT validation failure",
            "Multiple concurrent refreshes causing token invalidation",
            "Permission revoked on broker side",
        ],
        "recovery_actions": [
            "Generate fresh API token from broker dashboard",
            "Verify system clock is NTP-synchronized",
            "Check token refresh interval and pre-emptive refresh window",
            "Validate credentials in broker adapter configuration",
        ],
        "severity": "CRITICAL",
    },
    "network_outage": {
        "description": "Network connectivity lost",
        "common_causes": [
            "ISP or data center network outage",
            "Firewall rule changed blocking outbound connections",
            "DNS resolution failure for API endpoints",
            "Proxy or VPN connection dropped",
            "Network interface saturation or packet loss",
        ],
        "recovery_actions": [
            "Ping external endpoints to verify basic connectivity",
            "Check DNS resolution for broker/data provider URLs",
            "Verify firewall rules allow outbound connections",
            "Restart network interface or VPN connection",
            "Check if failover network path is available",
        ],
        "severity": "HIGH",
    },
    "memory_pressure": {
        "description": "System memory threshold exceeded",
        "common_causes": [
            "Memory leak in long-running trading process",
            "Unbounded cache growth without eviction policy",
            "Large DataFrame operations holding references",
            "Too many concurrent WebSocket connections",
            "Insufficient system memory for current workload",
        ],
        "recovery_actions": [
            "Check process memory usage with memory_profiler",
            "Verify cache TTL and eviction policies",
            "Add explicit gc.collect() calls after large operations",
            "Consider memory limits and restart thresholds",
            "Reduce batch sizes for DataFrame operations",
        ],
        "severity": "HIGH",
    },
}


# ── Data Models ─────────────────────────────────────────────────────────────


@dataclass
class EvidenceItem:
    """A single piece of evidence collected during investigation."""

    category: str  # STACK_TRACE, GIT_COMMIT, CONFIG_CHANGE, DEPLOYMENT, DEPENDENCY, HISTORY, INFRASTRUCTURE, DB_SCHEMA
    description: str
    source: str
    relevance: float = 0.5  # 0.0 to 1.0
    timestamp: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "description": self.description,
            "source": self.source,
            "relevance": self.relevance,
            "timestamp": self.timestamp,
            "details": self.details,
        }


@dataclass
class RootCauseResult:
    """Complete root cause analysis result."""

    incident_type: str
    incident_message: str
    probable_cause: str = ""
    confidence: float = 0.0  # 0.0 to 1.0
    severity: str = "NORMAL"
    evidence: list[EvidenceItem] = field(default_factory=list)
    impacted_modules: list[str] = field(default_factory=list)
    recommended_fix: str = ""
    suggested_rollback: bool = False
    rollback_target: str = ""
    similar_incidents: list[dict[str, Any]] = field(default_factory=list)
    analysis_duration_ms: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "incident_type": self.incident_type,
            "incident_message": self.incident_message,
            "probable_cause": self.probable_cause,
            "confidence": self.confidence,
            "severity": self.severity,
            "evidence_count": len(self.evidence),
            "evidence": [e.to_dict() for e in self.evidence],
            "impacted_modules": self.impacted_modules,
            "recommended_fix": self.recommended_fix,
            "suggested_rollback": self.suggested_rollback,
            "rollback_target": self.rollback_target,
            "similar_incidents": self.similar_incidents,
            "analysis_duration_ms": round(self.analysis_duration_ms, 1),
            "timestamp": self.timestamp,
        }

    def summary_text(self) -> str:
        lines = [
            "═" * 60,
            f"  ROOT CAUSE ANALYSIS: {self.incident_type}",
            "═" * 60,
            f"  Message: {self.incident_message}",
            f"  Probable Cause: {self.probable_cause}",
            f"  Confidence: {self.confidence:.0%}",
            f"  Severity: {self.severity}",
            f"  Duration: {self.analysis_duration_ms:.0f}ms",
            "",
        ]
        if self.evidence:
            lines.append(f"  Evidence ({len(self.evidence)} items):")
            for e in self.evidence[:10]:
                lines.append(f"    [{e.category}] ({e.relevance:.0%}) {e.description}")
        if self.impacted_modules:
            lines.append("  Impacted Modules:")
            for m in self.impacted_modules[:10]:
                lines.append(f"    • {m}")
        if self.recommended_fix:
            lines.append(f"  Recommended Fix: {self.recommended_fix}")
        if self.suggested_rollback:
            lines.append(f"  ⚠ Suggested Rollback: {self.rollback_target}")
        if self.similar_incidents:
            lines.append(f"  Similar Incidents ({len(self.similar_incidents)}):")
            for s in self.similar_incidents[:3]:
                lines.append(f"    • {s.get('incident_type', '?')}: {s.get('probable_cause', '?')[:80]}")
        lines.append("═" * 60)
        return "\n".join(lines)


# ── Root Cause Analyzer ────────────────────────────────────────────────────


class RootCauseAnalyzer:
    """Root Cause Analysis Engine.

    Investigates incidents by collecting evidence from multiple sources:
    - Error classification (via ExecutionErrorClassifier)
    - Git commit history for related changes
    - Configuration change audit log
    - Historical incident database
    - Dependency update timeline
    - Recent deployments

    Uses pattern matching against known incident patterns to identify
    probable causes and recommend fixes.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._incident_history: list[RootCauseResult] = []
        self._max_history = 500
        self._history_path = Path("json/incident_history.json")
        self._history_path.parent.mkdir(parents=True, exist_ok=True)
        self._load_history()
        # Pattern Learner integration (lazy-loaded to avoid circular imports)
        self._pattern_learner: Any = None

    # ── Public API ────────────────────────────────────────────────────────

    def investigate(
        self,
        error_type: str,
        error_message: str,
        stack_trace: str = "",
        module: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> RootCauseResult:
        """Investigate an incident and determine root cause.

        Args:
            error_type: Type of incident (e.g., 'broker_disconnect', 'db_failure').
            error_message: Human-readable error message.
            stack_trace: Optional stack trace string.
            module: Optional module name where the error occurred.
            metadata: Optional additional metadata.

        Returns:
            RootCauseResult with probable cause, confidence, and recommendations.
        """
        start_time = time.time()
        result = RootCauseResult(
            incident_type=error_type,
            incident_message=error_message,
        )

        # 1. Collect evidence from known patterns
        pattern = KNOWN_INCIDENT_PATTERNS.get(error_type, {})
        result.severity = pattern.get("severity", "NORMAL")

        # 2. Collect stack trace evidence
        if stack_trace:
            result.evidence.append(self._analyze_stack_trace(stack_trace))
            result.impacted_modules = self._extract_modules_from_stack(stack_trace)

        # 3. Collect git commit evidence
        git_evidence = self._collect_git_evidence(error_type, error_message, module)
        result.evidence.extend(git_evidence)

        # 4. Collect config change evidence
        config_evidence = self._collect_config_change_evidence()
        result.evidence.extend(config_evidence)

        # 5. Collect infrastructure evidence
        infra_evidence = self._collect_infrastructure_evidence()
        result.evidence.extend(infra_evidence)

        # 6. Collect DB schema change evidence
        db_evidence = self._collect_db_schema_evidence()
        result.evidence.extend(db_evidence)

        # 7. Collect dependency update evidence
        dep_evidence = self._collect_dependency_evidence()
        result.evidence.extend(dep_evidence)

        # 8. Find similar historical incidents
        result.similar_incidents = self._find_similar_incidents(error_type)

        # 9. Determine probable cause and confidence
        if error_type in KNOWN_INCIDENT_PATTERNS:
            causes = pattern.get("common_causes", [])
            if causes:
                result.probable_cause = self._rank_causes(
                    causes, result.evidence, result.similar_incidents
                )
        else:
            # Fallback for unknown error types
            result.probable_cause = (
                f"Unknown incident type '{error_type}'. "
                f"Investigate manually based on error message: {error_message[:100]}"
            )

        # 10. Generate recommended fix
        result.recommended_fix = self._generate_fix(
            error_type, result.probable_cause, result.evidence
        )

        # 11. Determine if rollback is needed
        result.suggested_rollback, result.rollback_target = self._assess_rollback(
            error_type, result.evidence
        )

        # 12. Calculate confidence based on evidence strength
        result.confidence = self._calculate_confidence(result.evidence)

        result.analysis_duration_ms = (time.time() - start_time) * 1000

        # Save to history
        self._save_incident(result)

        # Auto-learn patterns from this investigation (non-blocking)
        self._learn_from_result(result)

        return result

    def investigate_from_classified_error(
        self,
        classified_error: Any,
        module: str = "",
        stack_trace: str = "",
    ) -> RootCauseResult:
        """Investigate from a classified error (ExecutionErrorClassifier result).

        Args:
            classified_error: ErrorClassification from ExecutionErrorClassifier.
            module: Module where error occurred.
            stack_trace: Optional stack trace.

        Returns:
            RootCauseResult.
        """
        return self.investigate(
            error_type=classified_error.category.value if hasattr(classified_error, "category") else "UNKNOWN",
            error_message=classified_error.message if hasattr(classified_error, "message") else str(classified_error),
            stack_trace=stack_trace,
            module=module,
        )

    def get_incident_history(
        self,
        incident_type: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get incident history, optionally filtered by type."""
        with self._lock:
            results = self._incident_history
            if incident_type:
                results = [r for r in results if r.incident_type == incident_type]
            return [r.to_dict() for r in results[-limit:]]

    def get_incident_stats(self) -> dict[str, Any]:
        """Get statistics about historical incidents."""
        with self._lock:
            if not self._incident_history:
                return {"total": 0}

            by_type: dict[str, int] = {}
            by_severity: dict[str, int] = {}
            total = len(self._incident_history)

            for r in self._incident_history:
                by_type[r.incident_type] = by_type.get(r.incident_type, 0) + 1
                by_severity[r.severity] = by_severity.get(r.severity, 0) + 1

            return {
                "total": total,
                "by_type": by_type,
                "by_severity": by_severity,
                "last_24h": sum(
                    1 for r in self._incident_history
                    if time.time() - datetime.fromisoformat(r.timestamp).timestamp() < 86400
                ),
            }

    def clear_history(self) -> None:
        """Clear all incident history."""
        with self._lock:
            self._incident_history.clear()
            if self._history_path.exists():
                self._history_path.unlink()

    # ── Evidence Collection ───────────────────────────────────────────────

    def _analyze_stack_trace(self, stack_trace: str) -> EvidenceItem:
        """Analyze a stack trace to extract useful information."""
        details: dict[str, Any] = {
            "trace_length": len(stack_trace),
            "line_count": len(stack_trace.splitlines()),
        }

        # Extract module names from stack trace
        modules = re.findall(r'File\s+"([^"]+)"', stack_trace)
        if modules:
            details["modules"] = list(set(modules))

        # Extract error type from trace
        error_type_match = re.search(r'(\w+Error):\s+(.+)', stack_trace.splitlines()[-1] if stack_trace.splitlines() else "")
        if error_type_match:
            details["python_error_type"] = error_type_match.group(1)
            details["python_error_message"] = error_type_match.group(2)

        return EvidenceItem(
            category="STACK_TRACE",
            description=f"Stack trace analyzed: {len(stack_trace.splitlines())} lines",
            source="runtime",
            relevance=0.9,
            timestamp=time.time(),
            details=details,
        )

    def _extract_modules_from_stack(self, stack_trace: str) -> list[str]:
        """Extract affected module names from a stack trace."""
        modules: list[str] = []
        project_root = Path(".").resolve()
        # Match Python file paths in stack traces
        for match in re.finditer(r'File\s+"([^"]+)"', stack_trace):
            path_str = match.group(1)
            path = Path(path_str)
            try:
                # Try making it relative to project root
                if path.is_absolute():
                    rel = path.relative_to(project_root)
                else:
                    # Path is already relative; use as-is
                    rel = path
                modules.append(str(rel).replace("\\", "/"))
            except (ValueError, OSError):
                # If path can't be made relative, use raw path
                modules.append(path_str.replace("\\", "/"))
        # Deduplicate while preserving order
        seen: set[str] = set()
        return [m for m in modules if not (m in seen or seen.add(m))][:20]

    def _collect_git_evidence(
        self, error_type: str, error_message: str, module: str
    ) -> list[EvidenceItem]:
        """Collect evidence from recent git commits."""
        evidence: list[EvidenceItem] = []
        try:
            # Get recent commits (last 50)
            result = subprocess.run(
                ["git", "log", "--oneline", "-50", "--format=%H|%ai|%s"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                commits = result.stdout.strip().splitlines()
                evidence.append(EvidenceItem(
                    category="GIT_COMMIT",
                    description=f"Last {len(commits)} commits reviewed for related changes",
                    source="git",
                    relevance=0.6,
                    timestamp=time.time(),
                    details={"commit_count": len(commits)},
                ))

                # Check for commits related to the error
                if module:
                    keyword = module.replace("core/", "").replace(".py", "").replace("/", ".")
                    related = [c for c in commits if keyword.lower() in c.lower()]
                    if related:
                        evidence.append(EvidenceItem(
                            category="GIT_COMMIT",
                            description=f"{len(related)} commit(s) related to module '{module}'",
                            source="git",
                            relevance=0.8,
                            timestamp=time.time(),
                            details={"commits": related[:10]},
                        ))
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
            _log.debug("[RCA] Git evidence collection failed: %s", exc)
        return evidence

    def _collect_config_change_evidence(self) -> list[EvidenceItem]:
        """Collect evidence from configuration change audit log."""
        evidence: list[EvidenceItem] = []
        try:
            audit_path = Path("json/config_audit.jsonl")
            if audit_path.is_file():
                lines = audit_path.read_text(encoding="utf-8").splitlines()
                # Get changes from last 24 hours
                now = time.time()
                recent_changes: list[dict[str, Any]] = []
                for line in lines[-100:]:
                    try:
                        entry = json.loads(line)
                        entry_time = entry.get("timestamp", 0)
                        if now - entry_time < 86400:  # 24 hours
                            recent_changes.append(entry)
                    except (json.JSONDecodeError, ValueError):
                        continue

                if recent_changes:
                    evidence.append(EvidenceItem(
                        category="CONFIG_CHANGE",
                        description=f"{len(recent_changes)} config change(s) in last 24 hours",
                        source="json/config_audit.jsonl",
                        relevance=0.7,
                        timestamp=time.time(),
                        details={"changes": recent_changes[:20]},
                    ))
        except (OSError, json.JSONDecodeError) as exc:
            _log.debug("[RCA] Config evidence collection failed: %s", exc)
        return evidence

    def _find_similar_incidents(self, incident_type: str) -> list[dict[str, Any]]:
        """Find similar incidents from history."""
        with self._lock:
            similar: list[dict[str, Any]] = []
            for r in self._incident_history[-100:]:
                if r.incident_type == incident_type:
                    similar.append(r.to_dict())
            return similar[-10:]

    def _collect_infrastructure_evidence(self) -> list[EvidenceItem]:
        """Collect evidence from infrastructure metrics (CPU, disk, memory)."""
        evidence: list[EvidenceItem] = []
        try:
            # Check disk usage
            import shutil
            total, used, free = shutil.disk_usage(".")
            free_gb = free / (1024 ** 3)
            used_pct = used / max(total, 1) * 100

            if free_gb < 1.0:
                evidence.append(EvidenceItem(
                    category="INFRASTRUCTURE",
                    description=f"CRITICAL: Disk space critically low ({free_gb:.1f} GB free, {used_pct:.0f}% used)",
                    source="shutil.disk_usage",
                    relevance=0.85,
                    timestamp=time.time(),
                    details={"free_gb": round(free_gb, 1), "used_pct": round(used_pct, 1)},
                ))
            elif free_gb < 5.0:
                evidence.append(EvidenceItem(
                    category="INFRASTRUCTURE",
                    description=f"WARNING: Disk space running low ({free_gb:.1f} GB free)",
                    source="shutil.disk_usage",
                    relevance=0.5,
                    timestamp=time.time(),
                    details={"free_gb": round(free_gb, 1), "used_pct": round(used_pct, 1)},
                ))
        except (ImportError, OSError) as exc:
            _log.debug("[RCA] Disk evidence collection failed: %s", exc)

        return evidence

    def _collect_db_schema_evidence(self) -> list[EvidenceItem]:
        """Collect evidence from database schema changes."""
        evidence: list[EvidenceItem] = []
        try:
            # Check if schema migration log exists
            from core.db_migration import get_migration_log
            log = get_migration_log()
            if log:
                # Get last 3 migrations
                recent = log[-3:] if len(log) >= 3 else log
                evidence.append(EvidenceItem(
                    category="DB_SCHEMA",
                    description=f"{len(log)} database migrations found in history",
                    source="core.db_migration",
                    relevance=0.6,
                    timestamp=time.time(),
                    details={"recent_migrations": [str(m) for m in recent]},
                ))
        except ImportError:
            pass
        except Exception as exc:
            _log.debug("[RCA] DB schema evidence collection failed: %s", exc)

        # Check for schema version
        try:
            from core.db_migration import get_schema_version
            version = get_schema_version()
            if version:
                evidence.append(EvidenceItem(
                    category="DB_SCHEMA",
                    description=f"Current database schema version: {version}",
                    source="core.db_migration",
                    relevance=0.4,
                    timestamp=time.time(),
                    details={"schema_version": version},
                ))
        except ImportError:
            pass
        except Exception as exc:
            _log.debug("[RCA] Schema version check failed: %s", exc)

        return evidence

    def _collect_dependency_evidence(self) -> list[EvidenceItem]:
        """Collect evidence from dependency update timeline."""
        evidence: list[EvidenceItem] = []
        try:
            # Check requirements.txt for recently modified deps
            req_path = Path("requirements.txt")
            if req_path.is_file():
                mtime = req_path.stat().st_mtime
                age_days = (time.time() - mtime) / 86400
                if age_days < 7:
                    evidence.append(EvidenceItem(
                        category="DEPENDENCY",
                        description=f"Requirements file modified {age_days:.1f} days ago",
                        source="requirements.txt",
                        relevance=0.5,
                        timestamp=time.time(),
                        details={"modified_days_ago": round(age_days, 1)},
                    ))
        except OSError as exc:
            _log.debug("[RCA] Dependency evidence collection failed: %s", exc)

        return evidence

    # ── Analysis ──────────────────────────────────────────────────────────

    def _rank_causes(
        self,
        causes: list[str],
        evidence: list[EvidenceItem],
        similar_incidents: list[dict[str, Any]],
    ) -> str:
        """Rank possible causes and return the most likely one.

        Uses evidence relevance scores and historical patterns.
        """
        # Score each cause based on evidence matches
        cause_scores: list[tuple[str, float]] = []
        for cause in causes:
            score = 0.0
            cause_lower = cause.lower()

            # Check evidence keywords
            for ev in evidence:
                ev_text = ev.description.lower() + " ".join(str(v) for v in ev.details.values()).lower()
                if any(kw in ev_text for kw in cause_lower.split()):
                    score += ev.relevance * 2

            # Check similar incidents
            for si in similar_incidents:
                si_cause = si.get("probable_cause", "").lower()
                if any(kw in si_cause for kw in cause_lower.split()):
                    score += 0.5

            # Check if evidence confirms this cause
            if any(ev.category == "STACK_TRACE" and cause_lower in ev.description.lower() for ev in evidence):
                score += 1.0

            cause_scores.append((cause, score))

        # Return the highest-scored cause
        cause_scores.sort(key=lambda x: x[1], reverse=True)
        return cause_scores[0][0] if cause_scores else causes[0]

    def _generate_fix(
        self, error_type: str, probable_cause: str, evidence: list[EvidenceItem]
    ) -> str:
        """Generate a recommended fix based on the incident type and evidence."""
        pattern = KNOWN_INCIDENT_PATTERNS.get(error_type, {})
        actions = pattern.get("recovery_actions", [])
        fix_parts: list[str] = []

        # Customize fix based on evidence
        for ev in evidence:
            if ev.category == "CONFIG_CHANGE" and ev.relevance > 0.5:
                fix_parts.append("Review recent configuration changes - a config change may have triggered this.")
            if ev.category == "STACK_TRACE" and ev.relevance > 0.5:
                modules = ev.details.get("modules", [])
                if modules:
                    fix_parts.append(f"Check module(s): {', '.join(modules[:5])}")

        # Add standard recovery actions
        if actions:
            fix_parts.extend(f"• {a}" for a in actions[:3])

        if not fix_parts:
            fix_parts.append("Investigate the incident manually - no automated fix pattern available.")

        return "\n".join(fix_parts[:5])

    def _assess_rollback(
        self, error_type: str, evidence: list[EvidenceItem]
    ) -> tuple[bool, str]:
        """Determine if a rollback is needed and what to roll back to."""
        # Check if there's a recent config change that could be rolled back
        for ev in evidence:
            if ev.category == "CONFIG_CHANGE" and ev.relevance > 0.7:
                changes = ev.details.get("changes", [])
                if changes:
                    return True, "Roll back to last known-good configuration"

        # Critical errors may need rollback
        if error_type in ("risk_breach", "hard_halt"):
            return True, "Roll back to last stable version"

        return False, ""

    def _calculate_confidence(self, evidence: list[EvidenceItem]) -> float:
        """Calculate confidence level based on evidence quality.

        Uses Bayesian-inspired approach:
        - Prior: 0.1 (before any evidence)
        - Each evidence item adds weighted posterior lift
        - Diversity bonus for evidence from multiple categories
        """
        if not evidence:
            return 0.1

        category_weights = {
            "STACK_TRACE": 2.0,
            "GIT_COMMIT": 1.5,
            "CONFIG_CHANGE": 1.5,
            "DEPLOYMENT": 1.0,
            "DEPENDENCY": 1.0,
            "HISTORY": 0.8,
            "INFRASTRUCTURE": 1.5,
            "DB_SCHEMA": 1.2,
        }

        # Bayesian prior
        prior = 0.1
        prior_weight = 1.0

        total_weight = prior_weight
        weighted_sum = prior * prior_weight

        for ev in evidence:
            w = category_weights.get(ev.category, 1.0)
            total_weight += w
            weighted_sum += ev.relevance * w

        # Diversity bonus: evidence from more categories → higher confidence
        categories_used = {ev.category for ev in evidence}
        diversity_bonus = min(0.15, len(categories_used) * 0.03)

        if total_weight == 0:
            return min(1.0, prior + diversity_bonus)

        return min(1.0, (weighted_sum / total_weight) + diversity_bonus)

    # ── Pattern Learner Integration ──────────────────────────────────────

    def _learn_from_result(self, result: RootCauseResult) -> None:
        """Auto-learn patterns from an investigation result via PatternLearner.

        Called after every investigate() to capture new incident patterns
        in the Knowledge Base for future reference. Non-blocking — failures
        are silently logged.
        """
        if not result.incident_type or not result.probable_cause:
            return
        # Lazy import to avoid circular dependencies
        if self._pattern_learner is None:
            try:
                from core.pattern_learner import get_pattern_learner
                self._pattern_learner = get_pattern_learner()
            except ImportError:
                self._pattern_learner = False  # Mark unavailable
                return
        if not self._pattern_learner:
            return
        try:
            # Create a mock-compatible result for PatternLearner
            self._pattern_learner.learn_from_incident(result)
        except Exception as exc:
            _log.debug("[RCA] Pattern learning failed: %s", exc)

    # ── Persistence ───────────────────────────────────────────────────────

    def _load_history(self) -> None:
        """Load incident history from JSON file."""
        try:
            if self._history_path.is_file():
                data = json.loads(self._history_path.read_text(encoding="utf-8"))
                for item in data:
                    result = RootCauseResult(
                        incident_type=item.get("incident_type", "UNKNOWN"),
                        incident_message=item.get("incident_message", ""),
                        probable_cause=item.get("probable_cause", ""),
                        confidence=item.get("confidence", 0.0),
                    )
                    self._incident_history.append(result)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            _log.debug("[RCA] History load failed: %s", exc)

    def _save_incident(self, result: RootCauseResult) -> None:
        """Save an incident to the history file."""
        with self._lock:
            self._incident_history.append(result)
            if len(self._incident_history) > self._max_history:
                self._incident_history = self._incident_history[-self._max_history:]

            try:
                data = [
                    {
                        "incident_type": r.incident_type,
                        "incident_message": r.incident_message[:200],
                        "probable_cause": r.probable_cause[:200],
                        "confidence": r.confidence,
                        "timestamp": r.timestamp,
                    }
                    for r in self._incident_history[-200:]
                ]
                self._history_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            except (OSError, ValueError) as exc:
                _log.debug("[RCA] History save failed: %s", exc)


# ── Singleton ───────────────────────────────────────────────────────────────


_analyzer: RootCauseAnalyzer | None = None
_analyzer_lock = threading.RLock()


def get_root_cause_analyzer() -> RootCauseAnalyzer:
    """Get the singleton RootCauseAnalyzer instance."""
    global _analyzer
    with _analyzer_lock:
        if _analyzer is None:
            _analyzer = RootCauseAnalyzer()
        return _analyzer


def reset_root_cause_analyzer() -> None:
    """Force-reset singleton (for testing)."""
    global _analyzer
    with _analyzer_lock:
        _analyzer = None


def investigate_incident(
    error_type: str,
    error_message: str,
    stack_trace: str = "",
    module: str = "",
) -> RootCauseResult:
    """Convenience function: investigate a single incident."""
    return get_root_cause_analyzer().investigate(
        error_type=error_type,
        error_message=error_message,
        stack_trace=stack_trace,
        module=module,
    )


__all__ = [
    "EvidenceItem",
    "KNOWN_INCIDENT_PATTERNS",
    "RootCauseAnalyzer",
    "RootCauseResult",
    "get_root_cause_analyzer",
    "investigate_incident",
    "reset_root_cause_analyzer",
]
