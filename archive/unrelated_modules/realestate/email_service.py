"""Email Notification Service — transactional emails for the real estate platform.

Provides:
  - SMTP-based email sending with HTML templates
  - Transactional emails: enquiry notification, lead update, payment receipt,
    agreement signed, auction won, property match
  - Configurable SMTP settings via environment variables
  - Graceful fallback to logging when SMTP is not configured

Environment variables:
  - SMTP_HOST: SMTP server hostname
  - SMTP_PORT: SMTP port (default: 587)
  - SMTP_USER: SMTP username
  - SMTP_PASSWORD: SMTP password
  - SMTP_FROM: From email address
  - SMTP_USE_TLS: Enable TLS (default: True)
  - EMAIL_FROM_NAME: From name (default: "RealEstate India")
"""

from __future__ import annotations

import logging
import os
import smtplib
import time
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

_log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════════

SMTP_CONFIG = {
    "host": os.environ.get("SMTP_HOST", ""),
    "port": int(os.environ.get("SMTP_PORT", "587")),
    "user": os.environ.get("SMTP_USER", ""),
    "password": os.environ.get("SMTP_PASSWORD", ""),
    "from_email": os.environ.get("SMTP_FROM", "noreply@realestate.in"),
    "from_name": os.environ.get("EMAIL_FROM_NAME", "RealEstate India"),
    "use_tls": os.environ.get("SMTP_USE_TLS", "True").lower() in ("true", "1", "yes"),
}


def is_smtp_configured() -> bool:
    """Check if SMTP is configured for sending emails."""
    return bool(SMTP_CONFIG["host"] and SMTP_CONFIG["user"] and SMTP_CONFIG["password"])


# ═══════════════════════════════════════════════════════════════════════════════
# Email Templates
# ═══════════════════════════════════════════════════════════════════════════════

BASE_HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {{ font-family: -apple-system, 'Segoe UI', Roboto, sans-serif; background: #f8fafc; margin: 0; padding: 0; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background: linear-gradient(135deg, #0a0f1a, #1a1f3e); padding: 24px; text-align: center; border-radius: 12px 12px 0 0; }}
        .header h1 {{ color: #60a5fa; margin: 0; font-size: 20px; }}
        .body {{ background: white; padding: 24px; border-radius: 0 0 12px 12px; }}
        .body p {{ color: #334155; line-height: 1.6; margin: 0 0 12px; }}
        .button {{ display: inline-block; background: #3b82f6; color: white; padding: 12px 24px; border-radius: 8px; text-decoration: none; font-weight: 600; }}
        .footer {{ text-align: center; padding: 16px; color: #94a3b8; font-size: 12px; }}
        .details {{ background: #f1f5f9; border-radius: 8px; padding: 16px; margin: 16px 0; }}
        .details dt {{ color: #64748b; font-size: 12px; text-transform: uppercase; }}
        .details dd {{ color: #1e293b; font-weight: 600; margin: 0 0 8px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🏠 RealEstate India</h1>
        </div>
        <div class="body">
            {content}
        </div>
        <div class="footer">
            <p>RealEstate India Platform — Find Your Dream Home</p>
            <p>This is an automated message. Please do not reply directly.</p>
        </div>
    </div>
</body>
</html>"""


# ═══════════════════════════════════════════════════════════════════════════════
# Email Service
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class EmailRecord:
    """Record of a sent (or attempted) email."""
    to: str = ""
    subject: str = ""
    template: str = ""
    sent_at: float = 0.0
    success: bool = False
    error: str = ""


class EmailService:
    """Transactional email service for the real estate platform.

    Features:
      - SMTP delivery with HTML templates
      - In-memory sent log for testing
      - Graceful fallback to logging
      - Pre-built templates for common scenarios
    """

    def __init__(self) -> None:
        self._sent_emails: list[EmailRecord] = []

    # ── Core Send Method ──────────────────────────────────────────────────

    def send_email(
        self,
        to: str,
        subject: str,
        html_content: str,
    ) -> EmailRecord:
        """Send an HTML email.

        Falls back to logging if SMTP is not configured.
        """
        record = EmailRecord(
            to=to,
            subject=subject,
            template="custom",
            sent_at=time.time(),
        )

        if not to:
            record.error = "No recipient email address"
            record.success = False
            self._sent_emails.append(record)
            _log.warning("[EMAIL] No recipient — skipped")
            return record

        try:
            full_html = BASE_HTML_TEMPLATE.format(content=html_content)

            if is_smtp_configured():
                self._send_via_smtp(to, subject, full_html)
                record.success = True
                _log.info("[EMAIL] Sent to %s: %s", to, subject)
            else:
                _log.info("[EMAIL] (Log only) To: %s | Subject: %s", to, subject)

            record.success = True

        except Exception as e:
            record.error = str(e)
            record.success = False
            _log.error("[EMAIL] Failed to send to %s: %s", to, e)

        self._sent_emails.append(record)
        return record

    def _send_via_smtp(self, to: str, subject: str, html: str) -> None:
        """Send email via SMTP."""
        msg = MIMEMultipart("alternative")
        msg["From"] = f"{SMTP_CONFIG['from_name']} <{SMTP_CONFIG['from_email']}>"
        msg["To"] = to
        msg["Subject"] = subject
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP(SMTP_CONFIG["host"], SMTP_CONFIG["port"]) as server:
            if SMTP_CONFIG["use_tls"]:
                server.starttls()
            if SMTP_CONFIG["user"]:
                server.login(SMTP_CONFIG["user"], SMTP_CONFIG["password"])
            server.send_message(msg)

    # ── Transactional Email Templates ─────────────────────────────────────

    def send_enquiry_notification(
        self,
        owner_email: str,
        property_title: str,
        enquirer_name: str,
        enquirer_phone: str,
        enquirer_message: str,
        property_url: str = "",
    ) -> EmailRecord:
        """Notify property owner about a new enquiry."""
        button_html = f'<p style="text-align:center;"><a href="{property_url}" class="button">View Property</a></p>' if property_url else ""
        content = f"""
            <h2>New Enquiry Received! 📩</h2>
            <p>Someone is interested in your property <strong>"{property_title}"</strong>.</p>
            <dl class="details">
                <dt>From</dt>
                <dd>{enquirer_name}</dd>
                <dt>Phone</dt>
                <dd>{enquirer_phone}</dd>
                <dt>Message</dt>
                <dd>{enquirer_message}</dd>
            </dl>
            {button_html}
        """
        return self.send_email(owner_email, f"New Enquiry: {property_title}", content)

    def send_lead_update(
        self,
        broker_email: str,
        lead_name: str,
        property_title: str,
        new_status: str,
        leads_url: str = "",
    ) -> EmailRecord:
        """Notify broker about lead status change."""
        content = f"""
            <h2>Lead Status Updated 🔄</h2>
            <p>Lead <strong>{lead_name}</strong> has moved to <strong>"{new_status}"</strong> for property "{property_title}".</p>
            <p style="text-align:center;">
                <a href="{leads_url}" class="button">View Leads</a>
            </p>
        """
        return self.send_email(broker_email, f"Lead Updated: {lead_name} → {new_status}", content)

    def send_payment_receipt(
        self,
        user_email: str,
        user_name: str,
        amount: float,
        purpose: str,
        payment_method: str,
        transaction_id: str,
    ) -> EmailRecord:
        """Send payment receipt."""
        content = f"""
            <h2>Payment Receipt ✅</h2>
            <p>Thank you for your payment, <strong>{user_name}</strong>.</p>
            <dl class="details">
                <dt>Amount</dt>
                <dd>₹{amount:,.2f}</dd>
                <dt>Purpose</dt>
                <dd>{purpose}</dd>
                <dt>Payment Method</dt>
                <dd>{payment_method}</dd>
                <dt>Transaction ID</dt>
                <dd>{transaction_id}</dd>
            </dl>
        """
        return self.send_email(user_email, f"Payment Receipt — ₹{amount:,.0f}", content)

    def send_agreement_signed(
        self,
        user_email: str,
        property_title: str,
        agreement_id: str,
    ) -> EmailRecord:
        """Notify user about e-signed agreement."""
        content = f"""
            <h2>Agreement Signed 📜✅</h2>
            <p>The rent agreement for <strong>"{property_title}"</strong> has been successfully e-signed.</p>
            <dl class="details">
                <dt>Agreement ID</dt>
                <dd>{agreement_id}</dd>
            </dl>
        """
        return self.send_email(user_email, "Agreement Signed — RealEstate India", content)

    def send_auction_won(
        self,
        user_email: str,
        user_name: str,
        property_title: str,
        amount: float,
    ) -> EmailRecord:
        """Notify user about winning an auction."""
        content = f"""
            <h2>🎉 Congratulations! You Won the Auction!</h2>
            <p>Dear <strong>{user_name}</strong>,</p>
            <p>You won the auction for <strong>"{property_title}"</strong> at ₹{amount:,.0f}.</p>
            <p>Please complete the payment within 24 hours to secure your property.</p>
        """
        return self.send_email(user_email, "🎉 Auction Won! — RealEstate India", content)

    def send_property_match_alert(
        self,
        user_email: str,
        user_name: str,
        property_title: str,
        property_price: float,
        property_city: str,
        property_url: str,
    ) -> EmailRecord:
        """Alert user about a new property matching their saved search."""
        content = f"""
            <h2>New Property Match 🔍</h2>
            <p>Hi <strong>{user_name}</strong>, a new property matching your saved search is available.</p>
            <dl class="details">
                <dt>Property</dt>
                <dd>{property_title}</dd>
                <dt>Price</dt>
                <dd>₹{property_price:,.0f}</dd>
                <dt>Location</dt>
                <dd>{property_city}</dd>
            </dl>
            <p style="text-align:center;">
                <a href="{property_url}" class="button">View Property</a>
            </p>
        """
        return self.send_email(user_email, f"New Property Match: {property_title}", content)

    # ── History & Stats ───────────────────────────────────────────────────

    def get_sent_emails(self, limit: int = 50) -> list[EmailRecord]:
        """Get recently sent emails (newest first)."""
        return sorted(self._sent_emails, key=lambda r: r.sent_at, reverse=True)[:limit]

    def get_stats(self) -> dict[str, Any]:
        """Get email service statistics."""
        total = len(self._sent_emails)
        successful = sum(1 for r in self._sent_emails if r.success)
        failed = total - successful
        return {
            "total_sent": total,
            "successful": successful,
            "failed": failed,
            "smtp_configured": is_smtp_configured(),
            "success_rate": round(successful / total * 100, 1) if total > 0 else 0.0,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════════════════

_email_service_instance: EmailService | None = None


def get_email_service() -> EmailService:
    """Get the global email service singleton."""
    global _email_service_instance
    if _email_service_instance is None:
        _email_service_instance = EmailService()
    return _email_service_instance
