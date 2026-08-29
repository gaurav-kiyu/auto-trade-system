from pathlib import Path

REPORT_PAGES = [
    "intelligence.html","user_signals.html","trade_copier.html","performance.html",
    "metrics_trend.html","strategy_sandbox.html","capacity.html","system_health.html",
    "data_quality.html","reports.html","observability.html","admin_signals.html",
    "trade_journal.html","governance.html",
]

def test_report_pages_load_common_filter_asset():
    root = Path(__file__).resolve().parents[1]
    for name in REPORT_PAGES:
        p = root / "templates" / "enterprise" / name
        text = p.read_text(encoding="utf-8")
        assert "/static/report_filters.js" in text
        assert "/static/report_filters.css" in text

def test_report_filter_asset_exists():
    root = Path(__file__).resolve().parents[1]
    assert (root / "static" / "report_filters.js").is_file()
    assert (root / "static" / "report_filters.css").is_file()
