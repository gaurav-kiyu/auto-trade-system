# OPB Multi-Theme Architecture & Semantic Token Engine

## Supported Palettes
The OPB platform maintains 9 fully integrated, WCAG-compliant institutional themes:
1. **Dark Cyber** (Default institutional terminal dark)
2. **Nordic Frost** (High-contrast cool crisp light)
3. **Ivory & Gold** (Luxury institutional warm light)
4. **Tokyo Night** (Indigo neon-noir dark)
5. **Catppuccin Mocha** (Pastel dark)
6. **Obsidian Gold** (Luxury institutional dark gold)
7. **Sapphire Day** (Modern sapphire-blue finance light)
8. **Emerald Matrix** (Quant algorithmic green dark)
9. **Plum Cloud** (Premium plum-violet and rose light)

---

## Hierarchy
```
Theme Definition (9 Palettes in theme_engine.js)
       │
       ▼
Universal Design Tokens (static/opb_design_system.css)
       │
       ▼
Component Abstractions (.opb-card, .opb-stat, .opb-table, .opb-badge)
       │
       ▼
Enterprise HTML Templates
```

---

## Density Modes
Controlled globally via `[data-density="compact" | "comfortable" | "spacious"]`:
- **Compact**: 0.75rem padding, condensed fonts for multi-monitor institutional desks.
- **Comfortable** (Default): 1.25rem padding, balanced spacing.
- **Spacious**: 1.75rem padding for large display presentations.
