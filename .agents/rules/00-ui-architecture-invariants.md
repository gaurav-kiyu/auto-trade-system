# OPB UI ARCHITECTURE INVARIANTS

These rules are architectural invariants.

They MUST NOT be violated by individual screen implementations.

## 1. ONE GLOBAL SHELL

There is exactly one canonical application shell.

No page may implement its own header/navigation shell.

## 2. BRANDING ISOLATION

GAURAV / OPB branding is an identity component.

Branding is never a navigation item.

Branding is never duplicated inside navigation.

## 3. MOBILE IS NOT COMPRESSED DESKTOP

Mobile has an intentionally designed responsive shell.

Desktop controls must not simply be squeezed into mobile.

## 4. ONE MOBILE HEADER

Exactly one canonical mobile header.

## 5. ONE MOBILE DRAWER

Exactly one canonical mobile drawer.

## 6. ONE MOBILE BOTTOM NAV

Exactly one canonical mobile bottom navigation.

## 7. NAVIGATION OWNERSHIP

Header = essential controls.

Drawer = complete navigation.

Bottom navigation = highest-frequency destinations.

No duplicate navigation ownership.

## 8. COMPONENT-FIRST RESPONSIVENESS

Repeated UI problems must be fixed at the shared-component level.

Never solve systemic problems through page-specific CSS.

## 9. NO GLOBAL CSS DAMAGE

Global selectors must not modify component layout unless explicitly
classified as design-system primitives.

## 10. NO UNSUPPORTED CERTIFICATION

A feature cannot be marked VERIFIED without:

source evidence
+
automated test evidence
+
browser evidence
+
visual evidence

## 11. REGRESSION BEFORE CERTIFICATION

Any shared shell/theme/CSS change requires:

desktop regression
mobile regression
theme regression
functional regression

## 12. DOCUMENTATION MUST MATCH REALITY

If implementation and documentation disagree, documentation is wrong.

Update it.

## 13. ROOT CAUSE OVER PATCH

If the same issue occurs twice, stop patching and perform an
architectural RCA.

## 14. NO COMPLETION BY ASSUMPTION

"Should work" is not evidence.

"Looks correct" is not evidence.

"Tests passed" without browser verification is not sufficient for UI.

## 15. PRODUCTION CERTIFICATION

Production readiness requires:

clean Git state
passing tests
browser verification
visual verification
documentation synchronization
no known P0/P1 defects
verified deployment state
