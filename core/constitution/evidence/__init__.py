"""Evidence collection sub-package — category-focused modules.

Each sub-module collects objective evidence for one constitution scoring category
by scanning the codebase at init-time.

Usage:
    from core.constitution.evidence import collect_auto_evidence
    collect_auto_evidence(validator_instance)
"""
from __future__ import annotations

# The main entry point was moved to _evidence_main.py to avoid
# package/module name shadowing with the evidence/ sub-package.
from core.constitution._evidence_main import collect_auto_evidence
from core.constitution.evidence.arch_evidence import collect_arch_evidence
from core.constitution.evidence.boost_evidence import collect_boost_evidence
from core.constitution.evidence.dr_evidence import collect_dr_evidence
from core.constitution.evidence.exe_evidence import collect_exe_evidence
from core.constitution.evidence.gov_evidence import collect_gov_evidence
from core.constitution.evidence.lay_qgt_evidence import collect_lay_qgt_evidence
from core.constitution.evidence.obs_evidence import collect_obs_evidence
from core.constitution.evidence.prn_ast_evidence import collect_prn_ast_evidence
from core.constitution.evidence.rsk_evidence import collect_rsk_evidence
from core.constitution.evidence.sec_evidence import collect_sec_evidence
from core.constitution.evidence.sgs_pls_evidence import collect_sgs_pls_evidence
from core.constitution.evidence.sre_knw_evidence import collect_sre_knw_evidence
from core.constitution.evidence.tst_evidence import collect_tst_evidence

__all__ = [
    "collect_auto_evidence",
    "collect_arch_evidence",
    "collect_boost_evidence",
    "collect_sec_evidence",
    "collect_rsk_evidence",
    "collect_exe_evidence",
    "collect_tst_evidence",
    "collect_obs_evidence",
    "collect_gov_evidence",
    "collect_dr_evidence",
    "collect_lay_qgt_evidence",
    "collect_prn_ast_evidence",
    "collect_sgs_pls_evidence",
    "collect_sre_knw_evidence",
]
