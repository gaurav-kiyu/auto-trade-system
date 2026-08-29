# 🏛️ OPB SUPER-PLATFORM: SYSTEM ARCHITECTURE & COMPONENT MAP

**Classification**: Architecture Specification & Regression Control  
**Auditor**: Principal Software Architect & QA Director  
**Governance Standard**: `OPB-REGRESSION-GOVERNANCE-001`  

---

## 1. Global Architectural Hierarchy

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        CANONICAL APPLICATION SHELL                     │
│                        (templates/enterprise/_nav.html)                │
├───────────────────────────────────┬────────────────────────────────────┤
│           DESKTOP SHELL           │            MOBILE SHELL            │
│  ┌─────────────────────────────┐  │  ┌──────────────────────────────┐  │
│  │   Dedicated Brand Header    │  │  │    Dedicated Brand Header    │  │
│  │      "GAURAV™ | OPB"        │  │  │      "GAURAV™ | COCKPIT"     │  │
│  ├─────────────────────────────┤  │  ├──────────────────────────────┤  │
│  │   Primary Navigation Bar    │  │  │   Status & Quick Actions     │  │
│  │   (Command, Markets, Lab)   │  │  │   (Latency, Mode, Hamburger) │  │
│  ├─────────────────────────────┤  │  ├──────────────────────────────┤  │
│  │   Global Control Cluster    │  │  │   Slide-Over Nav Drawer      │  │
│  │   (Theme, Profile, Kill)    │  │  │   (All Categories + Search)  │  │
│  └─────────────────────────────┘  │  ├──────────────────────────────┤  │
│                                   │  │   Bottom 5-Destination Dock  │  │
│                                   │  └──────────────────────────────┘  │
└───────────────────────────────────┴────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│                          SHARED DESIGN TOKENS                          │
│                      (static/opb_design_system.css)                    │
│    Surfaces │ Typography │ Spacing │ Interactive States │ Breakpoints  │
├────────────────────────────────────────────────────────────────────────┤
│                       SHARED ATOMIC COMPONENTS                         │
│  • .opb-card                • .opb-table-container  • .opb-tab-group   │
│  • .opb-stat-card           • .opb-password-wrapper • .opb-badge       │
│  • .opb-btn (Primary/Ghost) • .opb-status-pill      • .opb-modal       │
└────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│                      DYNAMIC MULTI-THEME ENGINE                        │
│                        (static/theme_engine.js)                        │
│   9 Verified Themes │ LocalStorage Persistence │ Zero FOUC Injection   │
└────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│                       ENTERPRISE SCREEN LAYER                          │
│                          (42 Jinja2 Templates)                         │
│   Command Center │ Markets & Options │ Intelligence │ Administration   │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Core Architectural Invariants

### 1. BRANDING_INVARIANT
- **Identity Region**: GAURAV™ branding exists exclusively as the top-level identity anchor.
- **Strict Separation**: Branding is never rendered as a child of navigation lists, drawer menus, or page content cards.
- **Immutable Position**: Mobile shell places branding at `Row 1 (Top Appbar)`, Desktop shell places branding at `Top-Left Anchor`.

### 2. MOBILE_SHELL_CONTRACT
- Every authenticated screen inherits the canonical `_nav.html` mobile appbar and bottom dock.
- Zero screen-specific header overrides (`.dashboard-mobile-header` or `.custom-header` are prohibited).

### 3. TABLE_ANTI_SQUEEZE_INVARIANT
- Every data table inherits `.opb-table-container` with `overflow-x: auto;` and `white-space: nowrap;` on all table cells.
- Zero vertical letter stacking is permitted under any viewport (320px to 2560px).

### 4. FORM_RESPONSIVE_INVARIANT
- All form inputs, password wrappers, and action buttons collapse into a full-width vertical stack on mobile viewports (< 768px).
- Labels and inputs must never squeeze horizontally side-by-side on mobile devices.
