"""Tkinter trading desk for the index bot. Body lives in _desk_body.py and runs in the trader module namespace."""
from __future__ import annotations

import textwrap
from pathlib import Path


__all__ = [
    "run_trader_desk_gui",
]

def run_trader_desk_gui() -> None:
    import index_app.index_trader as mod

    g = dict(mod.__dict__)
    g["_GUI_PROJECT_ROOT"] = str(Path(mod.__file__).resolve().parent.parent)
    path = Path(__file__).with_name("_desk_body.py")
    body = path.read_text(encoding="utf-8")
    # Desk body uses early `return` when tkinter is missing; that is only valid inside a function.
    wrapped = "def __opbuying_desk_body():\n" + textwrap.indent(body, "    ") + "\n__opbuying_desk_body()\n"
    code = compile(wrapped, str(path), "exec")
    exec(code, g, g)
