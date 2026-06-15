"""Tests for core.secret_hygiene — secret hygiene validation."""

from __future__ import annotations

from pathlib import Path

from core.secret_hygiene import (
    KNOWN_SECRET_KEYS,
    SECRET_KEY_PARTS,
    SECRET_PATTERNS,
    SecretHygieneChecker,
    SecretHygieneResult,
    check_config_secrets,
    get_secret_checker,
    sanitize_for_log,
)


# ── SecretHygieneResult ─────────────────────────────────────────────────

def test_secret_hygiene_result_all_clean() -> None:
    result = SecretHygieneResult(passed=True, secrets_found=[], warnings=[])
    assert result.passed is True
    assert result.secrets_found == []


def test_secret_hygiene_result_with_secrets() -> None:
    result = SecretHygieneResult(
        passed=False,
        secrets_found=["TELEGRAM_BOT_TOKEN=****xyz1"],
        warnings=["High severity"],
    )
    assert result.passed is False
    assert "TELEGRAM_BOT_TOKEN" in result.secrets_found[0]


# ── SecretHygieneChecker construction ───────────────────────────────────

def test_checker_default_config() -> None:
    checker = SecretHygieneChecker()
    assert checker._config == {}
    assert len(checker._patterns) == len(SECRET_PATTERNS)


# ── is_secret_key ────────────────────────────────────────────────────────

def test_is_secret_key_exact_match() -> None:
    checker = SecretHygieneChecker()
    for key in KNOWN_SECRET_KEYS:
        assert checker.is_secret_key(key), f"Expected {key} to be detected"


def test_is_secret_key_partial_match() -> None:
    checker = SecretHygieneChecker()
    assert checker.is_secret_key("my_api_key_value")
    assert checker.is_secret_key("user_password_123")
    assert checker.is_secret_key("refresh_token_v2")


def test_is_secret_key_public_key() -> None:
    checker = SecretHygieneChecker()
    assert not checker.is_secret_key("SCORE_THRESHOLD")
    assert not checker.is_secret_key("MAX_DAILY_LOSS")
    assert not checker.is_secret_key("WATCHDOG_TIMEOUT")


# ── mask_value ───────────────────────────────────────────────────────────

def test_mask_value_long() -> None:
    checker = SecretHygieneChecker()
    masked = checker.mask_value("mySecretKey123", visible_chars=4)
    assert masked.endswith("y123")
    assert masked.startswith("*")


def test_mask_value_short() -> None:
    checker = SecretHygieneChecker()
    masked = checker.mask_value("abc")
    assert masked == "***"


def test_mask_value_non_string() -> None:
    checker = SecretHygieneChecker()
    assert checker.mask_value(12345) == "***"


# ── check_config ─────────────────────────────────────────────────────────

def test_check_config_clean() -> None:
    checker = SecretHygieneChecker()
    config = {"SCORE_THRESHOLD": 65, "MAX_DAILY_LOSS": -600, "EXECUTION_MODE": "MANUAL"}
    result = checker.check_config(config)
    assert result.passed is True
    assert result.secrets_found == []


def test_check_config_finds_secret() -> None:
    checker = SecretHygieneChecker()
    config = {"TELEGRAM_BOT_TOKEN": "abc123secret"}
    result = checker.check_config(config)
    assert result.passed is False
    assert len(result.secrets_found) >= 1


def test_check_config_skips_placeholder() -> None:
    checker = SecretHygieneChecker()
    config = {"TELEGRAM_BOT_TOKEN": "YOUR_TELEGRAM_BOT_TOKEN"}
    result = checker.check_config(config)
    # "YOUR_TELEGRAM_BOT_TOKEN" is not in the placeholder check list...
    # Actually the code checks for ["[REDACTED]", "***", "xxx", "placeholder"]
    # So "YOUR_TELEGRAM_BOT_TOKEN" would NOT be skipped
    assert result.passed is False


def test_check_config_nested_dict() -> None:
    checker = SecretHygieneChecker()
    config = {"BROKER_CONFIG": {"api_key": "real_key_123"}}
    result = checker.check_config(config)
    assert result.passed is False
    assert len(result.secrets_found) >= 1


def test_check_config_empty_string_skipped() -> None:
    checker = SecretHygieneChecker()
    config = {"TELEGRAM_BOT_TOKEN": ""}
    result = checker.check_config(config)
    assert result.passed is True  # empty string is skipped


# ── check_file ───────────────────────────────────────────────────────────

def test_check_file_not_exists(tmp_path: Path) -> None:
    checker = SecretHygieneChecker()
    result = checker.check_file(tmp_path / "nonexistent.json")
    assert result.passed is True


def test_check_file_skipped_extension(tmp_path: Path) -> None:
    checker = SecretHygieneChecker()
    f = tmp_path / "config.log"
    f.write_text("TELEGRAM_BOT_TOKEN=abc123")
    result = checker.check_file(f)
    assert result.passed is True  # .log is skipped


def test_check_file_finds_secret(tmp_path: Path) -> None:
    checker = SecretHygieneChecker()
    f = tmp_path / "config.json"
    f.write_text('{"TELEGRAM_BOT_TOKEN": "abc123"}')
    result = checker.check_file(f)
    assert result.passed is False
    assert "TELEGRAM_BOT_TOKEN" in result.secrets_found[0]


# ── check_directory ─────────────────────────────────────────────────────

def test_check_directory_clean(tmp_path: Path) -> None:
    checker = SecretHygieneChecker()
    f = tmp_path / "settings.json"
    f.write_text('{"SCORE_THRESHOLD": 65}')
    result = checker.check_directory(tmp_path, patterns=["*.json"])
    assert result.passed is True


def test_check_directory_skips_git(tmp_path: Path) -> None:
    checker = SecretHygieneChecker()
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    f = git_dir / "config"
    f.write_text("TELEGRAM_BOT_TOKEN=abc")
    result = checker.check_directory(tmp_path, patterns=["*"])
    assert result.passed is True  # .git is skipped


# ── sanitize_for_logging ────────────────────────────────────────────────

def test_sanitize_for_logging() -> None:
    checker = SecretHygieneChecker()
    data = {
        "TELEGRAM_BOT_TOKEN": "real_token",
        "SCORE_THRESHOLD": 65,
        "BROKER_CONFIG": {"api_key": "secret123"},
        "LIST": [1, 2, 3],
    }
    sanitized = checker.sanitize_for_logging(data)
    assert sanitized["TELEGRAM_BOT_TOKEN"] == "[REDACTED]"
    assert sanitized["SCORE_THRESHOLD"] == 65
    assert sanitized["BROKER_CONFIG"]["api_key"] == "[REDACTED]"
    assert sanitized["LIST"] == [1, 2, 3]


# ── Convenience functions ───────────────────────────────────────────────

def test_get_secret_checker_singleton() -> None:
    from core.secret_hygiene import _secret_checker
    original = _secret_checker
    try:
        import core.secret_hygiene
        core.secret_hygiene._secret_checker = None
        c1 = get_secret_checker()
        c2 = get_secret_checker()
        assert c1 is c2
    finally:
        core.secret_hygiene._secret_checker = original


def test_check_config_secrets_convenience() -> None:
    result = check_config_secrets({"TELEGRAM_BOT_TOKEN": "abc123"})
    assert result.passed is False


def test_sanitize_for_log_convenience() -> None:
    data = {"KITE_API_KEY": "secret", "SCORE": 75}
    sanitized = sanitize_for_log(data)
    assert sanitized["KITE_API_KEY"] == "[REDACTED]"
    assert sanitized["SCORE"] == 75
