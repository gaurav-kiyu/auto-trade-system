"""
Blue/Green Deployment Model - Item 15

Safer releases:
- old engine running
- new engine shadowing
- compare decisions
- switch when validated

Production maturity move.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.time_provider import time_provider

_log = logging.getLogger(__name__)


class DeploymentStatus(Enum):
    """Deployment status"""
    IDLE = "IDLE"
    DEPLOYING = "DEPLOYING"
    SHADOWING = "SHADOWING"
    VALIDATING = "VALIDATING"
    ACTIVE = "ACTIVE"
    ROLLING_BACK = "ROLLING_BACK"


@dataclass
class DeploymentConfig:
    """Blue/green deployment configuration"""
    version: str
    primary_color: str
    shadow_color: str
    validation_metrics: list[str] = field(default_factory=list)
    min_shadow_samples: int = 100
    max_shadow_duration_seconds: int = 3600
    divergence_threshold_pct: float = 5.0


@dataclass
class ComparisonResult:
    """Result of comparing primary vs shadow"""
    timestamp: str
    primary_signal: dict[str, Any]
    shadow_signal: dict[str, Any]
    match: bool
    divergence_pct: float
    decision_diff: str


class BlueGreenDeployment:
    """
    Blue/green deployment manager.
    Enables safe releases with shadow testing.
    """

    def __init__(self):
        self._primary_engine: Any | None = None
        self._shadow_engine: Any | None = None
        self._config: DeploymentConfig | None = None
        self._status = DeploymentStatus.IDLE
        self._lock = threading.Lock()

        self._comparisons: list[ComparisonResult] = []
        self._shadow_count = 0
        self._divergence_count = 0
        self._start_time: str | None = None

    def configure(self, version: str) -> None:
        """Configure deployment"""
        self._config = DeploymentConfig(
            version=version,
            primary_color="blue",
            shadow_color="green",
            validation_metrics=["signal_direction", "entry_price", "position_size"],
            min_shadow_samples=100,
            max_shadow_duration_seconds=3600,
            divergence_threshold_pct=5.0,
        )
        _log.info(f"Blue/green deployment configured: v{version}")

    def deploy_primary(self, engine: Any) -> bool:
        """Deploy primary (active) engine"""
        with self._lock:
            if self._status in [DeploymentStatus.SHADOWING, DeploymentStatus.VALIDATING]:
                _log.warning("Cannot deploy primary while shadow is active")
                return False

            self._primary_engine = engine
            self._status = DeploymentStatus.ACTIVE
            _log.info(f"Primary engine deployed: v{self._config.version if self._config else 'unknown'}")
            return True

    def start_shadow(self, shadow_engine: Any) -> bool:
        """Start shadow mode with new engine"""
        with self._lock:
            if not self._primary_engine:
                _log.error("No primary engine deployed")
                return False

            self._shadow_engine = shadow_engine
            self._status = DeploymentStatus.SHADOWING
            self._start_time = time_provider.format_ts()
            self._shadow_count = 0
            self._divergence_count = 0
            _log.info("Shadow mode started - new engine computing but not trading")

    def compare_decision(
        self,
        primary_result: dict[str, Any],
        shadow_result: dict[str, Any],
    ) -> ComparisonResult:
        """Compare primary vs shadow decisions"""
        if self._status != DeploymentStatus.SHADOWING:
            return None

        match = self._check_match(primary_result, shadow_result)

        divergence = self._calculate_divergence(primary_result, shadow_result)

        result = ComparisonResult(
            timestamp=time_provider.format_ts(),
            primary_signal=primary_result,
            shadow_signal=shadow_result,
            match=match,
            divergence_pct=divergence,
            decision_diff=self._get_diff_description(primary_result, shadow_result),
        )

        with self._lock:
            self._comparisons.append(result)
            self._shadow_count += 1
            if not match:
                self._divergence_count += 1

        return result

    def _check_match(self, primary: dict, shadow: dict) -> bool:
        """Check if decisions match"""
        if not self._config:
            return True

        for metric in self._config.validation_metrics:
            if primary.get(metric) != shadow.get(metric):
                return False
        return True

    def _calculate_divergence(self, primary: dict, shadow: dict) -> float:
        """Calculate divergence percentage"""
        try:
            p_price = primary.get("price", 0)
            s_price = shadow.get("price", 0)
            if p_price == 0:
                return 0.0
            return abs((s_price - p_price) / p_price) * 100
        except:
            return 0.0

    def _get_diff_description(self, primary: dict, shadow: dict) -> str:
        """Get description of differences"""
        diffs = []
        for key in ["signal", "price", "quantity", "stop_loss", "target"]:
            p = primary.get(key)
            s = shadow.get(key)
            if p != s:
                diffs.append(f"{key}: {p} vs {s}")
        return "; ".join(diffs) if diffs else "none"

    def should_promote(self) -> bool:
        """Check if shadow should be promoted to primary"""
        if self._status != DeploymentStatus.SHADOWING:
            return False

        if not self._config:
            return False

        if self._shadow_count < self._config.min_shadow_samples:
            return False

        elapsed = time.time() - time.mktime(time.strptime(self._start_time, "%Y-%m-%d %H:%M:%S"))
        if elapsed > self._config.max_shadow_duration_seconds:
            _log.warning("Max shadow duration reached")

        divergence_rate = (self._divergence_count / self._shadow_count * 100) if self._shadow_count > 0 else 0

        return divergence_rate < self._config.divergence_threshold_pct

    def promote_shadow(self) -> bool:
        """Promote shadow to primary"""
        if not self.should_promote():
            _log.warning("Promotion criteria not met")
            return False

        with self._lock:
            self._primary_engine = self._shadow_engine
            self._shadow_engine = None
            self._status = DeploymentStatus.ACTIVE
            _log.info("Shadow promoted to primary!")
            return True

    def rollback(self) -> bool:
        """Rollback to previous version"""
        with self._lock:
            self._shadow_engine = None
            self._status = DeploymentStatus.ROLLING_BACK
            _log.warning("Rolling back to previous version")
            self._status = DeploymentStatus.ACTIVE
            return True

    def get_status(self) -> dict[str, Any]:
        """Get deployment status"""
        return {
            "status": self._status.value,
            "version": self._config.version if self._config else None,
            "shadow_samples": self._shadow_count,
            "divergences": self._divergence_count,
            "divergence_rate": (self._divergence_count / self._shadow_count * 100) if self._shadow_count > 0 else 0,
            "can_promote": self.should_promote(),
        }


_deployment: BlueGreenDeployment | None = None
_deployment_lock = threading.Lock()


def get_blue_green_deployment() -> BlueGreenDeployment:
    """Get singleton blue/green deployment"""
    global _deployment
    with _deployment_lock:
        if _deployment is None:
            _deployment = BlueGreenDeployment()
        return _deployment
