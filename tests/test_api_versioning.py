"""Tests for API Versioning module."""

from __future__ import annotations

import pytest
from core.api_versioning import (
    APIRequestRecord,
    APIVersionInfo,
    APIVersionReport,
    get_api_version_manager,
    reset_api_version_manager,
)


@pytest.fixture(autouse=True)
def reset_mgr():
    reset_api_version_manager()
    yield
    reset_api_version_manager()


class TestVersionRegistration:
    def test_default_versions(self):
        mgr = get_api_version_manager()
        stats = mgr.get_stats()
        assert stats["registered_versions"] == 3
        assert stats["current_version"] == "v3"

    def test_register_new_version(self):
        mgr = get_api_version_manager()
        mgr.register_version("v4", status="BETA", changelog=["New feature X"])
        info = mgr.get_version_info("v4")
        assert info is not None
        assert info.status == "BETA"
        assert "New feature X" in info.changelog

    def test_deprecate_version(self):
        mgr = get_api_version_manager()
        assert mgr.deprecate_version("v1") is True
        info = mgr.get_version_info("v1")
        assert info.status == "DEPRECATED"

    def test_deprecate_nonexistent(self):
        mgr = get_api_version_manager()
        assert mgr.deprecate_version("v99") is False


class TestVersionExtraction:
    def test_extract_from_x_header(self):
        mgr = get_api_version_manager()
        headers = {"x-api-version": "v2"}
        version = mgr.extract_version(headers)
        assert version == "v2"

    def test_extract_from_accept_header(self):
        mgr = get_api_version_manager()
        headers = {"accept": "application/vnd.opb.v2+json"}
        version = mgr.extract_version(headers)
        assert version == "v2"

    def test_extract_default_version(self):
        mgr = get_api_version_manager()
        headers = {}
        version = mgr.extract_version(headers)
        assert version == "v3"

    def test_extract_invalid_version(self):
        mgr = get_api_version_manager()
        headers = {"x-api-version": "v99"}
        version = mgr.extract_version(headers)
        assert version == "v3"  # Falls back to default


class TestDeprecation:
    def test_is_deprecated(self):
        mgr = get_api_version_manager()
        assert mgr.is_deprecated("v1") is True  # SUNSET
        assert mgr.is_deprecated("v2") is True  # DEPRECATED

    def test_is_not_deprecated(self):
        mgr = get_api_version_manager()
        assert mgr.is_deprecated("v3") is False

    def test_is_deprecated_nonexistent(self):
        mgr = get_api_version_manager()
        assert mgr.is_deprecated("v99") is False


class TestRequestTracking:
    def test_record_request(self):
        mgr = get_api_version_manager()
        record = mgr.record_request("/api/v3/health", "GET", "v3", "test-client")
        assert record.path == "/api/v3/health"
        assert record.method == "GET"
        assert record.version == "v3"

    def test_record_deprecated_request(self):
        mgr = get_api_version_manager()
        record = mgr.record_request("/api/v1/old", "GET", "v1")
        assert record.deprecated is True

    def test_get_report(self):
        mgr = get_api_version_manager()
        mgr.record_request("/api/v3/health", "GET", "v3")
        mgr.record_request("/api/v2/old", "GET", "v2")
        mgr.record_request("/api/v1/legacy", "GET", "v1")
        report = mgr.get_report()
        assert report.requests_tracked == 3
        assert report.deprecated_requests >= 2
        assert "v3" in report.version_distribution

    def test_get_stats(self):
        mgr = get_api_version_manager()
        mgr.record_request("/api/v3/test", "GET", "v3")
        stats = mgr.get_stats()
        assert stats["requests_tracked"] >= 1
        assert stats["current_version"] == "v3"

    def test_migration_path(self):
        mgr = get_api_version_manager()
        path = mgr.get_migration_path("v1", "v3")
        assert len(path) >= 2
        assert any("v1" in step or "v3" in step for step in path)


class TestAPIVersionModels:
    def test_version_info_to_dict(self):
        info = APIVersionInfo(version="v4", status="BETA")
        d = info.to_dict()
        assert d["version"] == "v4"
        assert d["status"] == "BETA"

    def test_request_record_to_dict(self):
        r = APIRequestRecord(path="/api/test", method="GET", version="v3")
        d = r.to_dict()
        assert d["version"] == "v3"

    def test_report_summary_text(self):
        r = APIVersionReport(current_version="v3", requests_tracked=100, deprecated_percentage=0.1)
        text = r.summary_text()
        assert "API VERSION" in text
        assert "v3" in text
