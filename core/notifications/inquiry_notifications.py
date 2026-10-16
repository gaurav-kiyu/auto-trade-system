"""Contact Inquiry Notification Workflow for OPB Platform.

Dispatches non-blocking notifications:
1. Admin alert to configured administrator(s).
2. Submitter acknowledgment email with unique ticket ID.

Follows the canonical OPB design system and security guidelines.
"""

from __future__ import annotations

import html
import json
import logging
import os
import smtplib
import threading
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

_log = logging.getLogger("INQUIRY_NOTIFICATIONS")
_ROOT = Path(__file__).resolve().parents[2]


def _config() -> dict[str, Any]:
    path = _ROOT / "json" / "config.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception as exc:
        _log.warning("Unable to load config for inquiry notification: %s", exc)
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


def _send_email(to: list[str], subject: str, html_body: str, plain_body: str) -> bool:
    if not to:
        return False
    # Suppress real SMTP during tests
    if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("OPB_DISABLE_EXTERNAL_NOTIFICATIONS", "").lower() == "true":
        _log.debug("Inquiry email suppressed in test mode for %s", to)
        return True

    host, port, username, password, enabled, _ = _smtp_settings()
    if not enabled or not username or not password:
        _log.info("Inquiry email skipped: SMTP not configured or disabled")
        return False

    msg = MIMEMultipart("alternative")
    msg["From"] = username
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    msg.attach(MIMEText(plain_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP(host, port, timeout=15) as server:
            server.starttls()
            server.login(username, password)
            server.sendmail(username, to, msg.as_string())
        return True
    except (OSError, smtplib.SMTPException, TimeoutError, ValueError) as exc:
        _log.warning("Inquiry email delivery failed to %s: %s", to, exc)
        return False


def build_admin_alert_email(inquiry: dict[str, Any]) -> tuple[str, str]:
    """Build HTML and plain text notification for administrators."""
    inq_id = html.escape(str(inquiry.get("id") or ""))
    name = html.escape(str(inquiry.get("name") or ""))
    email = html.escape(str(inquiry.get("email") or ""))
    category = html.escape(str(inquiry.get("category") or "General"))
    subject = html.escape(str(inquiry.get("subject") or ""))
    message = html.escape(str(inquiry.get("message") or "")).replace("\n", "<br>")
    client_ip = html.escape(str(inquiry.get("client_ip") or "unknown"))
    created_at = html.escape(str(inquiry.get("created_at") or ""))

    html_content = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background:#080c14; color:#e2e8f0; margin:0; padding:20px; }}
.card {{ background:#0f172a; border:1px solid #334155; border-radius:10px; max-width:640px; margin:0 auto; padding:24px; box-shadow:0 8px 30px rgba(0,0,0,0.5); }}
.badge {{ background:rgba(56,189,248,0.15); border:1px solid #38bdf8; color:#38bdf8; font-weight:800; font-size:11px; padding:3px 8px; border-radius:4px; text-transform:uppercase; }}
.header {{ border-bottom:1px solid #1e293b; padding-bottom:16px; margin-bottom:20px; }}
.row {{ display:flex; justify-content:space-between; margin-bottom:8px; font-size:13px; }}
.label {{ color:#94a3b8; font-weight:600; width:120px; }}
.val {{ color:#f8fafc; font-weight:500; font-family:"JetBrains Mono", monospace; }}
.msg-box {{ background:#070d19; border:1px solid #1e293b; border-radius:6px; padding:16px; margin-top:16px; font-size:14px; line-height:1.6; color:#cbd5e1; }}
.footer {{ margin-top:24px; padding-top:16px; border-top:1px solid #1e293b; font-size:12px; color:#64748b; text-align:center; }}
</style>
</head>
<body>
<div class="card">
    <div class="header">
        <span class="badge">SUPPORT INQUIRY</span>
        <h2 style="margin:10px 0 0 0; color:#ffffff; font-size:18px;">New Contact Submission</h2>
        <div style="font-size:12px; color:#94a3b8; margin-top:4px;">Ticket ID: {inq_id} &bull; Received: {created_at}</div>
    </div>
    <div class="row"><span class="label">Submitter:</span><span class="val">{name} &lt;{email}&gt;</span></div>
    <div class="row"><span class="label">Category:</span><span class="val">{category}</span></div>
    <div class="row"><span class="label">Subject:</span><span class="val">{subject}</span></div>
    <div class="row"><span class="label">Client IP:</span><span class="val">{client_ip}</span></div>
    <div class="msg-box">{message}</div>
    <div class="footer">
        Gaurav OPB Platform &bull; Review in Admin Portal at <a href="/admin/inquiries" style="color:#38bdf8;">/admin/inquiries</a>
    </div>
</div>
</body>
</html>"""

    plain_content = f"""[OPB Support Ticket] {category}: {subject}
Ticket ID: {inquiry.get('id')}
Submitter: {inquiry.get('name')} <{inquiry.get('email')}>
Received: {inquiry.get('created_at')}
Client IP: {inquiry.get('client_ip')}

Message:
{inquiry.get('message')}

Review and respond via OPB Admin Portal.
"""
    return html_content, plain_content


def build_submitter_acknowledgment_email(inquiry: dict[str, Any]) -> tuple[str, str]:
    """Build HTML and plain text confirmation for the submitter."""
    inq_id = html.escape(str(inquiry.get("id") or ""))
    name = html.escape(str(inquiry.get("name") or "Valued Trader"))
    category = html.escape(str(inquiry.get("category") or "General"))
    subject = html.escape(str(inquiry.get("subject") or ""))
    created_at = html.escape(str(inquiry.get("created_at") or ""))

    html_content = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background:#080c14; color:#e2e8f0; margin:0; padding:20px; }}
.card {{ background:#0f172a; border:1px solid #334155; border-radius:10px; max-width:640px; margin:0 auto; padding:24px; box-shadow:0 8px 30px rgba(0,0,0,0.5); }}
.badge {{ background:rgba(16,185,129,0.15); border:1px solid #10b981; color:#10b981; font-weight:800; font-size:11px; padding:3px 8px; border-radius:4px; text-transform:uppercase; }}
.header {{ border-bottom:1px solid #1e293b; padding-bottom:16px; margin-bottom:20px; }}
.ticket {{ background:#070d19; border:1px solid #38bdf8; border-radius:6px; padding:12px; margin:16px 0; text-align:center; }}
.ticket-num {{ font-size:18px; font-weight:800; font-family:"JetBrains Mono", monospace; color:#38bdf8; letter-spacing:0.05em; }}
.footer {{ margin-top:24px; padding-top:16px; border-top:1px solid #1e293b; font-size:11px; color:#64748b; line-height:1.5; }}
</style>
</head>
<body>
<div class="card">
    <div class="header">
        <span class="badge">CONFIRMATION OF RECEIPT</span>
        <h2 style="margin:10px 0 0 0; color:#ffffff; font-size:18px;">Thank You for Contacting OPB</h2>
        <div style="font-size:12px; color:#94a3b8; margin-top:4px;">Gaurav OPB &bull; Indian Capital Market Super-App</div>
    </div>
    <p style="font-size:14px; color:#cbd5e1; line-height:1.6;">Hello <strong>{name}</strong>,</p>
    <p style="font-size:14px; color:#cbd5e1; line-height:1.6;">
        Your inquiry regarding <strong>{subject}</strong> ({category}) has been securely received by our engineering and quantitative support team.
    </p>
    <div class="ticket">
        <div style="font-size:11px; color:#94a3b8; text-transform:uppercase; font-weight:700;">Reference Ticket ID</div>
        <div class="ticket-num">{inq_id}</div>
        <div style="font-size:11px; color:#64748b; margin-top:4px;">Submitted: {created_at}</div>
    </div>
    <p style="font-size:13px; color:#94a3b8; line-height:1.5;">
        Our team reviews all inquiries during market sessions and will respond to this email address within 1 business day.
    </p>
    <div class="footer">
        <strong>Security Notice:</strong> OPB will never request your broker passwords, TOTP codes, or trading credentials via email.<br>
        &copy; 2026 Gaurav OPB. All rights reserved. SEBI / Indian Financial Markets Disclosures Apply.
    </div>
</div>
</body>
</html>"""

    plain_content = f"""Thank You for Contacting Gaurav OPB

Hello {inquiry.get('name')},

Your inquiry regarding '{inquiry.get('subject')}' ({inquiry.get('category')}) has been securely received.

Reference Ticket ID: {inquiry.get('id')}
Submitted: {inquiry.get('created_at')}

Our support team reviews all inquiries and will respond within 1 business day.

Security Notice: OPB will never request your broker passwords, TOTP codes, or trading credentials via email.
"""
    return html_content, plain_content


def dispatch_inquiry_notifications(inquiry_data: dict[str, Any]) -> dict[str, bool]:
    """Execute non-blocking dispatch of both admin alert and submitter acknowledgment."""
    from core.storage.inquiry_store import get_inquiry_store

    store = get_inquiry_store()
    inq_id = str(inquiry_data.get("id") or "")
    submitter_email = str(inquiry_data.get("email") or "").strip()
    category = str(inquiry_data.get("category") or "Inquiry")
    subject = str(inquiry_data.get("subject") or "")

    _, _, _, _, _, configured_admins = _smtp_settings()
    admin_recipients = configured_admins or ["ai.auto.gaurav@gmail.com"]

    # 1. Admin Alert
    admin_html, admin_plain = build_admin_alert_email(inquiry_data)
    admin_subject = f"[OPB Inquiry] {category}: {subject} ({inq_id})"
    admin_ok = _send_email(admin_recipients, admin_subject, admin_html, admin_plain)

    # 2. Submitter Acknowledgment
    user_ok = False
    if submitter_email:
        user_html, user_plain = build_submitter_acknowledgment_email(inquiry_data)
        user_subject = f"Your OPB Inquiry has been received [Ticket: {inq_id}]"
        user_ok = _send_email([submitter_email], user_subject, user_html, user_plain)

    overall_status = "DISPATCHED" if (admin_ok and user_ok) else ("PARTIAL" if (admin_ok or user_ok) else "FAILED")
    error_msg = None if overall_status in ("DISPATCHED", "PARTIAL") else "SMTP delivery failed or disabled"

    store.update_notification_status(inq_id, overall_status, error_msg)
    _log.info("Inquiry %s notifications dispatched: admin=%s, submitter=%s -> %s", inq_id, admin_ok, user_ok, overall_status)

    return {"admin_sent": admin_ok, "submitter_sent": user_ok}


def dispatch_inquiry_notifications_background(inquiry_data: dict[str, Any]) -> None:
    """Launch notification dispatch in a background daemon thread."""
    t = threading.Thread(
        target=dispatch_inquiry_notifications,
        args=(inquiry_data,),
        daemon=True,
        name=f"InquiryNotify-{inquiry_data.get('id')}",
    )
    t.start()
