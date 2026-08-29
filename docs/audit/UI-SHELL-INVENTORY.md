# 🏛️ OPB SUPER-PLATFORM: COMPLETE UI SHELL INVENTORY
**Audit Standard**: `OPB-UI-ARCHITECTURE-2026`  
**Classification**: Authoritative Component, Layout, and Navigation Inventory  
**Date**: August 23, 2026  
**Auditor**: Senior Principal UI Architect & Accessibility Engineer  

---

## 1. Executive Summary & Inventory Overview
The OPB Quantitative Super-Platform consists of 42 enterprise templates, 313 backend API routes, and 9 integrated high-contrast themes. This inventory indexes every layout, shell, header, navigation container, drawer, and global overlay across the entire repository.

---

## 2. Canonical Application Shell Map

```text
AppShell
│
├── Canonical Desktop Shell (>= 1024px)
│   ├── BrandBar (Identity Region: GAURAV™ SUPER-PLATFORM • Institutional Quant)
│   ├── DesktopNavigation (Primary, Markets, Execution, Intelligence, Governance, Admin)
│   └── TopUserArea (Live Telemetry Pulse, 9-Theme Selector, Emergency Kill Switch, User Profile)
│
├── Canonical Mobile Shell (< 1024px)
│   ├── MobileAppbar (Sticky 48px Header: [☰ Menu Button] • [GAURAV™ OPB Brand] • [● LIVE Status] • [🚨 KILL])
│   ├── MobileSlideDrawer (Slide-Over: Menu Header/Close ➔ User Profile ➔ Theme Selector ➔ Search Filter ➔ Navigation)
│   └── MobileBottomDock (Fixed Bottom: 🏠 Home • ⚡ Signals • 📈 P&L • 📊 Markets • ☰ Menu)
│
├── PageContentRegion (Responsive Card Grids, Data Tables, Charts, Form Groups)
│
└── GlobalOverlayLayer (Managed Modal Backdrops, Managed Toast Notifications, Zero Leaked Blurs)
```

---

## 3. Template & Consumer Audit

| Template Name | Category | Shell Consumer (`_nav.html`) | Custom Header Overrides | Tables (Wrapped) | Passwords |
| :--- | :---: | :---: | :---: | :---: | :---: |
| `_nav.html` | Partial (Canonical Shell) | Authoritative Provider | NONE | 0 (0) | 0 |
| `_pwa_head.html` | Partial | Head Metadata | NONE | 0 (0) | 0 |
| `_pwa_mobile_nav.html` | Partial | Supplemental PWA Nav | NONE | 0 (0) | 0 |
| `_pwa_sw_reg.html` | Partial | ServiceWorker Reg | NONE | 0 (0) | 0 |
| `dashboard.html` | Primary Screen | `_nav.html` | NONE (Purified) | 2 (2) | 0 |
| `margin_radar.html` | Primary Screen | `_nav.html` | NONE | 1 (1) | 0 |
| `options_chain.html` | Primary Screen | `_nav.html` | NONE | 1 (1) | 0 |
| `sector_radar.html` | Primary Screen | `_nav.html` | NONE | 1 (1) | 0 |
| `fii_dii_radar.html` | Primary Screen | `_nav.html` | NONE | 1 (1) | 0 |
| `expiry_harvester.html` | Primary Screen | `_nav.html` | NONE | 1 (1) | 0 |
| `strategy_sandbox.html` | Primary Screen | `_nav.html` | NONE | 1 (1) | 0 |
| `intelligence.html` | Primary Screen | `_nav.html` | NONE | 11 (11) | 0 |
| `ab_tester.html` | Primary Screen | `_nav.html` | NONE | 1 (1) | 0 |
| `performance.html` | Primary Screen | `_nav.html` | NONE | 2 (2) | 0 |
| `metrics_trend.html` | Primary Screen | `_nav.html` | NONE | 1 (1) | 0 |
| `whats_new.html` | Primary Screen | `_nav.html` | NONE | 0 (0) | 0 |
| `live_pnl.html` | Primary Screen | `_nav.html` | NONE | 2 (2) | 0 |
| `trade_journal.html` | Primary Screen | `_nav.html` | NONE | 1 (1) | 0 |
| `payoff_calculator.html`| Primary Screen | `_nav.html` | NONE | 1 (1) | 0 |
| `trade_copier.html` | Primary Screen | `_nav.html` | NONE | 2 (2) | 0 |
| `governance.html` | Primary Screen | `_nav.html` | NONE | 4 (4) | 0 |
| `security.html` | Primary Screen | `_nav.html` | NONE | 5 (5) | 0 |
| `capacity.html` | Primary Screen | `_nav.html` | NONE | 3 (3) | 0 |
| `data_quality.html` | Primary Screen | `_nav.html` | NONE | 4 (4) | 0 |
| `observability.html` | Primary Screen | `_nav.html` | NONE | 7 (7) | 0 |
| `system_health.html` | Primary Screen | `_nav.html` | NONE | 3 (3) | 0 |
| `event_store.html` | Primary Screen | `_nav.html` | NONE | 1 (1) | 0 |
| `admin_config.html` | Primary Screen | `_nav.html` | NONE | 0 (0) | 0 |
| `admin_signals.html` | Primary Screen | `_nav.html` | NONE | 2 (2) | 0 |
| `admin_users.html` | Primary Screen | `_nav.html` | NONE | 2 (2) | 2 |
| `admin_portfolio_analyzer.html`| Primary Screen | `_nav.html` | NONE | 2 (2) | 1 |
| `kill_switch.html` | Primary Screen | `_nav.html` | NONE | 1 (1) | 0 |
| `profile.html` | Primary Screen | `_nav.html` | NONE | 0 (0) | 3 |
| `pricing_plans.html` | Primary Screen | `_nav.html` | NONE | 0 (0) | 0 |
| `user_signals.html` | Primary Screen | `_nav.html` | NONE | 1 (1) | 0 |
| `login.html` | Auth Screen | Standalone Auth Shell | NONE | 0 (0) | 1 |
| `register.html` | Auth Screen | Standalone Auth Shell | NONE | 0 (0) | 2 |
| `forgot_password.html` | Auth Screen | Standalone Auth Shell | NONE | 0 (0) | 3 |
| `reset_password.html` | Auth Screen | Standalone Auth Shell | NONE | 0 (0) | 2 |
| `change_password.html` | Auth Screen | `_nav.html` | NONE | 0 (0) | 3 |
| `error.html` | Error Screen | Standalone Fallback Shell | NONE | 0 (0) | 0 |
| `offline.html` | Error Screen | Standalone Fallback Shell | NONE | 0 (0) | 0 |

---

## 4. Header Control Priority Classification (Mobile Contract)

| Priority | Control Name | Target Presentation | Rationale |
| :---: | :--- | :---: | :--- |
| **P0** | **Mobile Hamburger Menu** (`[☰]`) | Mobile Header (Left) | Primary gateway to full platform navigation. |
| **P0** | **Brand Identity** (`GAURAV™ OPB`) | Mobile Header (Center-Left) | Dedicated branding region (Branding Invariant). |
| **P0** | **Live Status & Pulse** (`[● LIVE]`) | Mobile Header (Right) | Essential runtime execution feedback. |
| **P0** | **Emergency Kill Switch** (`[🚨 KILL]`) | Mobile Header (Right) | Instant risk mitigation trigger. |
| **P1** | **Fast Route Tabs** (5 items) | Mobile Bottom Dock | 1-tap thumb navigation for top tasks. |
| **P2** | **User Profile & Role** | Slide-Over Drawer Top | Account identity with zero label wrapping. |
| **P2** | **9-Theme Selector & Pills** | Slide-Over Drawer Top | Theme customization without crowding header. |
| **P3** | **Deep Navigation Tree** | Slide-Over Drawer Body | Complete categorization with search filter. |
| **P3** | **Sign Out Button** | Slide-Over Drawer Bottom | Safe logout termination. |
