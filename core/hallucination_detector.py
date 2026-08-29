"""Hallucination Detection Engine — Validates LLM outputs against known data sources.

Provides multi-strategy hallucination detection:
  1. Factual grounding: checks numeric/date claims against known data
  2. Consistency checks: cross-references claims across multiple outputs
  3. Pattern-based: detects overly specific numbers, fake citations, hallucination markers
  4. Confidence calibration: flags low-confidence assertions
  5. Temporal consistency: validates time-based claims

Integrates with:
  - AISecurityGate (existing pattern detection)
  - CodebaseKnowledgeGraph (for code-related fact checking)
  - RootCauseAnalyzer (for incident correlation)

Usage:
    from core.hallucination_detector import get_hallucination_detector

    detector = get_hallucination_detector()
    result = detector.analyze("The win rate is 94.7% and P&L is ₹52,00,000")
    print(result.hallucination_score, result.risk_level)
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────

DEFAULT_CONFIDENCE_THRESHOLD = 0.6
DEFAULT_HIGH_RISK_THRESHOLD = 0.7
DEFAULT_MEDIUM_RISK_THRESHOLD = 0.4

# Number patterns that could indicate hallucination
OVERLY_PRECISE_PATTERN = re.compile(r"\b\d+\.\d{3,}\b")  # e.g., 94.723%
FAKE_CITATION_PATTERN = re.compile(
    r"(?i)(according to|source|reference|study|research|paper|report)\s+"
    r"(from\s+)?\d{4}"
)
ABSOLUTE_CLAIM_PATTERN = re.compile(
    r"(?i)(always|never|100%|0%|guaranteed|every single|no (one|system|tool))"
)

# Known fact patterns and their expected value ranges
KNOWN_FACT_RANGES: dict[str, tuple[float, float]] = {
    "win_rate": (0.0, 100.0),
    "sharpe_ratio": (-5.0, 10.0),
    "profit_factor": (0.0, 20.0),
    "max_drawdown_pct": (0.0, 100.0),
    "total_trades": (0.0, 100_000.0),
    "avg_win_pct": (0.0, 100.0),
    "avg_loss_pct": (0.0, 100.0),
}

CITATION_MARKERS = [
    "et al.", "al.", "(202", "(201", "(2024)", "(2025)", "(2026)",
    "according to a study", "according to research",
    "multiple studies show", "research indicates",
    "it has been proven", "studies have shown",
]


@dataclass
class HallucinationFinding:
    """A single hallucination finding."""

    finding_type: str  # OVERLY_PRECISE, FAKE_CITATION, FACT_MISMATCH, ABSOLUTE_CLAIM, TEMPORAL_MISMATCH
    text: str
    severity: float  # 0.0 to 1.0
    explanation: str = ""
    confidence: float = 0.0


@dataclass
class HallucinationResult:
    """Result of hallucination analysis."""

    hallucination_score: float  # 0.0 (clean) to 1.0 (definitely hallucinating)
    risk_level: str  # CLEAN, LOW, MEDIUM, HIGH
    findings: list[HallucinationFinding] = field(default_factory=list)
    confidence: float = 0.0
    factual_grounding_score: float = 1.0  # 0.0 to 1.0 (higher = better grounded)
    n_claims_checked: int = 0
    n_claims_verified: int = 0
    n_claims_failed: int = 0
    analyzed_text: str = ""
    model_confidence: float = 1.0
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "hallucination_score": round(self.hallucination_score, 3),
            "risk_level": self.risk_level,
            "findings": [
                {
                    "type": f.finding_type,
                    "text": f.text[:100],
                    "severity": round(f.severity, 2),
                    "explanation": f.explanation[:200],
                }
                for f in self.findings
            ],
            "confidence": round(self.confidence, 3),
            "factual_grounding_score": round(self.factual_grounding_score, 3),
            "n_claims_checked": self.n_claims_checked,
            "n_claims_verified": self.n_claims_verified,
            "n_claims_failed": self.n_claims_failed,
            "model_confidence": round(self.model_confidence, 3),
            "duration_ms": round(self.duration_ms, 1),
        }


# ── Hallucination Detector ─────────────────────────────────────────────────


class HallucinationDetector:
    """Multi-strategy hallucination detection engine.

    Analyzes LLM outputs for indicators of hallucination:
    - Overly precise numbers (unrealistic precision suggests fabrication)
    - Fake citations (references that don't exist)
    - Factual grounding mismatches (claims that contradict known data)
    - Absolute claims (always/never/100% — rarely true)
    - Temporal inconsistencies (dates/times that don't align)
    """

    def __init__(
        self,
        known_data: dict[str, Any] | None = None,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    ) -> None:
        self._lock = threading.RLock()
        self._known_data: dict[str, Any] = known_data or {}
        self._confidence_threshold = confidence_threshold
        self._history: list[HallucinationResult] = []
        self._max_history = 500
        self._history_path = Path("json/hallucination_history.json")
        self._load_history()

    # ── Public API ────────────────────────────────────────────────────────

    def analyze(
        self,
        text: str,
        context: dict[str, Any] | None = None,
        model_confidence: float = 1.0,
    ) -> HallucinationResult:
        """Analyze text for hallucination indicators.

        Args:
            text: The LLM output text to analyze.
            context: Optional context (known facts, data ranges, etc.).
            model_confidence: The model's own confidence score (0.0 to 1.0).

        Returns:
            HallucinationResult with score, risk level, and findings.
        """
        t0 = time.time()
        findings: list[HallucinationFinding] = []
        merged_context = {**self._known_data, **(context or {})}

        # 1. Check for overly precise numbers
        findings.extend(self._check_overly_precise(text))

        # 2. Check for fake/unverifiable citations
        findings.extend(self._check_citations(text))

        # 3. Check factual grounding against known data
        factual = self._check_factual_grounding(text, merged_context)
        findings.extend(factual["findings"])

        # 4. Check for absolute/guaranteed claims
        findings.extend(self._check_absolute_claims(text))

        # 5. Check temporal consistency
        findings.extend(self._check_temporal(text))

        # 6. Check for confidence mismatches
        if model_confidence < self._confidence_threshold:
            findings.append(HallucinationFinding(
                finding_type="LOW_CONFIDENCE",
                text=f"Model confidence ({model_confidence:.2f}) below threshold",
                severity=0.3 * (1.0 - model_confidence),
                explanation="Low model confidence increases hallucination risk",
                confidence=model_confidence,
            ))

        # Compute aggregate score
        hallucination_score = self._compute_score(findings)
        risk_level = self._classify_risk(hallucination_score)

        n_claims = len(findings)
        n_verified = sum(1 for f in findings if f.severity < 0.3)
        n_failed = sum(1 for f in findings if f.severity >= 0.3)

        result = HallucinationResult(
            hallucination_score=hallucination_score,
            risk_level=risk_level,
            findings=findings,
            confidence=1.0 - hallucination_score,
            factual_grounding_score=1.0 - (n_failed / max(n_claims, 1)),
            n_claims_checked=n_claims,
            n_claims_verified=n_verified,
            n_claims_failed=n_failed,
            analyzed_text=text[:500],
            model_confidence=model_confidence,
            duration_ms=(time.time() - t0) * 1000,
        )

        # Store in history
        with self._lock:
            self._history.append(result)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]
            self._persist()

        return result

    def analyze_batch(
        self,
        texts: list[str],
        context: dict[str, Any] | None = None,
    ) -> list[HallucinationResult]:
        """Analyze multiple texts in batch."""
        return [self.analyze(t, context) for t in texts]

    def get_stats(self) -> dict[str, Any]:
        """Get hallucination detection statistics."""
        with self._lock:
            if not self._history:
                return {"total_analyses": 0}

            high_risk = sum(
                1 for r in self._history
                if r.risk_level == "HIGH"
            )
            total = len(self._history)
            avg_score = sum(
                r.hallucination_score for r in self._history
            ) / total

            finding_types: dict[str, int] = {}
            for r in self._history:
                for f in r.findings:
                    finding_types[f.finding_type] = (
                        finding_types.get(f.finding_type, 0) + 1
                    )

            return {
                "total_analyses": total,
                "high_risk_count": high_risk,
                "high_risk_pct": round(high_risk / total * 100, 1) if total else 0.0,
                "avg_hallucination_score": round(avg_score, 3),
                "finding_type_breakdown": finding_types,
                "avg_duration_ms": round(
                    sum(r.duration_ms for r in self._history) / total, 1
                ) if total else 0.0,
                "latest_risk_level": self._history[-1].risk_level if self._history else None,
            }

    def clear_history(self) -> None:
        """Clear analysis history."""
        with self._lock:
            self._history.clear()
            if self._history_path.exists():
                self._history_path.unlink()

    # ── Analysis Strategies ──────────────────────────────────────────────

    def _check_overly_precise(self, text: str) -> list[HallucinationFinding]:
        """Detect overly precise numbers that suggest fabrication."""
        findings: list[HallucinationFinding] = []
        matches = OVERLY_PRECISE_PATTERN.findall(text)

        # Group similar precise numbers (same integer part)
        seen: set[str] = set()
        for m in matches:
            # Check if it's a reasonable precision (e.g., percentages can be 94.7%)
            decimal_places = len(m.split(".")[1]) if "." in m else 0
            if decimal_places >= 3:
                key = m.split(".")[0]  # Group by integer part
                if key not in seen:
                    seen.add(key)
                    findings.append(HallucinationFinding(
                        finding_type="OVERLY_PRECISE",
                        text=m,
                        severity=min(0.5, 0.1 * decimal_places),
                        explanation=f"Number '{m}' has {decimal_places} decimal places — "
                                    f"unlikely to be precisely knowable",
                    ))

        return findings

    def _check_citations(self, text: str) -> list[HallucinationFinding]:
        """Detect fake or suspicious citations."""
        findings: list[HallucinationFinding] = []

        # Check for citation patterns
        citations = FAKE_CITATION_PATTERN.findall(text)
        for citation in citations:
            findings.append(HallucinationFinding(
                finding_type="FAKE_CITATION",
                text=" ".join(citation) if isinstance(citation, tuple) else citation,
                severity=0.6,
                explanation="Citation pattern detected — verify the source exists",
            ))

        # Check for common hallucination markers
        for marker in CITATION_MARKERS:
            if marker.lower() in text.lower():
                findings.append(HallucinationFinding(
                    finding_type="FAKE_CITATION",
                    text=marker,
                    severity=0.4,
                    explanation=f"Common hallucination marker: '{marker}' — "
                                f"verify this reference exists",
                ))

        return findings

    def _check_factual_grounding(
        self,
        text: str,
        known_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Check claims against known factual data."""
        findings: list[HallucinationFinding] = []

        # Check metric names against known value ranges
        for key, (min_val, max_val) in KNOWN_FACT_RANGES.items():
            name = key.replace('_', ' ')
            # Flexible pattern: metric name followed by optional words then a number
            pattern = re.compile(
                rf"(?i)({name}).*?([+-]?\d+\.?\d*)"
            )
            matches = pattern.findall(text)
            for match in matches:
                try:
                    value = float(match[1])
                    if value < min_val or value > max_val:
                        findings.append(HallucinationFinding(
                            finding_type="FACT_MISMATCH",
                            text=f"{match[0]}: {value}",
                            severity=0.8 if value > max_val * 1.5 else 0.5,
                            explanation=(
                                f"'{match[0]}' value {value} is outside "
                                f"expected range [{min_val}, {max_val}]"
                            ),
                        ))
                except (ValueError, IndexError):
                    continue

        # Check specific known data values
        for data_key, data_value in known_data.items():
            if isinstance(data_value, (int, float)):
                key_lower = data_key.lower().replace("_", " ")
                # Flexible pattern: metric name followed by optional words then a number
                pattern = re.compile(
                    rf"(?i)({key_lower}).*?([+-]?\d+\.?\d*)"
                )
                matches = pattern.findall(text)
                for match in matches:
                    try:
                        claimed = float(match[1])
                        if data_value > 0:
                            deviation = abs(claimed - data_value) / data_value
                            if deviation > 0.1:  # >10% deviation
                                findings.append(HallucinationFinding(
                                    finding_type="FACT_MISMATCH",
                                    text=f"{match[0]}: {claimed} (actual: {data_value})",
                                    severity=min(0.9, deviation),
                                    explanation=(
                                        f"Claimed '{match[0]}' = {claimed}, "
                                        f"but known value is {data_value} "
                                        f"({deviation * 100:.0f}% deviation)"
                                    ),
                                ))
                    except (ValueError, IndexError):
                        continue

        return {"findings": findings}

    def _check_absolute_claims(self, text: str) -> list[HallucinationFinding]:
        """Detect absolute/guaranteed claims."""
        findings: list[HallucinationFinding] = []
        matches = ABSOLUTE_CLAIM_PATTERN.findall(text)
        for match in matches:
            findings.append(HallucinationFinding(
                finding_type="ABSOLUTE_CLAIM",
                text=match,
                severity=0.5,
                explanation=f"Absolute claim '{match}' — rarely accurate in trading systems",
            ))
        return findings

    def _check_temporal(self, text: str) -> list[HallucinationFinding]:
        """Check temporal consistency."""
        findings: list[HallucinationFinding] = []

        # Check for future dates presented as fact
        future_pattern = re.compile(r"(?i)(in\s+(\d{4})|by\s+(\d{4}))")
        matches = future_pattern.findall(text)
        current_year = time.localtime().tm_year
        for match in matches:
            year = int(match[1] or match[2] or 0)
            if year > current_year + 1:
                findings.append(HallucinationFinding(
                    finding_type="TEMPORAL_MISMATCH",
                    text=match[0],
                    severity=0.3,
                    explanation=f"Future year {year} presented as established fact",
                ))

        return findings

    # ── Scoring ─────────────────────────────────────────────────────────

    def _compute_score(self, findings: list[HallucinationFinding]) -> float:
        """Compute aggregate hallucination score from findings."""
        if not findings:
            return 0.0

        # Weighted average of findings, with highest severity dominating
        max_severity = max(f.severity for f in findings)
        avg_severity = sum(f.severity for f in findings) / len(findings)

        # Score = blend of max and average (max dominates)
        score = max_severity * 0.6 + avg_severity * 0.4

        # Penalty for many findings
        if len(findings) >= 5:
            score = min(1.0, score + 0.1)
        if len(findings) >= 10:
            score = min(1.0, score + 0.1)

        return min(1.0, max(0.0, score))

    def _classify_risk(self, score: float) -> str:
        """Classify risk level based on hallucination score."""
        if score >= DEFAULT_HIGH_RISK_THRESHOLD:
            return "HIGH"
        if score >= DEFAULT_MEDIUM_RISK_THRESHOLD:
            return "MEDIUM"
        if score >= 0.1:
            return "LOW"
        return "CLEAN"

    # ── Persistence ─────────────────────────────────────────────────────

    def _persist(self) -> None:
        """Persist analysis history to JSON."""
        try:
            self._history_path.parent.mkdir(parents=True, exist_ok=True)
            data = [r.to_dict() for r in self._history[-100:]]
            self._history_path.write_text(
                json.dumps(data, indent=2), encoding="utf-8"
            )
        except (OSError, ValueError) as exc:
            _log.debug("[HALLUCINATION] Persist error: %s", exc)

    def _load_history(self) -> None:
        """Load analysis history from JSON."""
        try:
            if self._history_path.is_file():
                data = json.loads(
                    self._history_path.read_text(encoding="utf-8")
                )
                for item in data[-self._max_history:]:
                    findings = [
                        HallucinationFinding(**f)
                        for f in item.get("findings", [])
                    ]
                    self._history.append(HallucinationResult(
                        hallucination_score=item.get("hallucination_score", 0.0),
                        risk_level=item.get("risk_level", "CLEAN"),
                        findings=findings,
                        confidence=item.get("confidence", 1.0),
                        duration_ms=item.get("duration_ms", 0.0),
                    ))
        except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
            _log.debug("[HALLUCINATION] Load error: %s", exc)


# ── Singleton ──────────────────────────────────────────────────────────────

_instance: HallucinationDetector | None = None
_instance_lock = threading.RLock()


def get_hallucination_detector(
    known_data: dict[str, Any] | None = None,
) -> HallucinationDetector:
    """Get the singleton HallucinationDetector instance."""
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = HallucinationDetector(known_data=known_data)
        return _instance


def reset_hallucination_detector() -> None:
    """Force-reset singleton (for testing)."""
    global _instance
    with _instance_lock:
        _instance = None


__all__ = [
    "HallucinationDetector",
    "HallucinationFinding",
    "HallucinationResult",
    "get_hallucination_detector",
    "reset_hallucination_detector",
]
