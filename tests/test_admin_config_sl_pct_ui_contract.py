from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADMIN_CONFIG = ROOT / "templates" / "enterprise" / "admin_config.html"


def _read_admin_config():
    return ADMIN_CONFIG.read_text(encoding="utf-8")


def test_admin_config_sl_pct_uses_numeric_dynamic_input_contract():
    text = _read_admin_config()

    # Dynamic config inputs must carry the canonical key and runtime type.
    assert 'class="cfg-input"' in text
    assert 'data-key="${key}"' in text
    assert 'data-type="${typeof val ===' in text or 'data-type="${' in text

    # Numeric config values must be converted to Number before changeKey().
    assert 'e.target.dataset.type === \'number\'' in text
    assert 'val = Number(val)' in text
    assert 'changeKey(key, val)' in text


def test_admin_config_sl_pct_input_events_are_delegated():
    text = _read_admin_config()

    # The dynamic inputs are rendered after page load, therefore event
    # handling must be delegated rather than bound only to static inputs.
    assert "document.addEventListener('change', handleInputChange)" in text
    assert "document.addEventListener('input', handleInputChange)" in text

    # Only configuration inputs should enter the change-tracking path.
    assert "e.target.classList.contains('cfg-input')" in text


def test_admin_config_save_uses_flat_changed_keys_and_validate_apply_flow():
    text = _read_admin_config()

    # The Admin UI must submit the changed key/value map directly.
    assert "JSON.stringify(changedKeys)" in text

    # Both canonical Admin config endpoints must remain present.
    assert "/api/config/validate" in text
    assert "/api/config/apply" in text

    # A successful apply must reload the canonical config state.
    assert "loadConfig()" in text
