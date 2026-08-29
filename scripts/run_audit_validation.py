#!/usr/bin/env python3
"""Comprehensive Validation Script for Audit Changes.

Usage:
    python scripts/run_audit_validation.py
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

# Ensure unbuffered output on Windows
try:
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore[union-attr]
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

passed = 0
failed = 0


def check(name: str, result: bool, detail: str = "") -> None:
    global passed, failed
    if result:
        print(f"  PASS: {name}")
        passed += 1
    else:
        print(f"  FAIL: {name} -- {detail}")
        failed += 1


print("=" * 60, flush=True)
print("AUDIT VALIDATION -- POST-CHANGE VERIFICATION", flush=True)
print("=" * 60, flush=True)

# 1. AST Syntax Check
print("\n[1] Python Syntax Check", flush=True)
MODIFIED_FILES = [
    "index_app/gui/_desk_body.py",
    "scripts/migrate_to_postgresql.py",
    "scripts/generate_architecture_pdf.py",
    "scripts/e2e_integration_test.py",
    "realestate/admin_panel.py",
]
for f in MODIFIED_FILES:
    path = ROOT / f
    if not path.exists():
        check(f"AST: {f}", False, "File not found")
        continue
    try:
        with open(path, encoding="utf-8") as fh:
            ast.parse(fh.read())
        check(f"AST: {f}", True)
    except SyntaxError as e:
        check(f"AST: {f}", False, str(e))

# 2. Import Validation
print("\n[2] Import Validation", flush=True)
try:
    from core.datetime_ist import now_ist
    t = now_ist()
    check("now_ist() import", t is not None)
except Exception as e:
    check("now_ist() import", False, str(e))

try:
    cfg_path = ROOT / ".coveragerc"
    cfg_text = cfg_path.read_text(encoding="utf-8")
    check(".coveragerc exists", True)
    check("fail_under = 90", "fail_under = 90" in cfg_text)
except Exception as e:
    check(".coveragerc", False, str(e))

# 3. Deliverable Files
print("\n[3] Deliverable Files", flush=True)
deliverables_dir = ROOT / "docs/deliverables"
found = sum(1 for f in deliverables_dir.iterdir() if f.suffix == ".md") if deliverables_dir.exists() else 0
check("Deliverables present", found >= 26, f"{found}/26")

# 4. Modified file changes verification
print("\n[4] Modified File Verification", flush=True)
for f in MODIFIED_FILES:
    path = ROOT / f
    if path.exists():
        content = path.read_text(encoding="utf-8")
        has_now_ist = "now_ist" in content
        has_datetime_now = "datetime.now()" not in content
        check(f"{f}: now_ist() present", has_now_ist)
        check(f"{f}: no datetime.now()", has_datetime_now)

# Summary
print(flush=True)
print("=" * 60, flush=True)
total = passed + failed
print(f"SUMMARY: {passed}/{total} passed", flush=True)
if failed == 0:
    print("ALL CHECKS PASSED", flush=True)
else:
    print(f"{failed} check(s) failed", flush=True)
print("=" * 60, flush=True)
sys.exit(0 if failed == 0 else 1)
