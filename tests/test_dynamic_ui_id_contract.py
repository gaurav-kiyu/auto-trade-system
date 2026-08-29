"""Regression guard for dynamically rendered enterprise controls.

Dynamic template fragments must not emit duplicate static DOM IDs.  Such IDs
break getElementById(), delegated event routing, accessibility relationships,
and can make only the first generated control functional.
"""
from pathlib import Path
import re

ENTERPRISE = Path(__file__).resolve().parents[1] / "templates" / "enterprise"


def test_dynamic_template_fragments_do_not_emit_static_duplicate_ids():
    problems = []
    for path in ENTERPRISE.glob("*.html"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        # Inspect template-literal regions that contain ${...}. A literal id
        # inside such a repeated fragment is unsafe unless it is itself unique.
        for match in re.finditer(r"`([\\s\\S]*?\\$\\{[\\s\\S]*?)`", text):
            fragment = match.group(1)
            ids = re.findall(r'\\bid=["\\\']([^"\\\']+)["\\\']', fragment)
            for dom_id in ids:
                if not dom_id.startswith("${"):
                    problems.append(f"{path.name}: dynamic fragment emits static id={dom_id!r}")
    assert not problems, "\\n".join(problems)


def test_tax_loss_results_have_no_fake_execute_button():
    path = ENTERPRISE / "admin_portfolio_analyzer.html"
    text = path.read_text(encoding="utf-8", errors="ignore")
    assert 'id="cspfix-23"' not in text
    assert "Execute Harvesting Swap" not in text
    assert "Manual Broker Execution Required" in text
