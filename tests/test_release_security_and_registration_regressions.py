from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_runtime_smtp_password_is_not_packaged_in_config() -> None:
    cfg = json.loads((ROOT / "json" / "config.json").read_text(encoding="utf-8"))
    assert cfg.get("EMAIL_PASS", "") == ""


def test_self_registration_defaults_to_pending_signal_authorization() -> None:
    src = (ROOT / "core" / "auth" / "routes.py").read_text(encoding="utf-8")
    marker = 'admin_username="self-register"'
    before = src[: src.index(marker)]
    window = before[-1800:]
    assert 'update_data["is_active"] = False' in window
    assert 'update_data["signals_enabled"] = False' in window


def test_admin_created_accounts_default_to_signal_deny() -> None:
    src = (ROOT / "core" / "auth" / "routes.py").read_text(encoding="utf-8")
    marker = 'admin_username=admin.username'
    before = src[: src.index(marker)]
    window = before[-2400:]
    assert '"is_active": True' in window
    assert '"signals_enabled": False' in window


def test_all_control_plane_roles_are_supported_by_auth_handler() -> None:
    src = (ROOT / "core" / "auth" / "handler" / "handler.py").read_text(encoding="utf-8")
    assert '"observer", "developer"' in src


def test_known_secret_is_absent_from_release_tree() -> None:
    secret = "ptwn" + "ovwv" + "facwafog"
    for path in ROOT.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        if path.suffix.lower() not in {".json", ".html", ".md", ".py", ".js", ".yml", ".yaml", ".txt"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        assert secret not in text, f"credential leaked in {path.relative_to(ROOT)}"
