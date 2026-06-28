#!/usr/bin/env python3
"""Validate config template is in sync with defaults."""
from __future__ import annotations
import json
import sys

# Load with utf-8 encoding explicitly
with open("index_config.defaults.json", encoding="utf-8") as f:
    defaults = json.load(f)

with open("config.template.json", encoding="utf-8") as f:
    template = json.load(f)

defaults_keys = {k for k in defaults if not k.startswith("_")}
template_keys = {k for k in template if not k.startswith("_")}

missing = defaults_keys - template_keys
extra = template_keys - defaults_keys

print(f"Defaults keys (non-comment): {len(defaults_keys)}")
print(f"Template keys (non-comment): {len(template_keys)}")
print(f"Missing from template: {len(missing)}")
print(f"Extra in template: {len(extra)}")

status = "OK" if len(missing) == 0 else "DRIFT DETECTED"
print(f"\nStatus: {status}")

if missing:
    for k in sorted(missing):
        print(f"  MISSING: {k}")

if extra:
    print(f"\nExtra keys (not in defaults, may be stale):")
    for k in sorted(extra):
        print(f"  EXTRA: {k}")

# Also verify config.json loads cleanly
try:
    with open("config.json", encoding="utf-8") as f:
        c = json.load(f)
    # Check for stale keys
    c_keys = set(c.keys())
    stale = {k for k in c_keys if not k.startswith("_") and k not in defaults_keys}
    if stale:
        print(f"\nStale keys in config.json (not in defaults): {len(stale)}")
        for k in sorted(stale):
            print(f"  STALE: {k}")
except Exception as e:
    print(f"\nERROR loading config.json: {e}")

sys.exit(0 if len(missing) == 0 else 1)
