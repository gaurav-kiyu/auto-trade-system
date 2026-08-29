# OPB Theme Refresh — 2026 Market-Trend Palette Update

## Objective
Increase light-mode coverage while keeping the OPB Super-App's 9-theme architecture and preserving stable theme IDs.

## Theme distribution
- 5 dark themes: Dark Cyber, Tokyo Night, Catppuccin Mocha, Obsidian Gold, Emerald Matrix
- 4 light themes: Nordic Frost, Ivory & Gold, Sapphire Day, Plum Cloud

## Updated themes
- `midnight-slate` → **Sapphire Day (Modern Finance Light)**
  - Cool off-white surfaces
  - Sapphire/electric blue primary accent
  - Emerald positive state, amber warning, red risk
- `dracula-purple` → **Plum Cloud (Premium Light)**
  - Soft lavender-white surfaces
  - Plum/violet + rose gradient accents
  - Same invariant trading semantic colors

Theme IDs were deliberately preserved to avoid breaking persisted user preferences or selectors.

## Design direction
The refresh follows current 2026 UI/fintech direction: tinted neutrals rather than pure white/black, trustworthy finance blues, growth-oriented emerald/teal, warm amber accents, and restrained premium plum/rose combinations. Dark themes remain available for extended monitoring sessions.

## Validation
- 9 theme definitions present.
- Static and core theme engines are identical.
- JavaScript syntax validation passed for both copies.
- Theme asset consistency tests: 3 passed.
- WCAG contrast spot-checks for primary/secondary/muted text and accent-on-card were performed across all 9 themes.
