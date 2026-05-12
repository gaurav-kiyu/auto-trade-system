import json
import logging
import os
import time
from typing import Any


def cleanup_old_prefixed_logs(
    logs_dir: str,
    filename_prefix: str,
    *,
    retain_days: int = 30,
    delete_rotated_variants: bool = True,
) -> None:
    """Remove ``{prefix}*.log`` and optional ``{prefix}*.log.*`` older than ``retain_days`` (best-effort, silent)."""
    try:
        cutoff = time.time() - retain_days * 86400
        for fn in os.listdir(logs_dir):
            if not fn.startswith(filename_prefix):
                continue
            fp = os.path.join(logs_dir, fn)
            if not os.path.isfile(fp):
                continue
            if os.path.getmtime(fp) >= cutoff:
                continue
            if fn.endswith(".log") or fn.endswith(".jsonl"):
                try:
                    os.remove(fp)
                except OSError:
                    pass
            elif delete_rotated_variants and (".log." in fn or ".jsonl." in fn):
                try:
                    os.remove(fp)
                except OSError:
                    pass
    except OSError:
        pass


class JsonFormatter(logging.Formatter):
    """
    Formatter that outputs JSON strings after parsing the LogRecord.
    """
    def format(self, record: logging.LogRecord) -> str:
        log_record = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "message": record.getMessage(),
        }
        if hasattr(record, "structured_data"):
            log_record.update(record.structured_data)

        return json.dumps(log_record)


def setup_structured_logger(log_file: str, level: int = logging.INFO) -> logging.Logger:
    """
    Configures a logger that writes structured JSON to a file.
    """
    logger = logging.getLogger("StructuredLogger")
    logger.setLevel(level)

    # Avoid adding handlers multiple times if re-called
    if not logger.handlers:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        handler = logging.FileHandler(log_file, encoding='utf-8')
        formatter = JsonFormatter()
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger

def log_structured_event(logger: logging.Logger, event_name: str, payload: dict[str, Any]) -> None:
    """
    Logs a structured JSON event.
    Example payload: {"score": 68, "type": "EARLY", "allowed": True}
    """
    extra = {"structured_data": {"event": event_name, **payload}}
    logger.info(f"Event: {event_name}", extra=extra)
