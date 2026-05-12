import sqlite3

conn = sqlite3.connect("trades.db")
rows = conn.execute(
    "SELECT net_pnl FROM trades WHERE mode=? ORDER BY ts", ("PAPER",)
).fetchall()
conn.close()

pnls = [float(r[0]) for r in rows if r[0] is not None]
cumulative = [sum(pnls[:i+1]) for i in range(len(pnls))]

print("=== Drawdown as % of CUMULATIVE equity (correct for trading) ===")
peak = 0.0
max_dd = 0.0
max_dd_trade = -1
for i, cum in enumerate(cumulative):
    if cum > peak:
        peak = cum
    if peak > 0:
        dd_pct = (peak - cum) / peak * 100
        dd_abs = peak - cum
        if dd_pct > max_dd:
            max_dd = dd_pct
            max_dd_trade = i + 1
            print(f"  Trade {i+1}: equity={cum:.0f} peak={peak:.0f} drawdown={dd_abs:.0f} ({dd_pct:.2f}%)")

print(f"\nMax Drawdown: {max_dd:.2f}% at trade {max_dd_trade}")

print("\n=== Drawdown as % of INITIAL capital (misleading) ===")
initial = 10000.0
peak = initial
max_dd2 = 0.0
for i, cum in enumerate(cumulative):
    equity = initial + cum
    if equity > peak:
        peak = equity
    if peak > 0:
        dd_pct = (peak - equity) / peak * 100
        if dd_pct > max_dd2:
            max_dd2 = dd_pct
            print(f"  Trade {i+1}: equity={equity:.0f} peak={peak:.0f} DD={dd_pct:.2f}%")

print(f"\nMax Drawdown (initial base): {max_dd2:.2f}%")

print("\n=== Equity curve ===")
for i, cum in enumerate(cumulative):
    equity = initial + cum
    print(f"Trade {i+1:2d}: equity={equity:8.0f} {'' if cum >= 0 else ''}")