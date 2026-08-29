# Typography System

## Font Families
- **Primary UI**: `Inter`, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif
- **Display / Cockpit Headers**: `Plus Jakarta Sans`, `Inter`, sans-serif
- **Quantitative & Financial**: `JetBrains Mono`, monospace

## Tabular Numeral Enforcement
All numerical financial metrics, timestamps, strike prices, and percentages must enable tabular numbers:
```css
font-variant-numeric: tabular-nums;
font-feature-settings: "tnum" 1, "zero" 1;
```
