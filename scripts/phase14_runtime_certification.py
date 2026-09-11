"""OPB v2.59.4 Phase-14 zero-trust runtime certification gate.

Run from the canonical repository root with the same Python environment used by
index_app/index_trader.py.  The gate is intentionally fail-closed for the NSE
OI workflow: a non-NSE fallback is never accepted as certification evidence.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if Path.cwd().resolve() != ROOT:
    print(f"[FAIL] Run from canonical root: {ROOT}")
    raise SystemExit(2)

print("=== OPB v2.59.4 PHASE-14 RUNTIME CERTIFICATION ===")
print(f"ROOT={ROOT}")

failures: list[str] = []


def fail(msg: str) -> None:
    failures.append(msg)
    print(f"[FAIL] {msg}")


def ok(msg: str) -> None:
    print(f"[PASS] {msg}")

# 1. Canonical source / architecture boundary.
try:
    from core.notifications.url_resolver import get_external_notification_base_url
    from core.nse_option_recorder import get_oi_summary
    from core.ports.market_data import MarketDataPort
    from core.services.market_data_service import MarketDataService
    ok("canonical market-data/OI modules import")
except Exception as exc:
    fail(f"module import failed: {exc}")
    raise SystemExit(1)

try:
    result = subprocess.run(
        [sys.executable, "scripts/check_architecture_compliance.py"],
        cwd=ROOT, text=True, capture_output=True, timeout=60,
    )
    if result.returncode == 0:
        ok("ADR-0010 architecture compliance")
    else:
        fail("ADR-0010 architecture compliance failed")
        print(result.stdout)
        print(result.stderr)
except Exception as exc:
    fail(f"architecture gate execution failed: {exc}")

# 2. Effective configuration.
config_path = Path(os.environ.get("OPBUYING_INDEX_CONFIG", "json/config.json"))
if not config_path.is_absolute():
    config_path = ROOT / config_path
try:
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(cfg, dict):
        raise ValueError("config is not an object")
    ok(f"effective config loaded: {config_path}")
except Exception as exc:
    fail(f"config load failed: {exc}")
    raise SystemExit(1)

# 3. External notification URL invariant.
external_url = get_external_notification_base_url(cfg)
if external_url.startswith("http://localhost") or "127.0.0.1" in external_url or "0.0.0.0" in external_url:
    fail(f"external notification URL is loopback: {external_url}")
else:
    ok(f"external notification URL={external_url}")

# 4. Central MDS wiring and provider registration.
mds = MarketDataService()
try:
    count = mds.populate_from_config(cfg)
    providers = mds.list_adapters()
    print(f"[INFO] MDS registered={count}: {list(providers)}")
    if bool(cfg.get("oi_snapshot_enabled", cfg.get("OI_SNAPSHOT_ENABLED", True))) and bool(cfg.get("DATA_PROVIDER_ENABLED", {}).get("nse", True)):
        if "nse" not in providers:
            fail("NSE provider is enabled/required but not registered")
        else:
            ok("required NSE provider registered in central MDS")
    else:
        ok("NSE OI workflow disabled by configuration")
except Exception as exc:
    fail(f"MDS configuration failed: {exc}")

# 5. Port conformance: MDS must be usable as the canonical MarketDataPort.
if not isinstance(mds, MarketDataPort):
    fail("MarketDataService does not satisfy MarketDataPort")
else:
    ok("MarketDataService satisfies MarketDataPort")

# 6. Fail-closed negative path: NSE outage must not fall back for OI.
class _FailingNSE:
    def get_option_chain(self, symbol, expiry_date=None):
        raise ConnectionError("synthetic NSE outage")

class _FakeYahoo:
    def get_option_chain(self, symbol, expiry_date=None):
        return [{"optionType": "CALL", "openInterest": 1, "volume": 1}]

negative = MarketDataService()
negative.register("nse", _FailingNSE(), ["index"], priority=10)
negative.register("yfinance", _FakeYahoo(), ["index"], priority=1)
chain, source = negative.get_option_chain_with_source("NIFTY", provider="nse")
if chain or source is not None:
    fail("NSE outage incorrectly produced fallback OI data")
else:
    ok("NSE OI failure path is fail-closed")

# 7. Actual runtime NSE option-chain check. This is the decisive external-data gate.
if "nse" in mds.list_adapters() and bool(cfg.get("DATA_PROVIDER_ENABLED", {}).get("nse", True)):
    nse_entry = mds._by_name.get("nse")
    # The probe is intentionally bounded so an exchange/network outage cannot
    # turn the certification command into a multi-minute retry loop.
    if nse_entry is not None and hasattr(nse_entry.adapter, "_max_retries"):
        nse_entry.adapter._max_retries = 1
    for symbol in ("NIFTY", "BANKNIFTY", "FINNIFTY"):
        chain, source = mds.get_option_chain_with_source(symbol, provider="nse")
        if source != "nse" or not chain:
            fail(f"LIVE NSE option chain unavailable for {symbol}: source={source!r}, contracts={len(chain)}")
            break
        ok(f"LIVE NSE option chain {symbol}: {len(chain)} contracts, source=nse")

# 8. OI summary must preserve NSE provenance.
if "nse" in mds.list_adapters():
    live = get_oi_summary(["NIFTY"], cfg, mds)
    item = live.get("NIFTY", {})
    if item.get("source") != "nse":
        fail(f"OI provenance is not NSE: {item}")
    elif item.get("total_oi", 0) <= 0:
        fail(f"NSE OI summary has no positive OI: {item}")
    else:
        ok("OI summary is live, positive, and NSE-provenanced")

# 9. Safety: certification run itself must not be live-order enabled.
mode = str(cfg.get("EXECUTION_MODE", "")).upper()
if mode not in {"PAPER", "SIGNAL_ONLY", "MANUAL"}:
    fail(f"runtime certification requires non-live execution mode, got {mode!r}")
else:
    ok(f"execution safety mode={mode}")

if failures:
    print("\n=== CERTIFICATION: HOLD ===")
    for failure in failures:
        print(f" - {failure}")
    raise SystemExit(1)

print("\n=== CERTIFICATION: GREEN ===")
print("All targeted Phase-14 runtime gates passed.")
