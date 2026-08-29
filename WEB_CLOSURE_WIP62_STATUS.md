# OPB WEB CLOSURE WIP62 — Admin Users Action/Filter Visibility Repair

## Concrete repair completed

The Admin Users grid used a wide table (`min-width: 1120px`) but its wrapper did not explicitly provide horizontal scrolling. This can push the ACTIONS column outside the usable viewport and make the View/Eye control appear missing or inaccessible.

WIP62 changes only the presentation boundary:
- `.admin-users-table-wrap` now uses `overflow-x: auto`;
- vertical overflow remains visible;
- the sticky Actions column is retained;
- action buttons are explicit inline-flex controls with minimum 34px targets;
- existing delegated click handling is retained;
- existing column-header filters are retained.

No backend, authorization, signal, database, or API behavior was changed.

## Focused validation

The regression suite verifies:
- action-column containment,
- View/Edit/Delete action presence,
- delegated dynamic-row click handling,
- all seven column-header filters.

NOT deployed to AWS.
NOT production-certified.
