"""Tests for core/db_migration.py - schema version registry + migration framework."""

import os
import sqlite3
import tempfile

from core.db_migration import (
    ensure_schema_version,
    get_migration_log,
    get_schema_version,
    migrate_to_latest,
)


class TestSchemaVersion:
    def _conn(self):
        fd, self._path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        return sqlite3.connect(self._path)

    def _clean(self):
        if hasattr(self, "_path") and os.path.exists(self._path):
            os.unlink(self._path)

    def test_fresh_db_has_version_zero(self):
        conn = self._conn()
        try:
            assert get_schema_version(conn) == 0
        finally:
            conn.close()
            self._clean()

    def test_set_schema_version(self):
        conn = self._conn()
        try:
            conn.execute("PRAGMA user_version = 5")
            conn.commit()
            assert get_schema_version(conn) == 5
        finally:
            conn.close()
            self._clean()

    def test_migrate_from_zero_to_latest(self):
        conn = self._conn()
        try:
            version = migrate_to_latest(conn)
            assert version >= 1
        finally:
            conn.close()
            self._clean()

    def test_migration_idempotent(self):
        conn = self._conn()
        try:
            v1 = migrate_to_latest(conn)
            v2 = migrate_to_latest(conn)
            assert v1 == v2
        finally:
            conn.close()
            self._clean()

    def test_get_migration_log_structure(self):
        conn = self._conn()
        try:
            log = get_migration_log(conn)
            assert isinstance(log, list)
            if log:
                entry = log[0]
                assert "version" in entry
                assert "description" in entry
                assert "applied" in entry
        finally:
            conn.close()
            self._clean()

    def test_ensure_schema_version_returns_int(self):
        conn = self._conn()
        try:
            version = ensure_schema_version(self._path)
            assert isinstance(version, int)
            assert version >= 1
        finally:
            conn.close()
            self._clean()

    def test_migration_applied_flag_true_after_migration(self):
        conn = self._conn()
        try:
            migrate_to_latest(conn)
            log = get_migration_log(conn)
            applied = [m for m in log if m["applied"]]
            assert len(applied) >= 1
        finally:
            conn.close()
            self._clean()
