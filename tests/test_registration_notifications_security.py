from core.auth.registration_notifications import notify_new_registration


def test_registration_email_html_escapes_user_controlled_fields(monkeypatch):
    captured = []
    monkeypatch.setattr(
        "core.auth.registration_notifications._send",
        lambda to, subject, html, plain: captured.append((html, plain)) or True,
    )
    result = notify_new_registration(
        username="user<svg onload=alert(1)>",
        display_name="<b>Injected</b>",
        email="a@example.com",
        role="viewer",
        created_by="self-register",
    )
    assert result["user_email_sent"] is True
    assert captured
    html_body = captured[0][0]
    assert "<svg" not in html_body
    assert "<b>Injected</b>" not in html_body
    assert "&lt;svg" in html_body
    assert "&lt;b&gt;Injected&lt;/b&gt;" in html_body
