"""
Tkinter trading desk body for the index bot.
Refactored from exec()-injected namespace pattern to a proper module function.

Usage:
    from index_app.gui._desk_body import build_desk_gui
    build_desk_gui(ctx)

Where ctx is a dict containing the following keys:
    _TK_AVAILABLE, ttk, _gui_alive, GUI_THEME, GUI_WINDOW, GUI_UX,
    VERSION, PAPER_MODE, GUI_REFRESH_MS, SCAN_INTERVAL, _shutdown,
    _display_lock, _display_snapshot, SHUTDOWN_ON_UI_CLOSE, format_pnl,
    _format_trading_desk_line, _config_reload_status, GUI_CONFIRM_EXIT,
    _DEBUG, INDEX_PRIORITY, MAX_LOT_CAPITAL_PCT, MIN_NET_RR,
    market_status, _GUI_PROJECT_ROOT
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import pathlib
import subprocess
import sys
import threading
import time
from pathlib import Path

import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox as tkmsg
from tkinter import ttk

_logger = logging.getLogger("index_trader.gui")


def build_desk_gui(ctx: dict) -> None:
    """Build and run the Tkinter trading desk GUI.

    Args:
        ctx: Dictionary with all required context from the parent module.
    """
    # ── Extract context ────────────────────────────────────────────────
    _TK_AVAILABLE = ctx.get("_TK_AVAILABLE", False)
    _gui_alive = ctx.get("_gui_alive", threading.Event())
    GUI_THEME = ctx.get("GUI_THEME", {})
    GUI_WINDOW = ctx.get("GUI_WINDOW", {})
    GUI_UX = ctx.get("GUI_UX", {})
    VERSION = ctx.get("VERSION", "dev")
    PAPER_MODE = ctx.get("PAPER_MODE", True)
    GUI_REFRESH_MS = int(ctx.get("GUI_REFRESH_MS", 2000))
    SCAN_INTERVAL = int(ctx.get("SCAN_INTERVAL", 30))
    _shutdown = ctx.get("_shutdown", threading.Event())
    _display_lock = ctx.get("_display_lock", threading.RLock())
    _display_snapshot = ctx.get("_display_snapshot", {})
    SHUTDOWN_ON_UI_CLOSE = ctx.get("SHUTDOWN_ON_UI_CLOSE", True)
    format_pnl = ctx.get("format_pnl", lambda v: f"{v:+.0f}")
    _format_trading_desk_line = ctx.get("_format_trading_desk_line", lambda s: (str(s or ""), "#c9d1d9"))
    _config_reload_status = ctx.get("_config_reload_status", "Config stable")
    GUI_CONFIRM_EXIT = ctx.get("GUI_CONFIRM_EXIT", True)
    _DEBUG = ctx.get("_DEBUG", False)
    INDEX_PRIORITY = ctx.get("INDEX_PRIORITY", [])
    MAX_LOT_CAPITAL_PCT = ctx.get("MAX_LOT_CAPITAL_PCT", 0.85)
    MIN_NET_RR = ctx.get("MIN_NET_RR", 1.5)
    market_status = ctx.get("market_status", lambda: "UNKNOWN")
    _GUI_PROJECT_ROOT = ctx.get("_GUI_PROJECT_ROOT", str(Path(__file__).resolve().parent.parent))

    # ── Early exit if tkinter not available ────────────────────────────
    if not _TK_AVAILABLE or ttk is None:
        from core.logging import LoggingService

        _gui_logger_svc = LoggingService(
            log_dir="logs",
            log_filename_prefix="gui_",
            retain_days=30,
            json_log_file="",
            version="UNKNOWN",
            enable_correlation_ids=False,
            enable_contextual_logging=False,
        )

        def _gui_log(msg: str, **extra) -> None:
            _gui_logger_svc.log(msg, **extra)

        _gui_log("[GUI] tkinter not available - running headless")
        sys.exit(0)

    # ── Module-level references (imported above) ───────────────────────

    _gui_alive.set()
    _GT = dict(GUI_THEME) if isinstance(GUI_THEME, dict) else {}
    _GW = dict(GUI_WINDOW) if isinstance(GUI_WINDOW, dict) else {}
    _GU = dict(GUI_UX) if isinstance(GUI_UX, dict) else {}
    R = chr(0x20B9)

    # ── Root window ────────────────────────────────────────────────────
    root = tk.Tk()
    _wt = str(_GW.get("window_title") or "Index Option Trader")
    root.title(f"{_wt} v{VERSION} {'[PAPER]' if PAPER_MODE else '[LIVE]'}")
    try:
        root.geometry(str(_GW.get("geometry", "1200x860")))
    except (tk.TclError, RuntimeError):
        root.geometry("1200x860")
    root.configure(bg=_GT.get("bg_main", "#010409"))
    try:
        root.minsize(int(_GW.get("minsize_w", 920)), int(_GW.get("minsize_h", 640)))
    except (tk.TclError, RuntimeError):
        root.minsize(920, 640)
    try:
        root.iconname("IndexTrader")
    except (tk.TclError, RuntimeError):
        _logger.exception("[GUI] Could not set icon name")

    def _gui_report_cb(exc, val, tb) -> None:
        try:
            import traceback
            _logger.log("[GUI CALLBACK] " + "".join(traceback.format_exception(exc, val, tb))[:1500])
        except (tk.TclError, RuntimeError) as _exc:
            _logger.warning("[GUI] Callback logging failed: %s", _exc)

    try:
        root.report_callback_exception = _gui_report_cb
    except (tk.TclError, RuntimeError):
        _logger.warning("[GUI] Could not hook report_callback_exception")

    # ── Layout file path ───────────────────────────────────────────────
    _gui_layout_path = pathlib.Path(_GUI_PROJECT_ROOT) / str(_GW.get("layout_filename", "index_trader_gui_layout.json"))

    def _read_gui_layout() -> dict:
        try:
            if _gui_layout_path.is_file():
                with open(_gui_layout_path, encoding="utf-8") as f:
                    return json.load(f)
        except (tk.TclError, RuntimeError) as e:
            if _gui_layout_path.is_file():
                _logger.log(f"[GUI] index_trader_gui_layout.json unreadable ({e!s}) - using defaults")
        return {}

    def _write_gui_layout() -> None:
        try:
            try:
                _wst = root.state()
            except (tk.TclError, RuntimeError):
                _wst = "normal"
            if _wst not in ("normal", "zoomed", "iconic"):
                _wst = "normal"
            d: dict = {
                "v": 4,
                "geometry": root.geometry(),
                "sash0": None,
                "topmost": bool(_layout_flags.get("topmost")),
                "win_state": _wst,
            }
            try:
                d["sash0"] = int(pan.sashpos(0))
            except (tk.TclError, RuntimeError):
                _logger.debug("[GUI] Could not read sash position")
            with open(_gui_layout_path, "w", encoding="utf-8") as f:
                json.dump(d, f, separators=(",", ":"))
        except (tk.TclError, RuntimeError) as _exc:
            _logger.debug("[GUI] Could not write layout: %s", _exc)

    # ── Layout flags ───────────────────────────────────────────────────
    _gui_layout_saved = _read_gui_layout()
    _layout_flags: dict = {"topmost": False}
    _tp_saved = _gui_layout_saved.get("topmost")
    if _tp_saved is True or (isinstance(_tp_saved, str) and str(_tp_saved).strip().lower() in ("true", "1", "yes")):
        _layout_flags["topmost"] = True
    elif _tp_saved is False or (isinstance(_tp_saved, str) and str(_tp_saved).strip().lower() in ("false", "0", "no")):
        _layout_flags["topmost"] = False

    _geo = _gui_layout_saved.get("geometry")
    if isinstance(_geo, str) and _geo.strip():
        try:
            root.geometry(_geo.strip())
        except (tk.TclError, RuntimeError) as e:
            _logger.log(f"[GUI] Saved window geometry invalid ({e!s}) - using default size")

    _wst_saved = str(_gui_layout_saved.get("win_state") or "").strip().lower()
    if _wst_saved == "zoomed":
        def _restore_maximized() -> None:
            try:
                root.state("zoomed")
            except (tk.TclError, RuntimeError) as e:
                _logger.log(f"[GUI] Could not restore maximized state ({e!s})")

        root.after(int(_GW.get("restore_zoom_delay_ms", 250)), _restore_maximized)

    # ── Font setup ─────────────────────────────────────────────────────
    try:
        _fam_avail = set(x.lower() for x in tkfont.families(root))
    except (tk.TclError, RuntimeError):
        _fam_avail = set()

    def _fam_ok(nm: str) -> bool:
        return not _fam_avail or str(nm).lower() in _fam_avail

    _pref_ui = str(_GW.get("font_ui_preferred") or "").strip()
    _pref_mo = str(_GW.get("font_mono_preferred") or "").strip()
    _FONT_UI = _pref_ui if _pref_ui and _fam_ok(_pref_ui) else ("Segoe UI" if _fam_ok("Segoe UI") else ("Tahoma" if _fam_ok("Tahoma") else "TkDefaultFont"))
    _FONT_MONO = _pref_mo if _pref_mo and _fam_ok(_pref_mo) else ("Consolas" if _fam_ok("Consolas") else ("Courier New" if _fam_ok("Courier New") else "Courier"))

    # ── Color constants ────────────────────────────────────────────────
    bg_main = _GT.get("bg_main", "#010409")
    bg_card = _GT.get("bg_card", "#161b22")
    bd = _GT.get("bd", "#30363d")
    accent = _GT.get("accent", "#58a6ff")
    _trh = int(_GU.get("tree_row_height", 26))

    # ── Style ──────────────────────────────────────────────────────────
    style = ttk.Style()
    try:
        style.theme_use("clam")
    except (tk.TclError, RuntimeError) as _exc:
        _logger.debug("[GUI] Could not set theme: %s", _exc)

    style.configure("Gui.Treeview",
                     background=_GT.get("tree_bg", "#0d1117"),
                     foreground=_GT.get("tree_fg", "#c9d1d9"),
                     fieldbackground=_GT.get("tree_bg", "#0d1117"),
                     rowheight=_trh,
                     font=(_FONT_UI, 9))
    style.configure("Gui.Treeview.Heading",
                     background=_GT.get("heading_bg", "#21262d"),
                     foreground=accent,
                     font=(_FONT_UI, 9, "bold"))
    style.map("Gui.Treeview",
              background=[("selected", _GT.get("select_bg", "#1f6feb"))],
              foreground=[("selected", _GT.get("select_fg", "#ffffff"))])
    try:
        style.configure("TPanedwindow", background=bg_main)
        style.configure("Sash", background=_GT.get("scrollbar_bg", "#30363d"), troughcolor=bg_main)
    except (tk.TclError, RuntimeError) as _exc:
        _logger.debug("[GUI] Could not configure style: %s", _exc)

    # ── Header ─────────────────────────────────────────────────────────
    header = tk.Frame(root, bg=bg_card, height=int(_GW.get("header_height", 48)))
    header.pack(fill=tk.X, side=tk.TOP)
    left_h = tk.Frame(header, bg=bg_card)
    left_h.pack(side=tk.LEFT, fill=tk.Y, padx=10, pady=6)
    tk.Label(left_h, text=_wt, font=(_FONT_UI, 13, "bold"), bg=bg_card, fg=accent).pack(anchor="w")
    lbl_header_hint = tk.Label(left_h, text="", font=(_FONT_UI, 8), bg=bg_card, fg=_GT.get("fg_muted", "#8b949e"))
    lbl_header_hint.pack(anchor="w")
    lbl_config_status = tk.Label(left_h, text="Config stable", font=(_FONT_UI, 8), bg=bg_card, fg=accent)
    lbl_config_status.pack(anchor="w", pady=(2, 0))

    def _sync_header_hint() -> None:
        try:
            rs = max(1, (GUI_REFRESH_MS + 500) // 1000)
            lbl_header_hint.config(text=f"KPI · desk · index table · full log · ~{rs}s UI · scan {SCAN_INTERVAL}s · Ctrl+F · layout JSON")
        except (tk.TclError, RuntimeError):
            _logger.debug("[GUI] Could not update header hint")

    _sync_header_hint()

    right_h = tk.Frame(header, bg=bg_card)
    right_h.pack(side=tk.RIGHT, padx=10, pady=6)
    mode_lbl = tk.Label(right_h, text=" PAPER ", font=(_FONT_UI, 10, "bold"),
                        bg=_GT.get("mode_paper", "#9e6a03"), fg="#ffffff", padx=8, pady=2)
    mode_lbl.pack(side=tk.RIGHT, padx=(8, 0))
    status_lbl = tk.Label(right_h, text=" STARTING ", font=(_FONT_UI, 10, "bold"),
                          bg=_GT.get("heading_bg", "#21262d"), fg=_GT.get("warn", "#f0883e"), padx=10, pady=2)
    status_lbl.pack(side=tk.RIGHT)

    # ── KPI cards ──────────────────────────────────────────────────────
    kpi_outer = tk.Frame(root, bg=bg_main)
    kpi_outer.pack(fill=tk.X, padx=10, pady=(10, 6))

    def _card(parent, title, subtitle=False):
        f = tk.Frame(parent, bg=bg_card, highlightbackground=bd, highlightthickness=1)
        tk.Label(f, text=title, font=(_FONT_UI, 8), bg=bg_card, fg=_GT.get("fg_muted", "#8b949e")).pack(anchor="w", padx=10, pady=(8, 0))
        v = tk.Label(f, text="-", font=(_FONT_UI, 14, "bold"), bg=bg_card, fg=_GT.get("fg_bright", "#f0f6fc"))
        v.pack(anchor="w", padx=10, pady=(0, 8))
        if subtitle:
            s = tk.Label(f, text="", font=(_FONT_UI, 8), bg=bg_card, fg=_GT.get("fg_dim", "#6e7681"))
            s.pack(anchor="w", padx=10, pady=(0, 6))
            return f, v, s
        return f, v

    kpi_row = tk.Frame(kpi_outer, bg=bg_main)
    kpi_row.pack(fill=tk.X)
    for i in range(4):
        kpi_row.grid_columnconfigure(i, weight=1)
    c0, v_time, v_time_sub = _card(kpi_row, "Last update", True)
    c0.grid(row=0, column=0, padx=(0, 6), sticky=tk.EW)
    c1, v_cap, v_cap_sub = _card(kpi_row, "Capital", True)
    c1.grid(row=0, column=1, padx=6, sticky=tk.EW)
    c2, v_pnl, v_pnl_sub = _card(kpi_row, "Day P&L", True)
    c2.grid(row=0, column=2, padx=6, sticky=tk.EW)
    c3, v_tr = _card(kpi_row, "Trades / Open slots")
    c3.grid(row=0, column=3, padx=(6, 0), sticky=tk.EW)

    # ── Trading desk ───────────────────────────────────────────────────
    desk_fr = tk.Frame(root, bg=_GT.get("desk_bg", "#0d1117"), highlightbackground=bd, highlightthickness=1)
    desk_fr.pack(fill=tk.X, padx=10, pady=(0, 8))
    tk.Label(desk_fr, text="TRADING DESK - risk, data & how your orders are handled",
             font=(_FONT_UI, 8, "bold"), bg=_GT.get("desk_bg", "#0d1117"),
             fg=_GT.get("desk_title", "#8b949e")).pack(anchor="w", padx=10, pady=(8, 0))
    lbl_desk = tk.Label(desk_fr, text="Waiting for first dashboard snapshot…",
                        font=(_FONT_UI, 9), bg=_GT.get("desk_bg", "#0d1117"),
                        fg=_GT.get("fg_label", "#c9d1d9"),
                        anchor="w", justify="left",
                        wraplength=int(_GU.get("default_wraplength_desk", 1040)))
    lbl_desk.pack(fill=tk.X, padx=10, pady=(4, 4))
    lbl_manual_flow = tk.Label(desk_fr, text="", font=(_FONT_UI, 9),
                               bg=_GT.get("desk_bg", "#0d1117"),
                               fg=_GT.get("accent_soft", "#79c0ff"),
                               anchor="w", justify="left",
                               wraplength=int(_GU.get("default_wraplength_desk", 1040)))
    lbl_manual_flow.pack(fill=tk.X, padx=10, pady=(0, 10))

    # ── Info row ───────────────────────────────────────────────────────
    info_row = tk.Frame(root, bg=bg_main)
    info_row.pack(fill=tk.X, padx=10, pady=(0, 8))
    lbl_headline = tk.Label(info_row, text="Waiting for first scan…",
                            font=(_FONT_UI, 11, "bold"),
                            bg=_GT.get("heading_bg", "#21262d"),
                            fg=_GT.get("fg_label", "#c9d1d9"),
                            anchor="w", padx=12, pady=8, wraplength=1050, justify="left")
    lbl_headline.pack(fill=tk.X)
    sub_info = tk.Frame(info_row, bg=bg_main)
    sub_info.pack(fill=tk.X, pady=(6, 0))
    lbl_tg = tk.Label(sub_info, text="", font=(_FONT_UI, 9), bg=bg_main,
                      fg=_GT.get("accent_soft", "#79c0ff"), anchor="w")
    lbl_tg.pack(fill=tk.X)
    lbl_api = tk.Label(sub_info, text="", font=(_FONT_UI, 9), bg=bg_main,
                       fg=_GT.get("warn", "#d29922"), anchor="w")
    lbl_api.pack(fill=tk.X)
    lbl_last_tg = tk.Label(sub_info, text="", font=(_FONT_UI, 8), bg=bg_main,
                           fg=_GT.get("tg_muted", "#bc8cff"), anchor="w",
                           wraplength=1080, justify="left")
    lbl_last_tg.pack(fill=tk.X, pady=(4, 0))
    lbl_gui_err = tk.Label(sub_info, text="", font=(_FONT_UI, 8), bg=bg_main,
                           fg=_GT.get("err", "#f85149"), anchor="w",
                           wraplength=1080, justify="left")
    lbl_gui_err.pack(fill=tk.X, pady=(2, 0))

    # ── Body paned window ──────────────────────────────────────────────
    body = tk.Frame(root, bg=bg_main)
    body.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 6))
    pan = ttk.Panedwindow(body, orient=tk.HORIZONTAL)
    pan.pack(fill=tk.BOTH, expand=True)
    left_col = tk.Frame(pan, bg=bg_main)
    right_col = tk.Frame(pan, bg=bg_main)
    pan.add(left_col)
    pan.add(right_col)
    try:
        pan.paneconfig(left_col, weight=1, minsize=int(_GW.get("pane_minsize_left", 280)))
        pan.paneconfig(right_col, weight=2, minsize=int(_GW.get("pane_minsize_right", 300)))
    except (tk.TclError, RuntimeError) as _exc:
        _logger.debug("[GUI] Could not set pane config: %s", _exc)

    # ── Layout save scheduling ─────────────────────────────────────────
    _layout_save_sched: list = [None]

    def _queue_gui_layout_save(_evt=None) -> None:
        if _layout_save_sched[0] is not None:
            try:
                root.after_cancel(_layout_save_sched[0])
            except (tk.TclError, RuntimeError):
                _logger.debug("[GUI] Could not cancel layout save timer")
        _layout_save_sched[0] = root.after(int(_GW.get("layout_save_debounce_ms", 1500)), _write_gui_layout)

    # ── Wrap sync ──────────────────────────────────────────────────────
    _wrap_sync_sched: list = [None]

    def _sync_wraplength() -> None:
        try:
            w = max(280, int(root.winfo_width()) - int(_GU.get("wrap_margin_px", 56)))
            lbl_headline.config(wraplength=w)
            lbl_tg.config(wraplength=w)
            lbl_api.config(wraplength=w)
            lbl_last_tg.config(wraplength=w)
            lbl_gui_err.config(wraplength=w)
            try:
                lbl_desk.config(wraplength=max(360, w - 24))
            except (tk.TclError, RuntimeError):
                _logger.debug("[GUI] Could not sync desk wraplength")
            try:
                lbl_manual_flow.config(wraplength=max(360, w - 24))
            except (tk.TclError, RuntimeError):
                _logger.debug("[GUI] Could not sync manual flow wraplength")
            ww = max(220, min(520, w // 2 + 40))
            for ch in wait_inner.winfo_children():
                if isinstance(ch, tk.Label):
                    ch.config(wraplength=ww)
        except (tk.TclError, RuntimeError):
            _logger.debug("[GUI] Could not sync wraplength")

    def _queue_wrap_sync() -> None:
        if _wrap_sync_sched[0] is not None:
            try:
                root.after_cancel(_wrap_sync_sched[0])
            except (tk.TclError, RuntimeError):
                _logger.debug("[GUI] Could not cancel wrap sync timer")
        _wrap_sync_sched[0] = root.after(int(_GW.get("wrap_sync_debounce_ms", 120)), _sync_wraplength)

    # ── Configure event bindings ───────────────────────────────────────
    def _on_root_configure(e) -> None:
        if getattr(e, "widget", None) is root:
            _queue_gui_layout_save()
            _queue_wrap_sync()

    root.bind("<Configure>", _on_root_configure)

    def _on_root_map(e) -> None:
        if getattr(e, "widget", None) is root:
            _queue_wrap_sync()

    root.bind("<Map>", _on_root_map)
    try:
        left_col.bind("<Configure>", lambda e: _queue_gui_layout_save())
        right_col.bind("<Configure>", lambda e: _queue_gui_layout_save())
        pan.bind("<ButtonRelease-1>", lambda e: _queue_gui_layout_save())
    except (tk.TclError, RuntimeError) as _exc:
        _logger.debug("[GUI] Could not bind configure events: %s", _exc)

    # ── Table setup ────────────────────────────────────────────────────
    left_col.grid_columnconfigure(0, weight=1)
    left_col.grid_rowconfigure(1, weight=1)
    tk.Label(left_col, text="Index snapshot - drag divider to widen status column",
             font=(_FONT_UI, 9, "bold"), bg=bg_main, fg=accent).grid(row=0, column=0, sticky="w")

    tbl_fr = tk.Frame(left_col, bg=bd, bd=0)
    tbl_fr.grid(row=1, column=0, sticky=tk.NSEW, pady=(4, 0))
    cols = ("idx", "price", "pct", "dir", "score", "thr", "gap", "adx", "iv", "reg", "st")
    tv = ttk.Treeview(tbl_fr, columns=cols, show="headings", height=8,
                      style="Gui.Treeview", selectmode="none", takefocus=0)
    for col_name in cols:
        tv.heading(col_name, text={"idx": "Index", "price": "Price", "pct": "Day %",
                                    "dir": "Dir", "score": "Score", "thr": "Thr",
                                    "gap": "Gap", "adx": "ADX", "iv": "IV",
                                    "reg": "Reg", "st": "Status / gate"}.get(col_name, col_name))
    tv.column("idx", width=82, stretch=False)
    tv.column("price", width=86, stretch=False)
    tv.column("pct", width=58, stretch=False)
    tv.column("dir", width=34, stretch=False)
    tv.column("score", width=46, stretch=False)
    tv.column("thr", width=40, stretch=False)
    tv.column("gap", width=40, stretch=False)
    tv.column("adx", width=42, stretch=False)
    tv.column("iv", width=40, stretch=False)
    tv.column("reg", width=56, stretch=False)
    tv.column("st", width=280, stretch=True)
    tsy = tk.Scrollbar(tbl_fr, command=tv.yview)
    tv.configure(yscrollcommand=tsy.set)
    tv.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    tsy.pack(side=tk.RIGHT, fill=tk.Y)
    tv.tag_configure("pass", foreground=_GT.get("profit", "#3fb950"))
    tv.tag_configure("watch", foreground=_GT.get("warn", "#d29922"))
    tv.tag_configure("wait", foreground=_GT.get("fg_muted", "#8b949e"))

    # ── Legend ─────────────────────────────────────────────────────────
    leg = tk.Frame(left_col, bg=bg_main)
    leg.grid(row=2, column=0, sticky="w", pady=(6, 0))
    tk.Label(leg, text="Regime: TR=Trend  N=Neutral  CH=Chop  EV=Event  -=n/a",
             font=(_FONT_UI, 8), bg=bg_main, fg="#6e7681").pack(anchor="w")
    tk.Label(leg, text="Status: PASS (≥thr) · WATCH (below thr) · WAIT (gated) · IV = option IV from chain",
             font=(_FONT_UI, 8), bg=bg_main, fg="#6e7681").pack(anchor="w")

    # ── Wait reasons ───────────────────────────────────────────────────
    wait_fr = tk.Frame(left_col, bg=bg_card, highlightbackground=bd, highlightthickness=1)
    wait_fr.grid(row=3, column=0, sticky=tk.EW, pady=(8, 0))
    tk.Label(wait_fr, text="Why entries are blocked (per index)",
             font=(_FONT_UI, 9, "bold"), bg=bg_card, fg="#f0883e").pack(anchor="w", padx=8, pady=(6, 2))
    wait_inner = tk.Frame(wait_fr, bg=bg_card)
    wait_inner.pack(fill=tk.X, padx=6, pady=(0, 6))

    # ── Pre-signal ─────────────────────────────────────────────────────
    pre_fr = tk.Frame(left_col, bg=bg_card, highlightbackground=bd, highlightthickness=1)
    pre_fr.grid(row=4, column=0, sticky=tk.EW, pady=(8, 0))
    tk.Label(pre_fr, text="Closest watchlist setup (not an entry yet)",
             font=(_FONT_UI, 9, "bold"), bg=bg_card, fg="#79c0ff").pack(anchor="w", padx=8, pady=(6, 2))
    pre_lbl = tk.Label(pre_fr, text="Waiting for first scan…", bg=bg_card,
                       fg=_GT.get("fg_label", "#c9d1d9"), font=(_FONT_UI, 9),
                       wraplength=int(_GU.get("wait_wrap_max", 520)), justify="left")
    pre_lbl.pack(anchor="w", padx=8, pady=(0, 6))

    # ── Right column: Detail text ──────────────────────────────────────
    right_col.grid_columnconfigure(0, weight=1)
    right_col.grid_rowconfigure(1, weight=1)
    detail_fr = tk.Frame(right_col, bg=bg_main)
    detail_fr.grid(row=1, column=0, sticky=tk.NSEW)
    detail_fr.grid_rowconfigure(0, weight=1)
    detail_fr.grid_columnconfigure(0, weight=1)
    tw = tk.Text(detail_fr, font=(_FONT_MONO, 9), bg=_GT.get("tree_bg", "#0d1117"),
                 fg=_GT.get("tree_fg", "#c9d1d9"), wrap=tk.WORD, state=tk.DISABLED,
                 borderwidth=0, padx=10, pady=8, insertbackground=accent,
                 selectbackground="#1f6feb", takefocus=1,
                 highlightthickness=1, highlightbackground="#30363d", highlightcolor=accent)
    dsy = tk.Scrollbar(detail_fr, command=tw.yview)
    tw.configure(yscrollcommand=dsy.set)
    tw.grid(row=0, column=0, sticky=tk.NSEW)
    dsy.grid(row=0, column=1, sticky=tk.NS)
    lbl_detail_hdr = tk.Label(right_col,
                              text="Signal & dashboard log - read-only · click to focus · Ctrl+A select all · Ctrl+C copy · Ctrl+F find",
                              font=(_FONT_UI, 9, "bold"), bg=bg_main, fg=accent, cursor="hand2")
    lbl_detail_hdr.grid(row=0, column=0, sticky="w", pady=(0, 4))
    lbl_detail_hdr.bind("<Button-1>", lambda _e: tw.focus_set())

    # ── Scrollbar colors ───────────────────────────────────────────────
    _sb_bg = _GT.get("scrollbar_bg", "#30363d")
    _sb_trough = _GT.get("scrollbar_trough", "#161b22")
    for _sb in (tsy, dsy):
        try:
            _sb.config(troughcolor=_sb_trough, bg=_sb_bg, activebackground="#484f58",
                       highlightthickness=0, bd=0, width=12)
        except (tk.TclError, RuntimeError):
            try:
                _sb.config(bg=_sb_bg, highlightthickness=0)
            except (tk.TclError, RuntimeError) as _exc:
                _logger.debug("[GUI] Could not configure scrollbar: %s", _exc)

    # ── Text tags ──────────────────────────────────────────────────────
    tw.tag_configure("header", foreground=accent, font=(_FONT_MONO, 9, "bold"))
    tw.tag_configure("profit", foreground="#3fb950")
    tw.tag_configure("loss", foreground="#f85149")
    tw.tag_configure("alert", foreground="#f0883e", font=(_FONT_MONO, 9, "bold"))
    tw.tag_configure("section", foreground="#8b949e", font=(_FONT_MONO, 9, "bold"))
    tw.tag_configure("signal_buy", foreground="#3fb950", font=(_FONT_MONO, 9, "bold"))
    tw.tag_configure("signal_watch", foreground="#d29922")
    tw.tag_configure("blocked", foreground="#d29922", font=(_FONT_MONO, 9, "bold"))
    tw.tag_configure("err", foreground="#f85149", font=(_FONT_MONO, 9, "bold"))
    tw.tag_configure("dim", foreground="#484f58")
    tw.tag_configure("separator", foreground="#30363d")
    tw.tag_configure("layman", foreground="#79c0ff", font=(_FONT_UI, 9))

    # ── Scrolling ──────────────────────────────────────────────────────
    def _on_wheel_text(e):
        try:
            tw.yview_scroll(int(-1 * (e.delta / 120)), "units")
        except (tk.TclError, RuntimeError):
            _logger.debug("[GUI] text wheel scroll failed")

    def _on_wheel_tree(e):
        try:
            tv.yview_scroll(int(-1 * (e.delta / 120)), "units")
        except (tk.TclError, RuntimeError):
            _logger.debug("[GUI] tree wheel scroll failed")

    tw.bind("<MouseWheel>", _on_wheel_text)
    detail_fr.bind("<MouseWheel>", _on_wheel_text)
    tv.bind("<MouseWheel>", _on_wheel_tree)
    tbl_fr.bind("<MouseWheel>", _on_wheel_tree)
    for evt, direction in [("<Button-4>", -2), ("<Button-5>", 2)]:
        detail_fr.bind(evt, lambda e, d=direction: tw.yview_scroll(d, "units"))
        tw.bind(evt, lambda e, d=direction: tw.yview_scroll(d, "units"))
        tv.bind(evt, lambda e, d=direction: tv.yview_scroll(d, "units"))
        tbl_fr.bind(evt, lambda e, d=direction: tv.yview_scroll(d, "units"))

    # ── Clipboard ──────────────────────────────────────────────────────
    def _clipboard_flush() -> None:
        try:
            root.update_idletasks()
        except (tk.TclError, RuntimeError):
            _logger.debug("[GUI] clipboard flush failed")

    def _copy_details_selection(_e=None) -> None:
        try:
            tw.config(state=tk.NORMAL)
            if tw.tag_ranges("sel"):
                tx = tw.get("sel.first", "sel.last")
            else:
                tx = ""
            tw.config(state=tk.DISABLED)
            if tx:
                root.clipboard_clear()
                root.clipboard_append(tx)
                _clipboard_flush()
        except (tk.TclError, RuntimeError):
            _logger.debug("[GUI] copy selection failed")
        return "break"

    def _copy_details_all() -> None:
        try:
            tw.config(state=tk.NORMAL)
            tx = tw.get("1.0", tk.END).rstrip()
            tw.config(state=tk.DISABLED)
            root.clipboard_clear()
            root.clipboard_append(tx[:16000])
            _clipboard_flush()
        except (tk.TclError, RuntimeError):
            _logger.debug("[GUI] copy all failed")

    def _select_details_all(_e=None) -> None:
        try:
            tw.config(state=tk.NORMAL)
            tw.tag_remove("sel", "1.0", tk.END)
            tw.tag_add("sel", "1.0", tk.END)
            tw.config(state=tk.DISABLED)
        except (tk.TclError, RuntimeError):
            _logger.debug("[GUI] select all failed")
        return "break"

    def _clear_details_sel(_e=None) -> None:
        try:
            tw.config(state=tk.NORMAL)
            tw.tag_remove("sel", "1.0", tk.END)
            tw.config(state=tk.DISABLED)
        except (tk.TclError, RuntimeError):
            _logger.debug("[GUI] clear selection failed")
        return "break"

    tw.bind("<Control-c>", _copy_details_selection)
    tw.bind("<Control-C>", _copy_details_selection)
    tw.bind("<Control-a>", _select_details_all)
    tw.bind("<Control-A>", _select_details_all)
    tw.bind("<Escape>", _clear_details_sel)

    # ── Text navigation shortcuts ──────────────────────────────────────
    def _tw_scroll_top(_e=None) -> None:
        try:
            tw.config(state=tk.NORMAL)
            tw.see("1.0")
            tw.config(state=tk.DISABLED)
        except (tk.TclError, RuntimeError):
            _logger.debug("[GUI] tw scroll to top failed")
        return "break"

    def _tw_scroll_bottom(_e=None) -> None:
        try:
            tw.config(state=tk.NORMAL)
            tw.see(tk.END)
            tw.config(state=tk.DISABLED)
        except (tk.TclError, RuntimeError):
            _logger.debug("[GUI] tw scroll to bottom failed")
        return "break"

    def _tw_pgup(_e=None) -> None:
        try:
            tw.config(state=tk.NORMAL)
            tw.yview_scroll(-1, "pages")
            tw.config(state=tk.DISABLED)
        except (tk.TclError, RuntimeError):
            _logger.debug("[GUI] tw page up failed")
        return "break"

    def _tw_pgdn(_e=None) -> None:
        try:
            tw.config(state=tk.NORMAL)
            tw.yview_scroll(1, "pages")
            tw.config(state=tk.DISABLED)
        except (tk.TclError, RuntimeError):
            _logger.debug("[GUI] tw page down failed")
        return "break"

    for seq, handler in [
        ("<Home>", _tw_scroll_top), ("<End>", _tw_scroll_bottom),
        ("<Prior>", _tw_pgup), ("<Next>", _tw_pgdn),
        ("<Control-Home>", _tw_scroll_top), ("<Control-End>", _tw_scroll_bottom),
    ]:
        tw.bind(seq, handler)

    # ── Find dialog ────────────────────────────────────────────────────
    _find_win: list = [None]
    _find_var = tk.StringVar(master=root, value="")
    _find_resume: list = [None]

    def _open_find_details() -> None:
        if _find_win[0] is not None:
            try:
                if _find_win[0].winfo_exists():
                    _find_win[0].deiconify()
                    _find_win[0].lift()
                    _find_win[0].focus_force()
                    return
            except (tk.TclError, RuntimeError):
                _find_win[0] = None
        _find_resume[0] = None
        w = tk.Toplevel(root)
        w.title("Find in details")
        try:
            w.transient(root)
        except (tk.TclError, RuntimeError):
            _logger.debug("[GUI] Could not set transient for find window")
        w.configure(bg=bg_card)
        w.resizable(False, False)
        fr = tk.Frame(w, bg=bg_card, padx=12, pady=10)
        fr.pack(fill=tk.BOTH, expand=True)
        tk.Label(fr, text="Search (case-insensitive) - Enter / F3 = next, Esc = close:",
                 bg=bg_card, fg="#c9d1d9", font=(_FONT_UI, 9)).pack(anchor="w")
        en = tk.Entry(fr, textvariable=_find_var, width=44, bg="#0d1117", fg="#c9d1d9",
                      insertbackground=accent, relief=tk.FLAT,
                      highlightthickness=1, highlightbackground=bd)
        en.pack(fill=tk.X, pady=(4, 6))
        st_lbl = tk.Label(fr, text="", bg=bg_card, fg="#8b949e", font=(_FONT_UI, 8))
        st_lbl.pack(anchor="w", pady=(0, 8))
        btnr = tk.Frame(fr, bg=bg_card)
        btnr.pack(fill=tk.X)

        def _do_find_next() -> None:
            q = _find_var.get().strip()
            if not q:
                st_lbl.config(text="Enter text to find.", fg="#f0883e")
                return
            try:
                tw.config(state=tk.NORMAL)
                start = _find_resume[0]
                if start is None:
                    try:
                        start = tw.index("insert")
                    except (tk.TclError, RuntimeError):
                        start = "1.0"
                pos = tw.search(q, start, tk.END, nocase=True, regexp=False)
                if not pos:
                    pos = tw.search(q, "1.0", tk.END, nocase=True, regexp=False)
                    _find_resume[0] = None
                if pos:
                    try:
                        end = tw.index(f"{pos} + {len(q)} chars")
                    except (tk.TclError, RuntimeError):
                        end = tw.index(f"{pos}+{len(q)}c")
                    tw.tag_remove("sel", "1.0", tk.END)
                    tw.tag_add("sel", pos, end)
                    tw.mark_set("insert", end)
                    tw.see(pos)
                    _find_resume[0] = end
                    st_lbl.config(text="Match selected - Find next for more.", fg="#3fb950")
                else:
                    _find_resume[0] = None
                    st_lbl.config(text="No match (searched whole log).", fg="#f0883e")
            except Exception as ex:
                st_lbl.config(text=f"Error: {ex!s}"[:120], fg="#f85149")
            finally:
                try:
                    tw.config(state=tk.DISABLED)
                except (tk.TclError, RuntimeError):
                    _logger.debug("[GUI] Could not disable text widget after find")

        def _close_find() -> None:
            try:
                w.destroy()
            except (tk.TclError, RuntimeError):
                _logger.debug("[GUI] Could not destroy find window")
            _find_win[0] = None
            _find_resume[0] = None

        tk.Button(btnr, text="Find next", command=_do_find_next,
                  bg="#21262d", fg="#c9d1d9", activebackground="#30363d").pack(side=tk.LEFT, padx=(0, 8))
        tk.Button(btnr, text="Close", command=_close_find,
                  bg="#21262d", fg="#c9d1d9", activebackground="#30363d").pack(side=tk.LEFT)
        w.protocol("WM_DELETE_WINDOW", _close_find)
        w.bind("<Escape>", lambda e: _close_find())
        w.bind("<Return>", lambda e: _do_find_next())
        w.bind("<F3>", lambda e: _do_find_next())
        _find_win[0] = w
        en.focus_set()

    def _accel_find(_e=None) -> None:
        _open_find_details()
        return "break"

    tw.bind("<Control-f>", _accel_find)
    tw.bind("<Control-F>", _accel_find)

    # ── Context menu ───────────────────────────────────────────────────
    def _details_context(e):
        has_sel = False
        try:
            tw.config(state=tk.NORMAL)
            has_sel = bool(tw.tag_ranges("sel"))
        except (tk.TclError, RuntimeError):
            _logger.debug("[GUI] Could not check text selection range")
        try:
            tw.config(state=tk.DISABLED)
        except (tk.TclError, RuntimeError):
            _logger.debug("[GUI] Could not disable text widget after context menu")
        cm = tk.Menu(root, tearoff=0, bg=bg_card, fg="#c9d1d9",
                     activebackground="#21262d", activeforeground="#f0f6fc")
        cm.add_command(label="Select all", command=lambda: _select_details_all(None))
        cm.add_command(label="Copy selection", command=_copy_details_selection,
                       state=tk.NORMAL if has_sel else tk.DISABLED)
        cm.add_command(label="Copy all details", command=_copy_details_all)
        cm.add_command(label="Save details as…", command=_save_details_as)
        cm.add_command(label="Find in details…", command=_open_find_details)
        cm.add_separator()
        cm.add_command(label="Scroll to top", command=lambda: _tw_scroll_top(None))
        cm.add_command(label="Scroll to bottom", command=lambda: _tw_scroll_bottom(None))
        try:
            cm.tk_popup(e.x_root, e.y_root)
        finally:
            try:
                cm.grab_release()
            except (tk.TclError, RuntimeError):
                _logger.debug("[GUI] Could not release context menu grab")

    tw.bind("<Button-3>", _details_context)

    # ── Sash init ──────────────────────────────────────────────────────
    def _init_pan_sash():
        try:
            sp = _gui_layout_saved.get("sash0")
            _psmin = int(_GW.get("pane_sash_min", 220))
            _psmax = int(_GW.get("pane_sash_max", 1400))
            _pdsmin = int(_GW.get("pane_sash_default_min", 380))
            _pdsmax = int(_GW.get("pane_sash_default_max", 520))
            if isinstance(sp, (int, float)) and _psmin < int(sp) < _psmax:
                pan.sashpos(0, int(sp))
            else:
                w = max(_pdsmin, min(_pdsmax, root.winfo_width() // 2))
                pan.sashpos(0, w)
        except (tk.TclError, RuntimeError):
            _logger.debug("[GUI] Could not initialize sash position")

    root.after(int(_GW.get("init_sash_delay_ms", 300)), _init_pan_sash)

    # ── Scheduler ──────────────────────────────────────────────────────
    sched_after: list = [None]
    _last_gui_tw_text: list = [None]

    def _cancel_sched_after() -> None:
        if sched_after[0] is not None:
            try:
                root.after_cancel(sched_after[0])
            except (tk.TclError, ValueError, RuntimeError):
                pass
            sched_after[0] = None

    # ── Color application ──────────────────────────────────────────────
    def _apply_colors(widget, text):
        widget.config(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        for line in text.split("\n"):
            tag = None
            ll = line.strip()
            if ll.startswith("\u2550"):
                tag = "separator"
            elif ll.startswith("\u2500"):
                tag = "separator"
            elif "INDEX OPTION TRADER" in line:
                tag = "header"
            elif "Capital:" in line and "P&L:" in line:
                tag = "header"
            elif "ACTION ALERTS" in line:
                tag = "signal_buy"
            elif "WATCHLIST" in line:
                tag = "signal_watch"
            elif "OPEN POSITIONS" in line:
                tag = "alert"
            elif "LIVE INDEX PRICES" in line:
                tag = "section"
            elif "WAITING" in line:
                tag = "dim"
            elif "[ERROR]" in ll or "[SILENT_ERR]" in ll or "TRACEBACK" in ll or "EXCEPTION" in ll:
                tag = "err"
            elif "[WARN]" in ll or "\u26a0\ufe0f" in line:
                tag = "blocked"
            elif "[SIGNAL]" in ll:
                tag = "signal_buy"
            elif "[BLOCKED]" in ll or "\U0001f6d1" in line or "\u274c" in line:
                tag = "blocked"
            elif "AT A GLANCE" in line:
                tag = "layman"
            elif "HOW TO READ" in line:
                tag = "layman"
            elif "REAL SIGNAL" in line:
                tag = "layman"
            elif "\u25b2" in line and "+" in line:
                tag = "profit"
            elif "\u25bc" in line and "-" in line:
                tag = "loss"
            elif "WHY:" in line:
                tag = "dim"
            elif "NO OPEN POSITIONS" in line:
                tag = "dim"
            elif "SIMPLE GUIDE" in line or line.strip().startswith("\u2022"):
                tag = "layman"
            if tag:
                widget.insert(tk.END, line + "\n", tag)
            else:
                widget.insert(tk.END, line + "\n")
        widget.config(state=tk.DISABLED)

    # ── Main _update function ──────────────────────────────────────────
    def _update():
        try:
            if not root.winfo_exists():
                return
        except tk.TclError:
            return
        if _shutdown.is_set():
            _cancel_sched_after()
            try:
                root.quit()
            except (tk.TclError, RuntimeError):
                _logger.debug("[GUI] Could not quit root on shutdown")
            return
        with _display_lock:
            struct = _display_snapshot.get("struct")
            full_txt = _display_snapshot.get("text", "  Waiting for first scan cycle\u2026")
            snap_ts = _display_snapshot.get("ts")
        detail = ""
        if isinstance(struct, dict) and struct.get("detail_text"):
            detail = struct["detail_text"]
        else:
            di = full_txt.find("\n  LIVE INDEX PRICES")
            detail = full_txt[di:] if di >= 0 else full_txt
        struct_ok = isinstance(struct, dict) and "capital" in struct
        try:
            lbl_gui_err.config(text="")
            if struct_ok:
                v_time.config(text=struct.get("time", "\u2014"))
                _sub = ("IST \u00b7 closing this window stops the bot & exits" if SHUTDOWN_ON_UI_CLOSE else "IST")
                try:
                    _sw = int(_GU.get("snapshot_warn_sec", 45))
                    _sh = int(_GU.get("snapshot_hint_sec", 20))
                    if isinstance(snap_ts, (int, float)) and snap_ts > 0:
                        _ag = int(max(0, time.time() - snap_ts))
                        if _ag >= _sw:
                            _sub = f"{_sub} \u00b7 data {_ag}s old \u2014 check bot if frozen"
                        elif _ag >= _sh:
                            _sub = f"{_sub} \u00b7 snapshot {_ag}s ago"
                except (tk.TclError, RuntimeError):
                    _logger.debug("[GUI] Could not compute snapshot age")
                try:
                    _lc = int(_GU.get("loop_lag_critical_sec", 120))
                    _lw = int(_GU.get("loop_lag_warn_sec", 45))
                    _lh = int(_GU.get("loop_lag_hint_sec", 18))
                    if struct.get("status") == "OPEN":
                        _lag = int(struct.get("loop_lag_s") or 0)
                        if _lag >= _lc:
                            _sub = f"{_sub} \u00b7 main loop gap {_lag}s (watchdog risk)"
                        elif _lag >= _lw:
                            _sub = f"{_sub} \u00b7 loop idle {_lag}s"
                        elif _lag >= _lh:
                            _sub = f"{_sub} \u00b7 loop {_lag}s"
                except (tk.TclError, RuntimeError):
                    _logger.debug("[GUI] Could not compute loop lag")
                try:
                    nf = int(struct.get("nse_fails", 0) or 0)
                    yf = int(struct.get("yf_fails", 0) or 0)
                    api_s = "API OK" if (nf + yf) == 0 else f"API NSE:{nf} YF:{yf}"
                    _sub = f"{_sub} \u00b7 {api_s}"
                except (tk.TclError, RuntimeError):
                    _logger.debug("[GUI] Could not compute API status")
                try:
                    _ssi = struct.get("scan_interval_s")
                    _gri = struct.get("gui_refresh_ms")
                    if isinstance(_ssi, (int, float)) and isinstance(_gri, (int, float)):
                        _sub = f"{_sub} \u00b7 scan {int(_ssi)}s \u00b7 UI {int(_gri)}ms"
                except (tk.TclError, RuntimeError):
                    _logger.debug("[GUI] Could not compute scan interval")
                v_time_sub.config(text=_sub)
                v_cap.config(text=f"{R}{struct.get('capital', 0):,.0f}")
                try:
                    av = float(struct.get("available_capital") or 0.0)
                    md = float(struct.get("max_deployable") or 0.0)
                    rp = float(struct.get("risk_per_trade") or 0.0)
                    v_cap_sub.config(text=f"Avail {R}{av:,.0f}  \u2022  Max deploy {R}{md:,.0f} ({int(round(MAX_LOT_CAPITAL_PCT * 100, 0))}%)  \u2022  Risk {R}{rp:,.0f}/trade")
                except (tk.TclError, RuntimeError):
                    try:
                        v_cap_sub.config(text="")
                    except (tk.TclError, RuntimeError):
                        _logger.debug("[GUI] Could not clear capital sub label")
                pnl = struct.get("pnl", 0.0)
                v_pnl.config(text=format_pnl(pnl),
                             fg=_GT.get("profit", "#3fb950") if pnl >= 0 else _GT.get("loss", "#f85149"))
                try:
                    b = struct.get("blockers") or {}
                    if isinstance(b, dict) and b:
                        top_t, top_n = max(b.items(), key=lambda kv: kv[1])
                        top_map = {
                            "VIX": "Top block: VIX", "EOD": "Top block: EOD",
                            "RR": "Top block: RR", "ADX": "Top block: ADX",
                            "SCORE": "Top block: Score", "COOLDOWN": "Top block: Cooldown",
                            "DATA": "Top block: Data", "CIRCUIT": "Top block: Circuit",
                            "CAPS": "Top block: Caps", "MISSING": "Top block: Missing",
                        }
                        top_lbl = top_map.get(str(top_t), f"Top block: {top_t}")
                        v_pnl_sub.config(text=f"{top_lbl} ({int(top_n)}/{len(INDEX_PRIORITY)}) \u00b7 lock={'on' if struct.get('lock') else 'off'}")
                    else:
                        v_pnl_sub.config(text=f"ADX chop \u2264{struct.get('adx_chop', 20)} \u00b7 lock={'on' if struct.get('lock') else 'off'}")
                except (tk.TclError, RuntimeError):
                    v_pnl_sub.config(text=f"ADX chop \u2264{struct.get('adx_chop', 20)} \u00b7 lock={'on' if struct.get('lock') else 'off'}")
                v_tr.config(text=f"{struct.get('trades_tc', 0)}/{struct.get('trades_max', 3)} trades  \u00b7  {struct.get('pos_n', 0)}/{struct.get('pos_max', 1)} open  \u00b7  scan {SCAN_INTERVAL}s")
                try:
                    _td, _fd = _format_trading_desk_line(struct.get("desk"))
                    lbl_desk.config(text=_td, fg=_fd)
                except Exception as _de:
                    if _DEBUG:
                        try:
                            lbl_desk.config(text=f"Desk line: {_de!s}"[:180], fg="#f85149")
                        except (tk.TclError, RuntimeError):
                            _logger.debug("[GUI] Could not set desk debug label")
                try:
                    if bool(_GU.get("show_manual_flow_banner", True)):
                        _mf = str(struct.get("manual_flow_banner") or "").strip()
                        lbl_manual_flow.config(text=_mf if _mf else "")
                    else:
                        lbl_manual_flow.config(text="")
                except (tk.TclError, RuntimeError):
                    _logger.debug("[GUI] Could not update manual flow banner")
                ht = struct.get("headline_tag", "muted")
                hc = {
                    "ok": (_GT.get("headline_ok_bg", "#0d1117"), _GT.get("profit", "#3fb950")),
                    "warn": (_GT.get("headline_warn_bg", "#0d1117"), _GT.get("warn", "#d29922")),
                    "muted": (_GT.get("headline_muted_bg", "#21262d"), _GT.get("fg_muted", "#8b949e")),
                }
                bg_, fg_ = hc.get(ht, hc["muted"])
                lbl_headline.config(text=struct.get("headline", ""), bg=bg_, fg=fg_)
                if struct.get("tg_ok"):
                    lbl_tg.config(text="Telegram: ON \u2014 ACTION alerts only after TG quality gates (margin, min score, vol, OPEN).",
                                  fg=_GT.get("profit", "#3fb950"))
                else:
                    lbl_tg.config(text="Telegram: OFF \u2014 add BOT_TOKEN + CHAT_ID in config.json for phone alerts.",
                                  fg=_GT.get("warn", "#f0883e"))
                nf, yf = struct.get("nse_fails", 0), struct.get("yf_fails", 0)
                if nf or yf:
                    lbl_api.config(text=f"API issues: NSE failures={nf}  Yahoo failures={yf} (data may be degraded).")
                else:
                    lbl_api.config(text="API: OK (no recent fetch failures).", fg=_GT.get("fg_dim", "#6e7681"))
                la = struct.get("last_tg_action") or {}
                ls = struct.get("last_tg_skip") or {}
                now_t = time.time()
                la_ts = float(la.get("ts") or 0)
                ls_ts = float(ls.get("ts") or 0)
                tg_bits = []
                _tga = int(_GU.get("tg_display_action_sec", 7200))
                _tgf = int(_GU.get("tg_display_filter_sec", 1800))
                if la_ts and (now_t - la_ts) < _tga:
                    tg_bits.append(f"Last ACTION: {la.get('line', '')} ({max(0, int((now_t - la_ts) // 60))}m ago)")
                if ls_ts and (now_t - ls_ts) < _tgf:
                    tg_bits.append(f"Last filter: {ls.get('name', '?')} \u2014 {ls.get('why', '')}")
                tg_on = bool(struct.get("tg_ok"))
                if tg_bits:
                    txt = "  \u2022  ".join(tg_bits)
                    if not tg_on:
                        txt = "[Log only \u2014 Telegram not configured]  " + txt
                    lbl_last_tg.config(text=txt, fg="#bc8cff" if tg_on else "#8b949e")
                else:
                    if tg_on:
                        lbl_last_tg.config(text="No Telegram ACTION yet \u2014 phone stays quiet until quality gates pass (see TG_ALERT_*).",
                                           fg="#6e7681")
                    else:
                        lbl_last_tg.config(text="Telegram off \u2014 this panel still shows setups; add BOT_TOKEN + CHAT_ID for phone alerts.",
                                           fg="#6e7681")
                cfg_status = str(struct.get("config_status") or _config_reload_status)
                cfg_fg = (_GT.get("profit", "#3fb950") if "Reloaded" in cfg_status or cfg_status.lower().startswith("config stable")
                          else (_GT.get("warn", "#d29922") if "Restart required" in cfg_status or "immutable" in cfg_status
                                else (_GT.get("err", "#f85149") if "Blocked" in cfg_status else _GT.get("fg_muted", "#8b949e"))))
                lbl_config_status.config(text=cfg_status, fg=cfg_fg)
                if struct.get("target_hit"):
                    lbl_headline.config(text="Daily target hit \u2014 no new trades today.",
                                        bg=_GT.get("headline_muted_bg", "#21262d"),
                                        fg=_GT.get("warn", "#d29922"))
                _md = struct.get("mode", "")
                _mbg = (_GT.get("mode_paper", "#9e6a03") if _md == "PAPER"
                        else (_GT.get("mode_live_manual", "#b4690e") if _md == "LIVE\u00b7MANUAL"
                              else _GT.get("mode_live_auto", "#da3633")))
                mode_lbl.config(text=f" {_md} ", bg=_mbg)
                for x in tv.get_children():
                    tv.delete(x)
                for row in struct.get("index_rows", []):
                    cmp_ = row.get("cmp") or 0
                    price_s = f"{R}{cmp_:,.1f}" if cmp_ > 0 else "\u2014"
                    pct = row.get("pct", 0.0)
                    pct_s = f"{pct:+.2f}%"
                    st_txt = str(row.get("status", "WAIT") or "WAIT")
                    st_key = "PASS" if st_txt.startswith("PASS") else ("WATCH" if st_txt.startswith("WATCH") else "WAIT")
                    tg_ = {"PASS": "pass", "WATCH": "watch", "WAIT": "wait"}.get(st_key, "wait")
                    tv.insert("", tk.END, values=(
                        row.get("name", ""),
                        price_s,
                        pct_s,
                        row.get("dir", "\u2014"),
                        row.get("score", "\u2014"),
                        row.get("thr", "\u2014"),
                        row.get("gap", "\u2014"),
                        row.get("adx", "\u2014"),
                        row.get("iv", "\u2014"),
                        row.get("reg", "\u2014"),
                        st_txt,
                    ), tags=(tg_,))
                for w in wait_inner.winfo_children():
                    w.destroy()
                wrows = struct.get("waiting") or []
                if not wrows:
                    tk.Label(wait_inner, text="No blockers logged (or market not OPEN) \u2014 see table Status column.",
                             bg=bg_card, fg="#8b949e", font=(_FONT_UI, 9),
                             wraplength=480, justify="left").pack(anchor="w")
                else:
                    for wr in wrows:
                        line = f"\u2022 {wr.get('name', '')}: {wr.get('reason', '')}"
                        tk.Label(wait_inner, text=line, bg=bg_card, fg="#c9d1d9",
                                 font=(_FONT_UI, 9), wraplength=480, justify="left").pack(anchor="w", pady=1)

                # ── Pre-signal detail ──────────────────────────────────
                try:
                    ps = struct.get("presignal") if isinstance(struct, dict) else None
                    _R_SYM = "\u20b9"
                    _SEP = "\u2500" * 36
                    _fg_muted = _GT.get("fg_muted", "#8b949e")
                    if isinstance(ps, dict) and ps.get("name"):
                        nm = ps.get("name", "?")
                        dr = ps.get("dir", "\u2014")
                        sc = ps.get("score")
                        th = ps.get("thr")
                        gp = ps.get("gap")
                        vr = ps.get("vol")
                        rr_rate = ps.get("rr")
                        stars = str(ps.get("stars") or "")
                        label = str(ps.get("label") or "")
                        price = ps.get("price")
                        sl = ps.get("stop_loss")
                        tp1 = ps.get("tp1")
                        tp2 = ps.get("tp2")
                        tp3 = ps.get("tp3")
                        lot = ps.get("lot", 0)
                        step = ps.get("step", 50)
                        smart = str(ps.get("smart") or "NEUTRAL")
                        vix_val = ps.get("vix", 0)
                        blocked = str(ps.get("blocked") or "").strip()
                        is_ce = (dr == "CE")
                        hdr_fg = _GT.get("profit", "#3fb950") if is_ce else (_GT.get("loss", "#f85149") if dr == "PE" else _fg_muted)
                        star_s = f"  {stars}" if stars else ""
                        lbl_s = f"  [{label}]" if label else ""
                        lines = [f"\u25b6 {nm} {dr}{star_s}{lbl_s}"]
                        if isinstance(sc, int) and isinstance(th, int):
                            gp_s = f"  ({gp:+d})" if isinstance(gp, int) else ""
                            lines.append(f"Score {sc} / Need {th}{gp_s}")
                        lines.append(_SEP)
                        if isinstance(price, (int, float)) and price > 0 and isinstance(step, (int, float)) and step > 0:
                            atm = int(round(float(price) / float(step)) * float(step))
                            lines.append(f"ATM Strike  {atm} {dr}   \u2190 buy this")
                            lines.append(f"Index Spot  {_R_SYM}{price:,.1f}")
                        if isinstance(sl, (int, float)) and sl > 0 and isinstance(price, (int, float)) and price > 0:
                            sl_pct = (sl - price) / price * 100
                            lines.append(f"Stop Loss   {_R_SYM}{sl:,.1f}  ({sl_pct:+.1f}%)")
                        if isinstance(tp1, (int, float)) and tp1 > 0 and isinstance(price, (int, float)) and price > 0:
                            t1p = (tp1 - price) / price * 100
                            lines.append(f"TP 1        {_R_SYM}{tp1:,.1f}  ({t1p:+.1f}%)")
                        if isinstance(tp2, (int, float)) and tp2 > 0 and isinstance(price, (int, float)) and price > 0:
                            t2p = (tp2 - price) / price * 100
                            lines.append(f"TP 2        {_R_SYM}{tp2:,.1f}  ({t2p:+.1f}%)  \u2190 primary")
                        if isinstance(tp3, (int, float)) and tp3 > 0 and isinstance(price, (int, float)) and price > 0:
                            t3p = (tp3 - price) / price * 100
                            lines.append(f"TP 3        {_R_SYM}{tp3:,.1f}  ({t3p:+.1f}%)")
                        lines.append(_SEP)
                        stat_parts = []
                        if isinstance(rr_rate, (int, float)):
                            stat_parts.append(f"RR {rr_rate:.1f} (need {MIN_NET_RR})")
                        if isinstance(vr, (int, float)):
                            stat_parts.append(f"Vol {vr:.1f}x")
                        if lot:
                            stat_parts.append(f"Lot {lot}")
                        if stat_parts:
                            lines.append("  \u2022  ".join(stat_parts))
                        _oi_map = {"BULLISH": "Big buyers active (BULLISH)", "BEARISH": "Big sellers active (BEARISH)"}
                        if smart in _oi_map:
                            lines.append(f"OI: {_oi_map[smart]}")
                        if isinstance(vix_val, (int, float)) and vix_val > 0:
                            lines.append(f"VIX {vix_val:.1f}")
                        if blocked:
                            lines.append(f"Block: {blocked}")
                        pre_lbl.config(text="\n".join(lines), fg=hdr_fg)
                    else:
                        pre_lbl.config(text="No near-signal yet \u2014 wait for score to approach the bar.", fg=_fg_muted)
                except (tk.TclError, RuntimeError):
                    try:
                        pre_lbl.config(text="No near-signal yet \u2014 wait for score to approach the bar.",
                                       fg=_GT.get("fg_muted", "#8b949e"))
                    except (tk.TclError, RuntimeError):
                        _logger.debug("[GUI] Could not set pre-signal fallback text")
                try:
                    _sync_wraplength()
                except (tk.TclError, RuntimeError):
                    _logger.debug("[GUI] Could not sync wraplength")
            else:
                try:
                    lbl_desk.config(text="Waiting for a valid dashboard snapshot from the bot\u2026", fg="#8b949e")
                except (tk.TclError, RuntimeError):
                    _logger.debug("[GUI] Could not update desk label")
                try:
                    lbl_manual_flow.config(text="")
                except (tk.TclError, RuntimeError):
                    _logger.debug("[GUI] Could not clear manual flow label")

            st = (struct.get("status") if struct_ok else None) or market_status()
            st_colors = {
                "OPEN": _GT.get("status_open", "#238636"),
                "CLOSED": _GT.get("status_closed", "#da3633"),
                "PRE": _GT.get("status_pre", "#9e6a03"),
                "HOLIDAY": _GT.get("status_idle", "#484f58"),
                "WEEKEND": _GT.get("status_idle", "#484f58"),
            }
            status_lbl.config(text=f" {st} ", bg=st_colors.get(st, "#21262d"), fg="#ffffff")

            detail_for_tw = detail or full_txt
            repaint_tw = _last_gui_tw_text[0] != detail_for_tw
            if repaint_tw:
                _last_gui_tw_text[0] = detail_for_tw
                try:
                    tw.config(state=tk.NORMAL)
                    y_top, y_bot = tw.yview()
                    stick_bottom = float(y_bot) >= 0.995
                except (tk.TclError, RuntimeError):
                    stick_bottom, y_top = True, 0.0
                _apply_colors(tw, detail_for_tw)
                try:
                    tw.config(state=tk.NORMAL)
                    if stick_bottom:
                        tw.see(tk.END)
                    else:
                        tw.yview_moveto(max(0.0, min(1.0, float(y_top))))
                except (tk.TclError, RuntimeError):
                    _logger.debug("[GUI] Could not restore scroll position")
                tw.config(state=tk.DISABLED)
        except (tk.TclError, RuntimeError) as e:
            if _DEBUG:
                _logger.debug("[GUI UPDATE] %s", e)
            try:
                lbl_gui_err.config(text=f"UI refresh issue: {e!s}"[:200])
            except (tk.TclError, RuntimeError):
                _logger.debug("[GUI] Could not set GUI error label")
        try:
            _sync_header_hint()
        except (tk.TclError, RuntimeError):
            _logger.debug("[GUI] Could not sync header hint")
        try:
            sched_after[0] = root.after(GUI_REFRESH_MS, _update)
        except tk.TclError:
            pass

    # ── Close handler ──────────────────────────────────────────────────
    def _on_close():
        if SHUTDOWN_ON_UI_CLOSE and GUI_CONFIRM_EXIT:
            if PAPER_MODE:
                _t, _m = "Stop paper session?", "Closing stops the paper bot and exits this run. Continue?"
            else:
                _t = "Stop LIVE bot?"
                _m = ("Closing stops the trading bot and exits.\n"
                      "Open positions may still exist at your broker \u2014 manage them if needed.\n\nContinue?")
            if not tkmsg.askokcancel(_t, _m):
                return
        _cancel_sched_after()
        if _layout_save_sched[0] is not None:
            try:
                root.after_cancel(_layout_save_sched[0])
            except (tk.TclError, RuntimeError):
                _logger.debug("[GUI] Could not cancel layout save timer on close")
            _layout_save_sched[0] = None
        if _wrap_sync_sched[0] is not None:
            try:
                root.after_cancel(_wrap_sync_sched[0])
            except (tk.TclError, RuntimeError):
                _logger.debug("[GUI] Could not cancel wrap sync timer on close")
            _wrap_sync_sched[0] = None
        try:
            _write_gui_layout()
        except (tk.TclError, RuntimeError):
            _logger.debug("[GUI] Could not write layout on close")
        _gui_alive.clear()
        if SHUTDOWN_ON_UI_CLOSE:
            _shutdown.set()
            _logger.log("[GUI] Window closed \u2014 stopping bot (SHUTDOWN_ON_UI_CLOSE=true). Console will exit when cleanup finishes. Use --nogui to run without this window.")
        try:
            root.quit()
        except (tk.TclError, RuntimeError):
            _logger.debug("[GUI] Could not quit root on close")

    # ── Refresh ─────────────────────────────────────────────────────────
    def _refresh_now():
        _cancel_sched_after()
        _last_gui_tw_text[0] = None
        try:
            root.after(0, _update)
        except (tk.TclError, RuntimeError):
            _logger.debug("[GUI] Could not schedule immediate refresh")

    # ── Open script folder ──────────────────────────────────────────────
    def _open_script_folder() -> None:
        p = _gui_layout_path.parent.resolve()
        try:
            if sys.platform == "win32":
                os.startfile(str(p))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(p)], stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                subprocess.Popen(["xdg-open", str(p)], stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (tk.TclError, RuntimeError):
            try:
                tkmsg.showerror("Open folder", "Could not open the script folder in the file manager.")
            except (tk.TclError, RuntimeError):
                _logger.debug("[GUI] Could not show folder error dialog")

    # ── Save details as ────────────────────────────────────────────────
    def _save_details_as() -> None:
        try:
            tw.config(state=tk.NORMAL)
            body = tw.get("1.0", tk.END).rstrip()
            tw.config(state=tk.DISABLED)
        except (tk.TclError, RuntimeError):
            body = ""
        if not body.strip():
            try:
                tkmsg.showwarning("Save details", "Nothing to save yet \u2014 wait for the first dashboard update.")
            except (tk.TclError, RuntimeError):
                _logger.debug("[GUI] Could not show save warning dialog")
            return
        _parent = _gui_layout_path.parent.resolve()
        _stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        _save_path = filedialog.asksaveasfilename(
            parent=root, title="Save details as", defaultextension=".txt",
            filetypes=[("Text", "*.txt"), ("All files", "*.*")],
            initialdir=str(_parent), initialfile=f"index_trader_details_{_stamp}.txt")
        if not _save_path:
            return
        try:
            with open(_save_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(body)
            _logger.log(f"[GUI] Saved details snapshot \u2192 {_save_path}")
            try:
                tkmsg.showinfo("Save details", f"Saved:\n{_save_path}")
            except (tk.TclError, RuntimeError):
                _logger.debug("[GUI] Could not show save success dialog")
        except (tk.TclError, RuntimeError) as e:
            try:
                tkmsg.showerror("Save details", str(e))
            except (tk.TclError, RuntimeError):
                _logger.debug("[GUI] Could not show save error dialog: %s", e)

    # ── Menu bar ────────────────────────────────────────────────────────
    menubar = tk.Menu(root, tearoff=0)
    mfile = tk.Menu(menubar, tearoff=0)
    menubar.add_cascade(label="File", menu=mfile)
    mfile.add_command(label="Open script folder\u2026", command=_open_script_folder)
    mfile.add_command(label="Save details as\u2026", command=_save_details_as, accelerator="Ctrl+Shift+S")
    mfile.add_separator()
    mfile.add_command(label="Exit (stop bot)", command=_on_close, accelerator="Ctrl+Q")

    medit = tk.Menu(menubar, tearoff=0)
    menubar.add_cascade(label="Edit", menu=medit)
    medit.add_command(label="Select all details", command=lambda: _select_details_all(None), accelerator="Ctrl+A")
    medit.add_command(label="Copy selection", command=_copy_details_selection, accelerator="Ctrl+C")
    medit.add_command(label="Copy all details", command=_copy_details_all)
    medit.add_separator()
    medit.add_command(label="Scroll details to top", command=lambda: _tw_scroll_top(None))
    medit.add_command(label="Scroll details to bottom", command=lambda: _tw_scroll_bottom(None))
    medit.add_separator()
    medit.add_command(label="Find in details\u2026", command=_open_find_details, accelerator="Ctrl+F")

    mview = tk.Menu(menubar, tearoff=0)
    menubar.add_cascade(label="View", menu=mview)
    mview.add_command(label="Refresh now", command=_refresh_now, accelerator="F5")
    _topmost_var = tk.BooleanVar(value=bool(_layout_flags.get("topmost")))

    def _sync_topmost() -> None:
        try:
            v = bool(_topmost_var.get())
            _layout_flags["topmost"] = v
            root.attributes("-topmost", v)
            _queue_gui_layout_save()
        except (tk.TclError, RuntimeError):
            _logger.debug("[GUI] Could not sync topmost attribute")

    try:
        root.attributes("-topmost", bool(_layout_flags.get("topmost")))
    except (tk.TclError, RuntimeError):
        _logger.debug("[GUI] Could not set initial topmost attribute")
    mview.add_checkbutton(label="Always on top", variable=_topmost_var, command=_sync_topmost)

    def _reset_saved_layout() -> None:
        if not tkmsg.askyesno("Reset saved layout?",
                              "Remove index_trader_gui_layout.json and apply default window size and divider?\n\n"
                              "No restart needed. A new layout file is written when you resize, move the sash, or exit."):
            return
        try:
            if _gui_layout_path.is_file():
                _gui_layout_path.unlink()
        except (tk.TclError, RuntimeError) as e:
            tkmsg.showerror("Reset layout", f"Could not remove the file:\n{e!s}")
            return
        _layout_flags["topmost"] = False
        try:
            _topmost_var.set(False)
            root.attributes("-topmost", False)
        except (tk.TclError, RuntimeError):
            _logger.debug("[GUI] Could not reset topmost attribute")
        try:
            root.geometry("1200x860")
        except (tk.TclError, RuntimeError):
            _logger.debug("[GUI] Could not reset geometry")

        def _pan_default_after_reset() -> None:
            try:
                root.update_idletasks()
                w = max(380, min(520, max(300, root.winfo_width() // 2)))
                pan.sashpos(0, w)
            except (tk.TclError, RuntimeError):
                _logger.debug("[GUI] Could not set default sash after reset")

        root.after(80, _pan_default_after_reset)
        try:
            _sync_wraplength()
            _sync_header_hint()
        except (tk.TclError, RuntimeError):
            _logger.debug("[GUI] Could not sync after layout reset")
        _logger.log("[GUI] Layout file removed \u2014 defaults applied")

    mview.add_separator()
    mview.add_command(label="Reset saved layout\u2026", command=_reset_saved_layout)

    mhelp = tk.Menu(menubar, tearoff=0)
    menubar.add_cascade(label="Help", menu=mhelp)

    def _help_box():
        tkmsg.showinfo(
            "Index trader \u2014 desk & shortcuts",
            "TRADING DESK (below KPI cards)\n"
            "\u2022 Blue paragraph under the desk line explains MANUAL vs AUTO vs PAPER (hybrid model). "
            "Hide it with GUI_UX.show_manual_flow_banner=false.\n"
            "\u2022 One-line context: India VIX vs block/halt, daily loss budget %, min net RR, SL/target %, "
            "circuit, hard halt, execution path,\n"
            "  plus signal-quality and API-latency summaries.\n"
            "\u2022 Orange desk text = circuit tripped; red = hard halt.\n\n"
            "INDEX TABLE\n"
            "\u2022 Thr = score threshold; Gap = score\u2212thr; ADX / IV from the signal engine "
            "(IV = option IV when available).\n"
            "\u2022 Status / gate = PASS \u00b7 WATCH \u00b7 WAIT with the same logic as the console dashboard.\n\n"
            "LAYOUT\n"
            "\u2022 Window size, divider, topmost, and maximized (win_state) save to "
            "index_trader_gui_layout.json.\n"
            "\u2022 File \u2192 Open script folder\u2026 / Save details as\u2026 (Ctrl+Shift+S).\n"
            f"\u2022 View \u2192 Refresh now (F5); GUI_REFRESH_MS = UI poll ({GUI_REFRESH_MS} ms); "
            f"SCAN_INTERVAL = bot scan.\n"
            "\u2022 \u201cLast update\u201d shows snapshot age; when OPEN, also main-loop lag "
            "(watchdog risk if very high).\n"
            "\u2022 Details panel: Ctrl+F find, Ctrl+A/C, Esc; Home/End; PgUp/PgDn; "
            "wheel scrolls table + log.\n"
            "\u2022 Ctrl+Q / File\u2192Exit: LIVE may confirm (GUI_CONFIRM_EXIT, SHUTDOWN_ON_UI_CLOSE).\n"
            "\u2022 --nogui = console-only.",
        )

    mhelp.add_command(label="Desk guide & shortcuts", command=_help_box)
    try:
        root.config(menu=menubar)
    except (tk.TclError, RuntimeError):
        _logger.debug("[GUI] Could not set menubar")

    # ── Keyboard shortcuts ──────────────────────────────────────────────
    def _accel_quit(_e=None):
        _on_close()
        return "break"

    root.bind("<Control-q>", _accel_quit)
    root.bind("<Control-Q>", _accel_quit)

    def _accel_refresh(_e=None):
        _refresh_now()
        return "break"

    root.bind("<F5>", _accel_refresh)
    root.bind("<Control-f>", _accel_find)
    root.bind("<Control-F>", _accel_find)

    def _accel_save_details(_e=None):
        _save_details_as()
        return "break"

    root.bind("<Control-Shift-s>", _accel_save_details)
    root.bind("<Control-Shift-S>", _accel_save_details)
    root.protocol("WM_DELETE_WINDOW", _on_close)

    # ── Start GUI ───────────────────────────────────────────────────────
    try:
        root.after(80, _sync_wraplength)
    except (tk.TclError, RuntimeError):
        _logger.debug("[GUI] Could not schedule initial wraplength sync")
    root.after(400, _update)
    try:
        root.mainloop()
    except (tk.TclError, RuntimeError):
        _logger.debug("[GUI] mainloop exited with error")
    finally:
        _gui_alive.clear()
        try:
            root.destroy()
        except (tk.TclError, RuntimeError):
            _logger.debug("[GUI] Could not destroy root window")
