# Workflow — Multi-Theme Validation Protocol

## Purpose
Ensure all 5 canonical integrated themes maintain perfect visual consistency and zero theme leakage.

## Execution Steps
1. **Switch Theme via API / Selector**:
   ```javascript
   OPBThemeEngine.applyTheme('dark-cyber');
   OPBThemeEngine.applyTheme('dracula-purple');
   OPBThemeEngine.applyTheme('ivory-gold');
   OPBThemeEngine.applyTheme('midnight-slate');
   OPBThemeEngine.applyTheme('emerald-matrix');
   ```
2. **Inspect Chart & Canvas Elements**: Verify Chart.js instances react to `window.addEventListener('opbThemeChanged')` and adapt grid/text colors.
3. **Verify Light Themes**: Pay special attention to `dracula-purple`, `ivory-gold`, and `midnight-slate` to ensure cards, text, and inputs have sufficient dark text contrast against bright surfaces.
4. **Verify Toasts & Modals**: Trigger test toasts (`showSuccess`, `showError`, `showWarning`) and confirm theme styling.

## Palette Direction
- Maintain the authoritative 5-theme portfolio: 2 Dark (`dark-cyber`, `emerald-matrix`) and 3 Light (`dracula-purple`, `ivory-gold`, `midnight-slate`).
- Light themes use soft off-white/cool-neutral surfaces instead of stark white, with finance-trust blues, warm amber, or plum/rose accents.
- Dark themes use tinted navy/slate/emerald surfaces rather than pure black.
- Keep trading semantics invariant: green = positive, red = negative/risk, amber = warning, and blue/violet are navigation/brand accents.
- Validate every theme for text, controls, charts, tables, toasts, modals, and mobile navigation.
