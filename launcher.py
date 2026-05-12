"""
launcher.py — OPBuying Index App  •  Setup & Launch
----------------------------------------------------
What it does every run
  1. Locate Python 3.10 – 3.19 on PATH
  2. Check packages in one subprocess; install only the missing/outdated ones
  3. Launch the app via CLI flag — config.json is NEVER read or modified

Mode is passed as a CLI argument (--paper | nothing) that the app's own
hybrid_execution.py resolves — no external state is mutated.

Configurable via:  launcher_settings.json  (same folder as this file)
"""
from __future__ import annotations

import sys

# ── Frozen-EXE: locate bundled Tcl/Tk before tkinter loads ───────────────────
# PyInstaller sets TCL_LIBRARY to a temp path; ensure it points to init.tcl.
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    import os as _os
    _mei = sys._MEIPASS
    for _d in ("_tcl_data", "tcl8.6", "tcl"):
        _p = _os.path.join(_mei, _d)
        if _os.path.isfile(_os.path.join(_p, "init.tcl")):
            _os.environ["TCL_LIBRARY"] = _p
            break
    for _d in ("_tk_data", "tk8.6", "tk"):
        _p = _os.path.join(_mei, _d)
        if _os.path.isfile(_os.path.join(_p, "tk.tcl")):
            _os.environ["TK_LIBRARY"] = _p
            break
    del _os, _mei, _d, _p
# ─────────────────────────────────────────────────────────────────────────────

import json
import os
import subprocess
import threading
from pathlib import Path
from typing import Optional
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

# ── Resolve app folder correctly when compiled by PyInstaller --onefile ──────
APP_DIR: Path = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent
)

# ── Launcher settings ─────────────────────────────────────────────────────────
_SETTINGS_FILE = APP_DIR / "launcher_settings.json"
_DEFAULTS: dict = {
    "default_mode":      "PAPER",
    "auto_launch":       False,
    "python_preference": ["py", "python", "python3"],
    "app_script":        "INDEX_OPTION_BUYING_APP_1.0.py",
    "extra_args":        [],
}

def _load_settings() -> dict:
    try:
        if _SETTINGS_FILE.exists():
            raw = json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
            return {**_DEFAULTS, **{k: v for k, v in raw.items() if not k.startswith("_")}}
    except Exception:
        pass
    return dict(_DEFAULTS)

_S = _load_settings()

# ── Packages: (pip_name, min_version, description) ───────────────────────────
# Import-name is pip_name with hyphens → underscores; handled automatically.
PACKAGES: list[tuple[str, str, str]] = [
    ("requests",        "2.31.0", "HTTP / API calls"),
    ("yfinance",        "0.2.36", "Market data feed"),
    ("pandas",          "2.0.0",  "Data processing"),
    ("numpy",           "1.24.0", "Numerical engine"),
    ("flask",           "3.0.0",  "Dashboard server"),
    ("flask-socketio",  "5.3.0",  "Real-time dashboard"),
]

# ── Execution modes ───────────────────────────────────────────────────────────
# flag=None means no CLI arg added (app uses config.json value unchanged)
MODES: dict[str, dict] = {
    "PAPER": {
        "flag":  "--paper",
        "desc":  "Simulate trades  •  adaptive learning ON  •  no real orders",
        "color": "#28a745",
    },
    "MANUAL": {
        "flag":  None,
        "desc":  "Signals only  •  you place orders manually",
        "color": "#fd7e14",
    },
}


# ─────────────────────────────────────────────────────────────────────────────
class LauncherApp:

    # ── Colour / font constants ───────────────────────────────────────────────
    C_BG    = "#12121c"
    C_PANEL = "#1a1a2e"
    C_DIM   = "#777"
    C_TEXT  = "#d4d4d4"
    C_BLUE  = "#64b5f6"
    C_RED   = "#dc3545"
    C_ACNT  = "#e94560"
    F_HEAD  = ("Segoe UI", 13, "bold")
    F_BODY  = ("Segoe UI", 9)
    F_HINT  = ("Segoe UI", 8, "italic")
    F_LOG   = ("Consolas", 8)

    def __init__(self, root: tk.Tk) -> None:
        self.root       = root
        self.python_exe: Optional[str] = None
        self._mode_var  = tk.StringVar(value=_S["default_mode"])
        self._setup_window()
        self._build_ui()
        self.root.after(300, self._start_setup)

    # ── Window ────────────────────────────────────────────────────────────────
    def _setup_window(self) -> None:
        self.root.title("OPBuying Index App v1.2.0")
        self.root.geometry("660x560")
        self.root.resizable(False, False)
        self.root.configure(bg=self.C_BG)
        try:
            self.root.iconbitmap(default="")
        except Exception:
            pass

    # ── UI ────────────────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        # Header
        hdr = tk.Frame(self.root, bg=self.C_PANEL, height=58)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="INDEX OPTION BUYING  v1.2.0",
                 font=self.F_HEAD, bg=self.C_PANEL, fg=self.C_ACNT
                 ).place(relx=0.5, rely=0.35, anchor="center")
        tk.Label(hdr, text="config.json is never modified — mode is passed as a CLI flag",
                 font=self.F_HINT, bg=self.C_PANEL, fg=self.C_DIM
                 ).place(relx=0.5, rely=0.72, anchor="center")

        # Mode selector
        mf = tk.Frame(self.root, bg=self.C_BG)
        mf.pack(fill="x", padx=24, pady=(12, 2))
        tk.Label(mf, text="Launch mode:", font=self.F_BODY,
                 bg=self.C_BG, fg=self.C_DIM).pack(side="left")
        for key, info in MODES.items():
            tk.Radiobutton(
                mf,
                text=f"  {key}  —  {info['desc']}",
                variable=self._mode_var, value=key,
                font=self.F_BODY, bg=self.C_BG, fg=info["color"],
                selectcolor=self.C_PANEL,
                activebackground=self.C_BG, activeforeground=info["color"],
                command=self._on_mode_change,
            ).pack(side="left", padx=(10, 0))

        # Progress bar
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("G.Horizontal.TProgressbar",
                        troughcolor="#0a0a14",
                        background="#28a745",
                        lightcolor="#28a745",
                        darkcolor="#28a745")
        self.progress = ttk.Progressbar(
            self.root, length=612,
            style="G.Horizontal.TProgressbar",
            mode="determinate")
        self.progress.pack(padx=24, pady=(10, 0))

        # Status line
        self._status_var = tk.StringVar(value="Initializing …")
        tk.Label(self.root, textvariable=self._status_var,
                 font=self.F_HINT, bg=self.C_BG, fg=self.C_BLUE
                 ).pack(pady=(2, 4))

        # Log area
        self.log = scrolledtext.ScrolledText(
            self.root, height=17, width=80,
            font=self.F_LOG, bg="#0a0a14", fg=self.C_TEXT,
            insertbackground="white", relief="flat", bd=0)
        self.log.pack(padx=24)

        # Buttons
        bf = tk.Frame(self.root, bg=self.C_BG)
        bf.pack(pady=10)
        self.launch_btn = tk.Button(
            bf, text="  Launch App  ", state="disabled",
            font=("Segoe UI", 10, "bold"),
            bg="#28a745", fg="white", activebackground="#1e7e34",
            relief="flat", padx=18, pady=7,
            command=self._on_launch)
        self.launch_btn.pack(side="left", padx=10)
        tk.Button(bf, text="  Exit  ",
                  font=("Segoe UI", 10),
                  bg=self.C_RED, fg="white", activebackground="#b02a37",
                  relief="flat", padx=18, pady=7,
                  command=self.root.quit
                  ).pack(side="left", padx=10)

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _log(self, msg: str = "") -> None:
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.root.update_idletasks()

    def _status(self, msg: str) -> None:
        self._status_var.set(msg)
        self.root.update_idletasks()

    def _set_progress(self, pct: float) -> None:
        self.progress["value"] = max(0.0, min(100.0, pct))
        self.root.update_idletasks()

    def _on_mode_change(self) -> None:
        col = MODES[self._mode_var.get()]["color"]
        self.launch_btn.configure(bg=col, activebackground=col)

    # ── Python detection ──────────────────────────────────────────────────────
    def _find_python(self) -> tuple[Optional[str], Optional[str]]:
        for cmd in _S.get("python_preference", ["py", "python", "python3"]):
            try:
                r = subprocess.run(
                    [cmd, "--version"], capture_output=True, text=True, timeout=5)
                raw = (r.stdout + r.stderr).strip()
                if r.returncode == 0 and raw.startswith("Python"):
                    parts = raw.split()
                    if len(parts) >= 2:
                        v = tuple(int(x) for x in parts[1].split(".")[:2])
                        if (3, 10) <= v < (3, 20):
                            return cmd, raw
            except Exception:
                continue
        return None, None

    # ── Batch package status check ────────────────────────────────────────────
    def _check_packages(self, python: str) -> dict[str, bool]:
        """
        Single subprocess call checks all packages at once.
        Returns {pip_name: is_satisfied} for every package in PACKAGES.
        """
        checks = {pip_name: min_ver for pip_name, min_ver, _ in PACKAGES}
        script = (
            "import json, sys\n"
            "from importlib.metadata import version, PackageNotFoundError\n"
            "def _ok(name, req):\n"
            "    try:\n"
            "        v = tuple(int(x) for x in version(name).split('.')[:3])\n"
            "        r = tuple(int(x) for x in req.split('.')[:3])\n"
            "        return v >= r\n"
            "    except PackageNotFoundError:\n"
            "        return False\n"
            f"checks = {json.dumps(checks)}\n"
            "print(json.dumps({k: _ok(k, v) for k, v in checks.items()}))\n"
        )
        try:
            r = subprocess.run(
                [python, "-c", script],
                capture_output=True, text=True, timeout=15)
            if r.returncode == 0 and r.stdout.strip():
                return json.loads(r.stdout.strip())
        except Exception:
            pass
        # Fallback: assume nothing installed
        return {pip_name: False for pip_name, _, _ in PACKAGES}

    # ── Main setup thread ─────────────────────────────────────────────────────
    def _start_setup(self) -> None:
        threading.Thread(target=self._run_setup, daemon=True).start()

    def _run_setup(self) -> None:
        SEP  = "─" * 64
        SEP2 = "═" * 64

        # ── Step 1: Python ────────────────────────────────────────────────────
        self._status("Checking Python installation …")
        self._log(SEP2)
        self._log("  INDEX OPTION BUYING APP  —  Launcher")
        self._log(SEP2)
        self._log()
        self._log("STEP 1  Locate Python 3.10 – 3.19")
        self._log(SEP)

        cmd, ver = self._find_python()
        if not cmd:
            self._log("  [FAIL]  No compatible Python found on PATH.")
            self._log()
            self._log("  Install Python 3.10 – 3.19:")
            self._log("    https://www.python.org/downloads/")
            self._log("  Tick  'Add Python to PATH'  during install, then re-run.")
            self._status("Python not found — see log.")
            messagebox.showerror(
                "Python Not Found",
                "Python 3.10 – 3.19 not found on PATH.\n\n"
                "1. Download from  python.org/downloads\n"
                "2. Tick  'Add Python to PATH'\n"
                "3. Re-run this launcher.")
            return

        self.python_exe = cmd
        self._log(f"  [OK]  {ver}  →  '{cmd}'")
        self._set_progress(10)

        # ── Step 2: Check all packages in one call ────────────────────────────
        self._log()
        self._log("STEP 2  Check / install required packages")
        self._log(SEP)
        self._status("Checking installed packages …")

        status = self._check_packages(cmd)
        total_steps = sum(1 for ok in status.values() if not ok)
        done_steps  = 0

        failed: list[str] = []
        for i, (pip_name, min_ver, desc) in enumerate(PACKAGES, 1):
            tag = f"[{i}/{len(PACKAGES)}]"
            if status.get(pip_name, False):
                self._log(f"  {tag}  {pip_name:<18} >= {min_ver}   ({desc})  →  OK (already installed)")
                continue

            self._status(f"Installing {pip_name} …")
            self._log(f"  {tag}  {pip_name:<18} >= {min_ver}   ({desc})  →  installing …")
            try:
                r = subprocess.run(
                    [cmd, "-m", "pip", "install",
                     f"{pip_name}>={min_ver}",
                     "--quiet", "--disable-pip-version-check"],
                    capture_output=True, text=True, timeout=180)
                if r.returncode == 0:
                    self._log(f"  {'':6}  {'':18}            {'':15}     installed OK")
                else:
                    err = (r.stderr or r.stdout).strip().splitlines()
                    self._log(f"  {'':6}  WARN: {(err[-1] if err else 'unknown')[:60]}")
                    failed.append(pip_name)
            except subprocess.TimeoutExpired:
                self._log(f"  {'':6}  WARN: timed out (slow network?)")
                failed.append(pip_name)
            except Exception as exc:
                self._log(f"  {'':6}  WARN: {exc}")
                failed.append(pip_name)

            done_steps += 1
            self._set_progress(10 + (done_steps / max(total_steps, 1)) * 88)

        self._set_progress(100)
        self._log()
        self._log(SEP2)

        if failed:
            self._log(f"  Completed with warning(s) on:  {', '.join(failed)}")
            self._log("  App may still run. Click Launch to try.")
            self._status("Done (with warnings) — select mode and click Launch.")
        else:
            mode = self._mode_var.get()
            self._log(f"  All packages ready.  Default mode: {mode}")
            self._log("  Select a mode above, then click  'Launch App'.")
            self._status(f"Ready — {mode} mode selected — click 'Launch App'.")

        self._log(SEP2)
        self.launch_btn["state"] = "normal"
        self.launch_btn.focus_set()
        self._on_mode_change()

        if _S.get("auto_launch"):
            self.root.after(500, self._on_launch)

    # ── Launch ────────────────────────────────────────────────────────────────
    def _on_launch(self) -> None:
        mode   = self._mode_var.get()
        info   = MODES[mode]
        script = APP_DIR / _S.get("app_script", "INDEX_OPTION_BUYING_APP_1.0.py")

        if not script.exists():
            messagebox.showerror(
                "Script Not Found",
                f"Cannot find:\n  {script}\n\n"
                "Keep this launcher in the same folder as the app files.")
            return

        # config.json is NEVER modified.
        # The app's hybrid_execution.py resolves --paper to PAPER mode internally.
        args: list[str] = [self.python_exe, str(script)]
        if info["flag"]:
            args.append(info["flag"])
        args.extend(_S.get("extra_args", []))

        self._log()
        self._log(f"  Mode:     {mode}  ({info['desc']})")
        self._log(f"  Script:   {script.name}")
        self._log(f"  Command:  {' '.join(args)}")

        # Strip PyInstaller's TCL_LIBRARY / TK_LIBRARY overrides so the
        # subprocess uses its own Python's Tcl/Tk — not the bundled temp path.
        _env = os.environ.copy()
        for _k in ("TCL_LIBRARY", "TK_LIBRARY", "TCLLIBPATH",
                   "TCL_DATA", "TK_DATA"):
            _env.pop(_k, None)

        try:
            subprocess.Popen(
                args,
                cwd=str(APP_DIR),
                creationflags=subprocess.CREATE_NEW_CONSOLE,
                env=_env,
            )
        except Exception as exc:
            messagebox.showerror("Launch Failed", str(exc))
            return

        self._status(f"Launched [{mode}] — this window closes in 3 s …")
        self.root.after(3000, self.root.quit)


# ─────────────────────────────────────────────────────────────────────────────
def main() -> None:
    root = tk.Tk()
    LauncherApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
