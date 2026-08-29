"""API Versioning — Version Header Enforcement Middleware (Constitution v4.0).

Provides API version management:
- Version header extraction and validation (X-API-Version, Accept header)
- Deprecation warnings for older versions
- Version routing support
- API changelog tracking
- Version compatibility matrix

Integrates with:
- EnterpriseDashboard for route registration
- LivingDocumentation for API docs

Usage:
    from core.api_versioning import APIVersionManager, get_api_version_manager

    mgr = get_api_version_manager()
    mgr.register_version("v1", deprecated=False)
    mgr.register_version("v2", deprecated=False)

    # In FastAPI middleware:
    version = mgr.extract_version(request)
    if mgr.is_deprecated(version):
        response.headers["X-API-Deprecated"] = version
"""

from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

_log = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────

ACCEPT_VERSION_PATTERN = re.compile(r"application/vnd\.opb\.(\w+)\+json")
HEADER_VERSION_PATTERN = re.compile(r"^[vV](\d+)$")

CURRENT_VERSION = "v3"
SUPPORTED_VERSIONS = ("v1", "v2", "v3")
VERSION_LIFECYCLE = ("ALPHA", "BETA", "STABLE", "DEPRECATED", "SUNSET")


# ── Data Models ────────────────────────────────────────────────────────────


@dataclass
class APIVersionInfo:
    """Information about a single API version."""

    version: str = ""
    status: str = "STABLE"  # ALPHA, BETA, STABLE, DEPRECATED, SUNSET
    introduced_at: float = 0.0
    deprecated_at: float = 0.0
    sunset_at: float = 0.0
    changelog: list[str] = field(default_factory=list)
    migration_guide: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "status": self.status,
            "introduced_at": self.introduced_at,
            "introduced_date": datetime.fromtimestamp(self.introduced_at).isoformat() if self.introduced_at else "",
            "deprecated_at": self.deprecated_at,
            "sunset_at": self.sunset_at,
            "changelog": self.changelog,
            "migration_guide": self.migration_guide[:200] if self.migration_guide else "",
            "is_deprecated": self.status == "DEPRECATED",
            "is_sunset": self.status == "SUNSET",
            "is_stable": self.status == "STABLE",
        }


@dataclass
class APIRequestRecord:
    """Record of an API request with version info."""

    timestamp: float = 0.0
    path: str = ""
    method: str = ""
    version: str = ""
    deprecated: bool = False
    client: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "date": datetime.fromtimestamp(self.timestamp).isoformat() if self.timestamp else "",
            "path": self.path[:80],
            "method": self.method,
            "version": self.version,
            "deprecated": self.deprecated,
            "client": self.client[:60],
        }


@dataclass
class APIVersionReport:
    """Aggregated API version report."""

    timestamp: float = 0.0
    current_version: str = CURRENT_VERSION
    versions: list[APIVersionInfo] = field(default_factory=list)
    requests_tracked: int = 0
    deprecated_requests: int = 0
    deprecated_percentage: float = 0.0
    version_distribution: dict[str, int] = field(default_factory=dict)
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "current_version": self.current_version,
            "versions": [v.to_dict() for v in self.versions],
            "requests_tracked": self.requests_tracked,
            "deprecated_requests": self.deprecated_requests,
            "deprecated_percentage": round(self.deprecated_percentage, 2),
            "version_distribution": self.version_distribution,
            "recommendations": self.recommendations,
        }

    def summary_text(self) -> str:
        lines = [
            "═" * 60,
            "  API VERSION MANAGEMENT REPORT",
            "═" * 60,
            f"  Current Version: {self.current_version}",
            f"  Requests Tracked: {self.requests_tracked}",
            f"  Deprecated Requests: {self.deprecated_requests} ({self.deprecated_percentage:.1%})",
            "",
        ]
        if self.versions:
            lines.append("  Registered Versions:")
            for v in self.versions:
                lines.append(f"    {v.version}: {v.status}")
        if self.version_distribution:
            lines.append("  Version Distribution:")
            for ver, count in sorted(self.version_distribution.items(), key=lambda x: x[1], reverse=True):
                lines.append(f"    {ver}: {count}")
        if self.recommendations:
            lines.append("  Recommendations:")
            for r in self.recommendations:
                lines.append(f"    → {r}")
        lines.append("═" * 60)
        return "\n".join(lines)


# ── API Version Manager ────────────────────────────────────────────────────


class APIVersionManager:
    """API Versioning — Header Enforcement & Management.

    Manages API version lifecycle:
    - Register versions with lifecycle status
    - Extract version from request headers
    - Deprecation tracking and warnings
    - Usage analytics per version
    - Migration guidance

    Thread-safe.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._versions: dict[str, APIVersionInfo] = {}
        self._request_log: list[APIRequestRecord] = []
        self._max_log = 1000
        self._init_defaults()

    def _init_defaults(self) -> None:
        """Initialize default API versions."""
        now = time.time()
        self._versions = {
            "v1": APIVersionInfo(
                version="v1", status="SUNSET",
                introduced_at=now - 86400 * 365,
                deprecated_at=now - 86400 * 180,
                sunset_at=now - 86400 * 90,
                changelog=["Initial API release"],
                migration_guide="Upgrade to v3: see https://docs.opb.io/migration/v1-to-v3",
            ),
            "v2": APIVersionInfo(
                version="v2", status="DEPRECATED",
                introduced_at=now - 86400 * 180,
                deprecated_at=now - 86400 * 30,
                changelog=["Added intelligence endpoints", "New config API"],
                migration_guide="Upgrade to v3: see https://docs.opb.io/migration/v2-to-v3",
            ),
            "v3": APIVersionInfo(
                version="v3", status="STABLE",
                introduced_at=now,
                changelog=["Unified intelligence API", "Webhook support", "RBAC integration"],
            ),
        }

    # ── Public API ────────────────────────────────────────────────────────

    def register_version(
        self,
        version: str,
        status: str = "STABLE",
        changelog: list[str] | None = None,
        migration_guide: str = "",
    ) -> APIVersionInfo:
        """Register a new API version.

        Args:
            version: Version identifier (e.g., 'v4').
            status: Lifecycle status (ALPHA, BETA, STABLE, DEPRECATED, SUNSET).
            changelog: List of changes in this version.
            migration_guide: Migration instructions for upgrading.

        Returns:
            APIVersionInfo for the registered version.
        """
        clean_status = status.upper() if status.upper() in VERSION_LIFECYCLE else "STABLE"
        now = time.time()
        info = APIVersionInfo(
            version=version,
            status=clean_status,
            introduced_at=now,
            changelog=changelog or [],
            migration_guide=migration_guide,
        )
        with self._lock:
            self._versions[version] = info
        _log.info("[API_VER] Registered version %s as %s", version, clean_status)
        return info

    def deprecate_version(self, version: str, sunset_days: int = 90) -> bool:
        """Mark a version as deprecated.

        Args:
            version: Version to deprecate.
            sunset_days: Days until the version is fully sunset.

        Returns:
            True if deprecated, False if version not found.
        """
        with self._lock:
            info = self._versions.get(version)
            if info is None:
                return False
            info.status = "DEPRECATED"
            info.deprecated_at = time.time()
            info.sunset_at = time.time() + (86400 * sunset_days)
            return True

    def extract_version(self, headers: dict[str, str]) -> str:
        """Extract API version from request headers.

        Checks (in order):
        1. X-API-Version header
        2. Accept header (application/vnd.opb.v3+json)
        3. Default to current version

        Args:
            headers: Request headers dict.

        Returns:
            Version string (e.g., 'v3').
        """
        # Check X-API-Version header
        api_version = headers.get("x-api-version", headers.get("X-API-Version", ""))
        if api_version:
            match = HEADER_VERSION_PATTERN.match(api_version)
            if match and f"v{match.group(1)}" in self._versions:
                return f"v{match.group(1)}"

        # Check Accept header
        accept = headers.get("accept", headers.get("Accept", ""))
        match = ACCEPT_VERSION_PATTERN.search(accept)
        if match:
            version = match.group(1)
            if version in self._versions:
                return version

        return CURRENT_VERSION

    def is_deprecated(self, version: str) -> bool:
        """Check if a version is deprecated or sunset."""
        with self._lock:
            info = self._versions.get(version)
            if info is None:
                return False
            return info.status in ("DEPRECATED", "SUNSET")

    def get_version_info(self, version: str) -> APIVersionInfo | None:
        """Get info about a specific version."""
        with self._lock:
            return self._versions.get(version)

    def record_request(
        self,
        path: str,
        method: str = "GET",
        version: str = CURRENT_VERSION,
        client: str = "",
    ) -> APIRequestRecord:
        """Record an API request for analytics.

        Args:
            path: Request path.
            method: HTTP method.
            version: API version used.
            client: Client identifier.

        Returns:
            APIRequestRecord.
        """
        record = APIRequestRecord(
            timestamp=time.time(),
            path=path,
            method=method,
            version=version,
            deprecated=self.is_deprecated(version),
            client=client,
        )
        with self._lock:
            self._request_log.append(record)
            if len(self._request_log) > self._max_log:
                self._request_log = self._request_log[-self._max_log:]
        return record

    def get_report(self) -> APIVersionReport:
        """Generate aggregated API version report."""
        with self._lock:
            report = APIVersionReport(
                timestamp=time.time(),
                current_version=CURRENT_VERSION,
                versions=list(self._versions.values()),
                requests_tracked=len(self._request_log),
            )

            # Deprecated request tracking
            deprecated = [r for r in self._request_log if r.deprecated]
            report.deprecated_requests = len(deprecated)
            if self._request_log:
                report.deprecated_percentage = len(deprecated) / len(self._request_log)

            # Version distribution
            dist: dict[str, int] = {}
            for r in self._request_log:
                dist[r.version] = dist.get(r.version, 0) + 1
            report.version_distribution = dist

            # Recommendations
            report.recommendations = self._generate_recommendations(report)

            return report

    def get_stats(self) -> dict[str, Any]:
        """Get API version statistics."""
        with self._lock:
            return {
                "registered_versions": len(self._versions),
                "current_version": CURRENT_VERSION,
                "deprecated_versions": sum(1 for v in self._versions.values() if v.status == "DEPRECATED"),
                "sunset_versions": sum(1 for v in self._versions.values() if v.status == "SUNSET"),
                "requests_tracked": len(self._request_log),
                "versions": {k: v.status for k, v in self._versions.items()},
            }

    def get_migration_path(self, from_version: str, to_version: str = CURRENT_VERSION) -> list[str]:
        """Get migration steps between versions."""
        steps: list[str] = []
        with self._lock:
            from_info = self._versions.get(from_version)
            to_info = self._versions.get(to_version)
            if not from_info or not to_info:
                return ["Migration path not available"]
            steps.append(f"Upgrading from {from_version} ({from_info.status}) to {to_version} ({to_info.status})")
            if from_info.migration_guide:
                steps.append(from_info.migration_guide)
            if to_info.migration_guide:
                steps.append(to_info.migration_guide)
        return steps

    # ── Recommendations ─────────────────────────────────────────────────

    def _generate_recommendations(self, report: APIVersionReport) -> list[str]:
        """Generate recommendations based on usage data."""
        recs: list[str] = []

        if report.deprecated_requests > 0:
            pct = report.deprecated_percentage * 100
            recs.append(f"{pct:.0f}% of requests use deprecated versions — plan migration")

        # Check if any deprecated versions have active traffic
        with self._lock:
            active_deprecated = set()
            for r in self._request_log[-500:]:
                if r.deprecated:
                    active_deprecated.add(r.version)
            for ver in active_deprecated:
                info = self._versions.get(ver)
                if info and info.status == "SUNSET":
                    recs.append(f"SUNSET version {ver} still receiving traffic — clients must migrate immediately")
                elif info:
                    recs.append(f"Deprecated version {ver} still in use — set sunset date and notify clients")

        if not recs:
            recs.append("API versioning is healthy — all traffic uses current versions")

        return recs[:8]


# ── CLI ────────────────────────────────────────────────────────────────────


def _cli() -> None:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m core.api_versioning",
        description="API Versioning — Version header enforcement and management",
    )
    ap.add_argument("--report", action="store_true", help="Show API version report")
    ap.add_argument("--register", type=str, help="Register a new version (e.g., v4:BETA)")
    ap.add_argument("--deprecate", type=str, help="Deprecate a version (e.g., v2)")
    ap.add_argument("--stats", action="store_true", help="Show statistics")
    ap.add_argument("--json", action="store_true", help="Output as JSON")
    args = ap.parse_args()

    mgr = get_api_version_manager()

    if args.register:
        parts = args.register.split(":")
        version = parts[0]
        status = parts[1] if len(parts) > 1 else "STABLE"
        info = mgr.register_version(version, status=status)
        print(f"Registered: {info.version} ({info.status})")
        return

    if args.deprecate:
        ok = mgr.deprecate_version(args.deprecate)
        print(f"Deprecated {args.deprecate}: {ok}")
        return

    if args.report:
        report = mgr.get_report()
        if args.json:
            import json
            print(json.dumps(report.to_dict(), indent=2))
        else:
            print(report.summary_text())
        return

    if args.stats:
        stats = mgr.get_stats()
        if args.json:
            import json
            print(json.dumps(stats, indent=2))
        else:
            print(f"Current: {stats['current_version']}")
            print(f"Versions: {stats['registered_versions']}")
            print(f"Deprecated: {stats['deprecated_versions']}")
            print(f"Requests Tracked: {stats['requests_tracked']}")
        return

    ap.print_help()


if __name__ == "__main__":
    _cli()

# ── Singleton ──────────────────────────────────────────────────────────────

_mgr: APIVersionManager | None = None
_mgr_lock = threading.RLock()


def get_api_version_manager() -> APIVersionManager:
    """Get the singleton APIVersionManager instance."""
    global _mgr
    with _mgr_lock:
        if _mgr is None:
            _mgr = APIVersionManager()
        return _mgr


def reset_api_version_manager() -> None:
    """Force-reset singleton (for testing)."""
    global _mgr
    with _mgr_lock:
        _mgr = None


__all__ = [
    "APIRequestRecord",
    "APIVersionInfo",
    "APIVersionManager",
    "APIVersionReport",
    "get_api_version_manager",
    "reset_api_version_manager",
]
