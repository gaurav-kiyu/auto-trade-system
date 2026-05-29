"""Tkinter trading desk for the index bot. Body lives in _desk_body.py and runs in the trader module namespace."""
from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path
from types import ModuleType

_log = logging.getLogger(__name__)

_DESK_MODULE_NAME = "_opbuying_desk_body_loader"


def _load_desk_body_as_module() -> ModuleType:
    """Load _desk_body.py as a proper module instead of using exec().

    This eliminates the arbitrary code execution risk of exec() while
    preserving access to the index_trader module namespace.
    """
    import index_app.index_trader as mod

    path = Path(__file__).with_name("_desk_body.py")
    if not path.is_file():
        raise FileNotFoundError(f"Desk body not found: {path}")

    # Build a module from _desk_body.py using importlib
    spec = importlib.util.spec_from_file_location(_DESK_MODULE_NAME, str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not create module spec for {path}")

    desk_mod = importlib.util.module_from_spec(spec)

    # Inject the index_trader namespace so the desk body can access bot internals
    for key, val in dict(mod.__dict__).items():
        setattr(desk_mod, key, val)
    desk_mod._GUI_PROJECT_ROOT = str(Path(mod.__file__).resolve().parent.parent)

    sys.modules[_DESK_MODULE_NAME] = desk_mod
    spec.loader.exec_module(desk_mod)
    return desk_mod


def run_trader_desk_gui() -> None:
    try:
        _load_desk_body_as_module()
    except Exception as exc:
        _log.critical("Failed to load trader desk GUI: %s", exc)
        raise
