"""Legacy Signal Engine — backward-compatible ``build_full_signal`` path.

**Deprecated** — replaced by ``SignalEvaluator`` (``index_app.domains.signal.evaluator``).

This module was previously a wrapper around ``core.legacy.signal_engine.build_full_signal``.
Now it re-exports ``SignalEvaluator`` from the modern path for backward compatibility.

All callers should import from ``index_app.domains.signal.evaluator`` directly.
"""

from __future__ import annotations

import warnings

warnings.warn(
    "index_app.domains.signal.legacy is deprecated. "
    "Use index_app.domains.signal.evaluator.SignalEvaluator instead.",
    DeprecationWarning,
    stacklevel=2,
)

# Re-export the modern class for backward compatibility
from index_app.domains.signal.evaluator import SignalEvaluator as LegacySignalEngine  # noqa: F401


__all__ = [
    "LegacySignalEngine",
]
