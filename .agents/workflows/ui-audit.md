# Workflow — Institutional UI Audit

## Purpose
Execute a comprehensive UX/UI audit across all 41 templates before and after any visual enhancements.

## Audit Checklist
1. **Semantic Color Audit**: Scan templates for rogue hardcoded `#hex` or `rgb()` values. Ensure all styling uses `var(--...)`.
2. **Tabular Numeral Enforcement**: Verify `.opb-num` or `tabular-nums` is applied to all financial numbers, prices, and timestamps.
3. **Layout & Overflow Check**: Verify zero horizontal scrollbars on desktop viewports (`max-width: 100vw`).
4. **Accessibility & Contrast**: Verify WCAG AA compliance for text-to-background contrast across light and dark themes.
5. **Responsive Adaptability**: Test cockpit grid collapsing on tablet (1024px) and mobile (640px).
