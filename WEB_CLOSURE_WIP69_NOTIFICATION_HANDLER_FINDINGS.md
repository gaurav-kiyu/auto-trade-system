# OPB WEB CLOSURE WIP69 — Concrete Registration Notification Findings

Notification signals: 4

## Findings
- `/register` — `core/auth/routes.py:137+69` — `notification_result = notify_new_registration(`
- `/register` — `core/auth/routes.py:137+79` — `"notification": notification_result,`
- `/users` — `core/auth/routes.py:422+52` — `notification_result = notify_new_registration(`
- `/users` — `core/auth/routes.py:422+59` — `result["notification"] = notification_result`