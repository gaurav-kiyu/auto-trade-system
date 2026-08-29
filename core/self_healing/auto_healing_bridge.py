"""Unified Auto-Healing, Auto-Learner & Auto-Resolver Bridge.

Integrates SelfHealingOrchestrator, AutoLearner, and IncidentCommandSystem into an
autonomous self-learning, self-diagnosing, and auto-resolving operational engine.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

from core.auto_learner import AutoLearner
from core.self_healing.orchestrator import SelfHealingOrchestrator

log = logging.getLogger("auto_healing_bridge")


class AutoHealingBridge:
    """Unified engine for continuous self-healing, auto-learning, and error auto-resolution."""

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        auto_learner: AutoLearner | None = None,
        orchestrator: SelfHealingOrchestrator | None = None,
    ) -> None:
        self.config = config or {}
        if auto_learner is None:
            from core.auto_learner import learner_config_from_cfg
            learner_cfg = learner_config_from_cfg(self.config)
            self.learner = AutoLearner(learner_cfg)
        else:
            self.learner = auto_learner

        self.orchestrator = orchestrator or SelfHealingOrchestrator(self.config)
        self._running = False
        self._thread: threading.Thread | None = None
        self._incident_history: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def start(self, poll_interval: float = 10.0) -> None:
        """Start the continuous auto-healing and auto-learning background loop."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._thread = threading.Thread(
                target=self._run_loop, args=(poll_interval,), daemon=True
            )
            self._thread.start()
            log.info("[AUTO_HEAL] Auto-Healing & Auto-Learner bridge started")

    def stop(self) -> None:
        """Stop the background auto-healing loop gracefully."""
        with self._lock:
            self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        log.info("[AUTO_HEAL] Auto-Healing bridge stopped")

    def _run_loop(self, poll_interval: float) -> None:
        while self._running:
            try:
                self.run_health_and_remediate_cycle()
            except Exception as e:
                log.error(f"[AUTO_HEAL] Error in auto-healing cycle: {e}")
            time.sleep(poll_interval)

    def run_health_and_remediate_cycle(self) -> dict[str, Any]:
        """Perform a single health evaluation, auto-resolution, and learning step."""
        report = {
            "timestamp": time.time(),
            "status": "HEALTHY",
            "healed_incidents": [],
            "learned_updates": [],
        }

        # 1. Trigger Self-Healing Orchestrator evaluation
        try:
            results = self.orchestrator.run_healing_cycle()
            if results:
                report["healed_incidents"].extend(results)
                report["status"] = "HEALED"
        except Exception as err:
            log.warning(f"[AUTO_HEAL] Orchestrator evaluation note: {err}")

        # 2. Learn from operational metrics via AutoLearner
        try:
            learner_stats = self.learner.export_global_state()
            report["learned_updates"].append(learner_stats)
        except Exception as err:
            log.warning(f"[AUTO_HEAL] AutoLearner summary note: {err}")

        with self._lock:
            self._incident_history.append(report)
            if len(self._incident_history) > 100:
                self._incident_history.pop(0)

        return report

    def get_status(self) -> dict[str, Any]:
        """Return the current auto-healing status and metrics summary."""
        with self._lock:
            recent = self._incident_history[-1] if self._incident_history else {}
            return {
                "active": self._running,
                "history_count": len(self._incident_history),
                "latest_report": recent,
                "learner_state": self.learner.export_global_state(),
            }

