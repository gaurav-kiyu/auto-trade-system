"""
Tests for ``scripts.check_architecture_compliance`` - ADR 0010 enforcement.

These tests use temporary directories to simulate the project structure
and verify that the checker correctly identifies violations.
"""
from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

# ── Helper to create temp project trees ───────────────────────────────────────


@pytest.fixture
def temp_project(tmp_path: Path) -> Generator[Path, None, None]:
    """Create a temporary directory structure mimicking the project layout.

    Returns the temp root path.
    """
    # core/ modules
    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "services").mkdir()
    (tmp_path / "core" / "ports").mkdir()
    (tmp_path / "core" / "adapters").mkdir()
    (tmp_path / "core" / "invariants").mkdir()
    (tmp_path / "core" / "strategy").mkdir()

    # infrastructure/
    (tmp_path / "infrastructure").mkdir()
    (tmp_path / "infrastructure" / "adapters").mkdir()
    (tmp_path / "infrastructure" / "config").mkdir()
    (tmp_path / "infrastructure" / "market_data").mkdir()

    # scripts/
    (tmp_path / "scripts").mkdir()

    # tests/
    (tmp_path / "tests").mkdir()

    # __init__.py files (needed for imports)
    for pkg in ("core", "infrastructure", "core/services", "core/ports",
                "core/adapters", "core/invariants", "core/strategy",
                "infrastructure/adapters", "infrastructure/config", "infrastructure/market_data"):
        (tmp_path / pkg / "__init__.py").write_text("")

    yield tmp_path


def _write_py(temp_root: Path, rel_path: str, content: str) -> None:
    """Write a Python file under *temp_root* at *rel_path*."""
    full_path = temp_root / rel_path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(content)


# ── Tests for core/ → infrastructure/ import check ──────────────────────────


class TestCoreNoInfrastructureImports:
    def test_clean_core_module_passes(self, temp_project: Path) -> None:
        """A core module that only imports other core/ modules should pass."""
        _write_py(temp_project, "core/foo.py", """
from core.services.risk_service import RiskService
from core.ports.config import ConfigPort
""")
        from unittest.mock import patch

        from scripts.check_architecture_compliance import (
            check_core_no_infrastructure_imports,
        )
        with patch(
            "scripts.check_architecture_compliance.ROOT", temp_project
        ):
            violations = check_core_no_infrastructure_imports()
        # Should have no violations for a clean module
        foo_violations = [v for v in violations if "/foo" in v or "core.foo" in v]
        assert len(foo_violations) == 0

    def test_core_importing_infrastructure_fails(self, temp_project: Path) -> None:
        """A core module importing from infrastructure/ should violate."""
        _write_py(temp_project, "core/bar.py", """
from infrastructure.config.secure_config import SecureConfig
""")
        from unittest.mock import patch

        from scripts.check_architecture_compliance import (
            check_core_no_infrastructure_imports,
        )
        with patch(
            "scripts.check_architecture_compliance.ROOT", temp_project
        ):
            violations = check_core_no_infrastructure_imports()
        # Should find a violation for bar.py importing from infrastructure/
        bar_violations = [v for v in violations if "/bar" in v or "core.bar" in v]
        assert len(bar_violations) >= 1
        assert "IMPORT_VIOLATION" in bar_violations[0]


# ── Tests for dead module import check ─────────────────────────────────────


class TestDeadModulesNotImported:
    def test_dead_module_violation_detected(self, temp_project: Path) -> None:
        """Importing a dead module should be flagged."""
        _write_py(temp_project, "core/zing.py", """
from core.risk.authoritative_engine import something
""")
        from unittest.mock import patch

        from scripts.check_architecture_compliance import (
            check_dead_modules_not_imported,
        )
        # Patch ROOT and _SOURCE_DIRS to use temp project
        patched_dirs = [temp_project / "core"]
        with patch(
            "scripts.check_architecture_compliance.ROOT", temp_project
        ):
            with patch(
                "scripts.check_architecture_compliance._SOURCE_DIRS",
                patched_dirs,
            ):
                violations = check_dead_modules_not_imported()
        # Should find a violation for importing dead module
        zing_violations = [v for v in violations if "core.zing" in v]
        assert len(zing_violations) >= 1
        assert "DEAD_IMPORT" in zing_violations[0]

    def test_clean_module_no_dead_import(self, temp_project: Path) -> None:
        """A clean module should not trigger dead import violations."""
        _write_py(temp_project, "core/safe_mod.py", """
from core.services.risk_service import RiskService
from core.datetime_ist import now_ist
""")
        from unittest.mock import patch

        from scripts.check_architecture_compliance import (
            check_dead_modules_not_imported,
        )
        patched_dirs = [temp_project / "core"]
        with patch(
            "scripts.check_architecture_compliance.ROOT", temp_project
        ):
            with patch(
                "scripts.check_architecture_compliance._SOURCE_DIRS",
                patched_dirs,
            ):
                violations = check_dead_modules_not_imported()
        safe_violations = [v for v in violations if "core.safe_mod" in v]
        assert len(safe_violations) == 0


# ── Tests for canonical module importability ────────────────────────────────


class TestCanonicalModulesImportable:
    def test_required_canonical_list(self) -> None:
        from scripts.check_architecture_compliance import REQUIRED_CANONICAL
        assert "core.services.risk_service" in REQUIRED_CANONICAL
        assert "core.oi_snapshot_store" in REQUIRED_CANONICAL
        assert "core.datetime_ist" in REQUIRED_CANONICAL
        assert len(REQUIRED_CANONICAL) >= 5

    def test_check_function_returns_list(self) -> None:
        from scripts.check_architecture_compliance import (
            check_canonical_modules_importable,
        )
        violations = check_canonical_modules_importable()
        assert isinstance(violations, list)


# ── Tests for strategy no broker import check ───────────────────────────────


class TestStrategyNoBrokerImports:
    def test_strategy_importing_broker_fails(self, temp_project: Path) -> None:
        """A strategy module importing broker adapters should be flagged."""
        _write_py(temp_project, "core/strategy/foo.py", """
from core.adapters.broker_adapters import PaperBrokerAdapter
""")
        from unittest.mock import patch

        from scripts.check_architecture_compliance import (
            check_strategy_no_broker_imports,
        )
        patched_dirs = [temp_project / "core"]
        with patch(
            "scripts.check_architecture_compliance.ROOT", temp_project
        ):
            with patch(
                "scripts.check_architecture_compliance._SOURCE_DIRS",
                patched_dirs,
            ):
                violations = check_strategy_no_broker_imports()
        foo_violations = [v for v in violations if "core.strategy.foo" in v]
        assert len(foo_violations) >= 1
        assert "BROKER_IMPORT_VIOLATION" in foo_violations[0]

    def test_non_strategy_module_not_flagged(self, temp_project: Path) -> None:
        """Non-strategy modules should not be flagged for broker imports."""
        _write_py(temp_project, "core/user_service.py", """
from core.adapters.broker_adapters import PaperBrokerAdapter
""")
        from unittest.mock import patch

        from scripts.check_architecture_compliance import (
            check_strategy_no_broker_imports,
        )
        patched_dirs = [temp_project / "core"]
        with patch(
            "scripts.check_architecture_compliance.ROOT", temp_project
        ):
            with patch(
                "scripts.check_architecture_compliance._SOURCE_DIRS",
                patched_dirs,
            ):
                violations = check_strategy_no_broker_imports()
        # user_service is NOT in STRATEGY_NO_BROKER_MODULES, so shouldn't be flagged
        user_violations = [v for v in violations if "core.user_service" in v]
        assert len(user_violations) == 0


# ── Tests for direct broker SDK import check ───────────────────────────────


class TestNoDirectBrokerSdkImports:
    def test_broker_sdk_in_core_fails(self, temp_project: Path) -> None:
        """Direct kiteconnect import in core/ should be flagged."""
        _write_py(temp_project, "core/foobar.py", """
import kiteconnect
""")
        from unittest.mock import patch

        from scripts.check_architecture_compliance import (
            check_no_direct_broker_sdk_imports,
        )
        with patch(
            "scripts.check_architecture_compliance.ROOT", temp_project
        ):
            violations = check_no_direct_broker_sdk_imports()
        foobar_violations = [v for v in violations if "core.foobar" in v]
        assert len(foobar_violations) >= 1
        assert "BROKER_SDK_IMPORT" in foobar_violations[0]

    def test_exempt_module_not_flagged(self, temp_project: Path) -> None:
        """Exempt modules should not be flagged."""
        _write_py(temp_project, "core/kite_ticker_feed.py", """
from kiteconnect.ticker import KiteTicker
""")
        from unittest.mock import patch

        from scripts.check_architecture_compliance import (
            BROKER_SDK_EXEMPT_MODULES,
            check_no_direct_broker_sdk_imports,
        )
        assert "core.kite_ticker_feed" in BROKER_SDK_EXEMPT_MODULES
        with patch(
            "scripts.check_architecture_compliance.ROOT", temp_project
        ):
            violations = check_no_direct_broker_sdk_imports()
        ticker_violations = [v for v in violations if "core.kite_ticker_feed" in v]
        assert len(ticker_violations) == 0

    def test_clean_module_not_flagged(self, temp_project: Path) -> None:
        """A clean module with no broker SDK imports should not be flagged."""
        _write_py(temp_project, "core/clean_mod.py", """
from core.services.risk_service import RiskService
""")
        from unittest.mock import patch

        from scripts.check_architecture_compliance import (
            check_no_direct_broker_sdk_imports,
        )
        with patch(
            "scripts.check_architecture_compliance.ROOT", temp_project
        ):
            violations = check_no_direct_broker_sdk_imports()
        clean_violations = [v for v in violations if "core.clean_mod" in v]
        assert len(clean_violations) == 0


# ── Tests for main() CLI entry point ─────────────────────────────────────────


class TestMainFunction:
    def test_main_returns_int(self) -> None:
        """Running check on the real project should at least not crash."""
        from scripts.check_architecture_compliance import main
        # Use --ci mode for quiet output
        rc = main(["--ci"])
        assert isinstance(rc, int)
        # rc may be 0 or 1 depending on whether violations exist

    def test_main_respects_ci_flag(self) -> None:
        """--ci flag should suppress verbose output."""
        import contextlib

        # Capture stdout to verify quiet mode
        import io

        from scripts.check_architecture_compliance import main
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = main(["--ci"])
        # In --ci mode, nothing should go to stdout
        assert buf.getvalue() == ""
        assert isinstance(rc, int)

    def test_main_accepts_fixme_flag(self) -> None:
        from scripts.check_architecture_compliance import main
        rc = main(["--fixme"])
        assert isinstance(rc, int)


# ── Tests for helper functions ────────────────────────────────────────────────


class TestHelperFunctions:
    def test_module_name_from_file(self) -> None:
        from scripts.check_architecture_compliance import (
            ROOT,
            _module_name_from_file,
        )
        # Use actual files in the project
        test_file = ROOT / "core" / "oi_snapshot_store.py"
        name = _module_name_from_file(test_file)
        assert name == "core.oi_snapshot_store"

    def test_module_name_from_init(self) -> None:
        from scripts.check_architecture_compliance import (
            ROOT,
            _module_name_from_file,
        )
        test_file = ROOT / "core" / "__init__.py"
        name = _module_name_from_file(test_file)
        assert name == "core"

    def test_list_imports_parses_imports(self, temp_project: Path) -> None:
        from scripts.check_architecture_compliance import _list_imports
        test_file = temp_project / "test_mod.py"
        test_file.write_text("""
import os
import sys
from pathlib import Path
from core.services.risk_service import RiskService
from typing import Any
""")
        imports = _list_imports(test_file)
        assert "os" in imports
        assert "sys" in imports
        assert "core.services.risk_service" in imports

    def test_list_imports_handles_from_import(self, temp_project: Path) -> None:
        from scripts.check_architecture_compliance import _list_imports
        test_file = temp_project / "test_mod2.py"
        test_file.write_text("""
from infrastructure.config import SecureConfig
from core.risk import get_margin_validator
""")
        imports = _list_imports(test_file)
        assert "infrastructure.config" in imports
        assert "core.risk" in imports

    def test_list_imports_handles_syntax_error(self, tmp_path: Path) -> None:
        from scripts.check_architecture_compliance import _list_imports
        test_file = tmp_path / "bad_syntax.py"
        test_file.write_text("this is not valid python {{")
        imports = _list_imports(test_file)
        assert imports == []
