"""Tests for core/state_sync_manager.py - HA heartbeat & failover detection."""

from __future__ import annotations

import json
import os
import tempfile
import time

from core.state_sync_manager import StateSyncManager


class TestInit:
    def test_default_heartbeat_path(self) -> None:
        m = StateSyncManager(state_path="state.json")
        assert m.state_path == "state.json"
        assert m.heartbeat_path == "heartbeat.json"

    def test_custom_paths(self) -> None:
        m = StateSyncManager(state_path="custom.json", heartbeat_path="hb.json")
        assert m.state_path == "custom.json"
        assert m.heartbeat_path == "hb.json"


class TestUpdateHeartbeat:
    def test_writes_heartbeat_file(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            hb_path = f.name

        try:
            m = StateSyncManager(state_path="state.json", heartbeat_path=hb_path)
            m.update_heartbeat({"capital": 10000, "positions": 2})

            with open(hb_path) as f2:
                data = json.load(f2)

            assert "timestamp" in data
            assert data["state"]["capital"] == 10000
            assert data["state"]["positions"] == 2
            assert "instance_id" in data
        finally:
            os.unlink(hb_path)

    def test_includes_instance_id(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            hb_path = f.name

        try:
            m = StateSyncManager(state_path="state.json", heartbeat_path=hb_path)
            m.update_heartbeat({})
            with open(hb_path) as f2:
                data = json.load(f2)
            assert isinstance(data["instance_id"], int)
            assert data["instance_id"] == os.getpid()
        finally:
            os.unlink(hb_path)

    def test_overwrites_previous(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            hb_path = f.name

        try:
            m = StateSyncManager(state_path="state.json", heartbeat_path=hb_path)
            m.update_heartbeat({"version": 1})
            m.update_heartbeat({"version": 2})
            with open(hb_path) as f2:
                data = json.load(f2)
            assert data["state"]["version"] == 2
        finally:
            os.unlink(hb_path)

    def test_bad_path_does_not_raise(self) -> None:
        m = StateSyncManager(
            state_path="state.json",
            heartbeat_path="/nonexistent_dir/hb.json",
        )
        m.update_heartbeat({"test": 1})  # should not raise


class TestCheckFailover:
    def test_no_heartbeat_returns_false(self) -> None:
        m = StateSyncManager(state_path="state.json", heartbeat_path="/nonexistent/hb.json")
        assert m.check_failover() is False

    def test_fresh_heartbeat_returns_false(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            hb_path = f.name
            json.dump({"timestamp": time.time(), "state": {}}, f)

        try:
            m = StateSyncManager(state_path="state.json", heartbeat_path=hb_path)
            assert m.check_failover() is False
        finally:
            os.unlink(hb_path)

    def test_stale_heartbeat_returns_true(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            hb_path = f.name
            json.dump({"timestamp": time.time() - 120, "state": {}}, f)

        try:
            m = StateSyncManager(state_path="state.json", heartbeat_path=hb_path)
            assert m.check_failover() is True  # 120s old > 60s threshold
        finally:
            os.unlink(hb_path)

    def test_corrupt_heartbeat_returns_false(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            hb_path = f.name
            f.write("not valid json")

        try:
            m = StateSyncManager(state_path="state.json", heartbeat_path=hb_path)
            assert m.check_failover() is False  # corrupt -> no trigger
        finally:
            os.unlink(hb_path)
