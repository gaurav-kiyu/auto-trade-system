"""
API Gateway / Control Plane - Item 23

Future control interface:
- pause strategy
- kill switch
- update flags
- health dashboard
- broker state

Provides unified REST API for runtime control.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from core.datetime_ist import now_ist

_log = logging.getLogger(__name__)


class ControlAction(Enum):
    """Control actions that can be triggered via API"""
    PAUSE = "PAUSE"
    RESUME = "RESUME"
    HARD_HALT = "HARD_HALT"
    SOFT_STOP = "SOFT_STOP"
    UPDATE_FEATURE_FLAG = "UPDATE_FEATURE_FLAG"
    UPDATE_RISK_LIMIT = "UPDATE_RISK_LIMIT"
    SWITCH_BROKER = "SWITCH_BROKER"
    RELOAD_CONFIG = "RELOAD_CONFIG"


@dataclass
class ControlRequest:
    """Control request from API"""
    action: ControlAction
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=now_ist)
    request_id: str = ""


@dataclass
class ControlResponse:
    """Control response to API"""
    success: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=now_ist)


class ControlPlane:
    """
    API Gateway / Control Plane for runtime control.
    
    Provides endpoints for:
    - Strategy pause/resume
    - Emergency kill switch
    - Feature flag updates
    - Risk limit modifications
    - Broker failover
    - Configuration reload
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._paused = False
        self._halted = False
        self._control_history: list[dict[str, Any]] = []
        self._handlers: dict[ControlAction, Callable[[ControlRequest], ControlResponse]] = {}
        self._max_history = 1000

    def register_handler(self, action: ControlAction, handler: Callable[[ControlRequest], ControlResponse]) -> None:
        """Register handler for specific control action"""
        with self._lock:
            self._handlers[action] = handler
            _log.info(f"Registered handler for {action.value}")

    def execute_control(self, request: ControlRequest) -> ControlResponse:
        """Execute a control action"""
        with self._lock:
            if request.action == ControlAction.PAUSE:
                return self._handle_pause(request)
            elif request.action == ControlAction.RESUME:
                return self._handle_resume(request)
            elif request.action == ControlAction.HARD_HALT:
                return self._handle_hard_halt(request)
            elif request.action == ControlAction.SOFT_STOP:
                return self._handle_soft_stop(request)
            elif request.action == ControlAction.UPDATE_FEATURE_FLAG:
                return self._handle_update_feature_flag(request)
            elif request.action == ControlAction.UPDATE_RISK_LIMIT:
                return self._handle_update_risk_limit(request)
            elif request.action == ControlAction.SWITCH_BROKER:
                return self._handle_switch_broker(request)
            elif request.action == ControlAction.RELOAD_CONFIG:
                return self._handle_reload_config(request)
            else:
                return ControlResponse(False, f"Unknown action: {request.action}")

    def _handle_pause(self, request: ControlRequest) -> ControlResponse:
        """Pause all trading"""
        self._paused = True
        self._record_control(request, True, "Trading paused")
        _log.critical("CONTROL PLANE: Trading PAUSED via API")
        return ControlResponse(True, "Trading paused", {"paused": True})

    def _handle_resume(self, request: ControlRequest) -> ControlResponse:
        """Resume trading"""
        if self._halted:
            return ControlResponse(False, "Cannot resume: system is halted. Restart required.")
        self._paused = False
        self._record_control(request, True, "Trading resumed")
        _log.critical("CONTROL PLANE: Trading RESUMED via API")
        return ControlResponse(True, "Trading resumed", {"paused": False})

    def _handle_hard_halt(self, request: ControlRequest) -> ControlResponse:
        """Emergency halt - all trading stops"""
        self._paused = True
        self._halted = True
        reason = request.payload.get("reason", "Manual trigger")
        self._record_control(request, True, f"Hard halt: {reason}")
        _log.critical(f"CONTROL PLANE: HARD HALT TRIGGERED - {reason}")
        return ControlResponse(True, "Hard halt activated", {"halted": True})

    def _handle_soft_stop(self, request: ControlRequest) -> ControlResponse:
        """Soft stop - allow positions to close but no new entries"""
        self._paused = True
        self._record_control(request, True, "Soft stop initiated")
        _log.warning("CONTROL PLANE: Soft stop initiated")
        return ControlResponse(True, "Soft stop initiated", {"soft_stop": True})

    def _handle_update_feature_flag(self, request: ControlRequest) -> ControlResponse:
        """Update feature flag at runtime"""
        from core.config.feature_flags import FeatureFlagName, get_feature_flags
        flag_name = request.payload.get("flag_name")
        enabled = request.payload.get("enabled")

        if not flag_name or enabled is None:
            return ControlResponse(False, "Missing flag_name or enabled")

        try:
            ff = get_feature_flags()
            ff.set_enabled(FeatureFlagName(flag_name), enabled)
            self._record_control(request, True, f"Feature flag {flag_name} = {enabled}")
            return ControlResponse(True, f"Feature flag {flag_name} updated", {"flag": flag_name, "enabled": enabled})
        except Exception as e:
            return ControlResponse(False, str(e))

    def _handle_update_risk_limit(self, request: ControlRequest) -> ControlResponse:
        """Update risk limit at runtime"""
        limit_name = request.payload.get("limit_name")
        new_value = request.payload.get("value")

        if not limit_name or new_value is None:
            return ControlResponse(False, "Missing limit_name or value")

        _log.warning(f"CONTROL PLANE: Risk limit update {limit_name} = {new_value}")
        self._record_control(request, True, f"Risk limit {limit_name} = {new_value}")
        return ControlResponse(True, f"Risk limit {limit_name} updated", {"limit": limit_name, "value": new_value})

    def _handle_switch_broker(self, request: ControlRequest) -> ControlResponse:
        """Trigger broker failover"""
        broker_name = request.payload.get("broker", "auto")
        _log.critical(f"CONTROL PLANE: Broker switch to {broker_name}")
        self._record_control(request, True, f"Broker switch to {broker_name}")
        return ControlResponse(True, f"Switching to {broker_name}", {"broker": broker_name})

    def _handle_reload_config(self, request: ControlRequest) -> ControlResponse:
        """Reload configuration from disk"""
        _log.info("CONTROL PLANE: Config reload requested")
        self._record_control(request, True, "Config reload")
        return ControlResponse(True, "Config reload initiated", {"reload": True})

    def _record_control(self, request: ControlRequest, success: bool, message: str) -> None:
        """Record control action in history"""
        entry = {
            "request_id": request.request_id or str(time.time()),
            "action": request.action.value,
            "payload": request.payload,
            "timestamp": request.timestamp.isoformat(),
            "success": success,
            "message": message
        }
        self._control_history.append(entry)
        if len(self._control_history) > self._max_history:
            self._control_history = self._control_history[-self._max_history:]

    def get_status(self) -> dict[str, Any]:
        """Get current control plane status"""
        with self._lock:
            return {
                "paused": self._paused,
                "halted": self._halted,
                "available_actions": [a.value for a in ControlAction],
                "recent_controls": self._control_history[-10:]
            }

    def is_paused(self) -> bool:
        """Check if trading is paused"""
        return self._paused

    def is_halted(self) -> bool:
        """Check if system is halted"""
        return self._halted


_control_plane: ControlPlane | None = None
_control_plane_lock = threading.Lock()


def get_control_plane() -> ControlPlane:
    """Get singleton control plane"""
    global _control_plane
    with _control_plane_lock:
        if _control_plane is None:
            _control_plane = ControlPlane()
        return _control_plane
