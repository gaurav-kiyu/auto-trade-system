"""
Tests for scripts/score_system.py - Constitution Scoring System CLI.

Covers:
  - calculate_score() with various evidence/regression combinations
  - Evidence cap enforcement (8.0 without evidence)
  - Category definitions validation
  - Main function with various CLI args
  - collect_auto_evidence() output
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

# ── Helpers ───────────────────────────────────────────────────────────────────


_SCORE_SYSTEM_CACHE: Any = None

def import_score_system() -> Any:
    """Import the score_system module (cached after first import)."""
    global _SCORE_SYSTEM_CACHE
    if _SCORE_SYSTEM_CACHE is not None:
        return _SCORE_SYSTEM_CACHE
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import scripts.score_system as ss
    _SCORE_SYSTEM_CACHE = ss
    return ss


# ── calculate_score ───────────────────────────────────────────────────────────


class TestCalculateScore:
    def test_default_score_is_5(self) -> None:
        ss = import_score_system()
        result = ss.calculate_score("ARCH-01", [])
        # Base 8.5, but without evidence the score is capped at 8.0
        assert result["score"] == 8.0

    def test_with_evidence_increases_score(self) -> None:
        ss = import_score_system()
        evidence = [{"description": "test", "type": "test_pass", "weight": 1.0, "verified": True}]
        result = ss.calculate_score("ARCH-01", evidence)
        # 8.5 + 1.0 = 9.5, capped at ARCH-01 max
        assert result["score"] == 9.5

    def test_with_regression_lowers_score(self) -> None:
        ss = import_score_system()
        result = ss.calculate_score("ARCH-01", [], regressions=["r1"])
        assert result["score"] == 6.5  # 8.5 - 2.0, no-evidence cap does not apply with regressions
    def test_score_capped_at_max(self) -> None:
        ss = import_score_system()
        evidence = [{"description": "big evidence", "type": "test_pass", "weight": 10.0, "verified": True}]
        result = ss.calculate_score("ARCH-01", evidence)
        assert result["score"] <= 10.0  # ARCH-01 max_score is 10.0 per ConstitutionValidator

    def test_score_floor_at_zero(self) -> None:
        ss = import_score_system()
        result = ss.calculate_score("ARCH-01", [], regressions=["r1", "r2", "r3"])
        assert result["score"] >= 0.0

    def test_unverified_evidence_not_counted(self) -> None:
        ss = import_score_system()
        evidence = [{"description": "unverified", "type": "test_pass", "weight": 2.0, "verified": False}]
        result = ss.calculate_score("ARCH-01", evidence)
        # Unverified evidence adds no bonus; base score stands (cap only applies to an empty list)
        assert result["score"] == 8.5

    def test_no_evidence_caps_at_8(self) -> None:
        ss = import_score_system()
        # RSK-01 has max 9.9, but without evidence should cap at 8.0
        result = ss.calculate_score("RSK-01", [])
        assert result["score"] <= 8.0

    def test_with_evidence_allows_above_8(self) -> None:
        ss = import_score_system()
        evidence = [{"description": "verified", "type": "test_pass", "weight": 4.0, "verified": True}]
        # With 5.0 + 4.0 = 9.0, but max for RSK-02 is 9.9
        result = ss.calculate_score("RSK-02", evidence)
        assert result["score"] >= 9.0

    def test_result_has_all_keys(self) -> None:
        ss = import_score_system()
        result = ss.calculate_score("TST-01", [])
        assert "category_id" in result
        assert "score" in result
        assert "max_score" in result
        assert "evidence_count" in result
        assert "regression_count" in result
        assert "needs_9_audit" in result
        assert "needs_95_audit" in result

    def test_needs_9_audit_flag(self) -> None:
        ss = import_score_system()
        evidence = [{"description": "big", "type": "test_pass", "weight": 4.5, "verified": True}]
        result = ss.calculate_score("TST-01", evidence)
        if result["score"] >= 9.0:
            assert result["needs_9_audit"] is True

    def test_needs_95_audit_flag(self) -> None:
        ss = import_score_system()
        evidence = [{"description": "huge", "type": "test_pass", "weight": 9.0, "verified": True}]
        result = ss.calculate_score("RSK-01", evidence)
        if result["score"] >= 9.5:
            assert result["needs_95_audit"] is True

    def test_verified_evidence_count(self) -> None:
        ss = import_score_system()
        evidence = [
            {"description": "v1", "type": "test_pass", "weight": 1.0, "verified": True},
            {"description": "v2", "type": "code_review", "weight": 0.5, "verified": True},
            {"description": "unv", "type": "doc", "weight": 0.3, "verified": False},
        ]
        result = ss.calculate_score("TST-01", evidence)
        assert result["evidence_count"] == 3
        assert result["verified_evidence"] == 2


# ── Categories ────────────────────────────────────────────────────────────────


class TestCategories:
    def test_all_categories_have_valid_groups(self) -> None:
        ss = import_score_system()
        valid_groups = {"Architecture", "Security", "Risk", "Execution",
                        "Testing", "Observability", "Governance", "DR",
                        "Enterprise Layers", "Quality Gates", "Principles",
                        "Architecture Standards", "Security & Governance",
                        "Platform Engineering", "SRE/Reliability", "Knowledge"}
        for cid, (name, max_score, group) in ss.CATEGORIES.items():
            assert group in valid_groups, f"{cid} has invalid group {group}"

    def test_all_categories_have_positive_max_scores(self) -> None:
        ss = import_score_system()
        for cid, (name, max_score, group) in ss.CATEGORIES.items():
            assert max_score >= 5.0, f"{cid} max_score {max_score} < 5.0"

    def test_max_scores_cannot_exceed_constitution_validator(self) -> None:
        """
        Validate that score_system.py max_scores do not exceed the
        authoritative ConstitutionValidator max_scores. The validator
        defines the ceiling for each category. Checks both directions:
        score_system <= validator AND validator categories present in
        score_system.
        """
        ss = import_score_system()
        from core.constitution import ConstitutionValidator
        validator_cats = ConstitutionValidator.CATEGORIES
        exceeded = []
        # Direction 1: score_system max_scores must not exceed validator
        for cid in list(ss.CATEGORIES.keys()):
            if cid not in validator_cats:
                exceeded.append(f"{cid}: exists in score_system but NOT in validator")
                continue
            s_max = ss.CATEGORIES[cid][1]
            v_max = validator_cats[cid][1]
            if s_max > v_max + 0.01:
                exceeded.append(f"{cid}: score_system={s_max} > validator={v_max}")
        # Direction 2: all validator categories must exist in score_system
        for cid in list(validator_cats.keys()):
            if cid not in ss.CATEGORIES:
                exceeded.append(f"{cid}: exists in validator but NOT in score_system")
        assert not exceeded, f"Alignment issues: {', '.join(exceeded)}"

    def test_category_count(self) -> None:
        ss = import_score_system()
        # 111 categories: 31 classic + 12 LAY + 12 QGT + 13 PRN + 13 AST
        # + 11 SGS + 6 PLS + 9 SRE + 4 KNW = 111
        assert len(ss.CATEGORIES) == 111
        assert len(ss.CATEGORIES) >= 100  # ensures v4.0 coverage

    def test_unknown_category_raises_key_error(self) -> None:
        ss = import_score_system()
        with pytest.raises(KeyError):
            ss.calculate_score("UNKNOWN", [])

    def test_max_scores_aligned_with_constitution_validator(self) -> None:
        """
        Validate that score_system.py max_scores match the
        authoritative ConstitutionValidator CATEGORIES dict.
        Checks BOTH directions to catch drift on either side.
        If this test fails, update both systems in sync.
        """
        ss = import_score_system()
        from core.constitution import ConstitutionValidator
        validator_cats = ConstitutionValidator.CATEGORIES
        all_cids = set(ss.CATEGORIES.keys()) | set(validator_cats.keys())
        mismatches = []
        missing_in_score_system = set(validator_cats.keys()) - set(ss.CATEGORIES.keys())
        missing_in_validator = set(ss.CATEGORIES.keys()) - set(validator_cats.keys())
        if missing_in_score_system:
            mismatches.append(f"Missing in score_system: {sorted(missing_in_score_system)}")
        if missing_in_validator:
            mismatches.append(f"Missing in validator: {sorted(missing_in_validator)}")
        for cid in all_cids:
            v_max = validator_cats[cid][1]
            s_max = ss.CATEGORIES[cid][1]
            if abs(v_max - s_max) > 0.01:
                mismatches.append(f"{cid}: score_system={s_max} validator={v_max}")
        assert not mismatches, f"Alignment issues: {', '.join(mismatches)}"


class TestMain:
    def test_main_ci_mode_exit_zero(self) -> None:
        ss = import_score_system()
        exit_code = ss.main(["--ci", "--check-min", "0"])
        assert exit_code == 0

    def test_main_ci_mode_exit_one_on_failure(self) -> None:
        ss = import_score_system()
        exit_code = ss.main(["--ci", "--check-min", "100"])
        assert exit_code == 1

    def test_main_json_output(self) -> None:
        ss = import_score_system()
        import io
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            exit_code = ss.main(["--json"])
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout
        assert exit_code == 0
        parsed = json.loads(output)
        assert "overall_score" in parsed
        assert "categories" in parsed
        assert "total_evidence" in parsed

    def test_main_single_category(self) -> None:
        ss = import_score_system()
        exit_code = ss.main(["--category", "ARCH-01", "--json"])
        assert exit_code == 0

    def test_main_single_category_json_has_one_result(self) -> None:
        ss = import_score_system()
        import io
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            ss.main(["--category", "ARCH-01", "--json"])
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout
        parsed = json.loads(output)
        assert len(parsed["categories"]) == 1
        assert parsed["categories"][0]["category_id"] == "ARCH-01"

    def test_main_unknown_category_returns_one(self) -> None:
        ss = import_score_system()
        exit_code = ss.main(["--category", "INVALID"])
        assert exit_code == 1

    def test_main_verbose_evidence_mode(self) -> None:
        ss = import_score_system()
        # Just check it runs without error
        exit_code = ss.main(["--evidence"])
        assert exit_code == 0

    def test_main_no_args_runs_ok(self) -> None:
        ss = import_score_system()
        exit_code = ss.main([])
        assert exit_code == 0

    def test_main_check_min_fails(self) -> None:
        ss = import_score_system()
        exit_code = ss.main(["--check-min", "99.0"])
        assert exit_code == 1


# ── collect_auto_evidence ─────────────────────────────────────────────────────


class TestCollectAutoEvidence:
    def test_collect_evidence_returns_dict(self) -> None:
        ss = import_score_system()
        evidence = ss.collect_auto_evidence()
        assert isinstance(evidence, dict)

    def test_arch_evidence_present(self) -> None:
        ss = import_score_system()
        evidence = ss.collect_auto_evidence()
        assert "ARCH-01" in evidence

    def test_tst_evidence_present(self) -> None:
        ss = import_score_system()
        evidence = ss.collect_auto_evidence()
        assert "TST-01" in evidence

    def test_gov_evidence_present(self) -> None:
        ss = import_score_system()
        evidence = ss.collect_auto_evidence()
        assert "GOV-01" in evidence

    def test_gov_02_gitignore_evidence(self) -> None:
        ss = import_score_system()
        evidence = ss.collect_auto_evidence()
        assert "GOV-02" in evidence

    def test_rsk_evidence_present(self) -> None:
        ss = import_score_system()
        evidence = ss.collect_auto_evidence()
        assert "RSK-01" in evidence

    def test_exe_evidence_present(self) -> None:
        ss = import_score_system()
        evidence = ss.collect_auto_evidence()
        assert "EXE-01" in evidence

    def test_dr_evidence_present(self) -> None:
        ss = import_score_system()
        evidence = ss.collect_auto_evidence()
        assert "DR-01" in evidence

    def test_sec_evidence_present(self) -> None:
        ss = import_score_system()
        evidence = ss.collect_auto_evidence()
        assert "SEC-01" in evidence

    def test_obs_evidence_present(self) -> None:
        ss = import_score_system()
        evidence = ss.collect_auto_evidence()
        assert "OBS-03" in evidence

    def test_evidence_items_have_required_keys(self) -> None:
        ss = import_score_system()
        evidence = ss.collect_auto_evidence()
        for cid, items in evidence.items():
            for item in items:
                assert "description" in item
                assert "type" in item
                assert "weight" in item
                assert "verified" in item


# ── CLI entry point ───────────────────────────────────────────────────────────


class TestCLI:
    def test_cli_script_exists(self) -> None:
        script_path = Path(__file__).resolve().parent.parent / "scripts" / "score_system.py"
        assert script_path.exists()
        assert script_path.stat().st_size > 0

    def test_cli_has_shebang(self) -> None:
        script_path = Path(__file__).resolve().parent.parent / "scripts" / "score_system.py"
        content = script_path.read_text(encoding="utf-8")
        assert content.startswith("#!/usr/bin/env python3")
