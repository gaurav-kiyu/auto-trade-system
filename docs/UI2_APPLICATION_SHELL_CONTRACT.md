OPB v2.59.4 — UI-2 APPLICATION SHELL CONTRACT
Generated: 2026-09-10 09:33:41

STATUS
------
UI-2A-R: GREEN
UI-2B: CONTRACT FROZEN
Application certification: NOT CERTIFIED until final gates are GREEN

SCOPE
-----
Redesign application shell only.
No route changes.
No RBAC changes.
No persistence changes.
No API changes.
No trading/execution semantic changes.
No removal of existing functionality.

PRIMARY SHELL
-------------
Desktop:
  - Global brand/header
  - Telemetry/latency
  - Theme selector
  - Emergency KILL SWITCH
  - User/session controls
  - Primary workspace navigation

Tablet:
  - Mobile/tablet app bar
  - Hamburger navigation
  - Theme selector inside drawer
  - KILL SWITCH remains directly accessible
  - Full navigation drawer
  - Responsive content shell

Mobile:
  - Mobile app bar
  - Hamburger navigation
  - Full navigation drawer
  - Mobile bottom quick-routing dock
  - KILL SWITCH remains directly accessible
  - No desktop-table compression

REQUIRED SHELL ANCHORS
----------------------
desktopThemeSelect
drawerThemeSelect
opb-desktop-nav
opb-mobile-appbar
opb-mobile-drawer
opb-mobile-bottom-dock
mobileTopMenuBtn
mobileBottomMenuBtn
drawerNavList
KILL SWITCH
GAURAV
Command Center
Markets & Radar
Execution & PnL
Strategy & AI
Admin & Governance

THEME CONTRACT
--------------
Exactly five selectable themes.
Order is immutable:

1. dark-cyber
2. dracula-purple
3. ivory-gold
4. midnight-slate
5. emerald-matrix

Desktop and drawer selectors must expose exactly those five IDs
in exactly that order.

Internal theme-engine IDs outside this selectable set may remain
for compatibility, but must not become selectable.

TYPOGRAPHY
----------
Primary UI:
  Inter / system fallback stack

Display:
  existing display stack may remain only where explicitly required

Data:
  JetBrains Mono / monospace for:
    prices
    P&L
    percentages
    timestamps
    IDs
    technical values

Shell typography must consume canonical design tokens.

SPACING
-------
Use canonical 8-point spacing system:
4 / 8 / 12 / 16 / 20 / 24 / 32 / 40 / 48 / 64px

CONTROL SIZES
-------------
Interactive targets must remain accessible.
Mobile targets should preferentially provide approximately 44px
touch area.

VISUAL LANGUAGE
---------------
Premium institutional trading cockpit.

Use:
  - restrained gradients
  - selective glass/translucent surfaces
  - subtle borders
  - restrained shadows
  - small accent highlights
  - clear hierarchy
  - high information density with generous whitespace

Avoid:
  - excessive neon
  - excessive blur
  - giant gradients
  - excessive shadows
  - inconsistent corner radii
  - excessive rounded/pill UI
  - decorative effects that reduce readability

RESPONSIVE CONTRACT
-------------------
Desktop: >= 1200px
Tablet: 768px - 1199px
Mobile: < 768px

The existing 1024px navigation transition must be preserved
during migration unless browser regression proves an equivalent
or superior replacement.

Responsive redesign must test:
  - desktop
  - tablet
  - mobile

No horizontal overflow may be introduced by the shell.

ACCESSIBILITY
-------------
WCAG 2.2 AA target.

Required:
  - visible keyboard focus
  - semantic labels
  - keyboard-accessible navigation
  - sufficient contrast
  - accessible theme controls
  - accessible drawer controls
  - accessible KILL SWITCH
  - reduced-motion support

SAFETY
------
KILL SWITCH is safety-critical.

Redesign must not:
  - hide it
  - remove it
  - make it inaccessible
  - alter its endpoint
  - alter its authorization semantics
  - alter its confirmation behavior

FUNCTIONALITY PRESERVATION
--------------------------
Preserve:
  - all navigation routes
  - workspace groups
  - theme persistence
  - desktop theme selection
  - drawer theme selection
  - drawer search
  - mobile bottom routing
  - logout/session controls
  - telemetry display
  - KILL SWITCH
  - active navigation state
  - RBAC visibility behavior

ENCODING
--------
_nav.html must remain strict UTF-8.

No mojibake:
  Ã
  Â
  â€
  ðŸ
  ï¿½

IMPLEMENTATION PRINCIPLE
------------------------
Do not blindly rewrite _nav.html.

First consolidate shell styling into canonical design-system
tokens/classes where safe.

Preserve existing DOM hooks required by:
  JavaScript
  Playwright
  theme engine
  navigation logic
  drawer logic
  persistence logic
  RBAC/template logic

REGRESSION REQUIREMENT
----------------------
Every shell mutation requires:
  - structural guard
  - UTF-8 guard
  - theme exact-five guard
  - theme persistence regression
  - desktop regression
  - tablet regression
  - mobile regression
  - navigation regression
  - KILL SWITCH accessibility regression
  - no-horizontal-overflow regression

CERTIFICATION
-------------
UI-2 is not GREEN merely because CSS compiles.

UI-2 GREEN requires:
  - implementation complete
  - POST-GUARD GREEN
  - browser desktop PASS
  - browser tablet PASS
  - browser mobile PASS
  - theme matrix PASS
  - navigation PASS
  - no functionality loss
  - no P0/P1 regression