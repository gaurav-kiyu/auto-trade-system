"""Tests for Secrets Vault module (core/secrets_vault.py)."""

from __future__ import annotations

import pytest
from core.secrets_vault import SecretEntry, get_secrets_vault, reset_secrets_vault


@pytest.fixture(autouse=True)
def reset_vault():
    reset_secrets_vault()
    vault = get_secrets_vault(master_key="test-master-key-for-testing")
    vault.clear_all()
    yield
    reset_secrets_vault()


class TestSetGet:
    def test_set_and_get(self, reset_vault):
        vault = get_secrets_vault()
        vault.set("api.key", "secret-value-123")
        value = vault.get("api.key")
        assert value == "secret-value-123"

    def test_get_nonexistent(self, reset_vault):
        vault = get_secrets_vault()
        with pytest.raises(KeyError):
            vault.get("nonexistent")

    def test_get_or_none(self, reset_vault):
        vault = get_secrets_vault()
        assert vault.get_or_none("nonexistent") is None
        vault.set("exists", "val")
        assert vault.get_or_none("exists") == "val"

    def test_overwrite_increments_version(self, reset_vault):
        vault = get_secrets_vault()
        vault.set("my.key", "v1")
        meta = vault.get_metadata("my.key")
        assert meta.version == 1
        vault.set("my.key", "v2")
        meta = vault.get_metadata("my.key")
        assert meta.version == 2

    def test_set_with_tags_and_description(self, reset_vault):
        vault = get_secrets_vault()
        vault.set("broker.key", "kite123", tags=["broker", "production"], description="Kite API key")
        meta = vault.get_metadata("broker.key")
        assert "broker" in meta.tags
        assert meta.description == "Kite API key"


class TestExists:
    def test_exists(self, reset_vault):
        vault = get_secrets_vault()
        assert vault.exists("my.key") is False
        vault.set("my.key", "val")
        assert vault.exists("my.key") is True


class TestDelete:
    def test_delete(self, reset_vault):
        vault = get_secrets_vault()
        vault.set("tmp.key", "val")
        assert vault.exists("tmp.key") is True
        assert vault.delete("tmp.key") is True
        assert vault.exists("tmp.key") is False

    def test_delete_nonexistent(self, reset_vault):
        vault = get_secrets_vault()
        assert vault.delete("nonexistent") is False


class TestRotate:
    def test_rotate(self, reset_vault):
        vault = get_secrets_vault()
        vault.set("rotating.key", "old-value")
        assert vault.rotate("rotating.key", "new-value") is True
        value = vault.get("rotating.key")
        assert value == "new-value"

    def test_rotate_increments_version(self, reset_vault):
        vault = get_secrets_vault()
        vault.set("r.key", "v1")
        vault.rotate("r.key", "v2")
        meta = vault.get_metadata("r.key")
        assert meta.version == 2
        assert meta.rotated_at > 0

    def test_rotate_nonexistent(self, reset_vault):
        vault = get_secrets_vault()
        assert vault.rotate("nonexistent", "val") is False


class TestListKeys:
    def test_list_keys(self, reset_vault):
        vault = get_secrets_vault()
        vault.set("key.a", "a")
        vault.set("key.b", "b")
        keys = vault.list_keys()
        assert len(keys) == 2
        assert "key.a" in keys
        assert "key.b" in keys

    def test_list_keys_filtered_by_tag(self, reset_vault):
        vault = get_secrets_vault()
        vault.set("key.a", "a", tags=["alpha"])
        vault.set("key.b", "b", tags=["beta"])
        keys = vault.list_keys(tag="alpha")
        assert len(keys) == 1
        assert keys[0] == "key.a"

    def test_empty_list(self, reset_vault):
        vault = get_secrets_vault()
        assert len(vault.list_keys()) == 0


class TestMetadata:
    def test_get_metadata(self, reset_vault):
        vault = get_secrets_vault()
        vault.set("meta.key", "val", tags=["tag1"])
        meta = vault.get_metadata("meta.key")
        assert meta is not None
        assert meta.key == "meta.key"
        assert meta.version == 1
        # Metadata must not contain the decrypted value
        assert hasattr(meta, 'encrypted_value')

    def test_get_metadata_nonexistent(self, reset_vault):
        vault = get_secrets_vault()
        assert vault.get_metadata("nonexistent") is None


class TestAudit:
    def test_audit_log(self, reset_vault):
        vault = get_secrets_vault()
        vault.set("audit.key", "val")
        vault.get("audit.key")
        log = vault.get_audit_log()
        assert len(log) >= 2
        actions = [e.action for e in log]
        assert "set" in actions
        assert "get" in actions

    def test_audit_failed_get(self, reset_vault):
        vault = get_secrets_vault()
        try:
            vault.get("nonexistent")
        except KeyError:
            pass
        log = vault.get_audit_log(action="get")
        failed = [e for e in log if not e.success]
        assert len(failed) >= 1

    def test_audit_rotate(self, reset_vault):
        vault = get_secrets_vault()
        vault.set("r.key", "v1")
        vault.rotate("r.key", "v2")
        log = vault.get_audit_log(action="rotate")
        assert len(log) == 1
        assert log[0].success is True


class TestStats:
    def test_get_stats_empty(self, reset_vault):
        vault = get_secrets_vault()
        stats = vault.get_stats()
        assert stats["total_secrets"] == 0

    def test_get_stats_with_secrets(self, reset_vault):
        vault = get_secrets_vault()
        vault.set("key.a", "a", tags=["tag1"])
        vault.set("key.b", "b", tags=["tag2"])
        stats = vault.get_stats()
        assert stats["total_secrets"] == 2
        assert stats["total_versions"] == 2
        assert stats["has_master_key"] is True


class TestSecretEntryModel:
    def test_to_dict_does_not_include_value(self):
        entry = SecretEntry(key="test", encrypted_value="enc", salt="salt",
                            version=1, created_at=100.0, updated_at=100.0)
        d = entry.to_dict()
        assert d["key"] == "test"
        assert "encrypted_value" not in d  # Never expose encrypted value


class TestSingleton:
    def test_singleton(self):
        v1 = get_secrets_vault()
        v2 = get_secrets_vault()
        assert v1 is v2
