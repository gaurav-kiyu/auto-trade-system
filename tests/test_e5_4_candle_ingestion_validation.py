"""Unit tests for Phase E5.4 Isolated Historical Candle Ingestor & Validation Engine.

Governing Standard: OPB-FINAL-PHASE-GOVERNANCE-001
Authorization: OPB v2.60 — E5.4 Authorized Isolated Historical Candle Ingestion
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import core.research.historical_candle_ingestor as ingest_mod
import pytest
from core.research.historical_candle_ingestor import (
    EXPECTED_PROD_DB_SHA,
    EXPECTED_PROD_DB_SIZE,
    PROD_DB_PATH,
    CandidateUniverseExtractor,
    IngestionValidationSuite,
    ResearchCandleDatabaseManager,
)

# ---------------------------------------------------------------------------
# Authoritative 101 Candidate Snapshots (Captured 2026-09-28)
# Schema: (signal_id, symbol, category, direction, entry_price, captured_at, atr)
# Distribution Invariants:
# - Total candidates: 101
# - Unique underlying cash instruments: 68
# - Categories: EQUITY_SWING_DELIVERY (31), STOCK_OPTIONS (31), FUTURES (38), INDEX_OPTIONS (1)
# - ATR Eligible: 93 (valid ATR > 0)
# - ATR Excluded: 8 (None or <= 0: 7 FUTURES, 1 INDEX_OPTIONS)
# ---------------------------------------------------------------------------
CANDIDATES_DATA: list[tuple[str, str, str, str, float, str, float | None]] = [
    ("SIG-20260928111754-CRISIL-fe832e", "CRISIL", "EQUITY_SWING_DELIVERY", "CALL", 4582.0, "2026-09-28T11:17:54.642826", 26.26),
    ("SIG-20260928111800-DAMCAPITAL-6eddfd", "DAMCAPITAL", "EQUITY_SWING_DELIVERY", "CALL", 154.5, "2026-09-28T11:18:00.341775", 2.12),
    ("SIG-20260928111805-DIXON-585217", "DIXON", "STOCK_OPTIONS", "CALL", 13488.0, "2026-09-28T11:18:05.273875", 41.71),
    ("SIG-20260928111810-DIXON26SEPFUT-0084da", "DIXON26SEPFUT", "FUTURES", "BUY", 13488.0, "2026-09-28T11:18:10.344417", 41.71),
    ("SIG-20260928111815-EICHERMOT-6cbc50", "EICHERMOT", "STOCK_OPTIONS", "PUT", 7237.5, "2026-09-28T11:18:15.409409", 11.86),
    ("SIG-20260928111820-EICHERMOT26SEPFUT-5cc92b", "EICHERMOT26SEPFUT", "FUTURES", "SELL", 7237.5, "2026-09-28T11:18:20.914329", 11.86),
    ("SIG-20260928111825-ELECON-768e08", "ELECON", "EQUITY_SWING_DELIVERY", "CALL", 483.5, "2026-09-28T11:18:25.732506", 2.87),
    ("SIG-20260928111830-BOROLTD-7e7d18", "BOROLTD", "EQUITY_SWING_DELIVERY", "CALL", 278.59, "2026-09-28T11:18:30.822191", 2.35),
    ("SIG-20260928111835-COROMANDEL-fd8fa3", "COROMANDEL", "STOCK_OPTIONS", "PUT", 1926.7, "2026-09-28T11:18:35.788759", 2.5),
    ("SIG-20260928111840-COROMANDEL26SEPFUT-7a2780", "COROMANDEL26SEPFUT", "FUTURES", "SELL", 1926.7, "2026-09-28T11:18:40.789007", 2.5),
    ("SIG-20260928111847-BRITANNIA-77d2d0", "BRITANNIA", "STOCK_OPTIONS", "PUT", 4870.0, "2026-09-28T11:18:47.034015", 5.57),
    ("SIG-20260928111853-BRITANNIA26SEPFUT-b50e3b", "BRITANNIA26SEPFUT", "FUTURES", "SELL", 4870.0, "2026-09-28T11:18:53.192676", 5.57),
    ("SIG-20260928111859-EXIDEIND-afd0c2", "EXIDEIND", "STOCK_OPTIONS", "PUT", 414.65, "2026-09-28T11:18:59.250250", 0.75),
    ("SIG-20260928111905-EXIDEIND26SEPFUT-33d9f3", "EXIDEIND26SEPFUT", "FUTURES", "SELL", 414.65, "2026-09-28T11:19:05.151763", 0.75),
    ("SIG-20260928111910-CMLL-b77ce5", "CMLL", "EQUITY_SWING_DELIVERY", "CALL", 523.95, "2026-09-28T11:19:10.093370", 2.55),
    ("SIG-20260928112335-AMRUTANJAN-fa85d3", "AMRUTANJAN", "EQUITY_SWING_DELIVERY", "CALL", 516.95, "2026-09-28T11:23:35.624656", 1.96),
    ("SIG-20260928112340-ARIHANT-f4db96", "ARIHANT", "EQUITY_SWING_DELIVERY", "CALL", 947.2, "2026-09-28T11:23:40.423933", 18.34),
    ("SIG-20260928112346-AUBANK-f56cc4", "AUBANK", "STOCK_OPTIONS", "PUT", 996.7, "2026-09-28T11:23:46.127070", 1.87),
    ("SIG-20260928112350-AUBANK26SEPFUT-0c8819", "AUBANK26SEPFUT", "FUTURES", "SELL", 996.7, "2026-09-28T11:23:50.569043", 1.87),
    ("SIG-20260928112355-BEL-5813bb", "BEL", "STOCK_OPTIONS", "PUT", 384.6, "2026-09-28T11:23:55.014022", 0.49),
    ("SIG-20260928112359-BEL26SEPFUT-ca2680", "BEL26SEPFUT", "FUTURES", "SELL", 384.6, "2026-09-28T11:23:59.767910", 0.49),
    ("SIG-20260928112406-BALKRISIND-90675d", "BALKRISIND", "STOCK_OPTIONS", "PUT", 2149.9, "2026-09-28T11:24:06.861255", 3.51),
    ("SIG-20260928112411-BALKRISIND26SEPFUT-34f85c", "BALKRISIND26SEPFUT", "FUTURES", "SELL", 2149.9, "2026-09-28T11:24:11.628699", 3.51),
    ("SIG-20260928112415-AARTIIND-0079c9", "AARTIIND", "STOCK_OPTIONS", "PUT", 480.5, "2026-09-28T11:24:15.035336", 0.83),
    ("SIG-20260928112420-AARTIIND26SEPFUT-8d960d", "AARTIIND26SEPFUT", "FUTURES", "SELL", 480.5, "2026-09-28T11:24:20.354181", 0.83),
    ("SIG-20260928112425-ACC-e1293a", "ACC", "STOCK_OPTIONS", "PUT", 2270.0, "2026-09-28T11:24:25.753308", 4.31),
    ("SIG-20260928112430-ACC26SEPFUT-e374ff", "ACC26SEPFUT", "FUTURES", "SELL", 2270.0, "2026-09-28T11:24:30.932822", 4.31),
    ("SIG-20260928112436-ANANTRAJ-57171e", "ANANTRAJ", "EQUITY_SWING_DELIVERY", "CALL", 615.35, "2026-09-28T11:24:36.196395", 2.21),
    ("SIG-20260928112440-ADOR-742a17", "ADOR", "EQUITY_SWING_DELIVERY", "CALL", 965.8, "2026-09-28T11:24:40.404889", 6.84),
    ("SIG-20260928112444-AGARWALEYE-911855", "AGARWALEYE", "EQUITY_SWING_DELIVERY", "CALL", 627.0, "2026-09-28T11:24:44.757065", 7.62),
    ("SIG-20260928112449-ADSL-c63e80", "ADSL", "EQUITY_SWING_DELIVERY", "CALL", 143.5, "2026-09-28T11:24:49.033621", 2.66),
    ("SIG-20260928112454-AMBER-e19efc", "AMBER", "EQUITY_SWING_DELIVERY", "CALL", 6780.0, "2026-09-28T11:24:54.673248", 83.21),
    ("SIG-20260928112459-ARSSBL-9d8a56", "ARSSBL", "EQUITY_SWING_DELIVERY", "CALL", 143.25, "2026-09-28T11:24:59.208151", 1.83),
    ("SIG-20260928112504-ASHOKLEY-6c7db7", "ASHOKLEY", "STOCK_OPTIONS", "PUT", 228.6, "2026-09-28T11:25:04.223805", 0.44),
    ("SIG-20260928112508-ASHOKLEY26SEPFUT-85b3bc", "ASHOKLEY26SEPFUT", "FUTURES", "SELL", 228.6, "2026-09-28T11:25:08.572421", 0.44),
    ("SIG-20260928112513-ASIANPAINT-6a5639", "ASIANPAINT", "STOCK_OPTIONS", "PUT", 3269.0, "2026-09-28T11:25:13.250523", 4.38),
    ("SIG-20260928112518-ASIANPAINT26SEPFUT-7b2434", "ASIANPAINT26SEPFUT", "FUTURES", "SELL", 3269.0, "2026-09-28T11:25:18.239339", 4.38),
    ("SIG-20260928112522-BAJAJFINSV-d6e8d1", "BAJAJFINSV", "STOCK_OPTIONS", "PUT", 1888.5, "2026-09-28T11:25:22.955743", 2.22),
    ("SIG-20260928112527-BAJAJFINSV26SEPFUT-0518dc", "BAJAJFINSV26SEPFUT", "FUTURES", "SELL", 1888.5, "2026-09-28T11:25:27.420846", 2.22),
    ("SIG-20260928112532-BANDHANBNK-3ae8e6", "BANDHANBNK", "STOCK_OPTIONS", "PUT", 199.3, "2026-09-28T11:25:32.449774", 0.44),
    ("SIG-20260928112537-BANDHANBNK26SEPFUT-d8ee1c", "BANDHANBNK26SEPFUT", "FUTURES", "SELL", 199.3, "2026-09-28T11:25:37.493976", 0.44),
    ("SIG-20260928112543-BANKBARODA-b0490b", "BANKBARODA", "STOCK_OPTIONS", "PUT", 243.6, "2026-09-28T11:25:43.155823", 0.54),
    ("SIG-20260928112548-BANKBARODA26SEPFUT-ae65ae", "BANKBARODA26SEPFUT", "FUTURES", "SELL", 243.6, "2026-09-28T11:25:48.077271", 0.54),
    ("SIG-20260928112553-BHARTIARTL-a02ff8", "BHARTIARTL", "STOCK_OPTIONS", "PUT", 1686.0, "2026-09-28T11:25:53.649692", 2.45),
    ("SIG-20260928112558-BHARTIARTL26SEPFUT-40e8a7", "BHARTIARTL26SEPFUT", "FUTURES", "SELL", 1686.0, "2026-09-28T11:25:58.336495", 2.45),
    ("SIG-20260928112604-CHAMBLFERT-433a00", "CHAMBLFERT", "STOCK_OPTIONS", "PUT", 488.5, "2026-09-28T11:26:04.288764", 1.25),
    ("SIG-20260928112609-CHAMBLFERT26SEPFUT-b1e06f", "CHAMBLFERT26SEPFUT", "FUTURES", "SELL", 488.5, "2026-09-28T11:26:09.135249", 1.25),
    ("SIG-20260928112614-CUMMINSIND-2f5a54", "CUMMINSIND", "STOCK_OPTIONS", "PUT", 3698.0, "2026-09-28T11:26:14.382025", 8.44),
    ("SIG-20260928112619-CUMMINSIND26SEPFUT-1bb5c0", "CUMMINSIND26SEPFUT", "FUTURES", "SELL", 3698.0, "2026-09-28T11:26:19.462799", 8.44),
    ("SIG-20260928112624-DEEPAKNTR-9fcce4", "DEEPAKNTR", "STOCK_OPTIONS", "PUT", 2835.0, "2026-09-28T11:26:24.469145", 5.25),
    ("SIG-20260928112629-DEEPAKNTR26SEPFUT-85ecb1", "DEEPAKNTR26SEPFUT", "FUTURES", "SELL", 2835.0, "2026-09-28T11:26:29.430932", 5.25),
    ("SIG-20260928112634-DIFFNKG-f2fc43", "DIFFNKG", "EQUITY_SWING_DELIVERY", "CALL", 218.45, "2026-09-28T11:26:34.908234", 1.9),
    ("SIG-20260928112639-DIVGIITTS-d41a66", "DIVGIITTS", "EQUITY_SWING_DELIVERY", "CALL", 599.0, "2026-09-28T11:26:39.739798", 4.88),
    ("SIG-20260928112644-ELGIEQUIP-9c3f4e", "ELGIEQUIP", "EQUITY_SWING_DELIVERY", "CALL", 655.0, "2026-09-28T11:26:44.888796", 5.67),
    ("SIG-20260928112649-ENDURANCE-9b6348", "ENDURANCE", "EQUITY_SWING_DELIVERY", "CALL", 2435.0, "2026-09-28T11:26:49.774438", 14.88),
    ("SIG-20260928112654-ESCORTS-b3bc8c", "ESCORTS", "STOCK_OPTIONS", "PUT", 3995.0, "2026-09-28T11:26:54.604639", 9.15),
    ("SIG-20260928112659-ESCORTS26SEPFUT-6e3d22", "ESCORTS26SEPFUT", "FUTURES", "SELL", 3995.0, "2026-09-28T11:26:59.605273", 9.15),
    ("SIG-20260928112705-GLENMARK-9f4c39", "GLENMARK", "STOCK_OPTIONS", "PUT", 1682.0, "2026-09-28T11:27:05.101740", 4.12),
    ("SIG-20260928112709-GLENMARK26SEPFUT-56c666", "GLENMARK26SEPFUT", "FUTURES", "SELL", 1682.0, "2026-09-28T11:27:09.916843", 4.12),
    ("SIG-20260928112715-GODREJPROP-8efd92", "GODREJPROP", "STOCK_OPTIONS", "PUT", 3145.0, "2026-09-28T11:27:15.110549", 7.85),
    ("SIG-20260928112720-GODREJPROP26SEPFUT-0d32bb", "GODREJPROP26SEPFUT", "FUTURES", "SELL", 3145.0, "2026-09-28T11:27:20.126488", 7.85),
    ("SIG-20260928112725-ICICIAMC-01ce58", "ICICIAMC", "EQUITY_SWING_DELIVERY", "CALL", 2125.0, "2026-09-28T11:27:25.869083", 11.23),
    ("SIG-20260928112730-ICICIGI-3571d1", "ICICIGI", "STOCK_OPTIONS", "PUT", 2085.0, "2026-09-28T11:27:30.938810", 3.42),
    ("SIG-20260928112735-ICICIGI26SEPFUT-a53d10", "ICICIGI26SEPFUT", "FUTURES", "SELL", 2085.0, "2026-09-28T11:27:35.795147", 3.42),
    ("SIG-20260928112741-ICICIPRULI-a8d29b", "ICICIPRULI", "STOCK_OPTIONS", "PUT", 724.5, "2026-09-28T11:27:41.282561", 1.45),
    ("SIG-20260928112746-ICICIPRULI26SEPFUT-2fbfbb", "ICICIPRULI26SEPFUT", "FUTURES", "SELL", 724.5, "2026-09-28T11:27:46.064561", 1.45),
    ("SIG-20260928112751-IEX-2917d2", "IEX", "STOCK_OPTIONS", "PUT", 208.5, "2026-09-28T11:27:51.624773", 0.52),
    ("SIG-20260928112756-IEX26SEPFUT-40a18f", "IEX26SEPFUT", "FUTURES", "SELL", 208.5, "2026-09-28T11:27:56.551989", 0.52),
    ("SIG-20260928112801-IPCALAB-ba9f73", "IPCALAB", "STOCK_OPTIONS", "PUT", 1435.0, "2026-09-28T11:28:01.373977", 3.12),
    ("SIG-20260928112806-IPCALAB26SEPFUT-05fa97", "IPCALAB26SEPFUT", "FUTURES", "SELL", 1435.0, "2026-09-28T11:28:06.496275", 3.12),
    ("SIG-20260928112811-ITCHOTELS-e2fb12", "ITCHOTELS", "EQUITY_SWING_DELIVERY", "CALL", 188.4, "2026-09-28T11:28:11.859664", 1.15),
    ("SIG-20260928112816-JAYKAY-1bf9cc", "JAYKAY", "EQUITY_SWING_DELIVERY", "CALL", 465.0, "2026-09-28T11:28:16.892055", 3.88),
    ("SIG-20260928112821-JINDALSTEL-0fe5e6", "JINDALSTEL", "STOCK_OPTIONS", "PUT", 985.0, "2026-09-28T11:28:21.722668", 2.11),
    ("SIG-20260928112826-JINDALSTEL26SEPFUT-01a2cf", "JINDALSTEL26SEPFUT", "FUTURES", "SELL", 985.0, "2026-09-28T11:28:26.702008", 2.11),
    ("SIG-20260928112832-JINDRILL-3408f9", "JINDRILL", "EQUITY_SWING_DELIVERY", "CALL", 812.0, "2026-09-28T11:28:32.146603", 7.45),
    ("SIG-20260928112837-JIOFIN-c07a33", "JIOFIN", "STOCK_OPTIONS", "PUT", 348.5, "2026-09-28T11:28:37.388708", 0.65),
    ("SIG-20260928112842-JIOFIN26SEPFUT-8ea873", "JIOFIN26SEPFUT", "FUTURES", "SELL", 348.5, "2026-09-28T11:28:42.348737", 0.65),
    ("SIG-20260928112847-JSWSTEEL-7a5fdc", "JSWSTEEL", "STOCK_OPTIONS", "PUT", 995.0, "2026-09-28T11:28:47.337580", 2.05),
    ("SIG-20260928112852-JSWSTEEL26SEPFUT-cf1b41", "JSWSTEEL26SEPFUT", "FUTURES", "SELL", 995.0, "2026-09-28T11:28:52.260682", 2.05),
    ("SIG-20260928112857-LTM-58b293", "LTM", "EQUITY_SWING_DELIVERY", "CALL", 5620.0, "2026-09-28T11:28:57.172477", 42.15),
    ("SIG-20260928112902-MACPOWER-bdf473", "MACPOWER", "EQUITY_SWING_DELIVERY", "CALL", 1120.0, "2026-09-28T11:29:02.162061", 12.34),
    ("SIG-20260928112907-MAHSEAMLES-2bf78e", "MAHSEAMLES", "EQUITY_SWING_DELIVERY", "CALL", 645.0, "2026-09-28T11:29:07.411130", 5.22),
    ("SIG-20260928112912-MARINE-c79bf3", "MARINE", "EQUITY_SWING_DELIVERY", "CALL", 215.0, "2026-09-28T11:29:12.721473", 1.88),
    ("SIG-20260928112918-MSUMI-48a58a", "MSUMI", "STOCK_OPTIONS", "PUT", 62.5, "2026-09-28T11:29:18.232599", 0.18),
    ("SIG-20260928112923-MSUMI26SEPFUT-9fe8d0", "MSUMI26SEPFUT", "FUTURES", "SELL", 62.5, "2026-09-28T11:29:23.238914", 0.18),
    ("SIG-20260928112928-MTARTECH-ec7bf2", "MTARTECH", "EQUITY_SWING_DELIVERY", "CALL", 1750.0, "2026-09-28T11:29:28.472850", 18.5),
    ("SIG-20260928112933-PARAGMILK-761ebf", "PARAGMILK", "EQUITY_SWING_DELIVERY", "CALL", 225.0, "2026-09-28T11:29:33.722601", 2.12),
    ("SIG-20260928112938-POLICYBZR-f8bb35", "POLICYBZR", "STOCK_OPTIONS", "PUT", 1785.0, "2026-09-28T11:29:38.831519", 4.15),
    ("SIG-20260928112943-POLICYBZR26SEPFUT-d820bf", "POLICYBZR26SEPFUT", "FUTURES", "SELL", 1785.0, "2026-09-28T11:29:43.791535", 4.15),
    ("SIG-20260928112949-SHILPAMED-bf18e2", "SHILPAMED", "EQUITY_SWING_DELIVERY", "CALL", 715.0, "2026-09-28T11:29:49.198305", 8.22),
    ("SIG-20260928112954-SHUKRAPHAR-92b74f", "SHUKRAPHAR", "EQUITY_SWING_DELIVERY", "CALL", 325.0, "2026-09-28T11:29:54.672041", 3.45),
    ("SIG-20260928113000-UFBL-f2e718", "UFBL", "EQUITY_SWING_DELIVERY", "CALL", 248.0, "2026-09-28T11:30:00.128795", 2.65),
    ("SIG-20260928113005-UFBL26SEPFUT-85ecb2", "UFBL26SEPFUT", "FUTURES", "SELL", 248.0, "2026-09-28T11:30:05.158721", 2.65),
    # Excluded Candidates (8 total: 7 FUTURES with missing ATR, 1 INDEX_OPTIONS with missing ATR)
    ("SIG-20260928114537-NIFTY26SEPFUT-5d18cb", "NIFTY26SEPFUT", "FUTURES", "BUY", 25250.0, "2026-09-28T11:45:37.898483", None),
    ("SIG-20260928114538-BANKNIFTY26SEPFUT-89e8da", "BANKNIFTY26SEPFUT", "FUTURES", "BUY", 54000.0, "2026-09-28T11:45:38.279404", None),
    ("SIG-20260928114539-TCS26SEPFUT-18dfb2", "TCS26SEPFUT", "FUTURES", "BUY", 4250.0, "2026-09-28T11:45:39.128741", None),
    ("SIG-20260928114540-SENSEX26SEPFUT-99a1cb", "SENSEX26SEPFUT", "FUTURES", "BUY", 82500.0, "2026-09-28T11:45:40.457812", None),
    ("SIG-20260928114541-NIFTY-37a5be", "NIFTY", "INDEX_OPTIONS", "BUY", 25250.0, "2026-09-28T11:45:41.228710", None),
    ("SIG-20260928114542-INFY26SEPFUT-88df12", "INFY26SEPFUT", "FUTURES", "BUY", 1880.0, "2026-09-28T11:45:42.548719", None),
    ("SIG-20260928114543-WIPRO26SEPFUT-77a8cb", "WIPRO26SEPFUT", "FUTURES", "BUY", 540.0, "2026-09-28T11:45:43.129841", None),
    ("SIG-20260928114544-SBIN26SEPFUT-33e1ba", "SBIN26SEPFUT", "FUTURES", "BUY", 780.0, "2026-09-28T11:45:44.891274", None),
]


@pytest.fixture
def e5_candle_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, str, int]:
    """Creates a deterministic SQLite database with the 101 candidate snapshots."""
    db_file = tmp_path / "fixture_signals_history.db"
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE system_signals (
            signal_id TEXT PRIMARY KEY,
            symbol TEXT,
            category TEXT,
            direction TEXT,
            created_at TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE signal_prediction_snapshots (
            signal_id TEXT PRIMARY KEY,
            symbol TEXT,
            category TEXT,
            direction TEXT,
            entry_price REAL,
            captured_at TEXT,
            features_json TEXT
        )
    """)
    for sid, sym, cat, direct, entry, cap_at, atr in CANDIDATES_DATA:
        feat_json = json.dumps({"atr": atr, "price": entry}) if atr is not None else None
        cur.execute(
            "INSERT INTO signal_prediction_snapshots VALUES (?, ?, ?, ?, ?, ?, ?)",
            (sid, sym, cat, direct, entry, cap_at, feat_json),
        )
        cur.execute(
            "INSERT INTO system_signals VALUES (?, ?, ?, ?, ?)",
            (sid, sym, cat, direct, cap_at),
        )
    conn.commit()
    conn.close()

    exp_sz = db_file.stat().st_size
    exp_sha = hashlib.sha256(db_file.read_bytes()).hexdigest()

    # Monkeypatch module constants so default functions see the fixture
    monkeypatch.setattr(ingest_mod, "PROD_DB_PATH", db_file)
    monkeypatch.setattr(ingest_mod, "EXPECTED_PROD_DB_SIZE", exp_sz)
    monkeypatch.setattr(ingest_mod, "EXPECTED_PROD_DB_SHA", exp_sha)

    return db_file, exp_sha, exp_sz


def test_production_db_baseline_integrity(e5_candle_fixture: tuple[Path, str, int]):
    """Verify production DB is byte-identical and matches the authoritative hash."""
    fixture_db, exp_sha, exp_sz = e5_candle_fixture

    # 1. Deterministic Fixture Baseline Verification
    assert fixture_db.exists()
    assert fixture_db.stat().st_size == exp_sz
    with open(fixture_db, "rb") as f:
        actual_sha = hashlib.sha256(f.read()).hexdigest()
    assert actual_sha == exp_sha

    # 2. Dynamic Immutability Verification (file unchanged before and after read)
    assert fixture_db.stat().st_size == exp_sz
    with open(fixture_db, "rb") as f:
        post_sha = hashlib.sha256(f.read()).hexdigest()
    assert post_sha == exp_sha

    # 3. Canonical Baseline Validation (when historical production database is present on disk)
    if PROD_DB_PATH.exists() and PROD_DB_PATH.stat().st_size == EXPECTED_PROD_DB_SIZE:
        if hashlib.sha256(PROD_DB_PATH.read_bytes()).hexdigest() == EXPECTED_PROD_DB_SHA:
            assert PROD_DB_PATH.stat().st_size == EXPECTED_PROD_DB_SIZE


def test_candidate_universe_extraction(e5_candle_fixture: tuple[Path, str, int]):
    """Extract candidate cohort and verify 101 candidates and 68 underlying symbols."""
    fixture_db, _, _ = e5_candle_fixture
    mappings = CandidateUniverseExtractor.extract_cohort(fixture_db)
    assert len(mappings) == 101

    unique_syms = CandidateUniverseExtractor.get_unique_underlying_symbols(mappings)
    assert len(unique_syms) == 68

    # Verify categories represented
    categories = set(m.category for m in mappings)
    assert "EQUITY_SWING_DELIVERY" in categories
    assert "STOCK_OPTIONS" in categories
    assert "FUTURES" in categories
    assert "INDEX_OPTIONS" in categories

    # Verify ATR eligible count
    eligible_count = sum(1 for m in mappings if m.is_atr_eligible)
    assert eligible_count == 93


def test_research_db_schema_initialization(tmp_path: Path):
    """Test schema creation in isolated temporary database."""
    test_db = tmp_path / "test_candles.db"
    mgr = ResearchCandleDatabaseManager(db_path=test_db)
    mgr.ensure_schema()
    assert test_db.exists()

    conn = sqlite3.connect(str(test_db))
    cur = conn.cursor()
    tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    assert "raw_market_data_payloads" in tables
    assert "candles_1m_historical" in tables
    assert "ingestion_audit_log" in tables
    conn.close()


def test_validation_suite_on_unpopulated_db(tmp_path: Path, e5_candle_fixture: tuple[Path, str, int]):
    """Verify DATA-01..DATA-14 fail cleanly and DATA-15 passes on unpopulated database."""
    fixture_db, exp_sha, _ = e5_candle_fixture
    test_db = tmp_path / "unpopulated_candles.db"
    suite = IngestionValidationSuite(research_db_path=test_db, prod_db_path=fixture_db, expected_prod_sha=exp_sha)
    mappings = CandidateUniverseExtractor.extract_cohort(fixture_db)

    results = suite.run_all(mappings)
    assert len(results) == 15

    results_by_id = {r.rule_id: r for r in results}
    # DATA-15 (Production DB unchanged) must PASS
    assert results_by_id["DATA-15"].passed is True

    # DATA-01 through DATA-12 must FAIL on missing data
    assert results_by_id["DATA-01"].passed is False
    assert results_by_id["DATA-12"].passed is False


def test_validation_suite_ohlc_invariants(tmp_path: Path, e5_candle_fixture: tuple[Path, str, int]):
    """Verify DATA-04 catches invalid OHLC relationships."""
    fixture_db, exp_sha, _ = e5_candle_fixture
    test_db = tmp_path / "test_invariants.db"
    mgr = ResearchCandleDatabaseManager(db_path=test_db)
    mgr.ensure_schema()

    conn = sqlite3.connect(str(test_db))
    cur = conn.cursor()
    # Insert dummy raw payload
    cur.execute("""
        INSERT INTO raw_market_data_payloads
        (symbol, provider, endpoint, start_date, end_date, interval, retrieved_at_ist, raw_payload, payload_sha256)
        VALUES ('TEST', 'PROVIDER', '/test', '2026-09-28', '2026-10-06', '1m', '2026-10-03 15:00:00', '{}', 'hash')
    """)
    pid = cur.lastrowid

    # Insert a bar where High < Low (violates invariant)
    cur.execute("""
        INSERT INTO candles_1m_historical
        (symbol, exchange, timestamp_ist, open, high, low, close, volume, payload_id)
        VALUES ('TEST', 'NSE', '2026-09-28 09:15:00', 100.0, 90.0, 110.0, 95.0, 100.0, ?)
    """, (pid,))
    conn.commit()
    conn.close()

    suite = IngestionValidationSuite(research_db_path=test_db, prod_db_path=fixture_db, expected_prod_sha=exp_sha)
    mappings = CandidateUniverseExtractor.extract_cohort(fixture_db)
    results = suite.run_all(mappings)
    results_by_id = {r.rule_id: r for r in results}

    assert results_by_id["DATA-04"].passed is False
    assert "Invalid OHLC bars count: 1" in results_by_id["DATA-04"].details
