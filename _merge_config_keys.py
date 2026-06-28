#!/usr/bin/env python3
"""Merge missing defaults keys into config.template.json."""
from __future__ import annotations
import json

with open("index_config.defaults.json", encoding="utf-8") as f:
    defaults = json.load(f)

with open("config.template.json", encoding="utf-8") as f:
    template = json.load(f)

defaults_keys = {k: v for k, v in defaults.items() if not k.startswith("_")}
template_keys = set(k for k in template.keys() if not k.startswith("_"))
missing = {k: v for k, v in defaults_keys.items() if k not in template_keys}
extra = {k: v for k, v in template.items() if not k.startswith("_") and k not in defaults_keys}

print(f"Missing keys to add: {len(missing)}")
for k in sorted(missing.keys()):
    print(f"  + {k}")

print(f"\nExtra keys in template (not in defaults): {len(extra)}")
for k in sorted(extra.keys()):
    print(f"  - {k}")

# Add missing keys to the template
for k, v in missing.items():
    template[k] = v

# Write back
with open("config.template.json", "w", encoding="utf-8") as f:
    json.dump(template, f, indent=2, ensure_ascii=False)

# Verify
with open("config.template.json", encoding="utf-8") as f:
    updated = json.load(f)
updated_keys = set(k for k in updated.keys() if not k.startswith("_"))
still_missing = set(defaults_keys.keys()) - updated_keys
print(f"\nVerification:")
print(f"  Template keys before: {len(template_keys)}")
print(f"  Template keys now: {len(updated_keys)}")
print(f"  Still missing: {len(still_missing)}")
if still_missing:
    for k in sorted(still_missing):
        print(f"    ! {k}")

print("\nDone.")
