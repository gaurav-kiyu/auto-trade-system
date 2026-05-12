"""Unit tests for core.config_schema_validate."""

from __future__ import annotations

from core.config_schema_validate import append_json_schema_errors


def test_append_json_schema_errors_rejects_bad_execution_mode():
    errors: list[str] = []
    append_json_schema_errors(errors, {"EXECUTION_MODE": "NOT_A_MODE"}, flavour="index")
    assert errors and any("EXECUTION_MODE" in e or "enum" in e.lower() for e in errors)


def test_append_json_schema_errors_skip_env(monkeypatch):
    monkeypatch.setenv("OPB_SKIP_JSON_SCHEMA", "1")
    errors: list[str] = []
    append_json_schema_errors(errors, {"EXECUTION_MODE": "NOT_A_MODE"}, flavour="index")
    assert not errors
    monkeypatch.delenv("OPB_SKIP_JSON_SCHEMA", raising=False)
