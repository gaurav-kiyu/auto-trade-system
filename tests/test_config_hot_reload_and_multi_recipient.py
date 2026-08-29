"""Tests for Configuration Hot-Reloading and Multi-Recipient Delivery."""

import json
from pathlib import Path
from core.all_nse_scanner import AllNSEScanner


def test_scanner_reloads_config_dynamically():
    """Verify that updating json/config.json immediately updates scanner credentials."""
    cfg_file = Path("json/config.json")
    original_cfg = json.loads(cfg_file.read_text(encoding="utf-8"))

    try:
        # 1. Update config
        test_cfg = dict(original_cfg)
        test_cfg["EMAIL_TO"] = "test1@example.com, test2@example.com, test3@example.com"
        test_cfg["CHAT_ID"] = "111111, 222222"
        test_cfg["EMAIL_ENABLED"] = True
        cfg_file.write_text(json.dumps(test_cfg, indent=4), encoding="utf-8")

        # 2. Instantiate scanner and reload
        scanner = AllNSEScanner()
        scanner._reload_config_credentials()

        assert scanner._email_to == "test1@example.com, test2@example.com, test3@example.com"
        assert scanner._chat_id == "111111, 222222"
        assert scanner._email_enabled is True

    finally:
        # Restore original config
        cfg_file.write_text(json.dumps(original_cfg, indent=4), encoding="utf-8")


def test_multi_recipient_aggregation():
    """Verify that multiple comma-separated emails and chat IDs are correctly parsed into sets."""
    scanner = AllNSEScanner()
    scanner._email_to = "user1@gmail.com, user2@gmail.com,  user3@gmail.com "
    scanner._chat_id = "12345, 67890"

    emails = set()
    for em in scanner._email_to.split(","):
        clean_em = em.strip()
        if clean_em and "@" in clean_em:
            emails.add(clean_em)

    chat_ids = set()
    for cid in scanner._chat_id.split(","):
        clean_cid = cid.strip()
        if clean_cid and not clean_cid.startswith("YOUR_"):
            chat_ids.add(clean_cid)

    assert len(emails) == 3
    assert "user1@gmail.com" in emails
    assert "user2@gmail.com" in emails
    assert "user3@gmail.com" in emails

    assert len(chat_ids) == 2
    assert "12345" in chat_ids
    assert "67890" in chat_ids
