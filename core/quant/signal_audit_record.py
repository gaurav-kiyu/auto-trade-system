"""Layer 6 Audit: Tamper-Evident SHA-256 Decision Audit Chain (v6.0 Production).

Audits both actionable signals and NO_TRADE outcomes before notification dispatch.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from core.logging import get_logger

_log = get_logger("QUANT_AUDIT")
_AUDIT_LOG_PATH = Path(__file__).resolve().parent.parent.parent / "json" / "signal_audit_ledger.jsonl"


@dataclass
class SignalAuditRecord:
    signal_id: str
    decision_timestamp: str
    data_snapshot_timestamp: str
    symbol: str
    asset_class: str

    # Three-Tier Decisions
    model_decision: str
    risk_decision: str
    final_decision: str
    final_reason_code: str

    # Layer Evidence & Weights
    regime: str
    regime_confidence: float
    composite_score: float
    cluster_scores: dict[str, float]
    resolved_weights: dict[str, Any]

    # Probabilities & Payoffs
    p_direction: float
    p_t1: float
    p_t2: float
    p_sl: float
    p_timeout: float
    expected_value: float
    net_rr_t1: float
    net_rr_t2: float
    r_timeout: float

    # SHAP Explanations
    direction_shap_drivers: list[str]
    outcome_shap_drivers: list[str]

    # Trade Levels
    entry_price: float
    stop_loss_price: float
    target_1_price: float
    target_2_price: float

    # Multi-Dimensional Versioning
    engine_version: str = "v6.0-production"
    strategy_version: str = "3.2.0"
    model_version: str = "2.1.0"
    calibration_version: str = "1.0.0"
    feature_schema_version: str = "2.0.0"
    weight_matrix_version: str = "1.5.0"
    risk_policy_version: str = "1.2.0"
    instrument_master_version: str = "NSE-2026.08.20"
    regime_model_version: str = "1.1.0"

    # Cryptographic Chain
    previous_record_hash: str = "GENESIS_HASH"
    payload_hash: str = ""

    def calculate_payload_hash(self) -> str:
        data = asdict(self)
        data["payload_hash"] = ""  # Exclude self hash
        canonical_json = json.dumps(data, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SignalAuditLedger:
    """Thread-safe, append-only SHA-256 tamper-evident ledger."""

    _instance: SignalAuditLedger | None = None
    _lock = threading.Lock()

    def __init__(self, ledger_path: Path | None = None) -> None:
        self._path = ledger_path or _AUDIT_LOG_PATH
        self._io_lock = threading.Lock()
        self._last_hash = "GENESIS_HASH"
        self._load_last_hash()

    @classmethod
    def get_instance(cls) -> SignalAuditLedger:
        with cls._lock:
            if cls._instance is None:
                cls._instance = SignalAuditLedger()
            return cls._instance

    def _load_last_hash(self) -> None:
        if self._path.exists():
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    if lines:
                        last_record = json.loads(lines[-1].strip())
                        self._last_hash = last_record.get("payload_hash", "GENESIS_HASH")
            except Exception as e:
                _log.warning("Could not read last hash from ledger: %s", e)

    def record_decision(self, record: SignalAuditRecord) -> SignalAuditRecord:
        """Calculate SHA-256 hash, link to previous hash, and append to immutable ledger."""
        with self._io_lock:
            record.previous_record_hash = self._last_hash
            record.payload_hash = record.calculate_payload_hash()
            self._last_hash = record.payload_hash

            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                with open(self._path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record.to_dict()) + "\n")
            except Exception as e:
                _log.error("Failed to append to signal audit ledger: %s", e)

            return record
