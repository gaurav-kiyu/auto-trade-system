# OPB Production Regression Governance

## STATUS

MANDATORY
FINAL-PHASE APPLICATION
REGRESSION-SENSITIVE SYSTEM

## NON-NEGOTIABLE RULE

NO CHANGE MAY BE IMPLEMENTED WITHOUT:

1. PRE-GUARD
2. RCA
3. IMPACT ANALYSIS
4. BLAST-RADIUS ANALYSIS
5. IMPLEMENTATION
6. POST-GUARD
7. DEEP REGRESSION
8. EVIDENCE
9. DOCUMENTATION SYNC
10. GIT VERIFICATION

## GLOBAL SHELL INVARIANT

The OPB application has exactly one canonical global shell.

Branding is NOT navigation.

Branding MUST remain a dedicated global identity region.

Branding MUST NOT be moved into:

- navigation
- menu items
- page content
- theme controls
- user controls

Desktop and mobile must use canonical shell components.

## FUNCTIONAL PARITY INVARIANT

Visual redesign MUST NOT remove existing functionality.

Existing controls MUST remain functionally available unless explicitly
approved for removal.

Examples:

- eye / password visibility
- search
- filter
- sort
- refresh
- save
- copy
- download
- expand
- collapse
- navigation
- keyboard shortcuts

## RESPONSIVE INVARIANT

Responsive design may change layout.

It MUST NOT silently remove functionality.

Every critical feature must have an accessible desktop AND mobile
interaction.

## THEME INVARIANT

Themes change presentation.

Themes MUST NOT change:

- functionality
- route structure
- navigation architecture
- component existence
- business behavior

## SHARED COMPONENT INVARIANT

Before modifying a shared component:

1. Discover every consumer.
2. Determine blast radius.
3. Test affected consumers.
4. Test critical unaffected consumers.
5. Test desktop.
6. Test mobile.
7. Test relevant themes.

## TABLE INVARIANT

Responsive financial/data tables MUST NEVER collapse text character-by-
character.

Use:

- horizontal scroll
- responsive cards
- priority columns
- semantic key/value layout

## FORM INVARIANT

Responsive labels MUST NEVER fragment into individual characters.

If horizontal layout cannot fit:

stack label above input.

## COMPLETION INVARIANT

The agent MUST NOT state:

"done"
"complete"
"production ready"
"all tests passed"

without evidence.

## EVIDENCE

Claims must be supported by:

- test output
- browser verification
- screenshots
- regression matrix
- logs
- commit SHA
- remote SHA

## GOLDEN RULE

DO NOT FIX ONE SCREEN BY BREAKING ANOTHER.

SYSTEM-WIDE CORRECTNESS > LOCAL OPTIMIZATION.
