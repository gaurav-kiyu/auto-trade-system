# OPB Institutional FinTech Design System (v5.0)

Welcome to the **OPB Institutional FinTech Design System**. This architecture serves as the single source of truth for all visual presentation, typography, theme fidelity, component abstractions, and data visualization across the 42 templates in the OPB Auto-Trade platform.

---

## Core Principles
1. **Financial Clarity First**: Quantitative metrics, strikes, premiums, and P&L figures are primary data points that must render with tabular monospaced alignment.
2. **4-Tier Surface Hierarchy**: Clean separation between canvas (`--bg-primary`), section wells (`--bg-secondary`), elevated cards (`--bg-card`), and form controls (`--input-bg`).
3. **High-Contrast Borders**: Crisp, intentional borders (`--border-color`) that provide clear component containment across OLED dark and Scandinavian daylight themes.
4. **Universal Word-Wrapping**: Zero horizontal text breaches across narrow viewports and technical identifiers (`overflow-wrap: anywhere; word-break: break-word`).
5. **Zero CSS Patch Culture**: All UI updates must inherit universally from design tokens rather than page-level ad-hoc overrides.
