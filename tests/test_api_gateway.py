"""Tests for API Gateway / Control Plane"""
import pytest
from datetime import datetime
from core.api_gateway import (
    ControlPlane,
    ControlRequest,
    ControlResponse,
    ControlAction,
    get_control_plane,
)


class TestControlPlane:
    def test_singleton(self):
        cp1 = get_control_plane()
        cp2 = get_control_plane()
        assert cp1 is cp2
        
    def test_pause(self):
        cp = ControlPlane()
        request = ControlRequest(action=ControlAction.PAUSE, request_id="test-1")
        response = cp.execute_control(request)
        
        assert response.success is True
        assert cp.is_paused() is True
        
    def test_resume(self):
        cp = ControlPlane()
        cp._paused = True
        
        request = ControlRequest(action=ControlAction.RESUME, request_id="test-2")
        response = cp.execute_control(request)
        
        assert response.success is True
        assert cp.is_paused() is False
        
    def test_resume_after_halt_fails(self):
        cp = ControlPlane()
        cp._paused = True
        cp._halted = True
        
        request = ControlRequest(action=ControlAction.RESUME, request_id="test-3")
        response = cp.execute_control(request)
        
        assert response.success is False
        assert "halted" in response.message.lower()
        
    def test_hard_halt(self):
        cp = ControlPlane()
        request = ControlRequest(
            action=ControlAction.HARD_HALT,
            payload={"reason": "Test halt"},
            request_id="test-4"
        )
        response = cp.execute_control(request)
        
        assert response.success is True
        assert cp.is_halted() is True
        assert cp.is_paused() is True
        
    def test_soft_stop(self):
        cp = ControlPlane()
        request = ControlRequest(action=ControlAction.SOFT_STOP, request_id="test-5")
        response = cp.execute_control(request)
        
        assert response.success is True
        assert cp.is_paused() is True
        
    def test_control_history_tracking(self):
        cp = ControlPlane()
        
        request = ControlRequest(action=ControlAction.PAUSE, request_id="test-6")
        cp.execute_control(request)
        
        status = cp.get_status()
        assert len(status["recent_controls"]) == 1
        assert status["recent_controls"][0]["action"] == "PAUSE"
        
    def test_get_status(self):
        cp = ControlPlane()
        status = cp.get_status()
        
        assert "paused" in status
        assert "halted" in status
        assert "available_actions" in status
        assert isinstance(status["available_actions"], list)
        assert len(status["available_actions"]) > 0