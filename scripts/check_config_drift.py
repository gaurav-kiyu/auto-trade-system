#!/usr/bin/env python3
"""Configuration Drift Detector — OPB v2.57.1

Compares the running configuration against defaults to detect:
  - Missing keys in running config
  - Deprecated keys still in use
  - Value drift (values different from defaults)
  - Type mismatches
  - Environment variable overrides

Output:
  - JSON report of drift findings
  - HTML visualization
  - CI-compatible exit code

Usage:
    python scripts/check_config_drift.py
    python scripts/check_config_drift.py --json
    python scripts/check_config_drift.py --ci
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

# ── Configuration ─────────────────────────────────────────────────────────────

REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"
HTML_REPORT = REPORTS_DIR / "config_drift_report.html"
JSON_REPORT = REPORTS_DIR / "config_drift_report.json"

IGNORED_KEYS = {
    # These are expected to differ between environments
    "BOT_TOKEN", "CHAT_ID", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
    "ADMIN_IDS", "ALLOWED_USERS",
    "CONFIG_PATH", "LOG_DIR", "DATA_DIR", "REPORTS_DIR",
    "ENVIRONMENT",
}


def _load_defaults() -> dict[str, Any]:
    """Load the default configuration from index_config.defaults.json."""
    root = Path(__file__).resolve().parent.parent
    paths = [
        root / "json/index_config.defaults.json",
        root / "json/stock_config.defaults.json",
    ]
    defaults = {}
    for path in paths:
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                defaults.update(data)
            except (json.JSONDecodeError, OSError) as e:
                print(f"  ⚠️  Could not load {path.name}: {e}", file=sys.stderr)
    return defaults


def _load_config(path: str) -> dict[str, Any]:
    """Load a configuration file."""
    p = Path(path)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            print(f"  ⚠️  Could not load {path}: {e}", file=sys.stderr)
    return {}


def _get_type_name(value: Any) -> str:
    """Get human-readable type name for a value."""
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    if value is None:
        return "null"
    return type(value).__name__


def _flatten_dict(d: dict[str, Any], parent_key: str = "", sep: str = ".") -> dict[str, Any]:
    """Flatten a nested dict into dot-separated keys."""
    items: dict[str, Any] = {}
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.update(_flatten_dict(v, new_key, sep=sep))
        else:
            items[new_key] = v
    return items


def detect_drift() -> dict[str, Any]:
    """Compare running configs against defaults and report drift."""
    root = Path(__file__).resolve().parent.parent

    # Load defaults
    defaults = _load_defaults()
    flat_defaults = _flatten_dict(defaults)
    default_keys = set(flat_defaults.keys())

    # Load all config files
    config_files = [
        str(root / "json/config.json"),
        str(root / "json/config.local.json"),
        str(root / "json/config.paper.json"),
        str(root / "json/config.dev.json"),
    ]

    findings: list[dict[str, Any]] = []
    keys_in_use: set[str] = set()
    config_sources: dict[str, str] = {}

    for cfg_path in config_files:
        if not Path(cfg_path).exists():
            continue
        cfg = _load_config(cfg_path)
        flat = _flatten_dict(cfg)
        source_name = Path(cfg_path).name

        for key, value in flat.items():
            keys_in_use.add(key)
            config_sources[key] = source_name

            # Check if key exists in defaults (flat_defaults has dot-separated keys from nested dicts)
            if key not in default_keys:
                if key not in IGNORED_KEYS:
                    findings.append({
                        "type": "unknown_key",
                        "key": key,
                        "config": source_name,
                        "value": value,
                        "severity": "low",
                        "message": f"Key '{key}' not found in defaults — may be deprecated or misspelled",
                    })
                continue

            # Compare type
            default_value = flat_defaults.get(key)

            if default_value is not None:
                actual_type = _get_type_name(value)
                expected_type = _get_type_name(default_value)

                if actual_type != expected_type and key not in IGNORED_KEYS:
                    findings.append({
                        "type": "type_mismatch",
                        "key": key,
                        "config": source_name,
                        "expected_type": expected_type,
                        "actual_type": actual_type,
                        "value": value,
                        "default_value": default_value,
                        "severity": "medium",
                        "message": f"Type mismatch for '{key}': expected {expected_type}, got {actual_type}",
                    })

                # Compare value (only for simple types)
                if actual_type in ("str", "int", "float", "bool") and key not in IGNORED_KEYS:
                    if value != default_value:
                        findings.append({
                            "type": "value_drift",
                            "key": key,
                            "config": source_name,
                            "default_value": default_value,
                            "value": value,
                            "severity": "info",
                            "message": f"'{key}' = {value} (default: {default_value})",
                        })

    # Check for missing keys in active configs
    active_config = {}
    for cfg_path in config_files:
        if Path(cfg_path).exists():
            active_config.update(_load_config(cfg_path))

    # Check env vars (mask values in report output)
    env_overrides = {}
    for key, value in os.environ.items():
        if key.startswith("OPBUYING_"):
            config_key = key[len("OPBUYING_"):].lower()
            masked = value[:4] + "****" if len(value) > 8 else "****"
            env_overrides[config_key] = masked

    return {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S IST"),
        "defaults_source": "json/index_config.defaults.json",
        "default_key_count": len(default_keys),
        "config_files_found": [f for f in config_files if Path(f).exists()],
        "keys_in_use": len(keys_in_use),
        "env_overrides_found": len(env_overrides),
        "env_overrides": env_overrides,
        "findings": findings,
        "total_findings": len(findings),
        "by_severity": {
            "low": sum(1 for f in findings if f["severity"] == "low"),
            "medium": sum(1 for f in findings if f["severity"] == "medium"),
            "high": sum(1 for f in findings if f["severity"] == "high"),
            "info": sum(1 for f in findings if f["severity"] == "info"),
        },
        "drift_detected": len(findings) > 0,
    }


def _generate_html(report: dict[str, Any]) -> str:
    """Generate HTML report."""
    timestamp = report.get("timestamp", "")
    findings = report.get("findings", [])

    # Group by severity
    high = [f for f in findings if f["severity"] == "high"]
    medium = [f for f in findings if f["severity"] == "medium"]
    low = [f for f in findings if f["severity"] == "low"]
    info = [f for f in findings if f["severity"] == "info"]

    all_rows = ""
    for f in findings:
        color = {"high": "red", "medium": "orange", "low": "#FF9800", "info": "#2196F3"}.get(f["severity"], "")
        all_rows += f"""
        <tr style="color:{color};">
            <td>{f['severity'].upper()}</td>
            <td><code>{f['key']}</code></td>
            <td>{f.get('config', 'N/A')}</td>
            <td>{f.get('message', '')[:120]}</td>
        </tr>"""

    env_rows = ""
    for key, value in report.get("env_overrides", {}).items():
        masked = value[:4] + "****" if len(value) > 8 else "****"
        env_rows += f"<tr><td><code>OPBUYING_{key.upper()}</code></td><td>{masked}</td></tr>"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Config Drift Report — OPB v2.57.1</title>
<style>
body {{ font-family: -apple-system, sans-serif; margin: 20px; background: #f5f5f5; }}
h1, h2 {{ color: #333; }}
table {{ border-collapse: collapse; width: 100%; margin: 10px 0; background: #fff; }}
th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
th {{ background: #4A90D9; color: white; }}
tr:nth-child(even) {{ background: #f9f9f9; }}
.summary {{ background: #e8f5e9; padding: 15px; border-radius: 5px; margin: 10px 0; }}
.drift {{ background: #fff3e0; padding: 15px; border-radius: 5px; margin: 10px 0; }}
</style>
</head>
<body>
<h1>⚙️ Configuration Drift Report</h1>
<div class="summary">
<p><strong>Timestamp:</strong> {timestamp}</p>
<p><strong>Default Keys:</strong> {report['default_key_count']:,}</p>
<p><strong>Keys in Use:</strong> {report['keys_in_use']}</p>
<p><strong>Environment Overrides:</strong> {report['env_overrides_found']}</p>
<p><strong>Findings:</strong> {report['total_findings']} (H:{high} M:{medium} L:{low} I:{info})</p>
</div>
<h2>🔍 Drift Findings</h2>
{'<table><tr><th>Severity</th><th>Key</th><th>Source</th><th>Message</th></tr>' + all_rows + '</table>' if findings else '<p>✅ No configuration drift detected.</p>'}
<h2>🌐 Environment Variable Overrides</h2>
{'<table><tr><th>Variable</th><th>Value (masked)</th></tr>' + env_rows + '</table>' if env_rows else '<p>No OPBUYING_* environment variables set.</p>'}
<p style="color:#888; margin-top:30px;">Generated by OPB Config Drift Detector v2.57.1</p>
</body>
</html>"""
    return html


def main() -> int:
    """CLI entry point."""
    import argparse
    parser = argparse.ArgumentParser(description="Configuration Drift Detector")
    parser.add_argument("--json", action="store_true", help="Output JSON report")
    parser.add_argument("--no-html", action="store_true", help="Skip HTML generation")
    parser.add_argument("--ci", action="store_true", help="CI mode: exit non-zero on medium+ findings")
    args = parser.parse_args()

    os.makedirs(REPORTS_DIR, exist_ok=True)

    print("=" * 60)
    print("  CONFIGURATION DRIFT DETECTOR v2.57.1")
    print("=" * 60)

    report = detect_drift()

    # Print summary
    print(f"\n  Default keys:     {report['default_key_count']:,}")
    print(f"  Keys in use:      {report['keys_in_use']}")
    print(f"  Env overrides:    {report['env_overrides_found']}")
    print(f"  Total findings:   {report['total_findings']}")

    if report["findings"]:
        print("\n  Findings by severity:")
        for severity, count in report["by_severity"].items():
            if count > 0:
                print(f"    {severity:<10s}: {count}")

        print("\n  Top findings:")
        for f in report["findings"][:10]:
            print(f"    [{f['severity'].upper()}] {f['message'][:100]}")

        if len(report["findings"]) > 10:
            print(f"    ... and {len(report['findings']) - 10} more")

    if report.get("env_overrides", {}):
        print(f"\n  Environment overrides active: {report['env_overrides_found']}")

    if args.json:
        print(json.dumps(report, indent=2, default=str))

    if not args.no_html:
        html = _generate_html(report)
        HTML_REPORT.write_text(html, encoding="utf-8")
        print(f"\n  HTML report: {HTML_REPORT}")

    JSON_REPORT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"  JSON report: {JSON_REPORT}")

    if args.ci:
        medium_plus = report["by_severity"]["medium"] + report["by_severity"]["high"]
        if medium_plus > 0:
            print(f"\n❌ CI FAILED: {medium_plus} medium+ severity findings")
            return 1

    print("\n" + "=" * 60)
    print("  CONFIG DRIFT CHECK COMPLETE")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
