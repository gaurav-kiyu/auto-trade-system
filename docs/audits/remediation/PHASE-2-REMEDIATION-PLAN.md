# 🏛️ OPB SUPER-PLATFORM: PHASE 2 REMEDIATION PLAN

**Plan Standard**: `FINAL-PHASE NO-REGRESSION LAW`  
**Classification**: Canonical Application Shell Remediation & Viewport Invariant Hardening  
**Auditor Lead**: Senior Principal UI Architect & Regression Lead  
**Date**: August 23, 2026  
**Status**: 🟢 **PHASE 2 REMEDIATION PLAN RATIFIED**  

---

## 1. SCOPE OF REMEDIATION
We are correcting and hardening ONLY the canonical global shell architecture:
1. **Desktop BrandBar**: Independent branding region (`GAURAV™ SUPER-PLATFORM • QUANTITATIVE COCKPIT`), never competing or sharing row flow with navigation links.
2. **Desktop TopUserArea**: Independent right-side cluster (`[12ms Live] [Theme Selector] [🚨 KILL SWITCH] [👤 admin] [Sign Out]`) with strict intrinsic bounding boxes and `flex-shrink: 0 !important; white-space: nowrap !important;`.
3. **Desktop PrimaryNavigation**: Clear visual row below the BrandBar containing primary workspace links and pure CSS `:hover` dropdown groups (`Markets & Radar ▾`, `Execution & PnL ▾`, `System ▾`).
4. **MobileAppBar**: Controlled 50px header geometry (`[☰ Menu Button] [GAURAV™ COCKPIT] [● LIVE Status] [🚨 KILL]`) with zero character wrapping and zero content overlap.
5. **MobileDrawer**: Pure off-canvas overlay (`position: fixed; top: 0; left: 0; bottom: 0; z-index: 10000;`), internal scrolling (`overflow-y: auto`), with absolute zero participation in desktop document flow (`@media (min-width: 1024px) { display: none !important; }`).
6. **MobileBottomDock**: Fixed 5-tab dock (`🏠 Home`, `⚡ Signals`, `📈 P&L`, `📊 Markets`, `☰ Menu`) with safe-area insets (`env(safe-area-inset-bottom)`).
7. **Responsive Breakpoints**: Continuous testing across 11 viewports (`375px`, `390px`, `393px`, `412px`, `430px`, `768px`, `820px`, `1024px`, `1280px`, `1366px`, `1440px`, `1600px`, `1920px`).

---

## 2. AFFECTED FILES & BLAST RADIUS
- **Target File**: `templates/enterprise/_nav.html`
- **Design Tokens**: `static/opb_design_system.css`
- **Blast Radius**: `GLOBAL (All 35 Enterprise templates consuming _nav.html)`
- **Consumers**: Desktop Header, Desktop Navigation, Mobile Appbar, Mobile Slide-Drawer, Mobile Bottom Dock across all 9 themes.

---

## 3. NON-TARGETED PROTECTED AREAS
- ❌ Zero mutations to backend, trading engine, broker adapters, or database.
- ❌ Zero modifications to theme engine colors or font family definitions.
- ❌ Zero modifications to business logic cards or data tables.
