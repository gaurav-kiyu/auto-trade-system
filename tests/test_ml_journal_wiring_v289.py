from pathlib import Path


CONTAINER = Path("index_app/domains/trading/container.py")


def test_ml_adapter_receives_configured_training_journal():
    source = CONTAINER.read_text(encoding="utf-8")

    expected = """ml_model_service = MLModelAdapter(
        journal_path=str(
            cfg.get("ml_journal_path", "db/trade_journal.db")
        ),
        config=dict(cfg),
    )"""

    assert expected in source


def test_ml_adapter_is_registered_as_ml_model_port():
    source = CONTAINER.read_text(encoding="utf-8")

    assert "container.register_instance(MlModelPort, ml_model_service)" in source


def test_ml_training_journal_and_tracker_paths_remain_distinct():
    source = CONTAINER.read_text(encoding="utf-8")

    assert 'cfg.get("ml_journal_path", "db/trade_journal.db")' in source
    assert "config=dict(cfg)" in source
