"""Comprehensive verification suite for the OPB v2.59.4 Canonical Notification Design System.

Verifies:
1. Canonical 9-tier severity taxonomy (INFO, SUCCESS, WARNING, ERROR, CRITICAL,
   SIGNAL_MODERATE, SIGNAL_STRONG, SECURITY, ACTION_REQUIRED).
2. All 10 representative OPB notification families across Email, Telegram, Plain Text, and In-App.
3. Reference B dark institutional card shell (#080b10 / #0d121c / #131a29) and elimination
   of Reference A plain white unstyled HTML emails.
4. Strict HTML entity escaping in Email and Telegram HTML (<, >, &, ₹, %, URLs, long strings).
5. EmailNotificationAdapter._to_html, EmailAlerter, notify_new_registration, and
   enterprise_dashboard Notification.to_dict canonical integration.
6. Multi-theme CSS tokens (--notification-*) and unified showToast / OPBNotify in
   static/opb_design_system.css and static/theme_engine.js across all 5 themes.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.alert_router import EmailAlerter
from core.auth.registration_notifications import notify_new_registration
from core.enterprise_dashboard.models import Notification as DashboardNotification
from core.notifications.rich_signal_formatter import RichSignalFormatter
from core.ports.notification.notification_port import (
    Notification,
    NotificationChannel,
    NotificationPriority,
)
from infrastructure.adapters.notifications.email_adapter import EmailNotificationAdapter

ROOT = Path(__file__).resolve().parents[1]

CANONICAL_SEVERITIES = [
    "INFO",
    "SUCCESS",
    "WARNING",
    "ERROR",
    "CRITICAL",
    "SIGNAL_MODERATE",
    "SIGNAL_STRONG",
    "SECURITY",
    "ACTION_REQUIRED",
]


@pytest.mark.parametrize("severity", CANONICAL_SEVERITIES)
def test_all_nine_canonical_severities_render_across_all_channels(severity: str) -> None:
    """Every canonical severity must render valid Email HTML, Telegram HTML, Plain Text, and In-App payload."""
    payload = RichSignalFormatter.build_canonical_event_notification(
        title=f"Severity Verification — {severity}",
        summary=f"Verifying canonical presentation for severity {severity} with ₹1,25,000.50 (+4.25%).",
        notification_type="CANONICAL_AUDIT",
        severity=severity,
        key_values=[
            ("Severity Tier", severity),
            ("Reference Notional", "₹1,25,000.50"),
            ("Conviction Delta", "+4.25%"),
        ],
        primary_action={"label": "Open Cockpit", "url": "/"},
        secondary_action={"label": "Observability", "url": "/observability"},
        base_url="https://gaurav-cockpit.servegame.com",
    )

    assert payload["severity"] == severity
    assert payload["notification_id"].startswith("OPB-")

    # 1. Email HTML checks (Reference B institutional dark card shell)
    email_html = payload["email_html"]
    assert "🎯 OPB QUANTITATIVE ENGINE" in email_html
    assert "background-color:#080b10" in email_html
    assert "background-color:#0d121c" in email_html
    assert "background:#131a29" in email_html
    assert "font-variant-numeric:tabular-nums" in email_html
    assert "https://gaurav-cockpit.servegame.com/" in email_html
    assert "border='1'" not in email_html
    assert "#f8f9fa" not in email_html

    # 2. Telegram HTML checks
    tg_html = payload["telegram_html"]
    assert "🎯 <b>OPB QUANTITATIVE ENGINE</b>" in tg_html
    assert "━━━━━━━━━━━━━━━━━━━━━" in tg_html
    assert f"<b>Severity Verification — {severity}</b>" in tg_html
    assert "<code>₹1,25,000.50</code>" in tg_html
    assert 'href="https://gaurav-cockpit.servegame.com/"' in tg_html

    # 3. Plain text checks
    plain = payload["plain_text"]
    assert "OPB QUANTITATIVE ENGINE" in plain
    assert f"Severity Verification — {severity}" in plain
    assert "₹1,25,000.50" in plain

    # 4. In-App payload checks
    in_app = payload["in_app"]
    assert in_app["severity"] == severity
    assert in_app["notification_id"] == payload["notification_id"]
    assert in_app["accent_token"].startswith("var(--notification-")
    assert len(in_app["key_values"]) == 3


def test_ten_representative_notification_families_cross_channel_parity() -> None:
    """Verify all 10 representative OPB notification families (A through J) produce canonical multi-channel outputs."""
    base_url = "https://gaurav-cockpit.servegame.com"

    families = {
        "A1_registration_welcome": RichSignalFormatter.build_registration_welcome_notification(
            username="rishi",
            email="rishi@example.com",
            full_name="Rishi Kumar",
            role="viewer",
            created_by="self-register",
            base_url=base_url,
        ),
        "A2_registration_admin": RichSignalFormatter.build_registration_admin_notification(
            username="rishi",
            email="rishi@example.com",
            full_name="Rishi Kumar",
            role="viewer",
            created_by="self-register",
            base_url=base_url,
        ),
        "B_strong_signal": RichSignalFormatter.build_canonical_notification(
            {
                "symbol": "RPOWER",
                "company_name": "Reliance Power Ltd",
                "category": "SMALL_CAP_EQUITY",
                "direction": "BUY",
                "price": 24.92,
                "score": 90,
                "tier": "STRONG",
                "signal_id": "SIG-RPOWER-001",
            },
            base_url=base_url,
        ),
        "C_moderate_signal": RichSignalFormatter.build_canonical_notification(
            {
                "symbol": "NIFTY26SEP25000CE",
                "company_name": "NIFTY 50 Index Option",
                "category": "INDEX_OPTIONS",
                "direction": "CALL",
                "price": 185.50,
                "score": 82,
                "tier": "MODERATE",
                "signal_id": "SIG-NIFTY-002",
            },
            base_url=base_url,
        ),
        "D_security_alert": RichSignalFormatter.build_security_notification(
            event_title="Role Privilege Escalation Review — @rishi",
            summary="Operator @rishi role permissions were updated from VIEWER to TRADER.",
            username="rishi",
            actor="admin",
            ip_address="13.235.226.207",
            role_change="VIEWER -> TRADER",
            base_url=base_url,
        ),
        "E_password_reset": RichSignalFormatter.build_password_notification(
            username="rishi",
            email="rishi@example.com",
            event_subtype="PASSWORD_RESET_REQUESTED",
            reset_link="https://gaurav-cockpit.servegame.com/profile",
            ip_address="13.235.226.207",
            base_url=base_url,
        ),
        "F_paper_trade": RichSignalFormatter.build_paper_trade_notification(
            symbol="RPOWER",
            side="BUY",
            quantity=100,
            price=24.92,
            status="COMPLETED",
            order_id="PAPER-90210",
            base_url=base_url,
        ),
        "G_system_kill_switch": RichSignalFormatter.build_system_alert_notification(
            title="Emergency Kill-Switch Activated",
            summary="Global circuit breaker engaged due to volatility threshold breach.",
            severity="CRITICAL",
            subsystem="Kill-Switch Governance",
            metric_label="Circuit State",
            metric_value="HALTED (LOCKED)",
            base_url=base_url,
        ),
        "H_billing_upi": RichSignalFormatter.build_billing_notification(
            title="UPI Scanner Payment Verification Pending",
            summary="A new subscription settlement reference was submitted via OPB UPI Scanner.",
            username="rishi",
            plan_name="OPB Institutional Pro",
            amount_inr=4999.00,
            payment_reference="UPI-4289102938",
            base_url=base_url,
        ),
        "I_broker_disconnect": RichSignalFormatter.build_broker_notification(
            broker_name="AngelOne SmartAPI",
            status="DISCONNECTED",
            summary="WebSocket feed heartbeat timed out; automatic reconnect scheduled.",
            error_code="WS_HEARTBEAT_TIMEOUT",
            latency_ms=4820.5,
            base_url=base_url,
        ),
        "J_delivery_dlq": RichSignalFormatter.build_delivery_failure_notification(
            failed_channel="WEBHOOK",
            recipient="https://hooks.example.com/opb",
            error_reason="HTTP 503 Service Unavailable",
            retry_count=2,
            dlq_status="QUEUED_FOR_RETRY",
            original_notification_id="OPB-7F8A91B2",
            base_url=base_url,
        ),
    }

    for name, bundle in families.items():
        assert "subject" in bundle, f"{name} missing subject"
        assert "email_html" in bundle, f"{name} missing email_html"
        assert "telegram_html" in bundle, f"{name} missing telegram_html"
        assert "plain_text" in bundle, f"{name} missing plain_text"
        assert "in_app" in bundle, f"{name} missing in_app"
        assert "OPB QUANTITATIVE ENGINE" in bundle["email_html"].upper(), f"{name} email missing canonical brand header"
        assert "OPB QUANTITATIVE ENGINE" in bundle["telegram_html"].upper(), f"{name} telegram missing canonical brand header"
        assert "#080b10" in bundle["email_html"], f"{name} email missing canonical #080b10 dark canvas"
        assert "localhost" not in bundle["email_html"], f"{name} email leaked localhost URL"
        assert "127.0.0.1" not in bundle["email_html"], f"{name} email leaked 127.0.0.1 URL"


def test_special_characters_and_xss_payloads_escaped_across_email_and_telegram() -> None:
    """Verify <, >, &, ₹, %, quotes, and script/svg tags are safely escaped in Email and Telegram HTML."""
    malicious_title = "Alert <script>alert('xss')</script> & <b>tag</b>"
    malicious_summary = "User <svg onload=alert(1)> triggered 100% breach @ ₹45,120.75 & more"
    payload = RichSignalFormatter.build_canonical_event_notification(
        title=malicious_title,
        summary=malicious_summary,
        severity="SECURITY",
        key_values=[
            ("User <img src=x>", "rishi<svg onload=1> & co"),
            ("Amount ₹ / %", "₹99,999.99 (100% <limit>)"),
        ],
    )

    for channel_key in ("email_html", "telegram_html"):
        rendered = payload[channel_key]
        assert "<script>" not in rendered
        assert "<svg" not in rendered
        assert "<img" not in rendered
        assert "&lt;script&gt;" in rendered
        assert "&lt;svg" in rendered
        assert "₹99,999.99" in rendered


def test_registration_notifications_use_canonical_opb_design_for_user_and_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify notify_new_registration sends canonical Reference B dark emails to both user and admin."""
    sent_messages: list[tuple[list[str], str, str, str]] = []
    monkeypatch.setattr(
        "core.auth.registration_notifications._send",
        lambda to, subject, html_body, plain_body: sent_messages.append((to, subject, html_body, plain_body)) or True,
    )
    monkeypatch.setattr(
        "core.auth.registration_notifications._smtp_settings",
        lambda: ("smtp.gmail.com", 587, "bot@example.com", "secret", True, ["admin@example.com"]),
    )

    result = notify_new_registration(
        username="rishi",
        display_name="rishi",
        email="rishi@gmail.com",
        role="viewer",
        created_by="self-register",
    )

    assert result["user_email_sent"] is True
    assert result["admin_email_sent"] is True
    assert len(sent_messages) == 2

    user_to, user_subj, user_html, _ = sent_messages[0]
    admin_to, admin_subj, admin_html, _ = sent_messages[1]

    assert user_to == ["rishi@gmail.com"]
    assert "Welcome to OPB Super-Platform" in user_subj
    assert "🎯 OPB QUANTITATIVE ENGINE" in user_html
    assert "#080b10" in user_html
    assert "border='1'" not in user_html

    assert admin_to == ["admin@example.com"]
    assert "OPB: New User Registration — rishi" in admin_subj
    assert "🎯 OPB QUANTITATIVE ENGINE" in admin_html
    assert "PENDING APPROVAL" in admin_html
    assert "Open User Controls" in admin_html
    assert "/admin/users" in admin_html
    assert "border='1'" not in admin_html


def test_email_notification_adapter_to_html_uses_canonical_opb_shell() -> None:
    """Verify EmailNotificationAdapter._to_html wraps plain notifications in the canonical OPB dark card shell."""
    adapter = EmailNotificationAdapter(enabled=False)
    notif = Notification(
        channel=NotificationChannel.EMAIL,
        recipient="operator@example.com",
        message="Broker WebSocket reconnected after 1.2s backoff.",
        priority=NotificationPriority.HIGH,
        metadata={
            "title": "Broker Feed Reconnected",
            "category_label": "BROKER CONNECTIVITY",
            "broker": "Zerodha Kite",
            "latency_ms": 42.5,
        },
    )
    rendered_html = adapter._to_html(notif.message, notif)
    assert "🎯 OPB QUANTITATIVE ENGINE" in rendered_html
    assert "Broker Feed Reconnected" in rendered_html
    assert "Zerodha Kite" in rendered_html
    assert "#080b10" in rendered_html
    assert "OPB Trading Bot" not in rendered_html


def test_email_alerter_attaches_canonical_html_and_plain_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify EmailAlerter in core/alert_router.py sends multipart/alternative with canonical OPB HTML."""
    captured_Raw: list[str] = []

    class DummySMTP:
        def __init__(self, *args, **kwargs):
            pass

        def starttls(self):
            pass

        def login(self, u, p):
            pass

        def sendmail(self, from_addr, to_addrs, msg_str):
            captured_Raw.append(msg_str)

        def quit(self):
            pass

    monkeypatch.setattr("core.alert_router.smtplib.SMTP", DummySMTP)
    alerter = EmailAlerter(
        {
            "EMAIL_ENABLED": True,
            "EMAIL_USER": "alerts@example.com",
            "EMAIL_PASS": "pass123",
            "EMAIL_TO": "admin@example.com",
        }
    )
    import email as email_pkg

    ok = alerter.send_alert("[CRITICAL] Kill Switch Triggered", "Daily drawdown limit reached.")
    assert ok is True
    assert len(captured_Raw) == 1
    parsed = email_pkg.message_from_string(captured_Raw[0])
    decoded_parts = [
        part.get_payload(decode=True).decode("utf-8", errors="ignore")
        for part in parsed.walk()
        if part.get_payload(decode=True) is not None
    ]
    combined = "\n".join(decoded_parts)
    assert "OPB QUANTITATIVE ENGINE" in combined
    assert "Daily drawdown limit reached." in combined


def test_dashboard_notification_to_dict_includes_canonical_attributes() -> None:
    """Verify enterprise_dashboard Notification.to_dict() includes canonical presentation fields."""
    n = DashboardNotification(
        message="Paper trade PAPER-101 queued for NIFTY",
        severity="SUCCESS",
        category="trading",
        source="paper_engine",
        details={"symbol": "NIFTY", "qty": 50},
    )
    d = n.to_dict()
    assert len(d["id"]) == 12
    assert d["notification_id"].startswith("OPB-")
    assert d["canonical_severity"] == "SUCCESS"
    assert d["severity_badge"] == "SUCCESS"
    assert d["accent_token"] == "var(--notification-success)"
    assert any(kv["label"] == "Symbol" and kv["value"] == "NIFTY" for kv in d["key_values"])


def test_css_and_theme_engine_define_canonical_notification_tokens_for_all_five_themes() -> None:
    """Verify static/opb_design_system.css and static/theme_engine.js define all --notification-* tokens across all 5 themes."""
    css_text = (ROOT / "static" / "opb_design_system.css").read_text(encoding="utf-8")
    js_text = (ROOT / "static" / "theme_engine.js").read_text(encoding="utf-8")

    required_tokens = [
        "--notification-success",
        "--notification-warning",
        "--notification-danger",
        "--notification-info",
        "--notification-neutral",
        "--notification-signal",
        "--notification-border",
        "--notification-surface",
        "--notification-muted-text",
    ]
    themes = ["dark-cyber", "dracula-purple", "ivory-gold", "midnight-slate", "emerald-matrix"]

    for token in required_tokens:
        assert token in css_text, f"Missing {token} in static/opb_design_system.css"
        assert token in js_text, f"Missing {token} in static/theme_engine.js"

    for theme in themes:
        assert f'[data-theme="{theme}"]' in css_text, f"Missing theme block {theme} in opb_design_system.css"
        assert f"'{theme}'" in js_text, f"Missing theme {theme} in theme_engine.js"

    assert "renderCanonicalNotificationCard" in js_text
    assert "window.OPBNotify" in js_text


def test_public_url_reconciliation_across_all_notification_families() -> None:
    """Verify all notification builders resolve external action URLs to https://gaurav-cockpit.servegame.com and never leak localhost/127.0.0.1/nip.io."""
    sig_pkg = RichSignalFormatter.build_canonical_notification(
        {
            "symbol": "NIFTY24AUG24500CE",
            "category": "INDEX_OPTIONS",
            "direction": "CALL",
            "price": 142.50,
            "score": 91,
            "tier": "STRONG",
            "signal_id": "SIG-URL-001",
        }
    )
    for field in ("email_html", "telegram_html"):
        content = sig_pkg[field]
        assert "https://gaurav-cockpit.servegame.com/my-signals" in content
        assert "localhost" not in content
        assert "127.0.0.1" not in content
        assert "nip.io" not in content

    assert sig_pkg["in_app"]["primary_action"]["url"].startswith(
        "https://gaurav-cockpit.servegame.com/my-signals"
    )

    # Verify event notification sanitizes even if a caller passes a localhost or nip.io URL
    ev_pkg = RichSignalFormatter.build_canonical_event_notification(
        title="Loopback Sanitization Check",
        summary="Verifying external action links resolve to the canonical public domain.",
        notification_type="SYSTEM_ALERT",
        severity="WARNING",
        primary_action={"label": "Open Admin", "url": "http://localhost:8000/admin/users?tab=pending"},
        secondary_action={"label": "Legacy Link", "url": "https://13.235.226.207.nip.io/admin/signals"},
    )
    assert ev_pkg["primary_action"]["url"] == "https://gaurav-cockpit.servegame.com/admin/users?tab=pending"
    assert ev_pkg["secondary_action"]["url"] == "https://gaurav-cockpit.servegame.com/admin/signals"
    assert "localhost" not in ev_pkg["email_html"]
    assert "nip.io" not in ev_pkg["email_html"]


def test_admin_signals_and_report_filters_have_zero_hardcoded_dark_filter_surfaces() -> None:
    """Verify /admin/signals and report_filters.css use canonical OPB theme variables instead of hardcoded dark hex backgrounds."""
    admin_sig_html = (ROOT / "templates" / "enterprise" / "admin_signals.html").read_text(encoding="utf-8")
    user_sig_html = (ROOT / "templates" / "enterprise" / "user_signals.html").read_text(encoding="utf-8")
    report_css = (ROOT / "static" / "report_filters.css").read_text(encoding="utf-8")

    forbidden_dark_hexes = ["#0f1523", "#131a29", "#0b1220", "#111827", "#0d121c"]
    for hex_code in forbidden_dark_hexes:
        assert hex_code not in admin_sig_html.lower(), f"Hardcoded dark hex {hex_code} found in admin_signals.html"
        assert hex_code not in user_sig_html.lower(), f"Hardcoded dark hex {hex_code} found in user_signals.html"
        assert hex_code not in report_css.lower(), f"Hardcoded dark hex {hex_code} found in report_filters.css"

    assert "var(--bg-card" in admin_sig_html
    assert "var(--input-bg" in admin_sig_html
    assert "var(--btn-primary-text" in admin_sig_html


def test_my_signals_template_contains_canonical_period_controls_and_four_outcome_metrics() -> None:
    """Verify /my-signals template has Daily/Weekly/Monthly/Yearly/All Time period buttons, Category filter, and 4 outcome metrics."""
    user_sig_html = (ROOT / "templates" / "enterprise" / "user_signals.html").read_text(encoding="utf-8")

    for period in ("daily", "weekly", "monthly", "yearly", "all"):
        assert f'data-period="{period}"' in user_sig_html, f"Missing period button {period} in user_signals.html"

    assert 'id="filterCategory"' in user_sig_html
    assert "Total Received:" in user_sig_html
    assert "Target 1 Hit:" in user_sig_html
    assert "Target 2 Hit:" in user_sig_html
    assert "Stop Loss Hit:" in user_sig_html
    assert 'id="totalCount"' in user_sig_html
    assert 'id="metricT1Hit"' in user_sig_html
    assert 'id="metricT2Hit"' in user_sig_html
    assert 'id="metricSlHit"' in user_sig_html


def test_signal_tracker_get_user_received_signals_period_filters_and_outcome_metrics(tmp_path: Path) -> None:
    """Verify SignalTracker.get_user_received_signals accurately computes period filters, deduplication, and T1/T2/SL metrics."""
    from core.datetime_ist import now_ist
    from core.signals.signal_tracker import SignalTracker

    db_file = tmp_path / "test_user_signals.db"
    tracker = SignalTracker(db_path=db_file)
    now = now_ist()
    today_str = now.date().isoformat()
    week_str = f"{now.year}-W{now.isocalendar()[1]}"
    month_str = f"{now.year}-{now.month:02d}"
    year_str = str(now.year)

    conn = tracker._get_conn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM user_deliveries")
        cur.execute("DELETE FROM system_signals")

        # Insert 5 canonical system signals: T1_HIT, T2_HIT, SL_HIT, AMBIGUOUS, ACTIVE
        signals_data = [
            ("SIG-U1", "NIFTY24AUG24500CE", "INDEX_OPTIONS", "CALL", 90, "STRONG", 100.0, 90.0, 120.0, 140.0, 122.0, "TARGET_1_HIT", 22.0, "T1", "EXACT_OBSERVATION", today_str, week_str, month_str, year_str),
            ("SIG-U2", "BANKNIFTY24AUG52000CE", "INDEX_OPTIONS", "CALL", 92, "STRONG", 200.0, 180.0, 240.0, 280.0, 285.0, "TARGET_2_HIT", 42.5, "T1", "EXACT_OBSERVATION", today_str, week_str, month_str, year_str),
            ("SIG-U3", "RELIANCE", "LARGE_CAP_EQUITY", "BUY", 84, "STRONG", 3000.0, 2910.0, 3120.0, 3240.0, 2905.0, "SL_HIT", -3.17, "SL", "EXACT_OBSERVATION", today_str, week_str, month_str, year_str),
            ("SIG-U4", "TCS", "LARGE_CAP_EQUITY", "BUY", 81, "STRONG", 4000.0, 3900.0, 4150.0, 4300.0, 4010.0, "AMBIGUOUS", 0.0, "AMBIGUOUS_SAME_BAR", "AMBIGUOUS", today_str, week_str, month_str, year_str),
            ("SIG-U5", "GOLDM", "COMMODITIES", "BUY", 78, "MODERATE", 72000.0, 71000.0, 73500.0, 75000.0, 72100.0, "ACTIVE", 0.14, "", "UNKNOWN", "2025-01-15", "2025-W3", "2025-01", "2025"),
        ]
        for s in signals_data:
            cur.execute(
                """INSERT INTO system_signals
                   (signal_id, symbol, company_name, category, direction, score, tier,
                    entry_price, stop_loss, target_1, target_2, current_price, status, pnl_pct,
                    first_touch, outcome_confidence, timestamp, created_date, created_week, created_month, created_year, raw_data)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}')""",
                (s[0], s[1], s[1], s[2], s[3], s[4], s[5], s[6], s[7], s[8], s[9], s[10], s[11], s[12], s[13], s[14], f"{s[15]}T10:00:00+05:30", s[15], s[16], s[17], s[18]),
            )
            # Insert user delivery (and insert a duplicate delivery for SIG-U1 to verify deduplication!)
            cur.execute(
                """INSERT INTO user_deliveries
                   (delivery_id, signal_id, username, symbol, category, direction, score, tier,
                    entry_price, stop_loss, target_1, target_2, current_price, status, pnl_pct,
                    timestamp, delivery_date, delivery_week, delivery_month, delivery_year, channels_sent)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (f"DEL-{s[0]}-1", s[0], "trader1", s[1], s[2], s[3], s[4], s[5], s[6], s[7], s[8], s[9], s[10], "ACTIVE", 0.0, f"{s[15]}T10:00:00+05:30", s[15], s[16], s[17], s[18], "Telegram, Email"),
            )
        # Duplicate delivery row for SIG-U1 (e.g. Email + Telegram)
        cur.execute(
            """INSERT INTO user_deliveries
               (delivery_id, signal_id, username, symbol, category, direction, score, tier,
                entry_price, stop_loss, target_1, target_2, current_price, status, pnl_pct,
                timestamp, delivery_date, delivery_week, delivery_month, delivery_year, channels_sent)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("DEL-SIG-U1-DUP", "SIG-U1", "trader1", "NIFTY24AUG24500CE", "INDEX_OPTIONS", "CALL", 90, "STRONG", 100.0, 90.0, 120.0, 140.0, 100.0, "ACTIVE", 0.0, f"{today_str}T10:00:05+05:30", today_str, week_str, month_str, year_str, "In-App"),
        )
        conn.commit()
    finally:
        conn.close()

    # 1. All Time: should have 5 deduplicated signals (1 T1, 1 T2, 1 SL, 1 AMBIGUOUS quarantined, 1 ACTIVE)
    res_all = tracker.get_user_received_signals("trader1", period="all")
    assert res_all["total_received"] == 5
    assert res_all["target_1_hit"] == 1
    assert res_all["target_2_hit"] == 1
    assert res_all["stop_loss_hit"] == 1
    assert res_all["ambiguous_count"] == 1
    assert res_all["active_count"] == 1

    # 2. Daily / Weekly / Monthly / Yearly: should have 4 signals from today/this year (excluding 2025 signal SIG-U5)
    for p in ("daily", "weekly", "monthly", "yearly"):
        res_p = tracker.get_user_received_signals("trader1", period=p)
        assert res_p["total_received"] == 4, f"Period {p} expected 4 signals"
        assert res_p["target_1_hit"] == 1
        assert res_p["target_2_hit"] == 1
        assert res_p["stop_loss_hit"] == 1
        assert res_p["ambiguous_count"] == 1

    # 3. Category filter: INDEX_OPTIONS should have 2 signals (1 T1, 1 T2, 0 SL)
    res_opt = tracker.get_user_received_signals("trader1", period="daily", category="INDEX_OPTIONS")
    assert res_opt["total_received"] == 2
    assert res_opt["target_1_hit"] == 1
    assert res_opt["target_2_hit"] == 1
    assert res_opt["stop_loss_hit"] == 0

    # 4. Empty state filter: CURRENCIES should have 0 signals and 0 metrics
    res_empty = tracker.get_user_received_signals("trader1", period="daily", category="CURRENCIES")
    assert res_empty["total_received"] == 0
    assert res_empty["target_1_hit"] == 0
    assert res_empty["target_2_hit"] == 0
    assert res_empty["stop_loss_hit"] == 0
    assert res_empty["signals"] == []


def test_notification_formatter_preserves_canonical_signal_tier_semantics() -> None:
    """Verify signal generator score -> canonical tier/severity -> RichSignalFormatter -> Email/Telegram/In-App are semantically identical."""
    from core.signal_utils import classify_strength
    from core.tier_engine import TIER_MODERATE_MIN, TIER_STRONG_MIN, TIER_WEAK_MIN, classify_tier

    assert TIER_STRONG_MIN == 80
    assert TIER_MODERATE_MIN == 70
    assert TIER_WEAK_MIN == 60

    # Case 1: Score 82 without explicit tier must classify as STRONG (not MODERATE from any legacy >=85 rule)
    for score, expected_tier, expected_sev in (
        (80, "STRONG", "SIGNAL_STRONG"),
        (82, "STRONG", "SIGNAL_STRONG"),
        (91, "STRONG", "SIGNAL_STRONG"),
        (70, "MODERATE", "SIGNAL_MODERATE"),
        (75, "MODERATE", "SIGNAL_MODERATE"),
        (79, "MODERATE", "SIGNAL_MODERATE"),
        (65, "WEAK", "INFO"),
    ):
        assert classify_tier(score) == expected_tier
        assert classify_strength(score) == expected_tier

        pkg = RichSignalFormatter.build_canonical_notification(
            {
                "symbol": "RELIANCE",
                "category": "LARGE_CAP_EQUITY",
                "direction": "BUY",
                "price": 2950.0,
                "score": score,
                "signal_id": f"SIG-TIER-{score}",
            }
        )
        assert pkg["metadata"]["tier"] == expected_tier
        assert pkg["severity"] == expected_sev
        assert pkg["in_app"]["severity"] == expected_sev
        assert pkg["in_app"]["status"] == f"{expected_tier} BUY"
        assert f"{score}/100 ({expected_tier})" in pkg["telegram_html"]
        assert f"{score}/100 — {expected_tier.title()}" in pkg["email_html"]
        assert f"{expected_tier} BUY SIGNAL" in pkg["email_html"]
        assert f"as a {expected_tier.lower()} bullish setup" in pkg["email_html"]
        assert f"Strength : {expected_tier} (Score: {score}/100)" in pkg["plain_text"]

    # Case 2: Explicit upstream tier / strength is preserved verbatim across all channels
    pkg_explicit = RichSignalFormatter.build_canonical_notification(
        {
            "symbol": "TCS",
            "category": "LARGE_CAP_EQUITY",
            "direction": "BUY",
            "price": 4100.0,
            "score": 81,
            "tier": "MODERATE",  # e.g. upstream category/adaptive tier override
            "signal_id": "SIG-EXPLICIT-MOD",
        }
    )
    assert pkg_explicit["metadata"]["tier"] == "MODERATE"
    assert pkg_explicit["severity"] == "SIGNAL_MODERATE"
    assert pkg_explicit["in_app"]["severity"] == "SIGNAL_MODERATE"
    assert "MODERATE BUY SIGNAL" in pkg_explicit["email_html"]
    assert "81/100 (MODERATE)" in pkg_explicit["telegram_html"]

