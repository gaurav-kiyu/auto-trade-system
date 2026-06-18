"""
AD-KIYU Compile Validation - syntax-check all .py files in source directories.
"""
from __future__ import annotations

import glob
import os
import py_compile
import sys


def main() -> int:
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    os.chdir("..")

    source_dirs = ("core", "index_app", "scripts", "infrastructure", "schemas")

    all_files = glob.glob("**/*.py", recursive=True)
    source_files = [f for f in all_files if f.split(os.sep)[0] in source_dirs]
    source_files.sort()

    print(f"Compile validation: checking {len(source_files)} source files...")

    failures = []
    for f in source_files:
        try:
            py_compile.compile(f, doraise=True)
        except py_compile.PyCompileError as e:
            failures.append((f, str(e)))
            print(f"  FAIL: {f}")
            print(f"        {e}")

    total = len(source_files)
    passed = total - len(failures)
    print(f"\nResults: {passed}/{total} passed, {len(failures)} failed")

    if failures:
        print("\nFailed files:")
        for f, err in failures:
            print(f"  - {f}: {err}")
        return 1

    print("All source files compile OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
