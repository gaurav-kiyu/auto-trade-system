import pathlib

from core.config_audit_log import append_soft_reload_audit_diff, format_config_audit_log_line


def test_format_config_audit_log_line_shape():
    line = format_config_audit_log_line("2026-04-19T10:00:00", "SCAN_INTERVAL", 60, 45)
    assert line == "2026-04-19T10:00:00 | SCAN_INTERVAL | 60 → 45\n"


def test_append_soft_reload_audit_diff(tmp_path: pathlib.Path):
    p = tmp_path / "config_audit.log"
    p.write_text("header\n", encoding="utf-8")
    tick = iter(["t1", "t2"]).__next__

    append_soft_reload_audit_diff(
        p,
        (
            {"key": "A", "old": 1, "new": 2},
            {"key": "B", "old": "x", "new": "y"},
        ),
        now_iso=tick,
    )
    text = p.read_text(encoding="utf-8")
    assert text == (
        "header\n"
        "t1 | A | 1 → 2\n"
        "t2 | B | x → y\n"
    )
