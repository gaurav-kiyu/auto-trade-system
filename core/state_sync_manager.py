import json
import logging
import os
import time
from typing import Any


class StateSyncManager:
    """
    High-Availability state synchronization.
    Writes a heartbeat file to disk for secondary bot instances to monitor.
    """
    def __init__(self, state_path: str, heartbeat_path: str = "heartbeat.json"):
        self.state_path = state_path
        self.heartbeat_path = heartbeat_path
        self.logger = logging.getLogger(__name__)

    def update_heartbeat(self, state: dict[str, Any]):
        """Writes current state and timestamp to the heartbeat file."""
        try:
            heartbeat = {
                "timestamp": time.time(),
                "state": state,
                "instance_id": os.getpid()
            }
            with open(self.heartbeat_path, "w") as f:
                json.dump(heartbeat, f)
        except (OSError, json.JSONDecodeError) as e:
            self.logger.error(f"Heartbeat update failed: {e}")

    def check_failover(self) -> bool:
        """Returns True if the primary bot has failed (heartbeat stale)."""
        if not os.path.exists(self.heartbeat_path):
            return False
        try:
            with open(self.heartbeat_path) as f:
                hb = json.load(f)
                if time.time() - hb["timestamp"] > 60:
                    self.logger.warning(f"Primary bot stale (last seen {round(time.time()-hb['timestamp'])}s ago).")
                    return True
        except (OSError, json.JSONDecodeError):
            pass
        return False
