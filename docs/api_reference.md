# API Reference — Pointer

This file previously did not exist despite being referenced from `CLAUDE.md`
as "all 30+ dashboard endpoints" — the real count is in the hundreds and
spread across many route modules, growing with every feature. Rather than
hand-duplicate an endpoint list here that would go stale the moment a route
is added or renamed, this points at the actual sources of truth.

## Live, always-current reference

The dashboard is a FastAPI app (`core/enterprise_dashboard/main.py`) — FastAPI
auto-generates an interactive OpenAPI reference at **`/docs`** (Swagger UI)
and **`/redoc`** on the running instance (default `http://localhost:8765`,
opt-in via `web_dashboard_enabled: true` in `json/config.json`). That is the
authoritative, always-in-sync endpoint list — check it there, not here.

## Route module map (where to read the source)

`core/enterprise_dashboard/routes/`:

| Module | Covers |
|---|---|
| `pages.py` | HTML page routes (`/`, `/login`, `/register`, `/admin/*` pages, feature pages) |
| `admin.py` | `/api/config/*`, `/api/system/kill|resume|pause`, `/api/changes/*`, `/api/v1/admin/*` (broker/portfolio/hedging/tax-loss/report-gen) |
| `system.py` | `/api/system/state`, `/trades`, `/health`, `/signals`, `/performance`, `/oi`, `/invariants`, `/events`, `/notifications` |
| `risk.py` | Risk-service read endpoints |
| `monitoring.py` | `/api/system/notifications/*`, `/api/broker/info`, `/api/ml/status` |
| `governance.py` | `/api/governance/*` |
| `capacity.py` | `/api/capacity/*` |
| `fundamentals.py` | `/api/fundamentals/*` |
| `metrics_trend.py` | `/api/metrics/trend*` |
| `payoff_calculator.py` | `POST /api/payoff-calculator/compute` — multi-leg option payoff-curve calculator (read-only) |
| `whats_new.py` | Backs the `/whats-new` page in `pages.py` — parses `CHANGELOG.md`'s newest entry, no API route of its own |
| `webhooks.py` | Inbound webhook receivers (see `docs/adr/` for the webhook signal receiver ADR if present) |
| `intelligence.py` + `_analysis`/`_bi`/`_incidents`/`_pipeline` variants | `/api/intelligence/*` — the largest surface (SBOM, chaos testing, root-cause, knowledge graph, BI reports, incidents, etc.) |
| `provisioning.py` | Provisioning-related endpoints |

Auth for all of the above goes through `core/auth/routes.py`
(`create_auth_router`) — `/login`, `/register`, `/logout`, `/session`,
`/change-password`, plus admin-only user management under
`/users/*` (role-gated via `AuthDependencies.require_role("admin")`).

## Rate limits / auth model

See `SECURITY.md` for the authoritative statement of the auth and
rate-limiting model — do not restate specific numbers here where they can
silently drift out of sync with the real policy.
