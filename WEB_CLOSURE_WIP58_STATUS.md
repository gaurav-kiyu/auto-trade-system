# OPB WEB CLOSURE WIP58 — Desktop Navigation Pointer-Continuity Repair

## Repair completed

The desktop dropdown was already using the correct hover/focus architecture and a transparent pointer bridge. WIP58 adds one conservative hardening change for the reported "submenu disappears before I can click it" defect:

- increased the hidden-state visibility delay from 120ms to 300ms;
- raised `.opb-ws-group` stacking context to keep the dropdown above adjacent shell content;
- retained the existing 14px transparent pointer bridge;
- retained `:hover`, `:focus-within`, and `.menu-pinned`;
- retained `pointer-events: auto` while visible.

No navigation target or backend logic was changed.

## User Controls

Source inspection confirms there are only two `/admin/users` navigation representations in `_nav.html`:
1. desktop Admin & Governance submenu;
2. mobile drawer representation.

There is no separate standalone User Controls navigation link in the current enterprise navigation source.

## Validation

Added `tests/test_wip58_desktop_submenu_hover.py`.

This pass is a targeted Web-shell repair, not a complete application certification.

NOT deployed to AWS.
NOT production-certified.
