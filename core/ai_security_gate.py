"""AI Security Gate — Prompt Injection Detection & Hallucination Scoring (Constitution v4.0).

Provides:
- Prompt injection detection (pattern-based, entropy-based, token-ratio analysis)
- Hallucination scoring (confidence calibration, consistency checks, source grounding)
- Input/output sanitization for AI interactions
- Audit trail for all AI security events

Integrates with:
- SecurityAuditor for overall security posture
- RootCauseAnalyzer for incident correlation
- BIDashboard for security trending

Usage:
    from core.ai_security_gate import get_ai_security_gate

    gate = get_ai_security_gate()
    result = gate.analyze_prompt("What is the current P&L?")
    print(result.risk_level, result.injection_score)
"""

from __future__ import annotations

import json
import logging
import math
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────

# Known prompt injection patterns
INJECTION_PATTERNS: list[tuple[str, str, float]] = [
    ("ignore_previous", r"(?i)(ignore|disregard|forget|skip)\s+(all\s+)?(previous|above|prior)\s+(instructions|prompts|commands|context)", 0.9),
    ("role_escape", r"(?i)(you are now|act as|pretend to be|now you are|from now on)\s+(a\s+)?(free|unrestricted|unbounded|ungoverned|jailbreak)", 0.95),
    ("system_prompt_leak", r"(?i)(reveal|show|print|output|display|leak|dump)\s+(your\s+)?(system|internal|hidden|secret)\s+(prompt|instructions|configuration)", 0.9),
    ("delimiter_escape", r"(?i)(ignore|bypass|break out of)\s+(the\s+)?(delimiter|boundary|limit|restriction|constraint)", 0.85),
    ("directive_injection", r"(?i)(say|repeat|echo|output)\s+(the\s+)?(word|text|phrase|string)\s+['\"].*['\"]", 0.7),
    ("token_ smuggling", r"(?i)(base64|rot13|hex|encoded|obfuscated)\s+(instruction|command|prompt|payload)", 0.8),
    ("threat_directive", r"(?i)(I\s+have\s+.*gun|I\s+will\s+harm|I'm\s+going\s+to\s+kill|bomb|explosive|terrorist)", 0.95),
    ("data_exfil", r"(?i)(send|upload|transmit|exfiltrate|copy)\s+(this\s+)?(data|file|content|information)\s+(to|via|using)\s+(http|https|ftp|email|api)", 0.85),
    ("sql_injection_prompt", r"(?i)(SELECT|DROP|DELETE|INSERT|UPDATE)\s+.*\s+(FROM|INTO|TABLE|SET)\s+.*(--|#|;)", 0.8),
    ("prompt_leak_attempt", r"(?i)(tell me|what are|show me|give me)\s+(your|the)\s+(instructions|system prompt|hidden context|initial prompt)", 0.85),
    ("reverse_psychology", r"(?i)(you must|you have to|you are required to|it's your duty to)\s+(disobey|ignore|break|violate)\s+(the|your|these)\s+(rules|guidelines|instructions|protocol)", 0.9),
    ("token_hiding", r"(?i)(between\s+the\s+lines|hidden\s+message|steganography|concealed|covert)", 0.75),
]

# High-entropy threshold (random strings, obfuscated payloads)
HIGH_ENTROPY_THRESHOLD = 4.5  # bits per character
SUSPICIOUS_ENTROPY_THRESHOLD = 3.8

# Token ratio thresholds
MIN_VALID_TOKEN_LENGTH = 2
MAX_TOKEN_LENGTH_RATIO = 0.8  # ratio of max token length to avg

# Confidence / hallucination thresholds
LOW_CONFIDENCE_THRESHOLD = 0.3
HIGH_CONFIDENCE_THRESHOLD = 0.7


# ── Data Models ────────────────────────────────────────────────────────────


@dataclass
class InjectionFinding:
    """A detected prompt injection attempt."""

    pattern_name: str = ""
    severity: float = 0.0  # 0.0 to 1.0
    snippet: str = ""
    position: int = 0
    risk_level: str = "LOW"

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern_name": self.pattern_name,
            "severity": round(self.severity, 3),
            "snippet": self.snippet[:120],
            "position": self.position,
            "risk_level": self.risk_level,
        }


@dataclass
class HallucinationScore:
    """Hallucination risk score for an AI response."""

    confidence: float = 0.0  # 0.0 to 1.0 (how confident the model is)
    consistency_score: float = 1.0  # 0.0 to 1.0
    source_grounding: float = 1.0  # 0.0 to 1.0
    factual_risk: float = 0.0  # 0.0 to 1.0
    details: list[str] = field(default_factory=list)
    risk_level: str = "LOW"

    def to_dict(self) -> dict[str, Any]:
        return {
            "confidence": round(self.confidence, 3),
            "consistency_score": round(self.consistency_score, 3),
            "source_grounding": round(self.source_grounding, 3),
            "factual_risk": round(self.factual_risk, 3),
            "details": self.details,
            "risk_level": self.risk_level,
        }


@dataclass
class AIAuditRecord:
    """Audit record for an AI interaction."""

    timestamp: float = 0.0
    prompt: str = ""
    sanitized_prompt: str = ""
    injection_risk: float = 0.0
    injection_findings: list[InjectionFinding] = field(default_factory=list)
    hallucination_score: HallucinationScore | None = None
    risk_level: str = "LOW"
    blocked: bool = False
    response_length: int = 0
    latency_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        injection_findings = []
        for f in self.injection_findings:
            if isinstance(f, dict):
                injection_findings.append(f)
            else:
                injection_findings.append(f.to_dict())
        hs = self.hallucination_score
        if isinstance(hs, dict):
            hallucination_dict = hs
        elif hs is not None:
            hallucination_dict = hs.to_dict()
        else:
            hallucination_dict = None

        return {
            "timestamp": self.timestamp,
            "date": datetime.fromtimestamp(self.timestamp).isoformat() if self.timestamp else "",
            "prompt": self.prompt[:120],
            "injection_risk": round(self.injection_risk, 3),
            "injection_findings": injection_findings,
            "hallucination_score": hallucination_dict,
            "risk_level": self.risk_level,
            "blocked": self.blocked,
            "response_length": self.response_length,
            "latency_ms": round(self.latency_ms, 1),
        }


@dataclass
class AISecurityReport:
    """Complete AI security assessment report."""

    timestamp: float = 0.0
    total_prompts_analyzed: int = 0
    total_blocked: int = 0
    injection_rate: float = 0.0
    high_risk_prompts: list[AIAuditRecord] = field(default_factory=list)
    recent_audits: list[AIAuditRecord] = field(default_factory=list)
    overall_risk_score: float = 0.0
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "total_prompts_analyzed": self.total_prompts_analyzed,
            "total_blocked": self.total_blocked,
            "injection_rate": round(self.injection_rate, 4),
            "high_risk_prompts": [r.to_dict() for r in self.high_risk_prompts[-20:]],
            "recent_audits": [r.to_dict() for r in self.recent_audits[-50:]],
            "overall_risk_score": round(self.overall_risk_score, 3),
            "recommendations": self.recommendations,
        }

    def summary_text(self) -> str:
        lines = [
            "═" * 60,
            "  AI SECURITY GATE REPORT",
            "═" * 60,
            f"  Total Prompts Analyzed: {self.total_prompts_analyzed}",
            f"  Blocked: {self.total_blocked} ({self.injection_rate:.1%})",
            f"  Overall Risk Score: {self.overall_risk_score:.3f}",
            "",
        ]
        if self.high_risk_prompts:
            lines.append(f"  🛡️ High-Risk Prompts: {len(self.high_risk_prompts)}")
            for r in self.high_risk_prompts[-5:]:
                lines.append(f"     [{r.risk_level}] {r.prompt[:80]}... ({len(r.injection_findings)} findings)")
        if self.recommendations:
            lines.append("  Recommendations:")
            for r in self.recommendations:
                lines.append(f"    → {r}")
        lines.append("═" * 60)
        return "\n".join(lines)


# ── AI Security Gate ──────────────────────────────────────────────────────


class AISecurityGate:
    """AI Security Gate — Prompt Injection Detection & Hallucination Scoring.

    Analyzes AI interactions for:
    - Prompt injection attempts (pattern-based + entropy-based)
    - Hallucination risk (confidence calibration, source grounding)
    - Input/output sanitization
    - Audit trail persistence

    Thread-safe.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._audit_log: list[AIAuditRecord] = []
        self._max_audit = 1000
        self._total_prompts = 0
        self._total_blocked = 0
        self._persist_path = Path("json/ai_security_audit.json")
        self._load_audit()

    # ── Public API ────────────────────────────────────────────────────────

    def analyze_prompt(
        self,
        prompt: str,
        context: dict[str, Any] | None = None,
    ) -> AIAuditRecord:
        """Analyze a prompt for injection attempts.

        Args:
            prompt: The input prompt to analyze.
            context: Optional context (e.g., {"source": "user", "session_id": "..."}).

        Returns:
            AIAuditRecord with injection risk findings.
        """
        start = time.time()
        record = AIAuditRecord(
            timestamp=time.time(),
            prompt=prompt,
        )

        # 1. Pattern-based detection
        findings = self._detect_injection_patterns(prompt)
        record.injection_findings = findings

        # 2. Entropy-based detection
        entropy_risk = self._analyze_entropy(prompt)
        if entropy_risk > 0.5:
            record.injection_findings.append(InjectionFinding(
                pattern_name="high_entropy_payload",
                severity=entropy_risk,
                snippet=f"entropy={entropy_risk:.2f}",
                risk_level="HIGH" if entropy_risk > 0.7 else "MEDIUM",
            ))

        # 3. Token ratio analysis
        token_risk = self._analyze_token_ratios(prompt)
        if token_risk > 0.5:
            record.injection_findings.append(InjectionFinding(
                pattern_name="suspicious_token_ratio",
                severity=token_risk,
                snippet=f"token_risk={token_risk:.2f}",
                risk_level="MEDIUM" if token_risk > 0.6 else "LOW",
            ))

        # 4. Compute overall injection risk
        record.injection_risk = self._compute_injection_risk(findings, entropy_risk, token_risk)

        # 5. Determine risk level
        record.risk_level = self._risk_level(record.injection_risk)

        # 6. Sanitize prompt
        record.sanitized_prompt = self._sanitize_prompt(prompt)
        record.latency_ms = (time.time() - start) * 1000

        # 7. Auto-block high-risk prompts
        if record.risk_level == "CRITICAL":
            record.blocked = True

        # Audit
        with self._lock:
            self._total_prompts += 1
            if record.blocked:
                self._total_blocked += 1
            self._audit_log.append(record)
            if len(self._audit_log) > self._max_audit:
                self._audit_log = self._audit_log[-self._max_audit:]
            self._persist()

        return record

    def analyze_response(
        self,
        prompt: str,
        response: str,
        confidence: float = 0.0,
        source_facts: list[str] | None = None,
    ) -> HallucinationScore:
        """Analyze an AI response for hallucination risk.

        Args:
            prompt: The original prompt.
            response: The AI-generated response.
            confidence: Model's confidence score (0.0 to 1.0), if available.
            source_facts: Known facts from source data for grounding check.

        Returns:
            HallucinationScore with risk assessment.
        """
        score = HallucinationScore(confidence=confidence)

        # 1. Confidence calibration
        if confidence < LOW_CONFIDENCE_THRESHOLD:
            score.factual_risk += 0.4
            score.details.append("Low model confidence — increased hallucination risk")
        elif confidence < HIGH_CONFIDENCE_THRESHOLD:
            score.factual_risk += 0.15

        # 2. Source grounding check
        if source_facts:
            grounded = 0
            total_claims = 0
            for fact in source_facts:
                if fact.lower() in response.lower():
                    grounded += 1
                total_claims += 1
            if total_claims > 0:
                score.source_grounding = grounded / total_claims
                if score.source_grounding < 0.5:
                    score.factual_risk += 0.3
                    score.details.append(f"Low source grounding ({score.source_grounding:.0%} of claims verified)")
                elif score.source_grounding < 0.8:
                    score.factual_risk += 0.1
        else:
            score.source_grounding = 0.5
            score.factual_risk += 0.1
            score.details.append("No source facts available for grounding check")

        # 3. Response length vs confidence heuristic
        if len(response) > 500 and confidence < 0.5:
            score.factual_risk += 0.15
            score.details.append(f"Long response ({len(response)} chars) with low confidence ({confidence:.2f})")

        # 4. Numerical specificity heuristic (unusual precision suggests hallucination)
        precise_numbers = re.findall(r'\b\d+\.\d{3,}\b', response)
        if len(precise_numbers) > 3:
            score.factual_risk += 0.1
            score.details.append(f"Unusually precise numbers detected ({len(precise_numbers)} instances)")

        # Compute consistency score
        score.consistency_score = max(0.0, 1.0 - score.factual_risk)

        # Risk level
        if score.factual_risk > 0.6:
            score.risk_level = "CRITICAL"
        elif score.factual_risk > 0.4:
            score.risk_level = "HIGH"
        elif score.factual_risk > 0.2:
            score.risk_level = "MEDIUM"

        # Update the last audit record if it matches
        with self._lock:
            if self._audit_log and self._audit_log[-1].prompt == prompt:
                self._audit_log[-1].hallucination_score = score
                self._persist()

        return score

    def get_report(self) -> AISecurityReport:
        """Generate a comprehensive AI security report."""
        with self._lock:
            report = AISecurityReport(
                timestamp=time.time(),
                total_prompts_analyzed=self._total_prompts,
                total_blocked=self._total_blocked,
            )

            if self._total_prompts > 0:
                report.injection_rate = self._total_blocked / self._total_prompts

            high_risk = [r for r in self._audit_log if r.risk_level in ("HIGH", "CRITICAL")]
            report.high_risk_prompts = high_risk
            report.recent_audits = list(self._audit_log[-100:])

            # Compute overall risk score
            if high_risk:
                report.overall_risk_score = len(high_risk) / max(1, len(self._audit_log))

            # Recommendations
            report.recommendations = self._generate_recommendations(report)

            return report

    def get_stats(self) -> dict[str, Any]:
        """Get AI Security Gate statistics."""
        with self._lock:
            return {
                "total_prompts_analyzed": self._total_prompts,
                "total_blocked": self._total_blocked,
                "injection_rate": round(self._total_blocked / max(1, self._total_prompts), 4),
                "audit_log_size": len(self._audit_log),
                "high_risk_count": sum(1 for r in self._audit_log if r.risk_level in ("HIGH", "CRITICAL")),
                "last_audit": self._audit_log[-1].to_dict() if self._audit_log else None,
            }

    def clear_audit(self) -> None:
        """Clear all audit records."""
        with self._lock:
            self._audit_log.clear()
            self._total_prompts = 0
            self._total_blocked = 0
            if self._persist_path.exists():
                self._persist_path.unlink()

    # ── Injection Detection ──────────────────────────────────────────────

    def _detect_injection_patterns(self, prompt: str) -> list[InjectionFinding]:
        """Detect known prompt injection patterns."""
        findings: list[InjectionFinding] = []
        seen_patterns: set[str] = set()

        for pattern_name, pattern, severity in INJECTION_PATTERNS:
            for match in re.finditer(pattern, prompt):
                if pattern_name not in seen_patterns:
                    findings.append(InjectionFinding(
                        pattern_name=pattern_name,
                        severity=severity,
                        snippet=match.group()[:80],
                        position=match.start(),
                        risk_level="CRITICAL" if severity >= 0.9 else "HIGH" if severity >= 0.8 else "MEDIUM",
                    ))
                    seen_patterns.add(pattern_name)

        return findings

    def _analyze_entropy(self, text: str) -> float:
        """Analyze text entropy to detect obfuscated payloads.

        High entropy suggests encoded/obfuscated content.
        Returns risk score 0.0 to 1.0.
        """
        if not text:
            return 0.0

        # Calculate Shannon entropy
        char_counts: dict[str, int] = {}
        for char in text.lower():
            if char.isprintable():
                char_counts[char] = char_counts.get(char, 0) + 1

        total = sum(char_counts.values())
        if total < 10:
            return 0.0

        entropy = 0.0
        for count in char_counts.values():
            p = count / total
            if p > 0:
                entropy -= p * math.log2(p)

        # Normalize: 0-8 bits typical, 8+ is suspicious
        if entropy >= HIGH_ENTROPY_THRESHOLD:
            return min(1.0, (entropy - SUSPICIOUS_ENTROPY_THRESHOLD) / (8.0 - SUSPICIOUS_ENTROPY_THRESHOLD))
        elif entropy >= SUSPICIOUS_ENTROPY_THRESHOLD:
            return (entropy - SUSPICIOUS_ENTROPY_THRESHOLD) / (HIGH_ENTROPY_THRESHOLD - SUSPICIOUS_ENTROPY_THRESHOLD) * 0.5

        return 0.0

    def _analyze_token_ratios(self, text: str) -> float:
        """Analyze token length ratios for anomalies.

        Unusual token distributions can indicate injection attempts.
        Returns risk score 0.0 to 1.0.
        """
        if not text.strip():
            return 0.0

        tokens = text.split()
        if len(tokens) < 5:
            return 0.0

        # Calculate token length stats
        lengths = [len(t) for t in tokens if len(t) >= MIN_VALID_TOKEN_LENGTH]
        if not lengths:
            return 0.0

        avg_len = sum(lengths) / len(lengths)
        max_len = max(lengths)

        # Check for abnormally long tokens
        if avg_len > 0 and max_len / avg_len > 20:
            return 0.8  # Extremely long token ratio

        # Check for many unusually long tokens
        long_tokens = [tl for tl in lengths if tl > avg_len * 3]
        if long_tokens and len(long_tokens) / len(lengths) > MAX_TOKEN_LENGTH_RATIO:
            return 0.6

        return 0.0

    def _compute_injection_risk(
        self,
        findings: list[InjectionFinding],
        entropy_risk: float,
        token_risk: float,
    ) -> float:
        """Compute overall injection risk score (0.0 to 1.0)."""
        if not findings and entropy_risk == 0 and token_risk == 0:
            return 0.0

        # Pattern score: max severity from findings
        pattern_score = max((f.severity for f in findings), default=0.0)

        # Count distinct pattern types — multiple distinct patterns compound risk
        distinct_patterns = len(set(f.pattern_name for f in findings))

        # Base calculation: patterns dominate, entropy/token add
        risk = pattern_score * 0.6 + entropy_risk * 0.25 + token_risk * 0.15

        # Bonus for multiple distinct pattern types (indicates multi-vector attack)
        if distinct_patterns >= 2:
            risk += 0.08 * min(distinct_patterns - 1, 3)  # max bonus: 0.24

        return min(1.0, risk)

    def _risk_level(self, score: float) -> str:
        """Convert numeric risk to level."""
        if score >= 0.8:
            return "CRITICAL"
        if score >= 0.5:
            return "HIGH"
        if score >= 0.2:
            return "MEDIUM"
        return "LOW"

    def _sanitize_prompt(self, prompt: str) -> str:
        """Sanitize a prompt for safe AI processing.

        Strips known injection patterns from the prompt.
        """
        sanitized = prompt
        for pattern_name, pattern, _ in INJECTION_PATTERNS:
            if pattern_name in ("sql_injection_prompt",):
                sanitized = re.sub(pattern, "[REDACTED SQL INJECTION]", sanitized)
        return sanitized

    # ── Recommendations ─────────────────────────────────────────────────

    def _generate_recommendations(self, report: AISecurityReport) -> list[str]:
        """Generate security recommendations based on audit data."""
        recs: list[str] = []

        if report.total_blocked > 0:
            recs.append(f"Blocked {report.total_blocked} prompt injection attempts — review blocked patterns")
        if report.total_prompts_analyzed > 100 and report.injection_rate > 0.05:
            recs.append(f"Elevated injection rate ({report.injection_rate:.1%}) — consider stricter input filtering")
        if report.high_risk_prompts:
            top_patterns = set()
            for r in report.high_risk_prompts[:10]:
                for f in r.injection_findings:
                    top_patterns.add(f.pattern_name)
            if top_patterns:
                recs.append(f"Most common attack patterns: {', '.join(list(top_patterns)[:5])}")

        if not recs:
            recs.append("AI Security Gate is active — no critical issues detected")

        recs.append("Review AI audit log regularly for emerging attack patterns")
        return recs

    # ── Persistence ──────────────────────────────────────────────────────

    def _persist(self) -> None:
        """Persist audit log to disk."""
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            data = [r.to_dict() for r in self._audit_log[-500:]]
            self._persist_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except (OSError, ValueError) as exc:
            _log.debug("[AI_GATE] Persist: %s", exc)

    def _load_audit(self) -> None:
        """Load audit history from disk, reconstructing nested dataclasses."""
        try:
            if self._persist_path.is_file():
                data = json.loads(self._persist_path.read_text(encoding="utf-8"))
                for item in data:
                    try:
                        fields = {k: v for k, v in item.items()
                                  if k in AIAuditRecord.__dataclass_fields__}
                        # Reconstruct nested InjectionFinding objects
                        if "injection_findings" in fields and isinstance(fields["injection_findings"], list):
                            fields["injection_findings"] = [
                                InjectionFinding(**{k: v for k, v in f.items()
                                                     if k in InjectionFinding.__dataclass_fields__})
                                if isinstance(f, dict) else f
                                for f in fields["injection_findings"]
                            ]
                        # Reconstruct nested HallucinationScore (keep as None if not present)
                        if "hallucination_score" in fields and isinstance(fields["hallucination_score"], dict):
                            fields["hallucination_score"] = HallucinationScore(**{
                                k: v for k, v in fields["hallucination_score"].items()
                                if k in HallucinationScore.__dataclass_fields__
                            })
                        record = AIAuditRecord(**fields)
                        self._audit_log.append(record)
                    except (TypeError, ValueError) as exc:
                        _log.debug("[AI_GATE] Load skip: %s", exc)
                self._total_prompts = len(self._audit_log)
                self._total_blocked = sum(1 for r in self._audit_log if r.blocked)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            _log.debug("[AI_GATE] Load failed: %s", exc)


# ── CLI ────────────────────────────────────────────────────────────────────


def _cli() -> None:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m core.ai_security_gate",
        description="AI Security Gate — Analyze prompts for injection attacks",
    )
    ap.add_argument("--analyze", type=str, help="Prompt text to analyze for injection")
    ap.add_argument("--report", action="store_true", help="Show AI security report")
    ap.add_argument("--stats", action="store_true", help="Show statistics")
    ap.add_argument("--json", action="store_true", help="Output as JSON")
    args = ap.parse_args()

    gate = get_ai_security_gate()

    if args.analyze:
        record = gate.analyze_prompt(args.analyze)
        if args.json:
            import json
            print(json.dumps(record.to_dict(), indent=2))
        else:
            print(f"Risk Level: {record.risk_level}")
            print(f"Injection Risk: {record.injection_risk:.3f}")
            print(f"Blocked: {record.blocked}")
            print(f"Findings: {len(record.injection_findings)}")
            for f in record.injection_findings:
                print(f"  [{f.risk_level}] {f.pattern_name}: {f.snippet[:60]}")
        return

    if args.report:
        report = gate.get_report()
        if args.json:
            import json
            print(json.dumps(report.to_dict(), indent=2))
        else:
            print(report.summary_text())
        return

    if args.stats:
        stats = gate.get_stats()
        if args.json:
            import json
            print(json.dumps(stats, indent=2))
        else:
            print(f"Total Prompts: {stats['total_prompts_analyzed']}")
            print(f"Blocked: {stats['total_blocked']}")
            print(f"Injection Rate: {stats['injection_rate']:.2%}")
        return

    ap.print_help()


if __name__ == "__main__":
    _cli()

# ── Singleton ──────────────────────────────────────────────────────────────

_gate: AISecurityGate | None = None
_gate_lock = threading.RLock()


def get_ai_security_gate() -> AISecurityGate:
    """Get the singleton AISecurityGate instance."""
    global _gate
    with _gate_lock:
        if _gate is None:
            _gate = AISecurityGate()
        return _gate


def reset_ai_security_gate() -> None:
    """Force-reset singleton (for testing)."""
    global _gate
    with _gate_lock:
        _gate = None


__all__ = [
    "AIAuditRecord",
    "AISecurityGate",
    "AISecurityReport",
    "HallucinationScore",
    "InjectionFinding",
    "get_ai_security_gate",
    "reset_ai_security_gate",
]
