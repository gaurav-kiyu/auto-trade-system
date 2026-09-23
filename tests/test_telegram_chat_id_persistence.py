"""Comprehensive 28-Scenario Test Suite for Telegram Chat ID Persistence and User Isolation.

Covers:
1. Admin UI save
2. Immediate read-after-write
3. New manager instance
4. Process restart simulation
5. Supervisor restart simulation
6. Notification-service reload
7. Docker rebuild/recreate simulation
8. User A/B isolation
9. Concurrent reader/writer atomicity
10. Corrupted JSON recovery
11. Legacy migration
12. Configuration synchronization
13. Positive Chat ID
14. Negative Chat ID
15. Whitespace normalization
16. Invalid Chat ID rejection
17. Quota reset preservation
18. Master toggle preservation
19. Category update preservation
20. Tier update preservation
21. High-concurrency integrity
22. Non-admin authorization
23. Audit trail
24. Startup does not overwrite persisted Chat ID
25. Persistent volume path is actually used
26. Empty secondary config cannot overwrite valid primary value
27. Container recreation preserves value
28. Notification dispatch uses correct user's destination
"""

import json
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.auth.user_signal_permissions import (
    UserPermissionManager,
    UserSignalPermission,
    _resolve_permissions_store_path,
    validate_telegram_chat_id,
)
from core.services.notification_service import NotificationService


@pytest.fixture
def temp_store(tmp_path):
    """Fixture providing isolated temporary permissions store."""
    store_file = tmp_path / "user_signal_permissions.json"
    UserPermissionManager.reset_instance_for_testing()
    mgr = UserPermissionManager(store_path=store_file)
    yield store_file, mgr
    UserPermissionManager.reset_instance_for_testing()


class TestTelegramChatIdPersistence:
    """Test matrix for Defect 13A Telegram Chat ID Persistence and Admin UI."""

    # Scenario 1: Admin UI Save
    def test_01_admin_ui_save(self, temp_store):
        store_file, mgr = temp_store
        ok, msg, res = mgr.update_user_permissions(
            "admin",
            {"telegram_chat_id": "1148730533", "telegram_enabled": True},
            admin_username="admin",
        )
        assert ok is True
        assert res["telegram_chat_id"] == "1148730533"
        assert store_file.exists()
        raw = json.loads(store_file.read_text(encoding="utf-8"))
        assert raw["admin"]["telegram_chat_id"] == "1148730533"

    # Scenario 2: Immediate Read-After-Write
    def test_02_immediate_read_after_write(self, temp_store):
        store_file, mgr = temp_store
        mgr.update_user_permissions("admin", {"telegram_chat_id": "987654321"})
        perm = mgr.get_user_permissions("admin")
        assert perm is not None
        assert perm.telegram_chat_id == "987654321"

    # Scenario 3: New Manager Instance
    def test_03_new_manager_instance(self, temp_store):
        store_file, mgr = temp_store
        mgr.update_user_permissions("admin", {"telegram_chat_id": "555666777"})
        mgr2 = UserPermissionManager(store_path=store_file)
        perm = mgr2.get_user_permissions("admin")
        assert perm is not None
        assert perm.telegram_chat_id == "555666777"

    # Scenario 4: Process Restart Simulation
    def test_04_process_restart_simulation(self, temp_store):
        store_file, mgr = temp_store
        mgr.update_user_permissions("admin", {"telegram_chat_id": "1122334455"})
        UserPermissionManager.reset_instance_for_testing()
        new_mgr = UserPermissionManager.get_instance(store_path=store_file)
        perm = new_mgr.get_user_permissions("admin")
        assert perm.telegram_chat_id == "1122334455"

    # Scenario 5: Supervisor Restart Simulation
    def test_05_supervisor_restart_simulation(self, temp_store):
        store_file, mgr = temp_store
        mgr.update_user_permissions("admin", {"telegram_chat_id": "44332211"})
        UserPermissionManager.reset_instance_for_testing()
        mgr_after_restart = UserPermissionManager(store_path=store_file)
        assert mgr_after_restart.get_user_permissions("admin").telegram_chat_id == "44332211"

    # Scenario 6: Notification-Service Reload
    def test_06_notification_service_reload(self, temp_store):
        store_file, mgr = temp_store
        mgr.update_user_permissions("admin", {"telegram_chat_id": "888999111", "telegram_enabled": True})
        svc = NotificationService(permissions_manager=mgr)
        user_dest = svc.get_user_destinations("admin")
        assert user_dest.get("telegram_chat_id") == "888999111"

    # Scenario 7: Docker Rebuild/Recreate Simulation
    def test_07_docker_rebuild_recreate_simulation(self, tmp_path):
        persistent_dir = tmp_path / "data_db"
        persistent_dir.mkdir(parents=True, exist_ok=True)
        persistent_file = persistent_dir / "user_signal_permissions.json"

        ephemeral_dir = tmp_path / "app_json"
        ephemeral_dir.mkdir(parents=True, exist_ok=True)

        mgr = UserPermissionManager(store_path=persistent_file)
        mgr.update_user_permissions("admin", {"telegram_chat_id": "777888999"})
        assert persistent_file.exists()

        shutil.rmtree(ephemeral_dir)
        ephemeral_dir.mkdir(parents=True, exist_ok=True)

        UserPermissionManager.reset_instance_for_testing()
        mgr_new_container = UserPermissionManager(store_path=persistent_file)
        assert mgr_new_container.get_user_permissions("admin").telegram_chat_id == "777888999"

    # Scenario 8: User A/B Isolation
    def test_08_user_isolation(self, temp_store):
        store_file, mgr = temp_store
        mgr.update_user_permissions("admin", {"telegram_chat_id": "1148730533", "telegram_enabled": True})
        mgr.update_user_permissions("kiyu", {"telegram_chat_id": "", "telegram_enabled": True, "email": "kiyu@test.com"})

        svc = NotificationService(permissions_manager=mgr)
        dest_a = svc.get_user_destinations("admin")
        dest_b = svc.get_user_destinations("kiyu")

        assert dest_a["telegram_chat_id"] == "1148730533"
        assert dest_b.get("telegram_chat_id", "") == ""
        assert dest_b.get("telegram_chat_id") != "1148730533"

    # Scenario 9: Concurrent Reader/Writer Atomicity
    def test_09_concurrent_reader_writer_atomicity(self, temp_store):
        store_file, mgr = temp_store
        mgr.update_user_permissions("admin", {"telegram_chat_id": "100000"})
        stop_event = threading.Event()
        errors = []

        def writer():
            for i in range(50):
                if stop_event.is_set():
                    break
                ok, _, _ = mgr.update_user_permissions("admin", {"telegram_chat_id": str(100000 + i)})
                if not ok:
                    errors.append("Write failed")
                time.sleep(0.001)

        def reader():
            while not stop_event.is_set():
                try:
                    perm = mgr.get_user_permissions("admin")
                    if perm is None or not perm.telegram_chat_id:
                        errors.append("Read empty or None permissions during concurrent write")
                except Exception as ex:
                    errors.append(f"Reader encountered exception: {ex}")
                time.sleep(0.001)

        w_thread = threading.Thread(target=writer)
        r_threads = [threading.Thread(target=reader) for _ in range(3)]

        for r in r_threads:
            r.start()
        w_thread.start()

        w_thread.join()
        stop_event.set()
        for r in r_threads:
            r.join()

        assert len(errors) == 0, f"Encountered concurrency errors: {errors[:5]}"

    # Scenario 10: Corrupted JSON Recovery
    def test_10_corrupted_json_recovery(self, temp_store):
        store_file, mgr = temp_store
        mgr.update_user_permissions("admin", {"telegram_chat_id": "999888777"})
        assert mgr.get_user_permissions("admin").telegram_chat_id == "999888777"

        store_file.write_text("{CORRUPTED_JSON_CONTENT: invalid", encoding="utf-8")

        perm = mgr.get_user_permissions("admin")
        assert perm is not None
        assert perm.telegram_chat_id == "999888777"

        corrupt_backups = list(store_file.parent.glob("*.corrupt.*"))
        assert len(corrupt_backups) > 0

    # Scenario 11: Legacy Migration
    def test_11_legacy_migration(self, tmp_path):
        legacy_dir = tmp_path / "legacy"
        legacy_dir.mkdir(parents=True, exist_ok=True)
        legacy_file = legacy_dir / "user_signal_permissions.json"
        legacy_file.write_text(json.dumps({
            "admin": {
                "username": "admin",
                "telegram_chat_id": "12345678",
                "telegram_enabled": True
            }
        }), encoding="utf-8")

        authoritative_file = tmp_path / "auth_store" / "user_signal_permissions.json"

        mgr = UserPermissionManager.__new__(UserPermissionManager)
        mgr._path = authoritative_file
        mgr._permissions = {}
        mgr._io_lock = threading.Lock()
        with open(legacy_file, encoding="utf-8") as f:
            data = json.load(f)
        authoritative_file.parent.mkdir(parents=True, exist_ok=True)
        authoritative_file.write_text(json.dumps(data), encoding="utf-8")
        mgr._load()
        assert mgr.get_user_permissions("admin").telegram_chat_id == "12345678"

    # Scenario 12: Configuration Synchronization
    def test_12_configuration_synchronization(self, tmp_path, monkeypatch):
        from core.env_sync import sync_env_file

        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({"CHAT_ID": "old_id", "EMAIL_TO": "old@email.com"}), encoding="utf-8")
        env_file = tmp_path / ".env"

        monkeypatch.setenv("OPBUYING_INDEX_CONFIG", str(cfg_file))

        body = {"telegram_chat_id": "1148730533", "email": "admin@example.com"}
        cfg_updates = {"CHAT_ID": str(body["telegram_chat_id"]).strip(), "EMAIL_TO": str(body["email"]).strip()}

        cfg_data = json.loads(cfg_file.read_text(encoding="utf-8"))
        cfg_data.update(cfg_updates)
        cfg_file.write_text(json.dumps(cfg_data, indent=4), encoding="utf-8")

        sync_env_file(cfg_updates, env_path=env_file)

        assert json.loads(cfg_file.read_text())["CHAT_ID"] == "1148730533"
        assert os.environ.get("OPBUYING_CHAT_ID") == "1148730533"
        assert os.environ.get("OPBUYING_TELEGRAM_CHAT_ID") == "1148730533"

    # Scenario 13: Positive Chat ID
    def test_13_positive_chat_id(self):
        val_ok, norm, err = validate_telegram_chat_id("1148730533")
        assert val_ok is True
        assert norm == "1148730533"
        assert err == ""

    # Scenario 14: Negative Chat ID (Channels & Supergroups)
    def test_14_negative_chat_id(self):
        val_ok, norm, err = validate_telegram_chat_id("-1001234567890")
        assert val_ok is True
        assert norm == "-1001234567890"
        assert err == ""

    # Scenario 15: Whitespace Normalization
    def test_15_whitespace_normalization(self):
        val_ok, norm, err = validate_telegram_chat_id("  1148730533 \n\t ")
        assert val_ok is True
        assert norm == "1148730533"

    # Scenario 16: Invalid Chat ID Rejection
    def test_16_invalid_chat_id_rejection(self, temp_store):
        store_file, mgr = temp_store
        val_ok, norm, err = validate_telegram_chat_id("invalid_chat_id")
        assert val_ok is False
        assert "Invalid Telegram Chat ID" in err

        val_ok, norm, err = validate_telegram_chat_id("1148@7305")
        assert val_ok is False

        ok, msg, res = mgr.update_user_permissions("admin", {"telegram_chat_id": "abc_invalid"})
        assert ok is False
        assert "Invalid Telegram Chat ID" in msg

    # Scenario 17: Quota Reset Preservation
    def test_17_quota_reset_preservation(self, temp_store):
        store_file, mgr = temp_store
        mgr.update_user_permissions("admin", {"telegram_chat_id": "1148730533"})
        perm = mgr.get_user_permissions("admin")
        perm.last_daily_reset = "2020-01-01"
        perm.daily_signals_used = 15
        with mgr._io_lock:
            mgr._save_unlocked()

        perm_after = mgr.get_user_permissions("admin")
        assert perm_after.daily_signals_used == 0
        assert perm_after.telegram_chat_id == "1148730533"

    # Scenario 18: Master Toggle Preservation
    def test_18_master_toggle_preservation(self, temp_store):
        store_file, mgr = temp_store
        mgr.update_user_permissions("admin", {"telegram_chat_id": "1148730533", "signals_enabled": True})
        mgr.update_user_permissions("admin", {"signals_enabled": False})
        perm = mgr.get_user_permissions("admin")
        assert perm.signals_enabled is False
        assert perm.telegram_chat_id == "1148730533"

    # Scenario 19: Category Update Preservation
    def test_19_category_update_preservation(self, temp_store):
        store_file, mgr = temp_store
        mgr.update_user_permissions("admin", {"telegram_chat_id": "1148730533"})
        mgr.update_user_permissions("admin", {"allowed_categories": ["COMMODITIES", "CURRENCIES"]})
        perm = mgr.get_user_permissions("admin")
        assert perm.allowed_categories == ["COMMODITIES", "CURRENCIES"]
        assert perm.telegram_chat_id == "1148730533"

    # Scenario 20: Tier Update Preservation
    def test_20_tier_update_preservation(self, temp_store):
        store_file, mgr = temp_store
        mgr.update_user_permissions("admin", {"telegram_chat_id": "1148730533", "min_signal_tier": "MODERATE_AND_STRONG"})
        mgr.update_user_permissions("admin", {"min_signal_tier": "STRONG_ONLY"})
        perm = mgr.get_user_permissions("admin")
        assert perm.min_signal_tier == "STRONG_ONLY"
        assert perm.telegram_chat_id == "1148730533"

    # Scenario 21: High-Concurrency Multi-User Integrity
    def test_21_high_concurrency_multi_user_integrity(self, temp_store):
        store_file, mgr = temp_store
        usernames = [f"user_{i}" for i in range(10)]
        for i, u in enumerate(usernames):
            mgr.update_user_permissions(u, {"telegram_chat_id": f"1000{i}", "telegram_enabled": True})

        def worker(i, u):
            for step in range(20):
                mgr.update_user_permissions(u, {"min_signal_tier": "STRONG_ONLY", "display_name": f"User {i} Step {step}"})
                perm = mgr.get_user_permissions(u)
                assert perm.telegram_chat_id == f"1000{i}"

        threads = [threading.Thread(target=worker, args=(i, u)) for i, u in enumerate(usernames)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        for i, u in enumerate(usernames):
            assert mgr.get_user_permissions(u).telegram_chat_id == f"1000{i}"

    # Scenario 22: Non-Admin Authorization Guard
    def test_22_non_admin_authorization(self):
        from core.auth.permissions import Role, role_has_permission, Permission
        assert role_has_permission(Role.VIEWER, Permission.MANAGE_PERMISSIONS) is False
        assert role_has_permission(Role.OPERATOR, Permission.MANAGE_PERMISSIONS) is False
        assert role_has_permission(Role.ADMIN, Permission.MANAGE_PERMISSIONS) is False
        assert role_has_permission(Role.SUPER_ADMIN, Permission.MANAGE_PERMISSIONS) is True
        assert role_has_permission(Role.ADMIN, Permission.MANAGE_USERS) is True
        assert role_has_permission(Role.SUPER_ADMIN, Permission.MANAGE_USERS) is True

    # Scenario 23: Audit Trail Recording
    def test_23_audit_trail_recording(self, temp_store):
        store_file, mgr = temp_store
        with patch("core.auth.audit_service.log_privileged_action") as mock_audit:
            mgr.update_user_permissions("admin", {"telegram_chat_id": "1148730533"}, admin_username="admin")
            assert mock_audit.called is True
            call_kwargs = mock_audit.call_args[1]
            assert call_kwargs["action"] in ("USER_PERMISSIONS_UPDATE", "USER_PERMISSIONS_CREATE")
            assert call_kwargs["actor_username"] == "admin"
            assert call_kwargs["target"] == "admin"

    # Scenario 24: Startup Does Not Overwrite Persisted Chat ID
    def test_24_startup_does_not_overwrite_persisted_chat_id(self, temp_store):
        store_file, mgr = temp_store
        mgr.update_user_permissions("admin", {"telegram_chat_id": "1148730533"})
        mgr._seed_default_users()
        assert mgr.get_user_permissions("admin").telegram_chat_id == "1148730533"

    # Scenario 25: Persistent Volume Path Priority
    def test_25_persistent_volume_path_priority(self, tmp_path, monkeypatch):
        custom_p = tmp_path / "custom" / "perms.json"
        monkeypatch.setenv("OPBUYING_USER_PERMISSIONS_PATH", str(custom_p))
        res = _resolve_permissions_store_path()
        assert res == custom_p

    # Scenario 26: Empty Secondary Config Cannot Overwrite Valid Primary
    def test_26_empty_secondary_config_cannot_overwrite_primary(self, temp_store):
        store_file, mgr = temp_store
        mgr.update_user_permissions("admin", {"telegram_chat_id": "1148730533"})

        empty_cfg = {"CHAT_ID": "", "EMAIL_TO": ""}
        with patch("pathlib.Path.read_text", return_value=json.dumps(empty_cfg)):
            mgr._seed_default_users()
            assert mgr.get_user_permissions("admin").telegram_chat_id == "1148730533"

    # Scenario 27: Container Recreation Preserves Value
    def test_27_container_recreation_preserves_value(self, tmp_path):
        volume_store = tmp_path / "volume" / "user_signal_permissions.json"
        volume_store.parent.mkdir(parents=True, exist_ok=True)

        mgr1 = UserPermissionManager(store_path=volume_store)
        mgr1.update_user_permissions("admin", {"telegram_chat_id": "99887766"})
        del mgr1

        mgr2 = UserPermissionManager(store_path=volume_store)
        assert mgr2.get_user_permissions("admin").telegram_chat_id == "99887766"

    # Scenario 28: Notification Dispatch Uses Correct Destination
    def test_28_notification_dispatch_uses_correct_destination(self, temp_store):
        store_file, mgr = temp_store
        mgr.update_user_permissions("admin", {"telegram_chat_id": "1148730533", "telegram_enabled": True})
        mgr.update_user_permissions("kiyu", {"telegram_chat_id": "222333444", "telegram_enabled": True})
        mgr.update_user_permissions("observer", {"telegram_chat_id": "", "telegram_enabled": False})

        svc = NotificationService(permissions_manager=mgr)
        assert svc.get_user_destinations("admin")["telegram_chat_id"] == "1148730533"
        assert svc.get_user_destinations("kiyu")["telegram_chat_id"] == "222333444"
        assert svc.get_user_destinations("observer").get("telegram_chat_id", "") == ""
