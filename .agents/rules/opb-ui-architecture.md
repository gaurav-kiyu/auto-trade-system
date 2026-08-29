# OPB UI Architecture & Golden Rules

## The OPB UI Golden Rule
> **Never implement a visual change as an isolated page-level solution when the change represents a reusable design concept.**

### Five-Step Component Lifecycle
Before creating new CSS, component styling, colors, spacing, shadows, radii, typography, or animations:
1. **Check Existing Design Tokens**: Inspect `static/opb_design_system.css` and `static/theme_engine.js`.
2. **Check Existing Components**: Reuse `.opb-card`, `.opb-stat-card`, `.opb-table`, `.opb-tab`, `.opb-badge`, `.opb-quick-tile`, `.opb-telemetry-dock`.
3. **Check Theme Architecture**: Ensure semantic tokens are consumed universally across all 9 integrated themes.
4. **Extend the Design System**: If a new abstraction is truly needed, add it to `static/opb_design_system.css` using dynamic CSS variables.
5. **Reuse Universally**: Apply the resulting abstraction across all 41 templates instead of writing inline style overrides.

---

## Strict Constraints
- **Zero Hardcoded Colors**: Never hardcode theme-specific hex values (e.g. `#1e293b`, `#ffffff`, `#3b82f6`) inside business templates or components. Always use `var(--opb-surface-card)`, `var(--market-buy)`, `var(--text-primary)`, etc.
- **No Duplicate Components for Themes**: Never create theme-specific duplicates of components (e.g., `card-dark.css`, `card-light.css`). The component markup must remain identical; only tokens vary.
- **Zero Mutation of Backend Logic**: Never modify trading, risk, execution, broker, or portfolio logic while performing a UI-only task.
- **Mandatory Verification**: Every UI change must be verified across ALL 9 themes.
