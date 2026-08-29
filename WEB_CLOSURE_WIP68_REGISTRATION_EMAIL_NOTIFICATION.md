# OPB WEB CLOSURE WIP68 — Registration Email/Notification Closure Review

Concrete registration handlers: 11
Email/notification signals in handlers: 4
Callable-looking direct signals: 2

## Direct lifecycle signals
- `/register` — `core/auth/routes.py:137+69` — `notification_result = notify_new_registration(`
- `/users` — `core/auth/routes.py:422+52` — `notification_result = notify_new_registration(`

## All email/notification signals
- `/register` — `core/auth/routes.py:137+69` — `notification_result = notify_new_registration(`
- `/register` — `core/auth/routes.py:137+79` — `"notification": notification_result,`
- `/users` — `core/auth/routes.py:422+52` — `notification_result = notify_new_registration(`
- `/users` — `core/auth/routes.py:422+59` — `result["notification"] = notification_result`