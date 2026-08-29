# 🌐 PHASE 14 — EXTERNAL URL & ACTION-LINK INVENTORY REPORT

**Execution Timestamp**: 2026-08-24T09:42:00 IST  
**Audit Scope**: Complete Repository (`core/`, `infrastructure/`, `templates/`, `static/`, `json/`, `tests/`)  
**Canonical Production URL**: `https://gaurav-cockpit.servegame.com`  
**Status**: **REMEDIATED & VERIFIED**

---

## 1. Executive Summary

A comprehensive forensic repository scan was executed to uncover all generated external URLs, notification endpoints, action-link handlers, and loopback/localhost bindings.

Prior to remediation, a critical production defect was identified in `core/notifications/rich_signal_formatter.py` where outgoing email HTML and notification action links were hardcoded to `http://localhost:8000/my-signals`.

All external URL generation paths have now been refactored to use the centralized **Canonical URL Resolver** (`core.notifications.url_resolver`), guaranteeing that production notifications point strictly to `https://gaurav-cockpit.servegame.com` while maintaining environment-aware development fallbacks.

---

## 2. Complete Discovered URL & Binding Classification

| Discovered Pattern / URL | Source File & Location | Category | Pre-Audit Status | Post-Remediation Status |
| :--- | :--- | :--- | :--- | :--- |
| `http://localhost:8000/my-signals` | `core/notifications/rich_signal_formatter.py:203` | Notification Link | 🚨 **CRITICAL DEFECT** | 🟢 **RESOLVED** (`build_action_url("/my-signals")`) |
| `callback_data: "dash:{symbol}"` | `core/all_nse_scanner.py:617` | TG Action Button | ⚠️ **BROKEN ACTION** | 🟢 **RESOLVED** (`url: "{base_url}/my-signals"`) |
| `callback_data: "dash:{symbol}"` | `core/enterprise_dashboard/routes/admin.py:143` | TG Action Button | ⚠️ **BROKEN ACTION** | 🟢 **RESOLVED** (`url: "{base_url}/my-signals"`) |
| `callback_data: "exec:{symbol}"` | `core/telegram/callback_handler.py:27` | Broker Action | ℹ️ Informational Only | 🟢 **ENHANCED** (Safe web redirect to `{base_url}/my-signals`) |
| `https://in.tradingview.com/chart/?symbol=NSE:...` | `core/notifications/rich_signal_formatter.py:202` | External Chart | 🟢 Valid External | 🟢 **VERIFIED** (`build_chart_url`) |
| `https://in.tradingview.com/chart/?symbol=NSE:...` | `core/all_nse_scanner.py:616` | External Chart | 🟢 Valid External | 🟢 **VERIFIED** |
| `https://in.tradingview.com/chart/?symbol=NSE:...` | `core/enterprise_dashboard/routes/admin.py:142` | External Chart | 🟢 Valid External | 🟢 **VERIFIED** |
| `https://api.telegram.org/bot.../sendMessage` | `core/all_nse_scanner.py:630` | API Webhook | 🟢 Valid External API | 🟢 **VERIFIED** |
| `https://api.telegram.org/bot.../sendMessage` | `core/enterprise_dashboard/routes/admin.py:130` | API Webhook | 🟢 Valid External API | 🟢 **VERIFIED** |
| `https://api.telegram.org/bot.../getUpdates` | `core/telegram_commander.py:462` | API Polling | 🟢 Valid External API | 🟢 **VERIFIED** |
| `https://archives.nseindia.com/.../EQUITY_L.csv` | `core/all_nse_scanner.py:41` | Data Ingestion | 🟢 Valid External API | 🟢 **VERIFIED** |
| `host = "0.0.0.0" / "127.0.0.1"` | `core/enterprise_dashboard/main.py:1330` | Server Bind | 🟢 Valid Internal Bind | 🟢 **VERIFIED** (Internal socket only) |
| `http://127.0.0.1:8000/...` | `scratch/mobile_audit_data.json` | Test Scratch File | 🟢 Internal Artifact | 🟢 **VERIFIED** (Local headless test logs) |

---

## 3. Environment Separation Architecture

The platform enforces strict separation between environments:

1. **Development (`dev`)**:
   - `PUBLIC_BASE_URL`: `http://localhost:8000` (or `http://127.0.0.1:8000`)
   - Binds to local loopback interface for isolated operator development.
2. **Testing / Staging (`test`)**:
   - Dynamic override via `os.environ["PUBLIC_BASE_URL"]` or test harness fixtures.
3. **Production (`production` / `live`)**:
   - Canonical Domain: `https://gaurav-cockpit.servegame.com`
   - Zero hardcoded local IPs, loopback ports, or internal AWS VPC hostnames in any outgoing payload.

---

## 4. Verification Evidence

- Unit Test Suite: `tests/test_phase14_url_and_notification_audit.py` -> **8/8 Passed (100%)**.
- Rich HTML Email Audit: Zero occurrences of `localhost`, `127.0.0.1`, or `:8000`.
- All Telegram inline action buttons point to valid HTTPS production endpoints.
