from pathlib import Path
import re


def _dashboard():
    return Path("templates/enterprise/dashboard.html").read_text(encoding="utf-8")


def test_dashboard_refresh_controls_have_unique_ids_and_shared_action():
    html = _dashboard()
    ids = re.findall(r'\bid=["\']([^"\']+)["\']', html)
    assert ids.count("dashboardRefreshBtnTop") == 1
    assert ids.count("dashboardRefreshBtnSubbar") == 1
    assert "id=\"dashboardRefreshBtn\"" not in html
    assert len(re.findall(r'data-action=\"refresh-dashboard\"(?=\s)', html)) == 2


def test_dashboard_refresh_action_is_bound_to_click_handler():
    html = _dashboard()
    marker = "document.querySelectorAll('[data-action=\"refresh-dashboard\"]').forEach"
    assert marker in html
    assert "btn.addEventListener('click'" in html
    assert "await loadDashboardData();" in html
