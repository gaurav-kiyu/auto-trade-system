import ast
from pathlib import Path

from scripts.run_mutation_tests import _apply_mutant, _generate_mutants

RISK_SERVICE = Path("core/services/risk_service.py")


def test_all_generated_risk_mutants_are_valid_python():
    source = RISK_SERVICE.read_text(encoding="utf-8")
    mutants = _generate_mutants(str(RISK_SERVICE))

    assert mutants
    for mutant in mutants:
        mutated = _apply_mutant(source, mutant)
        ast.parse(mutated, filename=str(RISK_SERVICE))


def test_greater_than_mutation_does_not_corrupt_greater_equal():
    mutants = _generate_mutants(str(RISK_SERVICE))

    for mutant in mutants:
        assert ">==" not in mutant.mutated_line


def test_less_than_mutation_does_not_corrupt_less_equal():
    mutants = _generate_mutants(str(RISK_SERVICE))

    for mutant in mutants:
        assert "<==" not in mutant.mutated_line


def test_mutation_generator_does_not_modify_source():
    before = RISK_SERVICE.read_bytes()
    _generate_mutants(str(RISK_SERVICE))
    after = RISK_SERVICE.read_bytes()

    assert after == before


def test_known_greater_than_mutation_is_correct():
    mutants = _generate_mutants(str(RISK_SERVICE))

    matches = [
        m for m in mutants
        if m.operator == "replace_gt_with_ge"
        and m.location == "risk_service.py:1139"
    ]

    assert matches
    assert all("score >= 75" in m.mutated_line for m in matches)
    assert all(">==" not in m.mutated_line for m in matches)
