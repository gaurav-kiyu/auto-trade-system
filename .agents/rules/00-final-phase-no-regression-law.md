# FINAL-PHASE NO-REGRESSION LAW

A defect fix is NEVER evaluated in isolation.

Every change MUST be classified as:

- LOCAL
- SHARED
- GLOBAL
- SECURITY
- DATA
- AUTH
- RESPONSIVE
- THEME
- FUNCTIONAL

The classification determines the regression blast radius.

### Blast Radius Protocol:
- **LOCAL change**: test the affected component and consumers.
- **SHARED change**: test every consumer.
- **GLOBAL change**: test every route, theme, viewport and shell state.
- **AUTH/SECURITY change**: test authenticated + unauthenticated + authorized + unauthorized paths.
- **THEME change**: test every registered theme.
- **RESPONSIVE change**: test desktop + tablet + mobile + resize transitions.

No change may be marked COMPLETE until its defined blast-radius
regression has passed with objective evidence.

A passing screenshot is NOT proof of functional correctness.

A passing unit test is NOT proof of visual correctness.

A passing desktop test is NOT proof of mobile correctness.

A passing mobile test is NOT proof of desktop correctness.

A passing one-theme test is NOT proof of theme compatibility.

**NO ASSUMPTION-BASED COMPLETION.**

---

## Shared Component Mutation Law

A shared component is considered HIGH-RISK if it is consumed by
more than one route, template, theme, viewport, or feature.

Examples:

- global header
- global navigation
- mobile drawer
- password input
- theme engine
- design-system CSS
- toast/error manager
- authentication components

Before modifying a HIGH-RISK component:

1. Enumerate every consumer.
2. Enumerate every route.
3. Enumerate every theme.
4. Enumerate desktop/mobile consumers.
5. Record the expected behavior.
6. Record the current passing behavior.
7. Identify blast radius.
8. Create regression cases.
9. Make the smallest change.
10. Re-run ALL affected consumers.
11. Run global regression when the component is global.
12. Compare previous PASS results against new results.

A mutation is forbidden if its blast radius is unknown.

A regression is not "fixed" by introducing another CSS/JS exception.

Repeated exceptions indicate architectural root cause and require
root-cause remediation instead of additional patching.
