from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


@dataclass(frozen=True)
class RetentionPolicy:
    max_files: int
    max_age_days: int


class RetentionEngine:
    """Keep operational folders tidy without deleting required live files."""

    def __init__(self, now_fn=None) -> None:
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc))

    def apply(self, folder: str | Path, patterns: Iterable[str], policy: RetentionPolicy) -> list[Path]:
        base = Path(folder)
        if not base.exists():
            return []
        now = self._now_fn()
        matches: list[Path] = []
        for pattern in patterns:
            matches.extend([p for p in base.glob(pattern) if p.is_file()])
        seen: dict[Path, None] = {}
        ordered = sorted((p for p in matches if not seen.setdefault(p, None)), key=lambda p: p.stat().st_mtime, reverse=True)
        cutoff = now - timedelta(days=max(0, int(policy.max_age_days)))
        removed: list[Path] = []
        for idx, path in enumerate(ordered):
            stat = path.stat()
            too_old = datetime.fromtimestamp(stat.st_mtime, timezone.utc) < cutoff
            over_count = idx >= max(0, int(policy.max_files))
            if too_old or over_count:
                try:
                    path.unlink(missing_ok=True)
                except PermissionError:
                    try:
                        os.chmod(path, 0o666)
                        path.unlink(missing_ok=True)
                    except PermissionError:
                        continue
                removed.append(path)
        return removed
