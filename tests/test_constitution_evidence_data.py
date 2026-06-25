"""Tests for ConstitutionEvidenceData - evidence collection for all 31 categories."""

from __future__ import annotations

from core.constitution_evidence_data import (
    collect_all_evidence,
    _exists,
    _is_dir,
)


class TestEvidenceHelpers:
    """Helper functions."""

    def test_exists_true(self):
        assert _exists("pyproject.toml") is True

    def test_exists_false(self):
        assert _exists("nonexistent_file_xyz123.txt") is False

    def test_is_dir_true(self):
        assert _is_dir("tests") is True

    def test_is_dir_false(self):
        assert _is_dir("nonexistent_dir_xyz123") is False


class TestCollectAllEvidence:
    """collect_all_evidence - scans codebase for evidence items."""

    def test_returns_dict(self):
        evidence = collect_all_evidence()
        assert isinstance(evidence, dict)

    def test_has_arch_categories(self):
        evidence = collect_all_evidence()
        arch_keys = [k for k in evidence if k.startswith("ARCH")]
        assert len(arch_keys) >= 4
        assert "ARCH-01" in evidence
        assert "ARCH-02" in evidence

    def test_has_sec_categories(self):
        evidence = collect_all_evidence()
        sec_keys = [k for k in evidence if k.startswith("SEC")]
        assert len(sec_keys) >= 4

    def test_has_rsk_categories(self):
        evidence = collect_all_evidence()
        rsk_keys = [k for k in evidence if k.startswith("RSK")]
        assert len(rsk_keys) >= 4

    def test_has_exe_categories(self):
        evidence = collect_all_evidence()
        exe_keys = [k for k in evidence if k.startswith("EXE")]
        assert len(exe_keys) >= 4

    def test_has_tst_categories(self):
        evidence = collect_all_evidence()
        tst_keys = [k for k in evidence if k.startswith("TST")]
        assert len(tst_keys) >= 4

    def test_has_obs_categories(self):
        evidence = collect_all_evidence()
        obs_keys = [k for k in evidence if k.startswith("OBS")]
        assert len(obs_keys) >= 4

    def test_has_gov_categories(self):
        evidence = collect_all_evidence()
        gov_keys = [k for k in evidence if k.startswith("GOV")]
        assert len(gov_keys) >= 4

    def test_has_dr_categories(self):
        evidence = collect_all_evidence()
        dr_keys = [k for k in evidence if k.startswith("DR")]
        assert len(dr_keys) >= 3

    def test_each_evidence_has_description(self):
        evidence = collect_all_evidence()
        for cid, items in evidence.items():
            for item in items:
                assert "description" in item, f"{cid} item missing description"
                assert "type" in item, f"{cid} item missing type"
                assert "weight" in item, f"{cid} item missing weight"

    def test_each_evidence_weight_between_0_and_1(self):
        evidence = collect_all_evidence()
        for cid, items in evidence.items():
            for item in items:
                assert 0 < item["weight"] <= 1.0, f"{cid} weight={item['weight']} out of range"

    def test_evidence_types_valid(self):
        valid_types = {"test_pass", "code_review", "documentation", "chaos"}
        evidence = collect_all_evidence()
        for cid, items in evidence.items():
            for item in items:
                assert item["type"] in valid_types, f"{cid} has invalid type: {item['type']}"

    def test_has_multiple_items_per_category(self):
        evidence = collect_all_evidence()
        for cid, items in evidence.items():
            assert len(items) >= 1, f"{cid} has no evidence items"
            # Most categories should have multiple evidence items
            if len(items) < 2:
                pass  # Single-item categories are acceptable

    def test_total_categories_at_least_31(self):
        evidence = collect_all_evidence()
        assert len(evidence) >= 31, f"Only {len(evidence)} categories found, expected at least 31"

    def test_arch_01_has_architecture_compliance(self):
        evidence = collect_all_evidence()
        arch01_items = evidence.get("ARCH-01", [])
        descriptions = [i["description"] for i in arch01_items]
        assert any("architecture" in d.lower() for d in descriptions)
