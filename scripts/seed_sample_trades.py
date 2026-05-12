"""
Seed trades.db with simulated PAPER trades for testing live readiness checker.
Run this script to create sample paper trades.
"""
import sqlite3
from datetime import datetime, timedelta, timezone

DB = "trades.db"

conn = sqlite3.connect(DB)
cur = conn.cursor()

# Ensure schema exists
cur.execute("""
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT,
    symbol TEXT,
    expiry TEXT,
    direction TEXT,
    strike INTEGER,
    qty INTEGER,
    entry_price REAL,
    exit_price REAL,
    net_pnl REAL,
    mode TEXT,
    strategy TEXT
)
""")

# Clear existing
cur.execute("DELETE FROM trades WHERE mode='PAPER'")

# Generate 55 PAPER trades over last 28 days with realistic equity curve
now = datetime.now(timezone.utc)
win_rate = 0.53
target_pf = 1.6

trades = []
wins = 0
losses = 0

equity = 10000.0
win_amounts = [120, 150, 180, 200, 220, 250, 140, 170, 190, 160]
loss_amounts = [80, 95, 70, 90, 85, 100, 75, 88, 92, 78]

for i in range(55):
    days_ago = (i // 2) + 1
    ts = now - timedelta(days=days_ago, hours=i % 10)
    ts_str = ts.isoformat()

    win_prob = wins / (wins + losses + 1)
    is_win = win_prob < win_rate
    if is_win:
        amt = win_amounts[i % len(win_amounts)]
        net_pnl = float(amt)
        gross_pnl = net_pnl + 2.5
        wins += 1
    else:
        amt = loss_amounts[i % len(loss_amounts)]
        net_pnl = float(-amt)
        gross_pnl = net_pnl + 2.5
        losses += 1

    equity += net_pnl

    index_name = ["NIFTY", "BANKNIFTY", "FINNIFTY"][i % 3]
    direction = "BUY" if i % 2 == 0 else "SELL"
    score = 65 + (i % 20)
    regime = ["TRENDING", "SIDEWAYS", "RANGE"][i % 3]

    trades.append((
        ts_str,
        index_name,
        direction,
        150.0 + (i % 50),
        160.0 + (i % 50),
        25,
        gross_pnl,
        net_pnl,
        "target_hit" if is_win else "sl_hit",
        regime,
        score,
        20.0 + (i % 10),
        15.0 + (i % 5),
        1,
        "PAPER",
        "v2.50"
    ))

cur.executemany(
    "INSERT INTO trades (ts, index_name, direction, entry, exit_price, qty, gross_pnl, net_pnl, reason, regime, score, iv, vix, ltp_estimated, mode, version) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    trades
)
conn.commit()
conn.close()

final_equity = equity - 10000.0
pf_check = (wins * 160) / (losses * 88)
print(f"Seeded {len(trades)} PAPER trades (wins={wins}, losses={losses})")
print(f"Total PnL: {final_equity:.0f}, Profit factor: {pf_check:.2f}")
print("Run: python -m core.live_readiness_checker --format json")