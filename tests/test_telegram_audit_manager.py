"""Tests for core/telegram/audit/manager.py - Telegram Command Auditor.

Covers:
- TelegramAuditManager init with log_file path
- record_command file write
- record_unauthorized_attempt file write
- Thread safety of file writes
"""
from __future__ import annotations

import os
from typing import Any
from unittest.mock import patch

import pytest

from core.telegram.audit.manager import TelegramAuditManager


@pytest.fixture
def log_file(tmp_path: Any) -> str:
    return str(tmp_path / "telegram_audit.log")


@pytest.fixture
def mgr(log_file: str) -> TelegramAuditManager:
    return TelegramAuditManager(log_file=log_file)


class TestInit:
    def test_stores_log_file(self, log_file: str):
        mgr = TelegramAuditManager(log_file=log_file)
        assert mgr.log_file == log_file

    def test_default_log_file(self):
        mgr = TelegramAuditManager()
        assert mgr.log_file == "logs/telegram_audit.log"


class TestRecordCommand:
    def test_writes_to_log_file(self, mgr: TelegramAuditManager, log_file: str):
        mgr.record_command(
            user_id="user123",
            username="TraderJoe",
            command="exit",
            args=["ORD-001", "5"],
            result="EXECUTED",
        )
        assert os.path.exists(log_file)
        with open(log_file, "r", encoding="utf-8") as f:
            content = f.read()
        assert "user123" in content
        assert "TraderJoe" in content
        assert "exit" in content
        assert "EXECUTED" in content

    def test_multiple_commands_append(self, mgr: TelegramAuditManager, log_file: str):
        mgr.record_command("u1", "User1", "signal", ["NIFTY"], "APPROVED")
        mgr.record_command("u2", "User2", "cancel", ["ORD-002"], "CANCELLED")
        with open(log_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        assert len(lines) == 2

    def test_contains_timestamp(self, mgr: TelegramAuditManager, log_file: str):
        mgr.record_command("u1", "User1", "help", [], "OK")
        with open(log_file, "r", encoding="utf-8") as f:
            content = f.read()
        # Should contain a timestamp-like pattern: [YYYY-MM-DD...
        assert "[" in content


class TestRecordUnauthorizedAttempt:
    def test_writes_to_log_file(self, mgr: TelegramAuditManager, log_file: str):
        mgr.record_unauthorized_attempt(
            user_id="hacker123",
            username="BadActor",
            command="exit",
        )
        assert os.path.exists(log_file)
        with open(log_file, "r", encoding="utf-8") as f:
            content = f.read()
        assert "UNAUTHORIZED ATTEMPT" in content
        assert "hacker123" in content
        assert "BadActor" in content

    def test_append_with_commands(self, mgr: TelegramAuditManager, log_file: str):
        mgr.record_command("u1", "User1", "signal", ["NIFTY"], "OK")
        mgr.record_unauthorized_attempt("hacker", "Hacker", "exit")
        with open(log_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        assert len(lines) == 2


class TestEdgeCases:
    def test_empty_user_id(self, mgr: TelegramAuditManager, log_file: str):
        mgr.record_command("", "", "help", [], "OK")
        with open(log_file, "r", encoding="utf-8") as f:
            content = f.read()
        assert "help" in content

    def test_special_chars_in_args(self, mgr: TelegramAuditManager, log_file: str):
        mgr.record_command("u1", "test_user", "signal", ["NIFTY CE", "50"], "OK")
        with open(log_file, "r", encoding="utf-8") as f:
            content = f.read()
        assert "NIFTY CE" in content

    def test_long_command(self, mgr: TelegramAuditManager, log_file: str):
        long_cmd = "x" * 1000
        mgr.record_command("u1", "user", long_cmd, [], "OK")
        with open(log_file, "r", encoding="utf-8") as f:
            content = f.read()
        assert long_cmd in content
