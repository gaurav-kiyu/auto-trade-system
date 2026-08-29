# OPB WEB CLOSURE WIP70 — `notify_new_registration()` Review

Implementation: `core/auth/registration_notifications.py`
Function starts at line 74

## Function implementation
```python
74: def notify_new_registration(
75:     *,
76:     username: str,
77:     display_name: str,
78:     email: str,
79:     role: str,
80:     created_by: str,
81: ) -> dict[str, bool]:
82:     """Send welcome/pending-approval email and administrator notification.
83: 
84:     Delivery failures are intentionally non-fatal: account creation must not be
85:     rolled back merely because SMTP is temporarily unavailable.
86:     """
87:     base = build_action_url("/login")
88:     safe_name = display_name or username
89:     # Registration fields are user-controlled; escape them before embedding in HTML mail.
90:     html_username = html.escape(username, quote=True)
91:     html_display_name = html.escape(safe_name, quote=True)
92:     html_email = html.escape(email or "-", quote=True)
93:     html_role = html.escape(role, quote=True)
94:     html_created_by = html.escape(created_by, quote=True)
95:     user_sent = False
96:     admin_sent = False
97: 
98:     if email:
99:         user_html = f"""
100:         <html><body style='font-family:Arial,sans-serif;color:#1f2937'>
101:         <h2>Welcome to OPB Super-Platform</h2>
102:         <p>Hello <b>{html_display_name}</b>,</p>
103:         <p>Your OPB account <b>{html_username}</b> has been created with the <b>{html_role}</b> role.</p>
104:         <p><b>Your account is pending administrator authorization.</b> Until the required permissions are granted, restricted signal and administration features will remain unavailable.</p>
105:         <h3>What happens next?</h3>
106:         <ol><li>An administrator reviews your account.</li><li>They assign the permitted menus, signal categories, conviction level and quotas.</li><li>You can then use the features authorized for your account.</li></ol>
107:         <p><a href='{base}' style='display:inline-block;padding:10px 16px;background:#2563eb;color:white;text-decoration:none;border-radius:6px'>Open OPB Login</a></p>
108:         <p style='font-size:12px;color:#6b7280'>This is an automated security notification. Please contact your OPB administrator if you did not request this account.</p>
109:         </body></html>
110:         """
111:         user_plain = (
112:             f"Welcome to OPB Super-Platform, {safe_name}.\n\n"
113:             f"Account: {username}\nRole: {role}\n\n"
114:             "Your account is pending administrator authorization. An administrator must assign the permissions, menus, signal categories, conviction level and quotas before restricted features become available.\n\n"
115:             f"Login: {base}\n"
116:         )
117:         user_sent = _send([email], "Welcome to OPB Super-Platform — Authorization Pending", user_html, user_plain)
118: 
119:     _, _, _, _, _, admin_recipients = _smtp_settings()
120:     if admin_recipients:
121:         admin_html = f"""
122:         <html><body style='font-family:Arial,sans-serif;color:#1f2937'>
123:         <h2>New OPB User Registration</h2>
124:         <p>A new user has registered and requires permission review.</p>
125:         <table cellpadding='6' cellspacing='0' border='1' style='border-collapse:collapse'>
126:         <tr><td><b>Username</b></td><td>{html_username}</td></tr>
127:         <tr><td><b>Display Name</b></td><td>{html_display_name}</td></tr>
128:         <tr><td><b>Email</b></td><td>{html_email}</td></tr>
129:         <tr><td><b>Role</b></td><td>{html_role}</td></tr>
130:         <tr><td><b>Created By</b></td><td>{html_created_by}</td></tr>
131:         </table>
132:         <p>Please review the account in <b>User Authorization & Controls</b> and explicitly assign the required privileges before the user begins using restricted features.</p>
133:         <p><a href='{build_action_url('/admin/users')}' style='display:inline-block;padding:10px 16px;background:#2563eb;color:white;text-decoration:none;border-radius:6px'>Open User Controls</a></p>
134:         </body></html>
135:         """
136:         admin_plain = (
137:             "New OPB user registration requires review.\n\n"
138:             f"Username: {username}\nDisplay Name: {safe_name}\nEmail: {email or '-'}\nRole: {role}\nCreated By: {created_by}\n\n"
139:             f"Review: {build_action_url('/admin/users')}\n"
140:         )
141:         admin_sent = _send(admin_recipients, f"OPB: New User Registration — {username}", admin_html, admin_plain)
142: 
143:     return {"user_email_sent": user_sent, "admin_email_sent": admin_sent}
```

## Direct communication concepts found
- `74` — `def notify_new_registration(`
- `78` — `email: str,`
- `82` — `"""Send welcome/pending-approval email and administrator notification.`
- `89` — `# Registration fields are user-controlled; escape them before embedding in HTML mail.`
- `92` — `html_email = html.escape(email or "-", quote=True)`
- `96` — `admin_sent = False`
- `98` — `if email:`
- `101` — `<h2>Welcome to OPB Super-Platform</h2>`
- `104` — `<p><b>Your account is pending administrator authorization.</b> Until the required permissions are granted, restricted signal and administration features will remain unavailable.</p>`
- `106` — `<ol><li>An administrator reviews your account.</li><li>They assign the permitted menus, signal categories, conviction level and quotas.</li><li>You can then use the features authorized for your account.</li></ol>`
- `108` — `<p style='font-size:12px;color:#6b7280'>This is an automated security notification. Please contact your OPB administrator if you did not request this account.</p>`
- `112` — `f"Welcome to OPB Super-Platform, {safe_name}.\n\n"`
- `114` — `"Your account is pending administrator authorization. An administrator must assign the permissions, menus, signal categories, conviction level and quotas before restricted features become available.\n\n"`
- `117` — `user_sent = _send([email], "Welcome to OPB Super-Platform — Authorization Pending", user_html, user_plain)`
- `119` — `_, _, _, _, _, admin_recipients = _smtp_settings()`
- `120` — `if admin_recipients:`
- `121` — `admin_html = f"""`
- `124` — `<p>A new user has registered and requires permission review.</p>`
- `128` — `<tr><td><b>Email</b></td><td>{html_email}</td></tr>`
- `133` — `<p><a href='{build_action_url('/admin/users')}' style='display:inline-block;padding:10px 16px;background:#2563eb;color:white;text-decoration:none;border-radius:6px'>Open User Controls</a></p>`
- `136` — `admin_plain = (`
- `138` — `f"Username: {username}\nDisplay Name: {safe_name}\nEmail: {email or '-'}\nRole: {role}\nCreated By: {created_by}\n\n"`
- `139` — `f"Review: {build_action_url('/admin/users')}\n"`
- `141` — `admin_sent = _send(admin_recipients, f"OPB: New User Registration — {username}", admin_html, admin_plain)`
- `143` — `return {"user_email_sent": user_sent, "admin_email_sent": admin_sent}`