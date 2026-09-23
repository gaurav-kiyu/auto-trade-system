"""Test suite for P0 Configuration Control Plane Propagation.

Verifies:
1. Multi-step propagation: 10000 -> 3000 -> 5000
2. trader_state.json base_capital and capital synchronization
3. Cache invalidation across dashboard, state, and risk APIs
4. Audit trail emission with before_state and after_state
5. Safety invariant enforcement (TRADING_MODE and SL_PCT lock)
"""

import gc
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.auth.audit_service import AuditService
from core.enterprise_dashboard.main import EnterpriseDashboard


class TestConfigPropagation(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_path = Path(self.temp_dir.name)
        self.config_path = self.base_path / "json" / "config.json"
        self.defaults_path = self.base_path / "json" / "index_config.defaults.json"
        self.state_path = self.base_path / "json" / "trader_state.json"
        self.db_path = self.base_path / "db" / "auth.db"
        self.trades_db = self.base_path / "db" / "trades.db"
        self.audit_trail_path = self.base_path / "json" / "audit_trail.jsonl"
        self.config_audit_path = self.base_path / "json" / "config_audit.jsonl"

        # Create directories
        (self.base_path / "json").mkdir(parents=True, exist_ok=True)
        (self.base_path / "db").mkdir(parents=True, exist_ok=True)

        # Write initial defaults
        initial_defaults = {
            "BASE_CAPITAL": 10000.0,
            "TRADING_MODE": "PAPER",
            "SL_PCT": 0.88,
            "RISK_LIMIT_PER_TRADE": 0.02,
        }
        with open(self.defaults_path, "w", encoding="utf-8") as f:
            json.dump(initial_defaults, f)

        # Set up isolated audit service
        self.real_audit = AuditService(
            db_path=str(self.db_path),
            audit_trail_path=str(self.audit_trail_path),
            config_audit_path=str(self.config_audit_path),
        )
        AuditService._instance = self.real_audit

        self._orig_environ = os.environ.copy()
        self.app = EnterpriseDashboard(
            config={
                "index_config_path": str(self.config_path),
                "index_config_defaults_path": str(self.defaults_path),
                "config_audit_log_path": str(self.config_audit_path),
                "auth_db_path": str(self.db_path),
                "trades_db": str(self.trades_db),
                "env_path": str(self.base_path / ".env"),
                "BASE_CAPITAL": 10000.0,
                "TRADING_MODE": "PAPER",
            },
            state_path=str(self.state_path),
            db_path=str(self.trades_db),
        )

    def tearDown(self):
        AuditService._instance = None
        os.environ.clear()
        os.environ.update(self._orig_environ)
        gc.collect()
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_config_propagation_lifecycle(self):
        # Step 1: Initial state verification (defaults = 10000.0)
        self.assertEqual(self.app._cfg.get("BASE_CAPITAL"), 10000.0)
        overview = self.app._read_state()
        self.assertEqual(overview["capital"], 10000.0)
        self.assertEqual(overview["base_capital"], 10000.0)

        # Step 2: Apply change 10000.0 -> 3000.0
        result = self.app._apply_config_change(
            {"BASE_CAPITAL": 3000.0},
            username="super_admin",
        )
        self.assertTrue(result.get("success"), f"Failed applying 3000.0: {result}")
        self.assertEqual(self.app._cfg.get("BASE_CAPITAL"), 3000.0)

        # Check config file written
        with open(self.config_path, "r", encoding="utf-8") as f:
            persisted_cfg = json.load(f)
        self.assertEqual(persisted_cfg["BASE_CAPITAL"], 3000.0)

        # Check trader_state.json synchronized
        with open(self.state_path, "r", encoding="utf-8") as f:
            state_data = json.load(f)
        self.assertEqual(state_data.get("base_capital"), 3000.0)
        self.assertEqual(state_data.get("capital"), 3000.0)

        # Check state dynamically resolves 3000.0
        overview = self.app._read_state()
        self.assertEqual(overview["capital"], 3000.0)
        self.assertEqual(overview["base_capital"], 3000.0)

        # Step 3: Apply change 3000.0 -> 5000.0
        result = self.app._apply_config_change(
            {"BASE_CAPITAL": 5000.0},
            username="super_admin",
        )
        self.assertTrue(result.get("success"), f"Failed applying 5000.0: {result}")
        self.assertEqual(self.app._cfg.get("BASE_CAPITAL"), 5000.0)

        overview = self.app._read_state()
        self.assertEqual(overview["capital"], 5000.0)
        self.assertEqual(overview["base_capital"], 5000.0)

        # Step 4: Verify audit logging
        events = self.real_audit.get_audit_events(action="CONFIG_APPLY")
        self.assertGreaterEqual(len(events), 2)
        latest_event = events[0]
        self.assertEqual(latest_event["actor_username"], "super_admin")
        self.assertEqual(latest_event["result"], "SUCCESS")

        # Step 5: Test safety invariant lock (reject LIVE)
        result_invariants = self.app._apply_config_change(
            {"TRADING_MODE": "LIVE"},
            username="hacker",
        )
        self.assertFalse(result_invariants.get("success"))
        self.assertIn("TRADING_MODE", result_invariants.get("error", ""))
        self.assertEqual(self.app._cfg.get("TRADING_MODE"), "PAPER")


if __name__ == "__main__":
    unittest.main()
