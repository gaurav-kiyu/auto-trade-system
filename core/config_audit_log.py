"""Append-only config audit lines after soft reload (stock + index parity).


__all__ = [
    "append_soft_reload_audit_diff",
    "format_config_audit_log_line",
]

Callers keep try/except + log on failure; this module only centralizes the
on-disk line shape so operators and tooling see one format across bots.
"""

from __future__ import annotations

import pathlib
from collections.abc import Callable, Mapping, Sequence

__all__ = [
    "append_soft_reload_audit_diff",
    "format_config_audit_log_line",
]


def format_config_audit_log_line(timestamp_iso: str, key: str, old: object, new: object) -> str:
    return f"{timestamp_iso} | {key} | {old} → {new}\n"


def append_soft_reload_audit_diff(
    audit_log_path: str | pathlib.Path,
    diff_log: Sequence[Mapping[str, object]],
    *,
    now_iso: Callable[[], str],
) -> None:
    path = pathlib.Path(audit_log_path)
    with open(path, "a", encoding="utf-8") as f:
        for d in diff_log:
            f.write(
                format_config_audit_log_line(
                    now_iso(),
                    str(d["key"]),
                    d["old"],
                    d["new"],
                )
            )
        f.flush()
