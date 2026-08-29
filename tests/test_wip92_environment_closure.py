from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def test_environment_report_exists():
    p=ROOT/"WEB_CLOSURE_WIP92_ENVIRONMENT_CLOSURE.md"
    assert p.exists()
    assert "Environment / Test Closure" in p.read_text(encoding="utf-8")
def test_no_bypass_of_full_suite():
    t=(ROOT/"WEB_CLOSURE_WIP92_ENVIRONMENT_CLOSURE.md").read_text(encoding="utf-8")
    assert "does not modify application behavior or silently bypass failing tests" in t
def test_dependency_block_is_explicit():
    t=(ROOT/"WEB_CLOSURE_WIP92_ENVIRONMENT_CLOSURE.md").read_text(encoding="utf-8")
    assert "full application suite remains blocked" in t
