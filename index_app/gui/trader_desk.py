"""Tkinter trading desk for the index bot. Delegates to _desk_body.build_desk_gui()."""
from __future__ import annotations

from pathlib import Path

__all__ = [
    "run_trader_desk_gui",
]

def _collect_context() -> dict:
    """Collect context dict from the index_trader module namespace."""
    import index_app.index_trader as mod

    ctx = dict(mod.__dict__)
    ctx["_GUI_PROJECT_ROOT"] = str(Path(mod.__file__).resolve().parent.parent)
    return ctx


def run_trader_desk_gui() -> None:
    from index_app.gui._desk_body import build_desk_gui

    ctx = _collect_context()
    build_desk_gui(ctx)
