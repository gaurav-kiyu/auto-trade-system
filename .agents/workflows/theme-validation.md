# Workflow — Multi-Theme Validation Protocol

## Purpose
Ensure all 9 integrated themes maintain perfect visual consistency and zero theme leakage.

## Execution Steps
1. **Switch Theme via API / Selector**:
   ```javascript
   OPBThemeEngine.applyTheme('dark-cyber');
   OPBThemeEngine.applyTheme('nordic-frost');
   OPBThemeEngine.applyTheme('ivory-gold');
   OPBThemeEngine.applyTheme('obsidian-gold');
   OPBThemeEngine.applyTheme('midnight-slate');
   OPBThemeEngine.applyTheme('emerald-matrix');
   OPBThemeEngine.applyTheme('dracula-purple');
   OPBThemeEngine.applyTheme('tokyo-night');
   OPBThemeEngine.applyTheme('catppuccin-mocha');
   ```
2. **Inspect Chart & Canvas Elements**: Verify Chart.js instances react to `window.addEventListener('opbThemeChanged')` and adapt grid/text colors.
3. **Verify Light Themes**: Pay special attention to `nordic-frost`, `ivory-gold`, `midnight-slate`, and `dracula-purple` to ensure cards, text, and inputs have sufficient dark text contrast against bright surfaces.
4. **Verify Toasts & Modals**: Trigger test toasts (`showSuccess`, `showError`, `showWarning`) and confirm theme styling.

## 2026 Palette Direction
- Maintain a balanced **5 dark / 4 light** theme portfolio rather than a dark-only catalog.
- Light themes use soft off-white/cool-neutral surfaces instead of stark white, with finance-trust blues, emerald/teal growth accents, warm amber, or plum/rose accents.
- Dark themes use tinted navy/slate/green/plum surfaces rather than pure black.
- Keep trading semantics invariant: green = positive, red = negative/risk, amber = warning, and blue/violet are navigation/brand accents.
- Validate every theme for text, controls, charts, tables, toasts, modals, and mobile navigation.
