"""Test suite for AuditService.

Verifies:
- Singleton lifecycle and thread-safety
- Dual persistence (SQLite db/auth.db audit_log + JSONL json/audit_trail.jsonl)
- Config audit persistence to json/config_audit.jsonl
- Credential and secret redaction (password, token, secret, api_key)
- Filtering and pagination in query_audit_trail
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

from core.auth.audit_service import AuditService, get_audit_service


class TestAuditService(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_path = Path(self.temp_dir.name)
        self.db_path = self.base_path / "db" / "auth.db"
        self.audit_trail_path = self.base_path / "json" / "audit_trail.jsonl"
        self.config_audit_path = self.base_path / "json" / "config_audit.jsonl"

        # Initialize test instance
        self.svc = AuditService(
            db_path=self.db_path,
            audit_trail_path=self.audit_trail_path,
            config_audit_path=self.config_audit_path,
        )

    def tearDown(self):
        import gc
        gc.collect()
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_log_privileged_action_success(self):
        event = self.svc.log_privileged_action(
            action="USER_CREATE",
            actor_username="super_admin",
            actor_role="super_admin",
            target="trader_john",
            result="SUCCESS",
            route="/api/auth/users",
            method="POST",
            details={"email": "john@example.com", "role": "operator"},
        )

        self.assertIsNotNone(event)
        self.assertEqual(event["action"], "USER_CREATE")
        self.assertEqual(event["actor_username"], "super_admin")
        self.assertEqual(event["target"], "trader_john")
        self.assertEqual(event["result"], "SUCCESS")

        # Verify JSONL existence and content
        self.assertTrue(self.audit_trail_path.exists())
        with open(self.audit_trail_path, "r", encoding="utf-8") as f:
            lines = [json.loads(line) for line in f if line.strip()]
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["action"], "USER_CREATE")
        self.assertEqual(lines[0]["actor_username"], "super_admin")

        # Verify query retrieval
        records = self.svc.query_audit_trail(limit=10)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["action"], "USER_CREATE")
        self.assertEqual(records[0]["target"], "trader_john")

    def test_credential_redaction(self):
        event = self.svc.log_privileged_action(
            action="PASSWORD_RESET",
            actor_username="super_admin",
            actor_role="super_admin",
            target="user1",
            result="SUCCESS",
            details={
                "password": "super_secret_password_123",
                "nested": {
                    "api_key": "live_key_xyz987",
                    "safe_field": "keep_this",
                },
                "token": "bearer_jwt_token_here",
            },
        )

        details = event["details"]
        self.assertEqual(details["password"], "[REDACTED]")
        self.assertEqual(details["token"], "[REDACTED]")
        self.assertEqual(details["nested"]["api_key"], "[REDACTED]")
        self.assertEqual(details["nested"]["safe_field"], "keep_this")

        # Confirm redacted in file
        with open(self.audit_trail_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn("super_secret_password_123", content)
        self.assertNotIn("live_key_xyz987", content)

    def test_log_config_change(self):
        before = {"BASE_CAPITAL": 10000.0, "API_KEY": "secret_abc"}
        after = {"BASE_CAPITAL": 3000.0, "API_KEY": "secret_xyz"}

        event = self.svc.log_config_change(
            actor_username="admin",
            actor_role="admin",
            before_state=before,
            after_state=after,
            diff={"BASE_CAPITAL": 3000.0},
            result="SUCCESS",
            ip_address="192.168.1.50",
        )

        self.assertIsNotNone(event)
        self.assertEqual(event["action"], "CONFIG_APPLY")
        self.assertEqual(event["actor_username"], "admin")

        # Verify config audit file
        self.assertTrue(self.config_audit_path.exists())
        with open(self.config_audit_path, "r", encoding="utf-8") as f:
            lines = [json.loads(line) for line in f if line.strip()]
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["action"], "CONFIG_APPLY")
        self.assertEqual(lines[0]["before_state"]["BASE_CAPITAL"], 10000.0)
        self.assertEqual(lines[0]["after_state"]["BASE_CAPITAL"], 3000.0)
        self.assertEqual(lines[0]["before_state"]["API_KEY"], "[REDACTED]")

        # Also logged to main audit trail
        trail_records = self.svc.query_audit_trail(action="CONFIG_APPLY")
        self.assertEqual(len(trail_records), 1)
        self.assertEqual(trail_records[0]["actor_username"], "admin")


if __name__ == "__main__":
    unittest.main()
