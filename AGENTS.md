# MANDATORY AGENT GOVERNANCE & ENGINEERING CONSTITUTION

This repository operates under strict engineering governance. Every agent operating in this repository MUST comply with the rules defined herein and in `.agents/rules/`.

---

## 1. HIGHEST AUTHORITY: NO ASSUMPTION-BASED COMPLETION (OPB-FINAL-PHASE-GOVERNANCE-001)
> **NEVER DECLARE COMPLETION BASED ON ASSUMPTION.**
> **Only PROVEN empirical test & remote verification results may be used as evidence for completion.**

Full rule specification: [`.agents/rules/opb-final-phase-governance.md`](.agents/rules/opb-final-phase-governance.md)

### Mandatory 17-Stage Change Lifecycle:
```text
REQUEST → PRE-CHANGE DISCOVERY → RCA → IMPACT ANALYSIS → RISK ANALYSIS → BLAST-RADIUS ANALYSIS → IMPLEMENTATION PLAN → CONTROLLED IMPLEMENTATION → POST-CHANGE VALIDATION → DEEP REGRESSION → DOCUMENTATION SYNC → REPOSITORY HYGIENE → FINAL EVIDENCE REVIEW → COMMIT → PUSH → REMOTE VERIFICATION (HEAD == origin/main) → COMPLETE
```

---

## 2. OPB UI GOLDEN RULE
> **Never implement a visual change as an isolated page-level solution when the change represents a reusable design concept.**

Full rule specification: [`.agents/rules/opb-ui-architecture.md`](.agents/rules/opb-ui-architecture.md)

### 5-Step Component Lifecycle:
1. Check existing design tokens (`static/opb_design_system.css`).
2. Check existing component abstractions (`.opb-card`, `.opb-stat-card`, `.opb-table`, `.opb-tab`, `.opb-badge`).
3. Check existing theme architecture (`static/theme_engine.js`).
4. Extend design system via dynamic CSS variables if needed.
5. Reuse abstractions universally across all 41 templates.

---

## 3. ZERO MUTATION CONSTRAINTS
- **Zero Hardcoded Colors**: No theme-specific hex codes inside business components or templates.
- **Zero Backend / Trading Mutations**: Never modify trading, risk, broker, strategy, execution, or database logic during UI-only tasks.
- **All-Theme Verification**: Every visual change must be verified across all 9 supported themes (`dark-cyber`, `nordic-frost`, `ivory-gold`, `obsidian-gold`, `midnight-slate`, `emerald-matrix`, `dracula-purple`).
- **Tabular Numeral Enforcement**: All financial figures, quantities, timestamps, and percentages must use tabular monospaced numbers (`"tnum" 1, "zero" 1`).

---

## 4. AGENT RULE REPOSITORY MAPPING
- [`.agents/rules/opb-final-phase-governance.md`](.agents/rules/opb-final-phase-governance.md): 32-clause Change Governance & Completion Gate
- [`.agents/rules/opb-ui-architecture.md`](.agents/rules/opb-ui-architecture.md): OPB UI Golden Rule & Component Architecture
- [`.agents/rules/opb-fintech-design.md`](.agents/rules/opb-fintech-design.md): 5-Second Cockpit Test & Fintech Standards
- [`.agents/rules/opb-2026-design-system.md`](.agents/rules/opb-2026-design-system.md): 2026 Modern Typography & Theme Design System Upgrade
- [`.agents/workflows/ui-audit.md`](.agents/workflows/ui-audit.md): 41-Template CSS, Contrast & Overflow Audit
- [`.agents/workflows/theme-validation.md`](.agents/workflows/theme-validation.md): Multi-Theme Testing Protocol
- [`.agents/workflows/visual-regression.md`](.agents/workflows/visual-regression.md): Automated Jinja & PyTest Quality Assurance
