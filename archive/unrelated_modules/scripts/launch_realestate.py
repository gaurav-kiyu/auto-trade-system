#!/usr/bin/env python3
"""Real Estate Platform — One-Click Launcher

Starts the complete real estate platform with a single command:
  - FastAPI/uvicorn server on port 8765
  - Seeds 35 realistic Indian property listings
  - Starts background scheduler worker (optional)
  - Prints health status and key URLs

Usage:
    python scripts/launch_realestate.py                    # Start with defaults
    python scripts/launch_realestate.py --port 8080        # Custom port
    python scripts/launch_realestate.py --no-seed          # Skip data seeding
    python scripts/launch_realestate.py --no-scheduler     # Skip scheduler worker
    python scripts/launch_realestate.py --verify           # Verify setup only, don't start
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
_log = logging.getLogger("launcher")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DEFAULT_PORT = 8765
APP_NAME = "realestate-api"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Real Estate Platform — One-Click Launcher",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/launch_realestate.py
  python scripts/launch_realestate.py --port 8080 --no-seed
  python scripts/launch_realestate.py --verify
        """,
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Server port (default: {DEFAULT_PORT})")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Server host (default: 127.0.0.1; use 0.0.0.0 only to expose on the network)")
    parser.add_argument("--no-seed", action="store_true", help="Skip seeding sample property data")
    parser.add_argument("--no-scheduler", action="store_true", help="Skip starting background scheduler worker")
    parser.add_argument("--verify", action="store_true", help="Verify setup only — don't start server")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    parser.add_argument("--log-level", type=str, default="info", choices=["debug", "info", "warning", "error"],
                        help="Logging level (default: info)")
    return parser.parse_args()


def verify_setup() -> dict[str, bool]:
    """Verify the platform can start by checking imports and service availability."""
    _log.info("═══ Real Estate Platform — Setup Verification ═══")
    checks: dict[str, bool] = {}
    import importlib

    # Module imports
    modules = [
        ("fastapi", "FastAPI web framework"),
        ("uvicorn", "ASGI server"),
        ("realestate.startup", "Real estate startup module"),
        ("realestate.seed_data", "Seed data module"),
        ("realestate.application.services", "Application services"),
    ]
    for module_name, description in modules:
        try:
            importlib.import_module(module_name)
            checks[module_name] = True
            _log.info("  ✅ %s — %s", module_name, description)
        except ImportError as exc:
            checks[module_name] = False
            _log.warning("  ❌ %s — %s (%s)", module_name, description, exc)

    # Optional modules
    try:
        importlib.import_module("realestate.scheduler")
        checks["scheduler"] = True
        _log.info("  ✅ realestate.scheduler — Background task worker")
    except ImportError:
        checks["scheduler"] = False
        _log.warning("  ⚠️  realestate.scheduler — Not available (optional)")

    try:
        importlib.import_module("realestate.fraud_detection")
        checks["fraud"] = True
        _log.info("  ✅ realestate.fraud_detection — Anti-fraud engine")
    except ImportError:
        checks["fraud"] = False
        _log.warning("  ⚠️  realestate.fraud_detection — Not available (optional)")

    try:
        importlib.import_module("realestate.prometheus_monitoring")
        checks["monitoring"] = True
        _log.info("  ✅ realestate.prometheus_monitoring — Prometheus metrics")
    except ImportError:
        checks["monitoring"] = False
        _log.warning("  ⚠️  realestate.prometheus_monitoring — Not available (optional)")

    try:
        importlib.import_module("realestate.seo")
        checks["seo"] = True
        _log.info("  ✅ realestate.seo — SEO/Sitemap module")
    except ImportError:
        checks["seo"] = False
        _log.warning("  ⚠️  realestate.seo — Not available (optional)")

    _log.info("═══ Verification complete: %d/%d checks passed ═══",
              sum(1 for v in checks.values() if v), len(checks))
    return checks


def seed_data() -> int:
    """Seed the platform with realistic Indian property listings."""
    from realestate.application.services import create_default_services
    from realestate.seed_data import seed_properties

    services = create_default_services()
    property_service = services.get("property_service")

    if not property_service:
        _log.warning("  ⚠️  Property service not available — skipping seed")
        return 0

    # Check if already seeded
    existing = property_service.list_all()
    if existing and len(existing) >= 10:
        _log.info("  ⏭️  Already seeded (%d properties exist) — skipping", len(existing))
        return len(existing)

    count = seed_properties(property_service)
    if count > 0:
        _log.info("  ✅ Seeded %d realistic Indian property listings", count)
    else:
        _log.warning("  ⚠️  No properties were seeded")

    return count


def print_banner(port: int, seeded: int, scheduler_active: bool) -> None:
    """Print a nice startup banner."""
    host_url = f"http://localhost:{port}"
    banner = f"""
╔══════════════════════════════════════════════════════════════╗
║           🏠  Real Estate India Platform  🏠                ║
╠══════════════════════════════════════════════════════════════╣
║  API Server:       {host_url:<41s}║
║  Home Page:        {host_url}/realestate              ║
║  Search:           {host_url}/realestate/search        ║
║  Property API:     {host_url}/api/realestate/properties  ║
║  Health Check:     {host_url}/api/realestate/health    ║
║  Prometheus:       {host_url}/metrics                  ║
║  Sitemap:          {host_url}/sitemap.xml               ║
║  API Docs:         {host_url}/docs                      ║
╠══════════════════════════════════════════════════════════════╣
║  Properties:       {seeded:<5d} listings                         ║
║  Scheduler:        {'✅ Active' if scheduler_active else '⏹️  Disabled':<38s}║
║  Dashboard URL:    {host_url}/realestate              ║
╚══════════════════════════════════════════════════════════════╝
"""
    print(banner)


def create_app() -> object:
    """Create the FastAPI application with all modules wired."""
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from realestate.startup import startup_realestate_system

    app = FastAPI(
        title="Real Estate India Platform",
        description="Indian real estate marketplace — property search, legal support, AI chatbot, fraud detection",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Wire all modules
    results = startup_realestate_system(app=app)
    active_modules = sum(
        1 for v in results.values()
        if isinstance(v, dict) and v.get("status") == "ok"
    )
    _log.info("Wired %d modules into FastAPI app", active_modules)

    return app


def main() -> int:
    """Main launcher entry point."""
    args = parse_args()

    # ── Verify setup ────────────────────────────────────────────────────
    _log.info("═══ Real Estate Platform Launcher ═══")
    _log.info("Python: %s", sys.version.split()[0])
    _log.info("Root:   %s", ROOT)
    _log.info("Port:   %d", args.port)

    checks = verify_setup()

    if args.verify:
        _log.info("Verify-only mode — exiting")
        all_ok = all(checks.values())
        return 0 if all_ok else 1

    # Check critical imports
    if not checks.get("fastapi") or not checks.get("uvicorn"):
        _log.error("Critical dependencies missing! Install with: pip install fastapi uvicorn")
        return 1

    # ── Seed data ───────────────────────────────────────────────────────
    seeded = 0
    if not args.no_seed:
        _log.info("═══ Seeding Property Data ═══")
        seeded = seed_data()

    # ── Start scheduler (in background thread) ──────────────────────────
    scheduler_active = False
    if not args.no_scheduler:
        try:
            from realestate.application.services import create_default_services
            from realestate.scheduler import initialize_scheduler

            services = create_default_services()
            scheduler = initialize_scheduler(services=services)

            import threading
            scheduler_thread = threading.Thread(
                target=scheduler.run_forever,
                args=(30,),
                daemon=True,
                name="scheduler-worker",
            )
            scheduler_thread.start()
            scheduler_active = True
            _log.info("═══ Scheduler worker started (check interval: 30s) ═══")
        except Exception as exc:
            _log.warning("Scheduler not available: %s", exc)

    # ── Print banner ───────────────────────────────────────────────────
    print_banner(args.port, seeded, scheduler_active)

    # ── Start server ────────────────────────────────────────────────────
    _log.info("═══ Starting FastAPI server on %s:%d ═══", args.host, args.port)
    import uvicorn
    app = create_app()
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level=args.log_level,
        reload=args.reload,
        access_log=True,
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
