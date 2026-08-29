"""Regression contracts for the read/write split on Admin Signals."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTES = ROOT / "core" / "auth" / "routes.py"
TEMPLATE = ROOT / "templates" / "enterprise" / "admin_signals.html"


def test_signal_analytics_is_readable_by_logs_or_user_manager():
    text = ROUTES.read_text(encoding="utf-8")
    assert 'view_signal_analytics = auth_deps.require_any_permission("manage_users", "view_logs")' in text
    assert 'admin: AuthUser = Depends(view_signal_analytics)' in text


def test_order_placed_remains_write_controlled():
    text = ROUTES.read_text(encoding="utf-8")
    start = text.index('@router.post("/signals/{signal_id}/mark-order-placed")')
    block = text[start:start + 900]
    assert 'Depends(manage_users)' in block


def test_read_only_signal_viewers_do_not_get_write_checkbox():
    text = TEMPLATE.read_text(encoding="utf-8")
    assert '{% if can_manage_users %}' in text
    assert "orderPlacedCheckbox" in text
    assert "View only" in text
