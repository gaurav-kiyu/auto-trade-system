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
) -> dict[str, Any]:
    """Send welcome/pending-approval email and administrator notification using the canonical OPB design system.

    Delivery failures are intentionally non-fatal: account creation must not be
    rolled back merely because SMTP is temporarily unavailable.
    """
    from core.notifications.rich_signal_formatter import RichSignalFormatter

    safe_name = display_name or username
    user_sent = False
    admin_sent = False

    user_payload = RichSignalFormatter.build_registration_welcome_notification(
        username=username,
        email=email or "-",
        full_name=safe_name,
        role=role,
        created_by=created_by,
        status="PENDING_APPROVAL",
    )
    admin_payload = RichSignalFormatter.build_registration_admin_notification(
        username=username,
        email=email or "-",
        full_name=safe_name,
        role=role,
        created_by=created_by,
        status="PENDING_APPROVAL",
    )

    if email:
        user_sent = _send(
            [email],
            user_payload["subject"],
            user_payload["email_html"],
            user_payload["plain_text"],
        )

    _, _, _, _, _, admin_recipients = _smtp_settings()
    if admin_recipients:
        admin_sent = _send(
            admin_recipients,
            admin_payload["subject"],
            admin_payload["email_html"],
            admin_payload["plain_text"],
        )

    return {
        "user_email_sent": user_sent,
        "admin_email_sent": admin_sent,
        "user_notification": user_payload,
        "admin_notification": admin_payload,
    }

