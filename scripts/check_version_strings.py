"""Find hardcoded version strings that should come from VERSION file.

Ignores known-false-positive patterns:
  - Version parsing/computation lines
  - The admin_control_plane.py fallback (uses VERSION file at runtime)
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION_PATH = os.path.join(ROOT, "VERSION")

# Lines matching any of these patterns are excluded from results
_IGNORE_PATTERNS = [
    r'major_minor\s*=',
    r'# e\.g\.',
    r'_VERSION\s*=\s*["\']\d',   # version assignment (e.g. admin_cp fallback)
]

def _is_ignored_line(line: str) -> bool:
    return any(re.search(p, line) for p in _IGNORE_PATTERNS)

def read_version():
    with open(VERSION_PATH) as f:
        return f.read().strip()

def find_hardcoded_versions():
    version = read_version()
    major_minor = ".".join(version.split(".")[:2])  # e.g. "2.53"

    found = []

    for dirpath, dirnames, filenames in os.walk(ROOT):
        rel = os.path.relpath(dirpath, ROOT)
        if any(skip in rel.split(os.sep) for skip in (".venv", "site-packages", ".git", "__pycache__")):
            continue

        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            fp = os.path.join(dirpath, fn)

            with open(fp, encoding="utf-8", errors="ignore") as f:
                for i, line in enumerate(f, 1):
                    stripped = line.strip()
                    if stripped.startswith("#"):
                        continue
                    if _is_ignored_line(stripped):
                        continue
                    if f'"{major_minor}' in stripped or f"'{major_minor}" in stripped:
                        if "version" in stripped.lower() or "v2." in stripped.lower() or "2.5" in stripped:
                            found.append((fp, i, stripped[:100]))

    return found, version

if __name__ == "__main__":
    found, ver = find_hardcoded_versions()
    print(f"Current version: {ver}")
    print(f"Hardcoded version strings found: {len(found)}")
    for fp, ln, text in found:
        rel = os.path.relpath(fp, ROOT)
        print(f"  {rel}:{ln}: {text}")
    sys.exit(0 if not found else 1)
