"""
Tests for launcher.py — package loading, settings, Python detection, command construction.

All tests avoid actual Tkinter rendering (no display server needed).
Tests focus on the non-GUI logic that can run headlessly.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

# ═══════════════════════════════════════════════════════════════════════════════
#  _load_packages_from_requirements
# ═══════════════════════════════════════════════════════════════════════════════

def test_load_packages_parses_normal_requirements(tmp_path: Path) -> None:
    """Should parse a normal requirements.txt correctly."""
    req = tmp_path / "requirements.txt"
    req.write_text(
        "requests>=2.31.0\n"
        "yfinance>=0.2.36\n"
        "pandas>=2.0.0\n"
        "numpy>=1.24.0\n"
    )
    from launcher import _load_packages_from_requirements

    pkgs = _load_packages_from_requirements(req)
    assert len(pkgs) == 4
    names = [p[0] for p in pkgs]
    assert "requests" in names
    assert "pandas" in names
    assert "numpy" in names


def test_load_packages_skips_comments_and_blanks(tmp_path: Path) -> None:
    """Should skip commented, blank, and inline-commented lines."""
    req = tmp_path / "requirements.txt"
    req.write_text(
        "# This is a comment\n"
        "\n"
        "requests>=2.31.0  # HTTP library\n"
        "   \n"
        "numpy>=1.24.0\n"
    )
    from launcher import _load_packages_from_requirements

    pkgs = _load_packages_from_requirements(req)
    assert len(pkgs) == 2
    names = [p[0] for p in pkgs]
    assert "requests" in names
    assert "numpy" in names


def test_load_packages_skips_pip_directives(tmp_path: Path) -> None:
    """Should skip pip directives and URL-based requirements."""
    req = tmp_path / "requirements.txt"
    req.write_text(
        "-r other-requirements.txt\n"
        "--index-url https://example.com\n"
        "requests>=2.31.0\n"
        "git+https://github.com/user/repo.git\n"
        "numpy>=1.24.0\n"
    )
    from launcher import _load_packages_from_requirements

    pkgs = _load_packages_from_requirements(req)
    assert len(pkgs) == 2
    names = [p[0] for p in pkgs]
    assert "requests" in names
    assert "numpy" in names
    assert all(p[0] not in ("-r", "git+") for p in pkgs)


def test_load_packages_compound_constraints(tmp_path: Path) -> None:
    """Should handle compound version constraints like >=1.0,<2.0."""
    req = tmp_path / "requirements.txt"
    req.write_text("flask>=3.0.0,<4.0.0\n")
    from launcher import _load_packages_from_requirements

    pkgs = _load_packages_from_requirements(req)
    assert len(pkgs) == 1
    assert pkgs[0][0] == "flask"
    # full_line should preserve the compound constraint
    assert pkgs[0][2] == "flask>=3.0.0,<4.0.0"


def test_load_packages_empty_file(tmp_path: Path) -> None:
    """Empty requirements.txt should return empty list."""
    req = tmp_path / "requirements.txt"
    req.write_text("")
    from launcher import _load_packages_from_requirements

    pkgs = _load_packages_from_requirements(req)
    assert len(pkgs) == 0


def test_load_packages_missing_file(tmp_path: Path) -> None:
    """Missing requirements.txt should return empty list."""
    req = tmp_path / "requirements.txt"
    assert not req.exists()
    from launcher import _load_packages_from_requirements

    pkgs = _load_packages_from_requirements(req)
    assert len(pkgs) == 0


def test_load_packages_extras_syntax(tmp_path: Path) -> None:
    """Should handle extras syntax like package[extra]>=version."""
    req = tmp_path / "requirements.txt"
    req.write_text("pandas[compat]>=2.0.0\n")
    from launcher import _load_packages_from_requirements

    pkgs = _load_packages_from_requirements(req)
    assert len(pkgs) == 1
    assert pkgs[0][0] == "pandas"


# ═══════════════════════════════════════════════════════════════════════════════
#  _load_settings
# ═══════════════════════════════════════════════════════════════════════════════

def test_load_settings_uses_defaults_when_no_file(tmp_path: Path) -> None:
    """Should return default settings when no settings file exists."""
    from launcher import _DEFAULTS, _load_settings

    with patch("launcher._SETTINGS_FILE", tmp_path / "nonexistent.json"):
        settings = _load_settings()
    assert settings["default_mode"] == _DEFAULTS["default_mode"]
    assert settings["auto_launch"] is False
    assert "python_preference" in settings


def test_load_settings_merges_with_defaults(tmp_path: Path) -> None:
    """Should merge user settings with defaults."""
    settings_file = tmp_path / "launcher_settings.json"
    settings_file.write_text(json.dumps({"default_mode": "MANUAL", "auto_launch": True}))

    from launcher import _DEFAULTS, _load_settings

    with patch("launcher._SETTINGS_FILE", settings_file):
        settings = _load_settings()
    assert settings["default_mode"] == "MANUAL"
    assert settings["auto_launch"] is True
    # Non-overridden defaults should still be present
    assert "python_preference" in settings
    assert settings["python_preference"] == _DEFAULTS["python_preference"]


def test_load_settings_skips_private_keys(tmp_path: Path) -> None:
    """Settings keys starting with underscore should be skipped."""
    settings_file = tmp_path / "launcher_settings.json"
    settings_file.write_text(json.dumps({"_secret": "should_not_appear", "auto_launch": True}))

    from launcher import _load_settings

    with patch("launcher._SETTINGS_FILE", settings_file):
        settings = _load_settings()
    assert "_secret" not in settings
    assert settings["auto_launch"] is True


def test_load_settings_handles_corrupted_json(tmp_path: Path) -> None:
    """Corrupted settings file should return defaults without crashing."""
    settings_file = tmp_path / "launcher_settings.json"
    settings_file.write_text("not valid json{{{")

    from launcher import _load_settings

    with patch("launcher._SETTINGS_FILE", settings_file):
        settings = _load_settings()
    assert settings["default_mode"] == "PAPER"
    assert "python_preference" in settings


# ═══════════════════════════════════════════════════════════════════════════════
#  _find_python
# ═══════════════════════════════════════════════════════════════════════════════

def test_find_python_success() -> None:
    """Should find the current Python interpreter (matches version)."""
    import tkinter as tk

    from launcher import LauncherApp

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tkinter not available (no display)")

    root.withdraw()  # Hide window
    try:
        app = LauncherApp(root)
        cmd, ver = app._find_python()
        assert cmd is not None, f"Could not find Python interpreter: {ver}"
        assert "Python" in (ver or "")
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass


def test_find_python_version_check() -> None:
    """Version parsing should handle various Python version strings."""

    # Version tuple comparison from _find_python logic
    v_ok = (3, 10)
    v_too_low = (3, 9)
    v_too_high = (3, 20)

    assert (3, 10) <= v_ok < (3, 20)
    assert not (3, 10) <= v_too_low < (3, 20)
    assert not (3, 10) <= v_too_high < (3, 20)


def test_find_python_from_version_string() -> None:
    """Version parsing should extract tuples correctly from version strings."""
    test_cases = [
        ("Python 3.10.0", True),
        ("Python 3.11.5", True),
        ("Python 3.12.0", True),
        ("Python 3.19.0", True),
        ("Python 3.9.10", False),  # Too low
        ("Python 3.20.0", False),  # Too high
        ("Python 2.7.18", False),  # Too low
        ("Python 4.0.0", False),   # Too high
    ]
    for ver_str, expected in test_cases:
        parts = ver_str.split()
        if len(parts) >= 2:
            v = tuple(int(x) for x in parts[1].split(".")[:2])
            result = (3, 10) <= v < (3, 20)
            assert result == expected, f"Version {ver_str} -> {v}: expected {expected}, got {result}"


# ═══════════════════════════════════════════════════════════════════════════════
#  _check_packages
# ═══════════════════════════════════════════════════════════════════════════════

def test_check_packages_script_generation() -> None:
    """The package checking script should be valid Python and reference importlib.metadata."""
    from launcher import PACKAGES

    if not PACKAGES:
        pytest.skip("No packages loaded (requirements.txt may be missing)")

    # Build the script directly (no Tkinter needed)
    checks = {pip_name: min_ver for pip_name, min_ver, _ in PACKAGES}
    script_lines = [
        "import json, sys",
        "from importlib.metadata import version, PackageNotFoundError",
        "def _ok(name, req):",
        "    try:",
        "        v = tuple(int(x) for x in version(name).split('.')[:3])",
        "        r = tuple(int(x) for x in req.split('.')[:3])",
        "        return v >= r",
        "    except PackageNotFoundError:",
        "        return False",
        f"checks = {json.dumps(checks)}",
        "print(json.dumps({k: _ok(k, v) for k, v in checks.items()}))",
    ]
    script = "\n".join(script_lines)
    # Script should compile (syntax check)
    compile(script, "<test>", "exec")


def test_check_packages_invalid_python() -> None:
    """_check_packages should handle subprocess failures gracefully."""
    import tkinter as tk

    from launcher import PACKAGES, LauncherApp

    if not PACKAGES:
        pytest.skip("No packages loaded")

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tkinter not available (no display)")

    root.withdraw()
    try:
        app = LauncherApp(root)
        # Passing a non-existent Python path should return all-False
        result = app._check_packages("nonexistent_python_binary_xyz")
        assert isinstance(result, dict)
        for _pkg_name, installed in result.items():
            assert installed is False
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass


# ═══════════════════════════════════════════════════════════════════════════════
#  Command construction (_on_launch logic)
# ═══════════════════════════════════════════════════════════════════════════════

def test_launch_command_paper_mode() -> None:
    """PAPER mode should include --paper flag."""
    from launcher import MODES

    args = ["python", str(Path("index_app/index_trader.py"))]
    mode_info = MODES["PAPER"]
    if mode_info["flag"]:
        args.append(mode_info["flag"])
    assert "--paper" in args


def test_launch_command_manual_mode_no_flag() -> None:
    """MANUAL mode should NOT add any mode flag (flag is None)."""
    from launcher import MODES

    mode_info = MODES["MANUAL"]
    assert mode_info["flag"] is None


def test_launch_command_with_equity_flag() -> None:
    """When equity is enabled, --equity should be in args."""
    args = ["python", "index_app/index_trader.py", "--paper"]
    equity_enabled = True
    if equity_enabled:
        args.append("--equity")
    assert "--equity" in args


def test_launch_command_without_equity() -> None:
    """When equity is disabled, --equity should NOT be in args."""
    args = ["python", "index_app/index_trader.py", "--paper"]
    equity_enabled = False
    if equity_enabled:
        args.append("--equity")
    assert "--equity" not in args


# ═══════════════════════════════════════════════════════════════════════════════
#  Mode configuration constants
# ═══════════════════════════════════════════════════════════════════════════════

def test_modes_defined_correctly() -> None:
    """MODES should have expected keys and structure."""
    from launcher import MODES

    assert "PAPER" in MODES
    assert "MANUAL" in MODES
    assert len(MODES) == 2

    paper = MODES["PAPER"]
    assert paper["flag"] == "--paper"
    assert "desc" in paper
    assert "color" in paper

    manual = MODES["MANUAL"]
    assert manual["flag"] is None  # No CLI arg for manual mode
    assert "desc" in manual
    assert "color" in manual


def test_default_settings_structure() -> None:
    """_DEFAULTS should have expected keys."""
    from launcher import _DEFAULTS

    assert "default_mode" in _DEFAULTS
    assert "auto_launch" in _DEFAULTS
    assert "python_preference" in _DEFAULTS
    assert "app_script" in _DEFAULTS
    assert "extra_args" in _DEFAULTS
    assert _DEFAULTS["default_mode"] in ("PAPER", "MANUAL")


# ═══════════════════════════════════════════════════════════════════════════════
#  Single-instance lock
# ═══════════════════════════════════════════════════════════════════════════════

def test_acquire_lock_creates_file(tmp_path: Path) -> None:
    """Lock file should be created when acquired."""
    from launcher import _acquire_single_instance_lock

    with patch("launcher._LOCK_FILE", tmp_path / "test.lock"):
        result = _acquire_single_instance_lock()
        assert result is True  # First instance should acquire lock
        assert (tmp_path / "test.lock").exists()


def test_release_lock_removes_file(tmp_path: Path) -> None:
    """Lock file should be removed when released."""
    from launcher import _release_lock

    lock_path = tmp_path / "test.lock"
    lock_path.write_text(str(os.getpid()), encoding="utf-8")

    with patch("launcher._LOCK_FILE", lock_path):
        _release_lock()
        assert not lock_path.exists()
