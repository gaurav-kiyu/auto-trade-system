"""Regression guard against direct external URL construction in runtime code."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOTS = [ROOT / "core", ROOT / "index_app", ROOT / "infrastructure"]

CONSTRUCTION_PATTERNS = [
    re.compile(r"request\.base_url\s*[+/]"),
    re.compile(r"\bbase_url\s*\+\s*[\"']"),
    re.compile(r"\bpublic_url\s*\+\s*[\"']"),
]


def test_runtime_does_not_concatenate_base_url_directly():
    offenders = []
    for root in RUNTIME_ROOTS:
        if not root.exists():
            continue
        for p in root.rglob("*.py"):
            text = p.read_text(encoding="utf-8", errors="ignore")
            for i, line in enumerate(text.splitlines(), 1):
                if any(rx.search(line) for rx in CONSTRUCTION_PATTERNS):
                    offenders.append(f"{p.relative_to(ROOT)}:{i}")
    assert not offenders, f"Direct base/public URL concatenation found: {offenders}"
