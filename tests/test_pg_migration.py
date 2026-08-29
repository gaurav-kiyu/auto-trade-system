"""Unit tests for scripts/migrate_to_postgresql.py — PostgreSQL Migration Engine.

Tests cover:
  - Data model serialization (MigrationResult, MigrationReport)
  - DDL constant validity (all 19 schemas parse, use PostgreSQL syntax)
  - PG_SCHEMAS dictionary completeness
  - PostgreSQLMigrator: table discovery, type conversion, dry-run mode
  - CLI argument parsing
"""

from __future__ import annotations

import builtins
import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from scripts.migrate_to_postgresql import (
    DDL_DATA_LINEAGE,
    DDL_EVENT_STORE,
    DDL_EXECUTION_STATE,
    DDL_FEATURE_STORE,
    DDL_FORMAL_ORDERS,
    DDL_FUNDAMENTAL_CACHE,
    DDL_FUNDAMENTALS,
    DDL_JOURNAL,
    DDL_MANUAL_SIGNALS,
    DDL_ML_TRACKER,
    DDL_OI_SNAPSHOTS,
    DDL_ORDER_STATE,
    DDL_REGIME,
    DDL_REPLAY,
    DDL_SHADOW_MODE,
    DDL_SME,
    DDL_STRATEGY_PERF,
    DDL_STRATEGY_VERSION,
    DDL_TRADES,
    PG_SCHEMAS,
    MigrationReport,
    MigrationResult,
    PostgreSQLMigrator,
    main,
)

# =========================================================================
# DDL Constants — All 19 schemas
# =========================================================================

ALL_DDLS: dict[str, str] = {
    "DDL_JOURNAL": DDL_JOURNAL,
    "DDL_ML_TRACKER": DDL_ML_TRACKER,
    "DDL_OI_SNAPSHOTS": DDL_OI_SNAPSHOTS,
    "DDL_MANUAL_SIGNALS": DDL_MANUAL_SIGNALS,
    "DDL_DATA_LINEAGE": DDL_DATA_LINEAGE,
    "DDL_SME": DDL_SME,
    "DDL_FUNDAMENTAL_CACHE": DDL_FUNDAMENTAL_CACHE,
    "DDL_EVENT_STORE": DDL_EVENT_STORE,
    "DDL_EXECUTION_STATE": DDL_EXECUTION_STATE,
    "DDL_FEATURE_STORE": DDL_FEATURE_STORE,
    "DDL_SHADOW_MODE": DDL_SHADOW_MODE,
    "DDL_STRATEGY_PERF": DDL_STRATEGY_PERF,
    "DDL_STRATEGY_VERSION": DDL_STRATEGY_VERSION,
    "DDL_FORMAL_ORDERS": DDL_FORMAL_ORDERS,
    "DDL_ORDER_STATE": DDL_ORDER_STATE,
    "DDL_REGIME": DDL_REGIME,
    "DDL_FUNDAMENTALS": DDL_FUNDAMENTALS,
    "DDL_REPLAY": DDL_REPLAY,
    "DDL_TRADES": DDL_TRADES,
}


class TestDDLConstants:
    """Verify all 19 DDL constants are valid PostgreSQL schemas."""

    @pytest.mark.parametrize("ddl_name,ddl_sql", list(ALL_DDLS.items()))
    def test_ddl_is_non_empty(self, ddl_name: str, ddl_sql: str) -> None:
        """Every DDL string must have content."""
        assert ddl_sql.strip(), f"{ddl_name} is empty"

    @pytest.mark.parametrize("ddl_name,ddl_sql", list(ALL_DDLS.items()))
    def test_ddl_has_create_table(self, ddl_name: str, ddl_sql: str) -> None:
        """Every DDL must contain at least one CREATE TABLE."""
        assert "CREATE TABLE" in ddl_sql, f"{ddl_name} missing CREATE TABLE"

    @pytest.mark.parametrize("ddl_name,ddl_sql", list(ALL_DDLS.items()))
    def test_ddl_uses_postgres_types(self, ddl_name: str, ddl_sql: str) -> None:
        """Verify PostgreSQL-specific types are used, not SQLite types."""
        # Should use SERIAL (not AUTOINCREMENT) for identity columns
        assert "AUTOINCREMENT" not in ddl_sql.upper(), (
            f"{ddl_name} uses SQLite AUTOINCREMENT"
        )
        # Every table must use a valid PostgreSQL primary key strategy
        # Valid patterns: SERIAL PRIMARY KEY, VARCHAR(n) PRIMARY KEY, or composite PRIMARY KEY (col, col)
        has_serial_pk = "SERIAL PRIMARY KEY" in ddl_sql.upper()
        has_varchar_pk = "VARCHAR" in ddl_sql.upper() and "PRIMARY KEY" in ddl_sql.upper()
        has_composite_pk = "PRIMARY KEY (" in ddl_sql.upper()
        # Table-only DDLs must have SOME PK strategy
        table_statements = [s.strip() for s in ddl_sql.split(";") if "CREATE TABLE" in s.upper()]
        if table_statements:
            assert has_serial_pk or has_varchar_pk or has_composite_pk or any(
                "PRIMARY KEY" in stmt.upper() for stmt in table_statements
            ), f"{ddl_name} lacks PostgreSQL PK strategy"

    @pytest.mark.parametrize("ddl_name,ddl_sql", list(ALL_DDLS.items()))
    def test_ddl_statements_parse(self, ddl_name: str, ddl_sql: str) -> None:
        """Each DDL should split into valid statements ending with semicolon."""
        statements = [s.strip() for s in ddl_sql.split(";") if s.strip()]
        assert len(statements) >= 1, f"{ddl_name} has no statements"
        for stmt in statements:
            # Each statement should start with a SQL keyword
            assert any(
                stmt.upper().startswith(kw)
                for kw in ["CREATE TABLE", "CREATE INDEX", "CREATE UNIQUE"]
            ), f"{ddl_name} has invalid statement: {stmt[:60]}..."

    def test_all_ddls_unique_names(self) -> None:
        """All DDL names should be distinct."""
        assert len(ALL_DDLS) == 19, f"Expected 19 DDLs, got {len(ALL_DDLS)}"

    def test_ddls_use_if_not_exists(self) -> None:
        """All CREATE TABLE/INDEX statements should use IF NOT EXISTS."""
        for name, ddl in ALL_DDLS.items():
            statements = [s.strip() for s in ddl.split(";") if s.strip()]
            for stmt in statements:
                if stmt.upper().startswith("CREATE"):
                    assert "IF NOT EXISTS" in stmt.upper(), (
                        f"{name} statement missing IF NOT EXISTS: {stmt[:80]}"
                    )


# =========================================================================
# PG_SCHEMAS Dictionary
# =========================================================================


class TestPGSCHEMAS:
    """Verify PG_SCHEMAS dictionary completeness."""

    def test_has_19_databases(self) -> None:
        """Must have exactly 19 database entries."""
        assert len(PG_SCHEMAS) == 19, f"Expected 19 DBs, got {len(PG_SCHEMAS)}"

    def test_all_entries_have_ddl_and_sources(self) -> None:
        """Each entry must be a tuple of (ddl_str, source_file_list)."""
        for db_name, (ddl, sources) in PG_SCHEMAS.items():
            assert isinstance(ddl, str), f"{db_name}: DDL is not a string"
            assert isinstance(sources, list), f"{db_name}: sources is not a list"
            assert len(sources) >= 1, f"{db_name}: no source files listed"

    def test_all_entries_have_create_table(self) -> None:
        """Each DDL must create at least one table."""
        for db_name, (ddl, _sources) in PG_SCHEMAS.items():
            assert "CREATE TABLE" in ddl, (
                f"{db_name}: DDL missing CREATE TABLE"
            )

    def test_known_databases_present(self) -> None:
        """Core databases must be in PG_SCHEMAS."""
        required = [
            "trades.db",
            "trade_journal.db",
            "ml_tracker.db",
            "event_store.db",
            "data_lineage.db",
            "execution_state.db",
        ]
        for db in required:
            assert db in PG_SCHEMAS, f"{db} is missing from PG_SCHEMAS"

    def test_ddl_trades_includes_sme(self) -> None:
        """trades.db DDL should combine DDL_TRADES + DDL_SME."""
        ddl, _sources = PG_SCHEMAS["trades.db"]
        assert "CREATE TABLE IF NOT EXISTS sme_stocks" in ddl
        assert "CREATE TABLE IF NOT EXISTS sme_positions" in ddl
        assert "CREATE TABLE IF NOT EXISTS trades" in ddl


# =========================================================================
# Data Models
# =========================================================================


class TestMigrationResult:
    """Test MigrationResult dataclass."""

    def test_default_values(self) -> None:
        r = MigrationResult()
        assert r.db_name == ""
        assert r.status == ""
        assert r.source_rows == 0
        assert r.migrated_rows == 0
        assert r.tables == []
        assert r.error == ""
        assert r.elapsed_seconds == 0.0
        assert r.warnings == []

    def test_to_dict_basic(self) -> None:
        r = MigrationResult(
            db_name="test.db",
            status="SUCCESS",
            source_rows=10,
            migrated_rows=10,
            tables=["t1"],
            elapsed_seconds=0.5,
        )
        d = r.to_dict()
        assert d["db_name"] == "test.db"
        assert d["status"] == "SUCCESS"
        assert d["source_rows"] == 10
        assert d["migrated_rows"] == 10
        assert d["tables"] == ["t1"]
        assert d["elapsed_seconds"] == 0.5
        assert "DB name" not in d  # not JSON serializable

    def test_to_dict_with_error(self) -> None:
        r = MigrationResult(
            db_name="bad.db",
            status="FAILED",
            error="Disk full",
            elapsed_seconds=1.23,
        )
        d = r.to_dict()
        assert d["error"] == "Disk full"
        assert d["status"] == "FAILED"

    def test_to_dict_json_serializable(self) -> None:
        """to_dict() must be JSON-serializable."""
        r = MigrationResult(
            db_name="j.db", status="SUCCESS", source_rows=5, migrated_rows=5
        )
        json_str = json.dumps(r.to_dict())
        parsed = json.loads(json_str)
        assert parsed["db_name"] == "j.db"


class TestMigrationReport:
    """Test MigrationReport dataclass."""

    def test_empty_report(self) -> None:
        r = MigrationReport()
        assert r.started_at == ""
        assert r.completed_at == ""
        assert r.results == []
        assert r.total_source_rows == 0
        assert r.total_migrated_rows == 0
        assert r.dry_run is False

    def test_summary_text_contains_counts(self) -> None:
        r = MigrationReport(
            started_at="2026-01-01",
            completed_at="2026-01-01",
            results=[
                MigrationResult(
                    db_name="a.db", status="SUCCESS", source_rows=5, migrated_rows=5
                ),
                MigrationResult(
                    db_name="b.db",
                    status="FAILED",
                    source_rows=0,
                    migrated_rows=0,
                    error="timeout",
                ),
            ],
            total_source_rows=5,
            total_migrated_rows=5,
            success_count=1,
            failed_count=1,
            skipped_count=0,
            dry_run=False,
        )
        text = r.summary_text()
        assert "POSTGRESQL MIGRATION REPORT" in text
        assert "LIVE" in text
        assert "[OK]" in text
        assert "[!!]" in text
        assert "a.db" in text
        assert "b.db" in text
        assert "timeout" in text

    def test_summary_dry_run_header(self) -> None:
        r = MigrationReport(dry_run=True)
        assert "DRY RUN" in r.summary_text()

    def test_summary_with_skipped(self) -> None:
        r = MigrationReport(
            results=[
                MigrationResult(db_name="c.db", status="SKIPPED"),
            ],
            skipped_count=1,
        )
        assert "[--]" in r.summary_text()
        assert "c.db" in r.summary_text()


# =========================================================================
# PostgreSQLMigrator — Constructor & Configuration
# =========================================================================


class TestPostgreSQLMigratorInit:
    """Test PostgreSQLMigrator constructor."""

    def test_default_construction(self) -> None:
        m = PostgreSQLMigrator()
        assert m._dry_run is False
        assert m._pg_url == ""
        assert m._pg_conn is None

    def test_dry_run_mode(self) -> None:
        m = PostgreSQLMigrator(dry_run=True)
        assert m._dry_run is True

    def test_pg_url_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPB_PG_URL", "postgresql://user:pass@localhost/mydb")
        m = PostgreSQLMigrator()
        assert m._pg_url == "postgresql://user:pass@localhost/mydb"

    def test_pg_url_constructor_overrides_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPB_PG_URL", "postgresql://bad/db")
        m = PostgreSQLMigrator(pg_url="postgresql://good/db")
        assert m._pg_url == "postgresql://good/db"

    def test_project_root_is_directory(self) -> None:
        m = PostgreSQLMigrator()
        assert m._project_root.is_dir()
        assert (m._project_root / "scripts").is_dir()


# =========================================================================
# PostgreSQLMigrator — _get_tables
# =========================================================================


class TestGetTables:
    """Test SQLite table discovery."""

    def test_discover_user_tables(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE trades (id INTEGER)")
        conn.execute("CREATE TABLE orders (id INTEGER)")
        conn.close()

        m = PostgreSQLMigrator()
        conn2 = sqlite3.connect(str(db))
        tables = m._get_tables(conn2, db)
        conn2.close()
        assert sorted(tables) == ["orders", "trades"]

    def test_filters_sqlite_system_tables(self, tmp_path: Path) -> None:
        db = tmp_path / "test.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE foo (id INTEGER)")
        # sqlite_sequence is auto-created with AUTOINCREMENT
        conn.close()

        m = PostgreSQLMigrator()
        conn2 = sqlite3.connect(str(db))
        tables = m._get_tables(conn2, db)
        conn2.close()
        assert "foo" in tables
        for t in tables:
            assert not t.startswith("sqlite_"), f"Found system table: {t}"

    def test_empty_database(self, tmp_path: Path) -> None:
        db = tmp_path / "empty.db"
        # Create empty database
        sqlite3.connect(str(db)).close()

        m = PostgreSQLMigrator()
        conn = sqlite3.connect(str(db))
        tables = m._get_tables(conn, db)
        conn.close()
        assert tables == []

    def test_no_connection_error_on_missing_db(self) -> None:
        """_get_tables should return empty list on errors."""
        m = PostgreSQLMigrator()
        conn = MagicMock()
        conn.execute.side_effect = Exception("db error")
        tables = m._get_tables(conn, Path("test.db"))  # type: ignore[arg-type]
        assert tables == []


# =========================================================================
# PostgreSQLMigrator — _convert_row
# =========================================================================


class TestConvertRow:
    """Test SQLite-to-PostgreSQL row conversion."""

    def test_normal_values_passthrough(self) -> None:
        m = PostgreSQLMigrator()
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE t (a INTEGER, b TEXT, c REAL)")
        conn.execute("INSERT INTO t VALUES (1, 'hello', 3.14)")
        row = conn.execute("SELECT * FROM t").fetchone()
        conn.close()

        values = m._convert_row(row, ["a", "b", "c"])
        assert values == [1, "hello", 3.14]

    def test_nan_converted_to_none(self) -> None:
        m = PostgreSQLMigrator()

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE t (val REAL)")
        conn.execute("INSERT INTO t VALUES (?)", (float("nan"),))
        row = conn.execute("SELECT * FROM t").fetchone()
        conn.close()

        values = m._convert_row(row, ["val"])
        assert values == [None]

    def test_inf_converted_to_none(self) -> None:
        m = PostgreSQLMigrator()

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE t (val REAL)")
        conn.execute("INSERT INTO t VALUES (?)", (float("inf"),))
        row = conn.execute("SELECT * FROM t").fetchone()
        conn.close()

        values = m._convert_row(row, ["val"])
        assert values == [None]

    def test_neg_inf_converted_to_none(self) -> None:
        m = PostgreSQLMigrator()

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE t (val REAL)")
        conn.execute("INSERT INTO t VALUES (?)", (float("-inf"),))
        row = conn.execute("SELECT * FROM t").fetchone()
        conn.close()

        values = m._convert_row(row, ["val"])
        assert values == [None]

    def test_none_values_passthrough(self) -> None:
        m = PostgreSQLMigrator()
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE t (a TEXT, b REAL)")
        conn.execute("INSERT INTO t VALUES (NULL, NULL)")
        row = conn.execute("SELECT * FROM t").fetchone()
        conn.close()

        values = m._convert_row(row, ["a", "b"])
        assert values == [None, None]

    def test_mixed_types(self) -> None:
        m = PostgreSQLMigrator()

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE t (a REAL, b REAL, c TEXT, d INTEGER, e REAL)"
        )
        conn.execute(
            "INSERT INTO t VALUES (?, ?, ?, ?, ?)",
            (1.0, float("nan"), "ok", 42, float("inf")),
        )
        row = conn.execute("SELECT * FROM t").fetchone()
        conn.close()

        values = m._convert_row(row, ["a", "b", "c", "d", "e"])
        assert values == [1.0, None, "ok", 42, None]


# =========================================================================
# PostgreSQLMigrator — migrate_db (dry-run mode)
# =========================================================================


class TestMigrateDB:
    """Test single database migration (dry-run)."""

    def test_skip_nonexistent_file(self) -> None:
        m = PostgreSQLMigrator(dry_run=True)
        result = m.migrate_db("nonexistent_xyz.db", DDL_TRADES)
        assert result.status == "SKIPPED"
        assert "not found" in (result.warnings[0] if result.warnings else "")

    def test_skip_empty_database(self, tmp_path: Path) -> None:
        db = tmp_path / "empty.db"
        sqlite3.connect(str(db)).close()

        m = PostgreSQLMigrator(dry_run=True)
        m._project_root = tmp_path
        result = m.migrate_db("empty.db", DDL_TRADES)
        assert result.status == "SKIPPED"
        assert "No tables" in (result.warnings[0] if result.warnings else "")

    def test_dry_run_with_data(self, tmp_path: Path) -> None:
        db = tmp_path / "test_data.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE test_table (id INTEGER, value TEXT)")
        conn.execute("INSERT INTO test_table VALUES (1, 'a')")
        conn.execute("INSERT INTO test_table VALUES (2, 'b')")
        conn.commit()
        conn.close()

        m = PostgreSQLMigrator(dry_run=True)
        m._project_root = tmp_path
        result = m.migrate_db("test_data.db", DDL_TRADES)
        assert result.status == "SUCCESS"
        assert result.source_rows == 2
        assert result.migrated_rows == 2  # dry-run reports all rows ready
        assert "DRY RUN" in (result.warnings[0] if result.warnings else "")
        assert "test_table" in (result.tables or [])

    def test_dry_run_reports_table_details(self, tmp_path: Path) -> None:
        db = tmp_path / "detail.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE t1 (a INTEGER, b TEXT, c REAL)")
        conn.execute("INSERT INTO t1 VALUES (10, 'x', 1.5)")
        conn.commit()
        conn.close()

        m = PostgreSQLMigrator(dry_run=True)
        m._project_root = tmp_path
        result = m.migrate_db("detail.db", DDL_TRADES)
        # Should have table detail in warnings
        has_table_detail = any(
            "Table: t1" in w for w in result.warnings
        )
        assert has_table_detail, "Expected table detail in warnings"

    def test_dry_run_does_not_connect_pg(self, tmp_path: Path) -> None:
        db = tmp_path / "nopg.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE t (id INTEGER)")
        conn.execute("INSERT INTO t VALUES (1)")
        conn.commit()
        conn.close()

        m = PostgreSQLMigrator(dry_run=True)
        m._project_root = tmp_path
        result = m.migrate_db("nopg.db", DDL_TRADES)
        assert result.status == "SUCCESS"
        # Should not have connected to PG
        assert m._pg_conn is None


# =========================================================================
# PostgreSQLMigrator — migrate_all
# =========================================================================


class TestMigrateAll:
    """Test full migration run."""

    def test_migrate_all_returns_report(self) -> None:
        m = PostgreSQLMigrator(dry_run=True)
        report = m.migrate_all()
        assert isinstance(report, MigrationReport)
        assert report.dry_run is True
        assert len(report.results) == 19
        assert report.started_at != ""
        assert report.completed_at != ""

    def test_migrate_all_totals_are_consistent(self) -> None:
        m = PostgreSQLMigrator(dry_run=True)
        report = m.migrate_all()
        # Total from report should match sum of individual results
        computed_source = sum(r.source_rows for r in report.results)
        computed_migrated = sum(r.migrated_rows for r in report.results)
        assert report.total_source_rows == computed_source
        assert report.total_migrated_rows == computed_migrated

    def test_migrate_all_no_failures_in_dry_run(self) -> None:
        """Dry-run should never produce FAILED status (only SUCCESS or SKIPPED)."""
        m = PostgreSQLMigrator(dry_run=True)
        report = m.migrate_all()
        for r in report.results:
            assert r.status in ("SUCCESS", "SKIPPED"), (
                f"{r.db_name} has unexpected status: {r.status}"
            )


# =========================================================================
# PostgreSQLMigrator — generate_schema_report
# =========================================================================


class TestGenerateSchemaReport:
    """Test schema report generation."""

    def test_report_mentions_all_databases(self) -> None:
        m = PostgreSQLMigrator()
        report = m.generate_schema_report()
        for db_name in PG_SCHEMAS:
            assert db_name in report, f"{db_name} missing from schema report"

    def test_report_has_correct_count(self) -> None:
        m = PostgreSQLMigrator()
        report = m.generate_schema_report()
        assert f"Databases: {len(PG_SCHEMAS)}" in report

    def test_report_has_source_files(self) -> None:
        m = PostgreSQLMigrator()
        report = m.generate_schema_report()
        for _db_name, (_ddl, sources) in PG_SCHEMAS.items():
            for src in sources:
                assert src in report, f"{src} missing from schema report"

    def test_report_mentions_statement_counts(self) -> None:
        m = PostgreSQLMigrator()
        report = m.generate_schema_report()
        assert "Statements:" in report


# =========================================================================
# PostgreSQLMigrator — _connect_pg
# =========================================================================


class TestConnectPG:
    """Test PostgreSQL connection."""

    def test_raises_value_error_without_url(self) -> None:
        m = PostgreSQLMigrator(pg_url="")
        with pytest.raises(ValueError, match="No PostgreSQL connection URL"):
            m._connect_pg()

    def test_raises_import_error_no_psycopg2(self) -> None:
        m = PostgreSQLMigrator(pg_url="postgresql://localhost/test")
        # Simulate psycopg2 not being installed by monkeypatching __import__
        real_import = builtins.__import__
        def mock_import(name: str, *args: object, **kwargs: object) -> object:
            if name == "psycopg2":
                raise ImportError("No module named psycopg2")
            return real_import(name, *args, **kwargs)
        with patch("builtins.__import__", side_effect=mock_import):
            with pytest.raises(ImportError, match="psycopg2"):
                m._connect_pg()

    @patch.dict("sys.modules", {"psycopg2": MagicMock()})
    def test_connects_successfully(self) -> None:
        import psycopg2  # type: ignore[import-untyped]

        psycopg2.connect.return_value = MagicMock()
        m = PostgreSQLMigrator(pg_url="postgresql://localhost/test")
        conn = m._connect_pg()
        assert conn is not None
        psycopg2.connect.assert_called_once_with(
            "postgresql://localhost/test"
        )


# =========================================================================
# CLI — main() function
# =========================================================================


class TestCLI:
    """Test CLI argument parsing."""

    def test_schema_only_flag(self) -> None:
        exit_code = main(["--schema-only"])
        assert exit_code == 0

    def test_dry_run_single_db(self) -> None:
        """Requesting --dry-run for a known DB should succeed."""
        exit_code = main(["--dry-run", "--db", "data_lineage.db"])
        assert exit_code == 0

    def test_unknown_db_returns_error(self) -> None:
        exit_code = main(["--db", "nonexistent.db"])
        assert exit_code == 1

    def test_default_mode_shows_help(self) -> None:
        """Running with no args should show help and exit 0."""
        exit_code = main([])
        assert exit_code == 0

    def test_dry_run_all(self) -> None:
        exit_code = main(["--dry-run", "--all"])
        assert exit_code == 0

    def test_verbose_flag(self) -> None:
        exit_code = main(["--verbose", "--schema-only"])
        assert exit_code == 0

    def test_connection_flag(self) -> None:
        """--connection should be accepted without error."""
        exit_code = main(
            ["--schema-only", "--connection", "postgresql://host/db"]
        )
        assert exit_code == 0


# =========================================================================
# Integration — dry-run on real SQLite databases
# =========================================================================


@pytest.mark.slow
class TestIntegrationDryRun:
    """Integration tests using actual SQLite databases in the project root.

    Marked @pytest.mark.slow because these open real SQLite databases from disk.
    Skipped gracefully if target databases are not found.
    """

    def test_dry_run_existing_db_produces_correct_counts(self) -> None:
        """Verify dry-run of ml_tracker.db returns correct row counts."""
        ml_db = Path("db/ml_tracker.db")
        if not ml_db.is_file():
            pytest.skip("ml_tracker.db not found — skipping integration test")
        m = PostgreSQLMigrator(dry_run=True)
        ddl, _sources = PG_SCHEMAS["ml_tracker.db"]
        result = m.migrate_db("ml_tracker.db", ddl)
        assert result.status == "SUCCESS"
        assert result.source_rows > 0, "Expected rows in ml_tracker.db"
        assert result.source_rows == result.migrated_rows

    def test_dry_run_data_lineage(self) -> None:
        """Verify dry-run of data_lineage.db works."""
        dl_db = Path("db/data_lineage.db")
        if not dl_db.is_file():
            pytest.skip("data_lineage.db not found")
        m = PostgreSQLMigrator(dry_run=True)
        ddl, _sources = PG_SCHEMAS["data_lineage.db"]
        result = m.migrate_db("data_lineage.db", ddl)
        assert result.status in ("SUCCESS", "SKIPPED")

    def test_dry_run_event_store(self) -> None:
        """Verify dry-run of event_store.db (largest DB) works."""
        ev_db = Path("db/event_store.db")
        if not ev_db.is_file():
            pytest.skip("event_store.db not found")
        import sqlite3

        conn = sqlite3.connect(str(ev_db))
        try:
            rows = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        finally:
            conn.close()
        if rows == 0:
            pytest.skip("event_store.db has no rows (runtime data not yet populated)")
        m = PostgreSQLMigrator(dry_run=True)
        ddl, _sources = PG_SCHEMAS["event_store.db"]
        result = m.migrate_db("event_store.db", ddl)
        assert result.status == "SUCCESS"
        assert result.source_rows > 0, "Expected events in event_store.db"
        # Should report events table details
        has_events_detail = any(
            "Table: events" in w for w in result.warnings
        )
        assert has_events_detail, "Expected events table detail in warnings"
