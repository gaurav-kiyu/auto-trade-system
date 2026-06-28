#!/usr/bin/env python3
"""Compute configuration drift between index_config.defaults.json and template files."""
from __future__ import annotations
import json
import sys

def load_json(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)

d = load_json("index_config.defaults.json")

# Compare with stock_config.template.json
try:
    t = load_json("stock_config.template.json")
    defaults_keys = set(k for k in d.keys() if not k.startswith("_"))
    template_keys = set(k for k in t.keys() if not k.startswith("_"))
    missing = defaults_keys - template_keys
    extra = template_keys - defaults_keys
    print(f"=== STOCK CONFIG TEMPLATE DRIFT ===")
    print(f"Defaults (non-comment): {len(defaults_keys)}")
    print(f"Template (non-comment): {len(template_keys)}")
    print(f"Missing from template: {len(missing)}")
    print(f"Extra in template: {len(extra)}")
    if missing:
        print("\nMissing keys:")
        for k in sorted(missing):
            print(f"  {k}")
    if extra:
        print("\nExtra keys:")
        for k in sorted(extra):
            print(f"  {k}")
except Exception as e:
    print(f"ERROR reading stock_config.template.json: {e}", file=sys.stderr)

# Compare with config.template.json
try:
    ct = load_json("config.template.json")
    ct_keys = set(k for k in ct.keys() if not k.startswith("_"))
    missing_ct = defaults_keys - ct_keys
    print(f"\n=== CONFIG TEMPLATE DRIFT ===")
    print(f"Config.template (non-comment): {len(ct_keys)}")
    print(f"Missing from config.template: {len(missing_ct)}")
    if missing_ct:
        print("\nMissing keys:")
        for k in sorted(missing_ct)[:30]:
            print(f"  {k}")
        if len(missing_ct) > 30:
            print(f"  ... and {len(missing_ct) - 30} more")
except Exception as e:
    print(f"ERROR reading config.template.json: {e}", file=sys.stderr)

# Also compare config.json
try:
    c = load_json("config.json")
    c_keys = set(k for k in c.keys() if not k.startswith("_"))
    extra_c = c_keys - defaults_keys
    if extra_c:
        print(f"\n=== CONFIG.JSON HAS EXTRA KEYS NOT IN DEFAULTS ===")
        for k in sorted(extra_c):
            print(f"  EXTRA: {k}")
except Exception as e:
    print(f"ERROR reading config.json: {e}", file=sys.stderr)

print("\nDone.")
