"""Tests for core/service_catalog.py — Platform Engineering Service Catalog.

Constitution v4.0 — Internal Developer Platform.
"""

from __future__ import annotations

import os

import pytest
from core.service_catalog import (
    Environment,
    GoldenPath,
    ServiceCatalog,
    ServiceEntry,
    get_service_catalog,
    reset_service_catalog,
)

# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_service_catalog()
    yield
    reset_service_catalog()


@pytest.fixture
def catalog(tmp_path) -> ServiceCatalog:
    storage = str(tmp_path / "test_catalog.json")
    return ServiceCatalog(storage_path=storage)


@pytest.fixture
def sample_service() -> ServiceEntry:
    return ServiceEntry(
        name="test_trader",
        domain="trading",
        owner="team-core",
        version="2.56.0",
        status="ACTIVE",
        runbook_path="docs/runbooks/test.md",
        sla_pct=99.5,
        has_tests=True,
        has_documentation=True,
    )


@pytest.fixture
def populated_catalog(tmp_path, sample_service) -> ServiceCatalog:
    storage = str(tmp_path / "populated.json")
    cat = ServiceCatalog(storage_path=storage)
    cat.register_service(sample_service)
    cat.register_service(ServiceEntry(
        name="risk_engine", domain="risk", owner="team-risk",
        status="ACTIVE", is_healthy=True,
    ))
    cat.register_service(ServiceEntry(
        name="old_service", domain="infrastructure", owner="team-infra",
        status="DORMANT", runbook_path="", has_tests=False,
        has_documentation=False, is_healthy=False,
    ))
    cat.register_environment(Environment(name="production", services=["test_trader"], is_healthy=True))
    cat.register_environment(Environment(name="staging", services=["test_trader"], is_healthy=True))
    cat.register_golden_path(GoldenPath(name="default", description="Standard service journey"))
    return cat


# ── ServiceEntry Tests ───────────────────────────────────────────────────────


class TestServiceEntry:
    def test_defaults(self):
        entry = ServiceEntry(name="svc")
        assert entry.domain == ""
        assert entry.owner == "unassigned"
        assert entry.status == "ACTIVE"
        assert entry.sla_pct == 99.0
        assert entry.maturity_level == "LEVEL_3"
        assert entry.registered_at > 0
        assert entry.is_healthy is True
        assert entry.has_tests is True
        assert entry.has_documentation is True

    def test_to_dict_includes_all_fields(self):
        entry = ServiceEntry(
            name="svc", domain="trading", owner="me",
            tags=["critical"], dependencies=["db"],
        )
        d = entry.to_dict()
        assert d["name"] == "svc"
        assert d["domain"] == "trading"
        assert d["tags"] == ["critical"]
        assert d["dependencies"] == ["db"]
        assert "registered_at" in d
        assert "updated_at" in d

    def test_to_dict_immutable(self):
        entry = ServiceEntry(name="svc", tags=["a"])
        d = entry.to_dict()
        d["tags"].append("b")
        # Original should not be affected
        assert entry.tags == ["a"]


# ── ServiceCatalog Tests ──────────────────────────────────────────────────────


class TestServiceCatalogRegistration:
    def test_register_service(self, catalog, sample_service):
        catalog.register_service(sample_service)
        assert catalog.get_service("test_trader") is not None
        assert catalog.get_service("test_trader").domain == "trading"

    def test_register_service_updates_timestamp(self, catalog, sample_service):
        catalog.register_service(sample_service)
        ts1 = catalog.get_service("test_trader").updated_at
        catalog.register_service(sample_service)
        ts2 = catalog.get_service("test_trader").updated_at
        assert ts2 >= ts1

    def test_register_service_preserves_registration_time(self, catalog, sample_service):
        catalog.register_service(sample_service)
        rt1 = catalog.get_service("test_trader").registered_at
        catalog.register_service(sample_service)
        rt2 = catalog.get_service("test_trader").registered_at
        assert rt2 == rt1

    def test_unregister_service(self, catalog, sample_service):
        catalog.register_service(sample_service)
        assert catalog.unregister_service("test_trader") is True
        assert catalog.get_service("test_trader") is None

    def test_unregister_nonexistent(self, catalog):
        assert catalog.unregister_service("nonexistent") is False

    def test_get_service_nonexistent(self, catalog):
        assert catalog.get_service("nonexistent") is None

    def test_list_services(self, populated_catalog):
        services = populated_catalog.list_services()
        assert len(services) == 3

    def test_list_services_filter_domain(self, populated_catalog):
        services = populated_catalog.list_services(domain="trading")
        assert len(services) == 1
        assert services[0].name == "test_trader"

    def test_list_services_filter_status(self, populated_catalog):
        services = populated_catalog.list_services(status="DORMANT")
        assert len(services) == 1
        assert services[0].name == "old_service"

    def test_list_services_filter_empty(self, catalog):
        assert len(catalog.list_services(domain="nonexistent")) == 0

    def test_update_health(self, catalog, sample_service):
        catalog.register_service(sample_service)
        assert catalog.update_health("test_trader", False) is True
        assert catalog.get_service("test_trader").is_healthy is False

    def test_update_health_nonexistent(self, catalog):
        assert catalog.update_health("nonexistent", True) is False


class TestServiceCatalogGoldenPaths:
    def test_register_golden_path(self, catalog):
        path = GoldenPath(name="critical_service")
        catalog.register_golden_path(path)
        paths = catalog.get_golden_paths()
        assert len(paths) == 1
        assert paths[0].name == "critical_service"

    def test_check_maturity_existing(self, catalog, sample_service):
        catalog.register_service(sample_service)
        result = catalog.check_service_maturity("test_trader")
        assert result["found"] is True
        assert result["maturity_level"] == "LEVEL_3"
        assert result["passed_checks"] >= 3

    def test_check_maturity_nonexistent(self, catalog):
        result = catalog.check_service_maturity("nonexistent")
        assert result["found"] is False

    def test_check_maturity_missing_runbook(self, catalog):
        entry = ServiceEntry(name="no_runbook", has_tests=True, has_documentation=True, runbook_path="")
        catalog.register_service(entry)
        result = catalog.check_service_maturity("no_runbook")
        assert result["checks"]["has_runbook"] is False
        assert result["passed_checks"] == result["total_checks"] - 1

    def test_get_golden_paths_empty(self, catalog):
        assert len(catalog.get_golden_paths()) == 0


class TestServiceCatalogEnvironments:
    def test_register_environment(self, catalog):
        env = Environment(name="production", services=["core"])
        catalog.register_environment(env)
        envs = catalog.get_environments()
        assert len(envs) == 1
        assert envs[0].name == "production"

    def test_deploy_to_environment(self, catalog):
        env = Environment(name="production")
        catalog.register_environment(env)
        assert catalog.deploy_to_environment("production", "2.56.0") is True
        envs = catalog.get_environments()
        assert envs[0].version == "2.56.0"
        assert envs[0].deploy_count == 1

    def test_deploy_to_nonexistent(self, catalog):
        assert catalog.deploy_to_environment("nonexistent", "1.0") is False

    def test_deploy_increments_count(self, catalog):
        env = Environment(name="prod")
        catalog.register_environment(env)
        catalog.deploy_to_environment("prod", "1.0")
        catalog.deploy_to_environment("prod", "2.0")
        envs = catalog.get_environments()
        assert envs[0].deploy_count == 2


class TestServiceCatalogReport:
    def test_get_report_counts(self, populated_catalog):
        report = populated_catalog.get_report()
        assert report.total_services == 3
        assert report.active_services == 2
        assert report.healthy_count == 2

    def test_get_report_domains(self, populated_catalog):
        report = populated_catalog.get_report()
        assert "trading" in report.domains
        assert "risk" in report.domains

    def test_get_report_maturity(self, populated_catalog):
        report = populated_catalog.get_report()
        assert "LEVEL_3" in report.maturity_distribution

    def test_get_report_unhealthy(self, populated_catalog):
        report = populated_catalog.get_report()
        assert "old_service" in report.unhealthy_services

    def test_get_report_owners(self, populated_catalog):
        report = populated_catalog.get_report()
        assert "team-core" in report.owners
        assert len(report.owners["team-core"]) == 1

    def test_get_report_missing_runbook(self, populated_catalog):
        report = populated_catalog.get_report()
        assert "old_service" in report.services_missing_runbook

    def test_get_report_missing_tests(self, populated_catalog):
        report = populated_catalog.get_report()
        assert "old_service" in report.services_missing_tests

    def test_get_report_missing_docs(self, populated_catalog):
        report = populated_catalog.get_report()
        assert "old_service" in report.services_missing_docs

    def test_get_report_average_sla(self, populated_catalog):
        report = populated_catalog.get_report()
        assert report.average_sla > 0

    def test_get_report_environment_summary(self, populated_catalog):
        report = populated_catalog.get_report()
        assert "production" in report.environment_summary
        assert report.environment_summary["production"]["services"] == 1

    def test_report_empty_catalog(self, catalog):
        report = catalog.get_report()
        assert report.total_services == 0
        assert report.average_sla == 0.0

    def test_report_summary_text(self, populated_catalog):
        text = populated_catalog.get_report().summary_text()
        assert "SERVICE CATALOG" in text
        assert "Platform Engineering" in text
        assert "3" in text  # total services


class TestServiceCatalogStats:
    def test_get_stats(self, populated_catalog):
        stats = populated_catalog.get_stats()
        assert stats["total_services"] == 3
        assert stats["active_services"] == 2
        assert stats["healthy_count"] == 2
        assert stats["golden_paths"] == 1
        assert stats["environments"] == 2

    def test_get_stats_empty(self, catalog):
        stats = catalog.get_stats()
        assert stats["total_services"] == 0


class TestServiceCatalogPersistence:
    def test_persists_and_loads(self, tmp_path, sample_service):
        storage = str(tmp_path / "persist.json")
        cat1 = ServiceCatalog(storage_path=storage)
        cat1.register_service(sample_service)
        cat1.register_environment(Environment(name="prod"))

        # Create new instance with same storage - should load saved data
        cat2 = ServiceCatalog(storage_path=storage)
        assert cat2.get_service("test_trader") is not None
        assert cat2.get_service("test_trader").domain == "trading"
        assert len(cat2.get_environments()) == 1

    def test_loads_corrupted_file_gracefully(self, tmp_path):
        storage = str(tmp_path / "corrupt.json")
        with open(storage, "w") as f:
            f.write("not valid json")
        cat = ServiceCatalog(storage_path=storage)
        # Should not crash
        assert cat.get_stats()["total_services"] == 0

    def test_loads_empty_file_gracefully(self, tmp_path):
        storage = str(tmp_path / "empty.json")
        with open(storage, "w") as f:
            f.write("")
        cat = ServiceCatalog(storage_path=storage)
        assert cat.get_stats()["total_services"] == 0

    def test_save_and_load_maturity(self, tmp_path):
        storage = str(tmp_path / "maturity.json")
        cat1 = ServiceCatalog(storage_path=storage)
        cat1.register_service(ServiceEntry(name="svc", maturity_level="LEVEL_1"))
        cat2 = ServiceCatalog(storage_path=storage)
        assert cat2.get_service("svc").maturity_level == "LEVEL_1"


class TestServiceCatalogEdgeCases:
    def test_register_same_name_twice(self, catalog, sample_service):
        catalog.register_service(sample_service)
        catalog.register_service(sample_service)
        assert len(catalog.list_services()) == 1

    def test_register_empty_name(self, catalog):
        entry = ServiceEntry(name="")
        catalog.register_service(entry)
        assert catalog.get_service("") is not None

    def test_unregister_all(self, catalog):
        for i in range(5):
            catalog.register_service(ServiceEntry(name=f"svc_{i}"))
        for i in range(5):
            assert catalog.unregister_service(f"svc_{i}") is True
        assert len(catalog.list_services()) == 0


class TestServiceCatalogReportMethods:
    def test_report_to_dict(self, populated_catalog):
        report = populated_catalog.get_report()
        d = report.to_dict()
        assert d["total_services"] == 3
        assert "domains" in d
        assert "owners" in d
        assert "health" in d or "healthy_count" in d  # schema name


class TestServiceCatalogLazyInit:
    def test_get_service_catalog_singleton(self):
        c1 = get_service_catalog()
        c2 = get_service_catalog()
        assert c1 is c2

    def test_reset_service_catalog(self):
        c1 = get_service_catalog()
        c1.register_service(ServiceEntry(name="before_reset"))
        reset_service_catalog()
        c2 = get_service_catalog()
        assert c1 is not c2
        assert c2.get_service("before_reset") is None


# ── ServiceCatalogReport SummaryText ─────────────────────────────────────────


class TestServiceCatalogReportSummary:
    def test_summary_text_formatting(self, populated_catalog):
        text = populated_catalog.get_report().summary_text()
        assert text.startswith("═")
        assert "SERVICE CATALOG" in text.upper()


# ── Singleton Tests ─────────────────────────────────────────────────────────


class TestSingleton:
    def test_nested_reset_safety(self):
        c1 = get_service_catalog()
        c1.register_service(ServiceEntry(name="svc1"))
        reset_service_catalog()
        c2 = get_service_catalog()
        c2.register_service(ServiceEntry(name="svc2"))
        assert c2.get_service("svc2") is not None
        assert c2.get_service("svc1") is None

    def test_multi_thread_safety(self):
        import threading
        errors = []
        def worker(name: str):
            try:
                cat = get_service_catalog()
                cat.register_service(ServiceEntry(name=name))
            except Exception as e:
                errors.append(e)
        threads = [
            threading.Thread(target=worker, args=(f"thread_svc_{i}",))
            for i in range(10)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(errors) == 0


@pytest.fixture(autouse=True)
def _clean_storage():
    """Remove any test service_catalog.json files after tests."""
    yield
    for f in ["service_catalog.json"]:
        if os.path.isfile(f):
            try:
                os.remove(f)
            except OSError:
                pass
