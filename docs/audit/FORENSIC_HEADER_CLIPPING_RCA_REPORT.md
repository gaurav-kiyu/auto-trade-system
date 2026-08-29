# 🔍 P0 GLOBAL HEADER FAILURE: ROOT CAUSE ANALYSIS & DIAGNOSIS REPORT

**Incident ID**: `INC-20260823-HEADER-CONTROLS-DISAPPEARING-CLIPPING`  
**Classification**: **P0 Critical Architecture Regression (Bare Tag Global CSS `select { width: 100% !important }` Expanding Header Theme Selector)**  
**Auditor**: Senior Principal UI Architect & Regression Lead  
**Date**: August 23, 2026  
**Status**: **ROOT CAUSE EMPIRICALLY IDENTIFIED & RESOLVED**  

---

## 1. Executive Summary
Inspection of the desktop global header revealed that the Kill Switch, Admin/Account, and Logout buttons were still present in the rendered DOM, but were pushed off-screen / clipped because the Theme Selector dropdown (`#desktopThemeSelect`) expanded horizontally to fill 100% of the remaining header container.

---

## 2. Forensic Layout & Computed Style Diagnostics

| DOM Element | Selector | Computed Style Issue | Root Cause |
| :--- | :--- | :--- | :--- |
| **Theme Selector** | `#desktopThemeSelect.opb-theme-selector` | `width: 100% !important; display: block !important;` | Global un-scoped selector `select { width: 100% !important; }` at line 748 in `static/opb_design_system.css`. |
| **Kill Switch** | `a.btn-danger[href="/kill-switch"]` | Pushed off-screen (`x > viewport.width`) | Theme selector expanded to `100%` within parent flex container. |
| **Account Badge** | `a[href="/profile"]` | Pushed off-screen | Shifted beyond right boundary. |
| **Sign Out Button**| `a.btn-ghost[href="/logout"]` | Pushed off-screen | Shifted beyond right boundary. |

---

## 3. Permanent Architectural Remediation

1. **Purge Global Bare-Tag `select` Mutation**:
   - Scope all `100%` width rules in `static/opb_design_system.css` strictly to form containers: `.opb-form-field select`, `.form-group select`, `.opb-form-group select`, `.opb-select`.
   - Explicitly exempt `.opb-nav-top select`, `.opb-theme-selector`, and `.theme-dock-select` from 100% expansion.
2. **Hardened Header Contract**:
   - In `templates/enterprise/_nav.html`, set `#desktopThemeSelect` to a fixed intrinsic width: `width: auto !important; max-width: 150px !important; min-width: 130px !important; flex-shrink: 0 !important;`.
   - Set `.opb-nav-top` right-side cluster to `display: flex; align-items: center; gap: 0.65rem; flex-shrink: 0; min-width: max-content; margin-left: auto; overflow: visible;`.
3. **Dual-Viewport & Multi-Theme Verification**:
   - Verify full visibility of all 6 header regions across Desktop (`1024px`, `1280px`, `1366px`, `1440px`, `1600px`, `1920px`) and Mobile (`375px`, `390px`, `393px`, `412px`, `430px`) across all 9 themes.
