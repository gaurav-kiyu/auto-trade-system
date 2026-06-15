import json
import logging
import os
import shutil
import threading
from collections.abc import Callable

from core.db_utils import get_connection
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.time_provider import time_provider

log = logging.getLogger("state_manager")

@dataclass(frozen=True)
class SessionRecoveryReport:
    local_positions: int
    broker_positions: int
    matched_symbols: int
    positions_aligned: bool = False
    note: str = ""

class StateManager:
    """
    Authoritative State Manager for the trading system.
    Ensures atomic updates to trader state and provides a bridge
    between the JSON state file and the SQLite trade database.
    """

    def __init__(
        self,
        state_file: str = "trader_state.json",
        db_path: str = "trades.db",
        save_fn: Callable[[], None] | None = None,
        load_fn: Callable[[], None] | None = None,
        local_positions_fn: Callable[[], dict[str, Any]] | None = None,
        broker_positions_fn: Callable[[], dict[str, Any]] | None = None,
        **kwargs # Preserve compatibility with old init
    ):
        self.state_path = Path(state_file)
        self.db_path = Path(db_path)
        self._state: dict[str, Any] = {}
        self._save_fn = save_fn
        self._load_fn = load_fn
        self._local_positions_fn = local_positions_fn
        self._broker_positions_fn = broker_positions_fn
        self._lock = threading.Lock()

        if self._load_fn is not None:
            self._load_fn()
        else:
            self.load_state()

    def load_state(self):
        """Loads state from disk with fallback to recovery."""
        try:
            if self.state_path.exists():
                with open(self.state_path) as f:
                    self._state = json.load(f)
                log.info(f"State loaded from {self.state_path}")
            else:
                self._state = {}
        except (OSError, json.JSONDecodeError) as e:
            log.error(f"State corrupted: {e}. Recovering from DB...")
            self.recover_state_from_db()

    def get(self, key: str, default: Any = None) -> Any:
        return self._state.get(key, default)

    def set(self, key: str, value: Any):
        with self._lock:
            self._state[key] = value
            self.save_state()

    def save_state(self):
        """Atomic write: Write to tmp -> Flush -> Rename."""
        if self._save_fn is not None:
            self._save_fn()
        tmp_path = self.state_path.with_suffix(".tmp")
        try:
            with open(tmp_path, "w") as f:
                json.dump(self._state, f, indent=4)
                f.flush()
                os.fsync(f.fileno())
            # Only rename if tmp and target are on same filesystem
            if tmp_path.exists():
                shutil.move(str(tmp_path), str(self.state_path))
        except Exception as e:
            log.error(f"Atomic save failed: {e} (type: {type(e).__name__})")

    def recover_state_from_db(self, broker_positions: dict[str, Any] | None = None):
        """Reconstructs positions from trades.db where exit_ts is NULL.

        If broker_positions is provided, cross-checks DB positions against
        broker reality to eliminate phantom positions from stale NULL exit_ts.
        """
        try:
            conn = get_connection(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT symbol, qty, entry_price FROM trades WHERE exit_ts IS NULL")
            open_pos = cursor.fetchall()

            recovered = {row[0]: {"qty": row[1], "entry_price": row[2]} for row in open_pos}

            # Cross-check against broker positions if available
            if broker_positions is not None:
                broker_symbols = set(str(k) for k in (broker_positions or {}).keys())
                db_symbols = set(recovered.keys())
                phantom = db_symbols - broker_symbols
                if phantom:
                    log.warning(
                        f"PHANTOM POSITIONS DETECTED (in DB but not on broker): {phantom}. "
                        f"Removing from recovered state."
                    )
                    for sym in phantom:
                        del recovered[sym]
                matched = db_symbols & broker_symbols
                if matched:
                    log.info(f"Broker-confirmed positions: {matched}")

            self._state["active_positions"] = recovered
            self._state["recovery_mode"] = True
            self._state["last_recovery_ts"] = time_provider.format_ts()
            self.save_state()
            conn.close()
        except Exception as e:
            log.critical(f"DB Recovery failed: {e} (type: {type(e).__name__})")

    def set_consecutive_losses(self, count: int) -> None:
        """Set the consecutive loss counter (protection against compounding losses)."""
        with self._lock:
            self._state["max_consecutive_losses"] = max(
                self._state.get("max_consecutive_losses", 0),
                count
            )
            self._state["consecutive_losses"] = count
            self.save_state()

    def get_consecutive_losses(self) -> int:
        """Get the current consecutive loss count."""
        return self._state.get("consecutive_losses", 0)

    def reset_consecutive_losses(self) -> None:
        """Reset the consecutive loss counter on a win."""
        with self._lock:
            self._state["consecutive_losses"] = 0
            self.save_state()

    def session_recovery_report(self, broker_positions: dict | None = None) -> SessionRecoveryReport:
        """Compares local state with broker reality."""
        if self._local_positions_fn is not None:
            local_pos = self._local_positions_fn() or {}
        else:
            local_pos = self.get("active_positions", {}) or {}

        if broker_positions is None:
            broker_pos = self._broker_positions_fn() if self._broker_positions_fn is not None else {}
        else:
            broker_pos = broker_positions or {}

        local_keys = set(local_pos.keys())
        broker_keys = set(broker_pos.keys())
        matched = len(local_keys & broker_keys)
        aligned = (matched == len(local_keys))

        return SessionRecoveryReport(
            local_positions=len(local_keys),
            broker_positions=len(broker_keys),
            matched_symbols=matched,
            positions_aligned=aligned,
            note="Aligned" if aligned else "Mismatch detected"
        )

    # Compatibility aliases for old code
    def save(self): self.save_state()
    def load(self): self.load_state()


# Compatibility alias for legacy imports and global access
state_manager = StateManager()
