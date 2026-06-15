"""
launcher.py — OPBuying Index App  •  Setup & Launch
----------------------------------------------------
What it does every run
  1. Locate Python 3.10 – 3.19 on PATH
  2. Read requirements.txt and install ALL missing/outdated packages
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

import atexit
import hashlib
import json
import os
import queue
import re
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk

# ── Single-instance lock ─────────────────────────────────────────────────────
# Prevents multiple launcher instances when the user double-clicks the EXE rapidly.
# Uses a lockfile in the user's temp directory with the launcher's full path as
# the lock name. If the lock exists AND the PID inside it is still running, we
# show a warning and exit immediately.
_LOCK_FILE = Path(
    os.environ.get("TEMP", os.environ.get("TMP", "/tmp"))
) / f"opbuying_launcher_{hashlib.md5(str(Path(sys.executable if getattr(sys, 'frozen', False) else __file__).resolve()).encode()).hexdigest()[:16]}.lock"

def _acquire_single_instance_lock() -> bool:
    """
    Try to acquire a single-instance lock. Returns True if this is the first/only
    instance. Returns False if another instance is already running.
    """
    try:
        if _LOCK_FILE.exists():
            pid_str = _LOCK_FILE.read_text(encoding="utf-8").strip()
            if pid_str:
                pid = int(pid_str)
                # On Windows, use tasklist to check if the PID is alive
                r = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                    capture_output=True, text=True, timeout=5
                )
                if str(pid) in r.stdout and "No tasks" not in r.stdout:
                    # Another instance is running
                    return False
        # Lock is stale or doesn't exist — acquire it
        _LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")
        return True
    except (OSError, ValueError, subprocess.TimeoutExpired):
        # If anything goes wrong with the lock, allow running anyway
        return True

def _release_lock() -> None:
    """Release the single-instance lock on exit."""
    try:
        if _LOCK_FILE.exists():
            pid_str = _LOCK_FILE.read_text(encoding="utf-8").strip()
            if pid_str == str(os.getpid()):
                _LOCK_FILE.unlink(missing_ok=True)
    except OSError:
        pass

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
    "app_script":        "index_app/index_trader.py",
    "extra_args":        [],
}

def _load_settings() -> dict:
    try:
        if _SETTINGS_FILE.exists():
            raw = json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
            return {**_DEFAULTS, **{k: v for k, v in raw.items() if not k.startswith("_")}}
    except (json.JSONDecodeError, OSError, KeyError):
        import logging as _launch_log
        _launch_log.getLogger(__name__).debug("Launcher settings load failed - using defaults")
    return dict(_DEFAULTS)

_S = _load_settings()

# ── Packages: dynamically read from requirements.txt ────────────────────────
# Loads ALL required packages (not just a hardcoded subset) to ensure
# index_trader.py does not crash on import with an ImportError.
# Skips commented-out lines (e.g. optional kiteconnect, pyotp).

def _load_packages_from_requirements(path: Path | None = None) -> list[tuple[str, str, str]]:
    """Parse requirements.txt and return [(pip_name, min_version, full_line), ...].

    full_line preserves the original requirement string (including compound
    constraints like ``>=1.0,<2.0``) so pip installs the exact version range.
    """
    reql = path or APP_DIR / "requirements.txt"
    pkgs: list[tuple[str, str, str]] = []
    try:
        if reql.exists():
            text = reql.read_text(encoding="utf-8")
            for line in text.splitlines():
                line_stripped = line.strip()
                # Skip blank / comment-only lines
                if not line_stripped or line_stripped.startswith("#"):
                    continue
                # Strip inline comments (space + #...)
                clean = line_stripped
                if " #" in line_stripped:
                    clean = line_stripped.split(" #")[0].strip()
                if not clean:
                    continue
                # Skip pip directives (-r, -e, --index-url etc.) and URLs
                if clean.startswith("-") or clean.startswith("git+") or clean.startswith("http"):
                    continue
                # Extract package name and version
                # PEP 508: package_name>=version[,constraint]...
                m = re.match(r"([a-zA-Z0-9_.-]+?)((?:\[[^\]]*\])?)\s*((?:[><=!~]+\s*[a-zA-Z0-9.*_]+(?:\s*,\s*[><=!~]+\s*[a-zA-Z0-9.*_]+)*)?)", clean)
                if m:
                    name = m.group(1).lower()
                    # Use the full original line (without extras) for pip install
                    full_line = f"{name}{m.group(3)}" if m.group(3) else name
                    # Extract min version for the check script
                    ver_match = re.search(r">=\s*([0-9.]+)", m.group(3) or "")
                    min_ver = ver_match.group(1) if ver_match else "0.0.0"
                    pkgs.append((name, min_ver, full_line))
    except OSError:
        import logging as _launch_log
        _launch_log.getLogger(__name__).debug("Could not read requirements.txt")
    if not pkgs:
        # Fallback when requirements.txt can't be read
        # Log a warning — this fallback may not cover all packages needed
        import logging
        logging.getLogger("launcher").warning(
            "requirements.txt not found at %s — using fallback package list",
            reql,
        )
    return pkgs

PACKAGES: list[tuple[str, str, str]] = _load_packages_from_requirements()
_MISSING_REQ_TXT = len(PACKAGES) == 0

# If requirements.txt is missing AND we're using the fallback, warn the user
if _MISSING_REQ_TXT:
    PACKAGES = [
        ("requests",        "2.31.0", ""),
        ("yfinance",        "0.2.36", ""),
        ("pandas",          "2.0.0",  ""),
        ("numpy",           "1.24.0", ""),
        ("flask",           "3.0.0",  ""),
        ("flask-socketio",  "5.3.0",  ""),
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
        self.python_exe: str | None = None
        self._mode_var  = tk.StringVar(value=_S["default_mode"])
        self._launched_process: subprocess.Popen | None = None
        self._update_queue: queue.Queue = queue.Queue()
        self._setup_window()
        self._build_ui()
        self._poll_updates()
        self.root.after(300, self._start_setup)

    # ── Window ────────────────────────────────────────────────────────────────
    def _setup_window(self) -> None:
        self.root.title("OPBuying Index App v1.2.0")
        self.root.geometry("660x560")
        self.root.resizable(False, False)
        self.root.configure(bg=self.C_BG)
        try:
            self.root.iconbitmap(default="")
        except (tk.TclError, OSError):
            pass  # Icon not available - window still works

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

        # Equity toggle row
        ef = tk.Frame(self.root, bg=self.C_BG)
        ef.pack(fill="x", padx=24, pady=(0, 4))
        self._equity_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            ef,
            text="Enable Equity Trading  (passes --equity to app)",
            variable=self._equity_var,
            font=self.F_BODY, bg=self.C_BG, fg="#3fb950",
            selectcolor=self.C_PANEL,
            activebackground=self.C_BG, activeforeground="#3fb950",
        ).pack(side="left")

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

    # ── Thread-safe display helpers ───────────────────────────────────────────
    # Tkinter is NOT thread-safe. All widget operations MUST happen on the
    # main thread. The daemon thread pushes display updates to _update_queue,
    # and _poll_updates() executes them on the main thread's event loop.

    def _poll_updates(self) -> None:
        """Process queued display updates on the main thread (runs every 50ms)."""
        try:
            while True:
                fn = self._update_queue.get_nowait()
                try:
                    fn()
                except tk.TclError:
                    pass  # Window may have been destroyed
        except queue.Empty:
            pass
        try:
            self.root.after(50, self._poll_updates)
        except tk.TclError:
            pass  # App is shutting down

    def _log(self, msg: str = "") -> None:
        """Append a line to the log area (thread-safe)."""
        def _do_log() -> None:
            self.log.insert("end", msg + "\n")
            self.log.see("end")
            self.root.update_idletasks()
        self._update_queue.put(_do_log)

    def _status(self, msg: str) -> None:
        """Update the status bar text (thread-safe)."""
        def _do_status() -> None:
            self._status_var.set(msg)
            self.root.update_idletasks()
        self._update_queue.put(_do_status)

    def _set_progress(self, pct: float) -> None:
        """Update the progress bar (thread-safe)."""
        def _do_progress() -> None:
            self.progress["value"] = max(0.0, min(100.0, pct))
            self.root.update_idletasks()
        self._update_queue.put(_do_progress)

    def _safe_exec(self, fn: callable) -> None:
        """Execute an arbitrary callable on the main thread (thread-safe)."""
        self._update_queue.put(fn)

    def _safe_messagebox(self, title: str, message: str, kind: str = "error") -> None:
        """Show a messagebox from ANY thread by scheduling on the main thread.

        Tkinter is NOT thread-safe — calling messagebox.showerror() from a
        daemon thread causes erratic behavior (flickering, repeated popups).
        This helper routes the call to the main thread via root.after().
        """
        if kind == "error":
            self.root.after(0, lambda: messagebox.showerror(title, message))
        elif kind == "warning":
            self.root.after(0, lambda: messagebox.showwarning(title, message))
        else:
            self.root.after(0, lambda: messagebox.showinfo(title, message))

    def _on_mode_change(self) -> None:
        col = MODES[self._mode_var.get()]["color"]
        self.launch_btn.configure(bg=col, activebackground=col)

    # ── Python detection ──────────────────────────────────────────────────────
    def _find_python(self) -> tuple[str | None, str | None]:
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
            except (subprocess.TimeoutExpired, OSError, ValueError):
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
        except (json.JSONDecodeError, OSError, subprocess.TimeoutExpired, subprocess.CalledProcessError) as _pkg_err:
            import logging as _launch_log
            _launch_log.getLogger(__name__).debug("Package check failed: %s", _pkg_err)
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
            self._safe_messagebox(
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

        # Warn if requirements.txt was not found
        if _MISSING_REQ_TXT:
            self._log("  [WARN] requirements.txt not found — using fallback package list")
            self._log("         Only 6 core packages will be checked. App may still")
            self._log("         crash if additional packages are missing.")
            self._log()

        status = self._check_packages(cmd)
        total_steps = sum(1 for ok in status.values() if not ok)
        done_steps  = 0

        failed: list[str] = []
        for i, (pip_name, min_ver, full_line) in enumerate(PACKAGES, 1):
            tag = f"[{i}/{len(PACKAGES)}]"
            if status.get(pip_name, False):
                self._log(f"  {tag}  {pip_name:<18} >= {min_ver}   →  OK (already installed)")
                continue

            self._status(f"Installing {pip_name} …")
            self._log(f"  {tag}  {pip_name:<18} >= {min_ver}   →  installing …")
            try:
                # Use the full requirement spec when available (preserves compound constraints)
                pip_spec = full_line if full_line else f"{pip_name}>={min_ver}"
                r = subprocess.run(
                    [cmd, "-m", "pip", "install",
                     pip_spec,
                     "--quiet", "--disable-pip-version-check"],
                    capture_output=True, text=True, timeout=180)
                if r.returncode == 0:
                    self._log(f"  {'':6}  {'':18}                installed OK")
                else:
                    err = (r.stderr or r.stdout).strip().splitlines()
                    self._log(f"  {'':6}  WARN: {(err[-1] if err else 'unknown')[:60]}")
                    failed.append(pip_name)
            except subprocess.TimeoutExpired:
                self._log(f"  {'':6}  WARN: timed out (slow network?)")
                failed.append(pip_name)
            except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
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
        # Enable Launch button (queued on main thread via _safe_exec)
        self._safe_exec(lambda: self.launch_btn.configure(state="normal", cursor="hand2"))
        self._safe_exec(self.launch_btn.focus_set)
        self._safe_exec(self._on_mode_change)

        if _S.get("auto_launch"):
            self.root.after(500, self._on_launch)

    # ── Launch ────────────────────────────────────────────────────────────────
    def _on_launch(self) -> None:
        mode   = self._mode_var.get()
        info   = MODES[mode]
        script = APP_DIR / _S.get("app_script", "index_app/index_trader.py")

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
        if self._equity_var.get():
            args.append("--equity")
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

        self.launch_btn["state"] = "disabled"
        try:
            proc = subprocess.Popen(
                args,
                cwd=str(APP_DIR),
                creationflags=subprocess.CREATE_NEW_CONSOLE,
                env=_env,
            )
        except (FileNotFoundError, OSError, subprocess.SubprocessError) as exc:
            messagebox.showerror("Launch Failed", str(exc))
            self.launch_btn["state"] = "normal"
            return

        # Track the process so we can detect if it crashes immediately
        self._launched_process = proc
        self._log("  App launched — checking if it stays running …")
        self.root.after(2000, self._check_launched_process, mode)

    # ── Post-launch crash detector ────────────────────────────────────────────
    def _check_launched_process(self, mode: str) -> None:
        """Check if the spawned process exited quickly (crashed on startup).

        If the process died within 2 seconds, it likely hit an ImportError
        or config issue. Show the error in the launcher log instead of
        letting the console window close silently.
        """
        proc = self._launched_process
        if proc is None:
            return
        ret = proc.poll()
        if ret is not None:
            if ret != 0:
                # Process exited with error — likely a startup crash
                self._log(f"\n  [ERROR] The app exited unexpectedly (exit code {ret}).")
                self._log(f"  Command:   {self.python_exe} {_S.get('app_script', 'index_app/index_trader.py')}")
                self._log()
                self._log("  Possible causes:")
                self._log("    • Missing packages — check log above for install failures")
                self._log("    • Missing config.json in the project folder")
                self._log("    • Python version mismatch (need 3.10 – 3.19)")
                self._log()
                self._log("  To see the full error, run this in a terminal:")
                self._log(f"    cd {APP_DIR}")
                self._log(f"    {self.python_exe} index_app\\index_trader.py --paper")
                self._log()
                self._status("Launch failed — see log for details.")
                self.launch_btn["state"] = "normal"
                messagebox.showerror(
                    "App Crashed",
                    f"The trading app exited with exit code {ret}.\n\n"
                    "This usually means a missing package or bad config.\n"
                    "Check the log in the launcher window for details.\n\n"
                    "To see the full error, run in a terminal:\n"
                    f"  cd {APP_DIR}\n"
                    f"  {self.python_exe} index_app\\index_trader.py --paper"
                )
            else:
                # Exit code 0 — clean exit (e.g. morning checklist run, or done after paper loop)
                self._log("\n  [INFO] The app completed successfully (exit code 0).")
                self._log()
                self._status("App completed successfully.")
                self.root.after(500, self.root.quit)
        else:
            # Process is still running — all good
            self._status(f"Launched [{mode}] — this window closes in 3 s …")
            self.root.after(3000, self.root.quit)


# ─────────────────────────────────────────────────────────────────────────────
def main() -> None:
    root = tk.Tk()
    LauncherApp(root)
    root.mainloop()


if __name__ == "__main__":
    if not _acquire_single_instance_lock():
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            0,
            "OPBuying Launcher is already running.\n\n"
            "Check your system tray or taskbar for the existing window.",
            "Already Running",
            0x10 | 0x0  # MB_ICONERROR | MB_OK
        )
        sys.exit(0)
    atexit.register(_release_lock)
    main()
