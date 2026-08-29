# ⚙️ PHASE 14 — URL CONFIGURATION & RESOLVER AUDIT REPORT

**Execution Date**: 2026-08-24  
**Audit Standard**: Centralized Configuration Governance (OPB-URL-GOVERNANCE-2026)  
**Status**: **COMPLETED & VERIFIED**

---

## 1. Centralized Configuration Architecture

To eliminate decentralized, hardcoded domain references across the codebase, a unified configuration and resolution architecture has been established.

### Resolution Hierarchy:
1. **Environment Variables**:
   - `PUBLIC_BASE_URL`
   - `APP_BASE_URL`
   - `EXTERNAL_BASE_URL`
   - `OPBUYING_PUBLIC_BASE_URL`
2. **Caller Configuration Dictionary**:
   - `cfg.get("PUBLIC_BASE_URL")`
   - `cfg.get("APP_BASE_URL")`
3. **Global Repository Configuration**:
   - `json/config.json` -> `"PUBLIC_BASE_URL": "https://gaurav-cockpit.servegame.com"`
4. **Environment Heuristic Fallback**:
   - Production / Server Runtime (`OPB_ENV=production` or AWS EC2 deployment) -> `https://gaurav-cockpit.servegame.com`
   - Development Runtime -> `http://localhost:8000`

---

## 2. Resolver API Specification (`core.notifications.url_resolver`)

| Function | Signature | Purpose | Example Return Value |
| :--- | :--- | :--- | :--- |
| `get_public_base_url` | `(cfg=None) -> str` | Resolves canonical base URL | `"https://gaurav-cockpit.servegame.com"` |
| `build_action_url` | `(path, params=None, cfg=None, base_url=None) -> str` | Constructs deep action links | `"https://gaurav-cockpit.servegame.com/my-signals"` |
| `build_chart_url` | `(symbol) -> str` | Builds TradingView chart links | `"https://in.tradingview.com/chart/?symbol=NSE:NIFTY"` |
| `is_production_environment`| `(cfg=None) -> bool` | Heuristic environment detection | `True` |

---

## 3. Configuration Hardening in `json/config.json`

The key `"PUBLIC_BASE_URL"` is permanently injected at the root of `json/config.json`:
```json
{
    "PUBLIC_BASE_URL": "https://gaurav-cockpit.servegame.com",
    "ADAPTIVE_HISTORY_LOOKBACK": 40,
    ...
}
```

This ensures that all platform services, background scanners, and API handlers reference the exact same canonical public URL without template-level divergence.
