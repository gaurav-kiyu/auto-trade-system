"""Registration notification workflow.

Sends non-blocking registration notifications to the new user and the configured
administrator recipients. SMTP configuration is read from environment/config;
no credentials are embedded in source code.
"""
from __future__ import annotations

import html
import json
import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

from core.notifications.url_resolver import build_action_url

_log = logging.getLogger("AUTH_REGISTRATION_NOTIFICATIONS")
_ROOT = Path(__file__).resolve().parents[2]


def _config() -> dict[str, Any]:
    path = _ROOT / "json" / "config.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception as exc:
        _log.warning("Unable to load config for registration notification: %s", exc)
        return {}


def _smtp_settings() -> tuple[str, int, str, str, bool, list[str]]:
    cfg = _config()
    host = str(os.getenv("OPBUYING_EMAIL_SMTP") or cfg.get("EMAIL_SMTP") or "smtp.gmail.com").strip()
    port = int(os.getenv("OPBUYING_EMAIL_PORT") or cfg.get("EMAIL_PORT") or 587)
    username = str(os.getenv("OPBUYING_EMAIL_USER") or cfg.get("EMAIL_USER") or "").strip()
    password = str(os.getenv("OPBUYING_EMAIL_PASS") or cfg.get("EMAIL_PASS") or "").strip()
    enabled = str(os.getenv("OPBUYING_EMAIL_ENABLED") or cfg.get("EMAIL_ENABLED", True)).lower() == "true"
    recipients_raw = str(os.getenv("OPBUYING_EMAIL_TO") or cfg.get("EMAIL_TO") or "")
    recipients = [x.strip() for x in recipients_raw.split(",") if x.strip()]
    return host, port, username, password, enabled, recipients


def _send(to: list[str], subject: str, html: str, plain: str) -> bool:
    if not to:
        return False
    # Unit/integration tests must never contact an external SMTP server.
    if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("OPB_DISABLE_EXTERNAL_NOTIFICATIONS", "").lower() == "true":
        _log.debug("Registration email suppressed in test/non-external mode")
        return False
    host, port, username, password, enabled, _ = _smtp_settings()
    if not enabled or not username or not password:
        _log.info("Registration email skipped: SMTP not configured/enabled")
        return False
    msg = MIMEMultipart("alternative")
    msg["From"] = username
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))
    try:
        with smtplib.SMTP(host, port, timeout=15) as server:
            server.starttls()
            server.login(username, password)
            server.sendmail(username, to, msg.as_string())
        return True
    except (OSError, smtplib.SMTPException, TimeoutError, ValueError) as exc:
        _log.warning("Registration email delivery failed: %s", exc)
        return False


def notify_new_registration(
    *,
    username: str,
    display_name: str,
    email: str,
    role: str,
    created_by: str,
) -> dict[str, bool]:
    """Send welcome/pending-approval email and administrator notification.

    Delivery failures are intentionally non-fatal: account creation must not be
    rolled back merely because SMTP is temporarily unavailable.
    """
    base = build_action_url("/login")
    safe_name = display_name or username
    # Registration fields are user-controlled; escape them before embedding in HTML mail.
    html_username = html.escape(username, quote=True)
    html_display_name = html.escape(safe_name, quote=True)
    html_email = html.escape(email or "-", quote=True)
    html_role = html.escape(role, quote=True)
    html_created_by = html.escape(created_by, quote=True)
    user_sent = False
    admin_sent = False

    if email:
        user_html = f"""
        <html><body style='font-family:Arial,sans-serif;color:#1f2937'>
        <h2>Welcome to OPB Super-Platform</h2>
        <p>Hello <b>{html_display_name}</b>,</p>
        <p>Your OPB account <b>{html_username}</b> has been created with the <b>{html_role}</b> role.</p>
        <p><b>Your account is pending administrator authorization.</b> Until the required permissions are granted, restricted signal and administration features will remain unavailable.</p>
        <h3>What happens next?</h3>
        <ol><li>An administrator reviews your account.</li><li>They assign the permitted menus, signal categories, conviction level and quotas.</li><li>You can then use the features authorized for your account.</li></ol>
        <p><a href='{base}' style='display:inline-block;padding:10px 16px;background:#2563eb;color:white;text-decoration:none;border-radius:6px'>Open OPB Login</a></p>
        <p style='font-size:12px;color:#6b7280'>This is an automated security notification. Please contact your OPB administrator if you did not request this account.</p>
        </body></html>
        """
        user_plain = (
            f"Welcome to OPB Super-Platform, {safe_name}.\n\n"
            f"Account: {username}\nRole: {role}\n\n"
            "Your account is pending administrator authorization. An administrator must assign the permissions, menus, signal categories, conviction level and quotas before restricted features become available.\n\n"
            f"Login: {base}\n"
        )
        user_sent = _send([email], "Welcome to OPB Super-Platform — Authorization Pending", user_html, user_plain)

    _, _, _, _, _, admin_recipients = _smtp_settings()
    if admin_recipients:
        admin_html = f"""
        <html><body style='font-family:Arial,sans-serif;color:#1f2937'>
        <h2>New OPB User Registration</h2>
        <p>A new user has registered and requires permission review.</p>
        <table cellpadding='6' cellspacing='0' border='1' style='border-collapse:collapse'>
        <tr><td><b>Username</b></td><td>{html_username}</td></tr>
        <tr><td><b>Display Name</b></td><td>{html_display_name}</td></tr>
        <tr><td><b>Email</b></td><td>{html_email}</td></tr>
        <tr><td><b>Role</b></td><td>{html_role}</td></tr>
        <tr><td><b>Created By</b></td><td>{html_created_by}</td></tr>
        </table>
        <p>Please review the account in <b>User Authorization & Controls</b> and explicitly assign the required privileges before the user begins using restricted features.</p>
        <p><a href='{build_action_url('/admin/users')}' style='display:inline-block;padding:10px 16px;background:#2563eb;color:white;text-decoration:none;border-radius:6px'>Open User Controls</a></p>
        </body></html>
        """
        admin_plain = (
            "New OPB user registration requires review.\n\n"
            f"Username: {username}\nDisplay Name: {safe_name}\nEmail: {email or '-'}\nRole: {role}\nCreated By: {created_by}\n\n"
            f"Review: {build_action_url('/admin/users')}\n"
        )
        admin_sent = _send(admin_recipients, f"OPB: New User Registration — {username}", admin_html, admin_plain)

    return {"user_email_sent": user_sent, "admin_email_sent": admin_sent}
