# OPB 2026 MODERN TYPOGRAPHY + THEME DESIGN SYSTEM UPGRADE

**Rule ID:** OPB-2026-DESIGN-SYSTEM-001
**Applies To:** Entire OPB Auto-Trade System UI & Design Architecture
**Lifecycle:** Mandatory for all typography, theme, and component visual upgrades
**Authority:** Highest-level UI/UX & Design System engineering constitution
**Status:** ACTIVE

---

# 1. FIRST RULE — AUDIT BEFORE IMPLEMENTATION

DO NOT MODIFY ANY FILE DURING THIS PHASE.

First inspect the complete existing UI architecture.

Analyze:
* existing CSS
* theme system
* design tokens
* typography
* components
* dashboard
* navigation
* cards
* tables
* charts
* strategy pages
* options pages
* portfolio pages
* risk pages
* forms
* dialogs
* alerts
* badges
* tooltips
* responsive behavior
* accessibility
* PWA/mobile behavior
* browser-specific behavior

Inspect ALL existing themes.
The application already contains multiple themes.
Do NOT remove them.
Do NOT replace them.
The objective is to evolve them into a centralized 2026 design system.

---

# 2. PRIMARY DESIGN OBJECTIVE

Transform the visual system from:
"Enterprise dashboard with multiple skins"
into:
"Unified institutional-grade FinTech / quantitative trading design system with multiple visual personalities."

The architecture MUST be:

```text
Design System
      ↓
Semantic Tokens
      ↓
Theme Tokens
      ↓
Shared Components
      ↓
Pages / Modules
```

NOT:

```text
Theme
   ↓
Page-specific CSS
```

No page may invent its own independent color system.
No component may contain unnecessary hardcoded theme colors.

---

# 3. TYPOGRAPHY SYSTEM

Evaluate the current typography and migrate toward a modern variable-font architecture.

Preferred typography candidates:
- **PRIMARY UI**: Inter Variable
- **SECONDARY / PREMIUM DISPLAY**: Manrope Variable / Plus Jakarta Sans
- **TECHNICAL / FORMULA / CODE**: JetBrains Mono

Preferred final architecture:
```css
--font-ui: 'Inter', system-ui, -apple-system, sans-serif;
--font-display: 'Plus Jakarta Sans', 'Inter', sans-serif;
--font-data: 'Inter', system-ui, sans-serif;
--font-mono: 'JetBrains Mono', 'SF Mono', monospace;
```

---

# 4. FINANCIAL TYPOGRAPHY

This is a trading application. Financial numbers MUST receive special treatment:
```css
font-variant-numeric: tabular-nums;
font-feature-settings: "tnum" 1, "zero" 1;
```

Apply tabular numerals to:
* prices, quantities, P&L, percentage values
* capital, portfolio values, option strikes, premiums, Greeks, risk metrics
* timestamps, tables, ledgers, trade history

---

# 5. TYPOGRAPHY SCALE

Centralize typography tokens:
`display-xl`, `display-lg`, `display-md`, `heading-xl`, `heading-lg`, `heading-md`, `heading-sm`, `body-lg`, `body-md`, `body-sm`, `body-xs`, `label-md`, `label-sm`, `caption`, `data-xl`, `data-lg`, `data-md`, `data-sm`, `formula`, `technical`.

---

# 6. 2026 VISUAL LANGUAGE

FinTech trading priority:
```text
TRUST → READABILITY → INFORMATION HIERARCHY → DATA DENSITY → PERFORMANCE → CONSISTENCY → AESTHETICS
```
Avoid visual gimmicks that damage readability or contrast. Glassmorphism MUST NOT be used behind critical financial numbers.

---

# 7. MODERN THEME ARCHITECTURE

Required semantic token categories:
`background`, `surface`, `surface-elevated`, `surface-hover`, `text-primary`, `text-secondary`, `text-muted`, `text-disabled`, `border`, `divider`, `accent`, `accent-hover`, `accent-active`, `success`, `warning`, `danger`, `info`, `profit`, `loss`, `neutral`, `chart-primary`, `chart-secondary`, `chart-grid`, `chart-axis`, `chart-tooltip`, `risk-safe`, `risk-warning`, `risk-danger`, `buy`, `sell`, `long`, `short`, `focus`, `selection`, `overlay`.

---

# 8. STRATEGY SANDBOX SPECIFICALLY

Visual hierarchy:
```text
STRATEGY IDENTITY → STRATEGY PURPOSE → FORMULA → SIGNAL CONDITIONS → TIMEFRAME → CONFIDENCE / HISTORICAL PERFORMANCE
```
Formulas MUST use `--font-mono` with crisp syntax highlighting and tabular metrics.

---

# 9. WORKFLOW MANDATE

```text
FIRST: Audit
SECOND: Produce Design-System Proposal
THIRD: Wait for approval
ONLY THEN: Implement
```
