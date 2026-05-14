"""Deep Backtest Analysis Script"""
import sqlite3
import os

conn = sqlite3.connect('trades.db')
cur = conn.cursor()
cur.execute('SELECT index_name, direction, gross_pnl, reason, regime, score, iv, vix, ts FROM trades ORDER BY ts')
trades = cur.fetchall()
print('=' * 70)
print('DEEP BACKTEST ANALYSIS')
print('=' * 70)
print(f'Total trades: {len(trades)}\n')

# By regime
print('=== PERFORMANCE BY REGIME ===')
regimes = {}
for t in trades:
    r = t[4] or 'UNKNOWN'
    if r not in regimes:
        regimes[r] = {'wins': 0, 'losses': 0, 'pnl': 0}
    regimes[r]['pnl'] += t[2]
    if t[2] > 0:
        regimes[r]['wins'] += 1
    else:
        regimes[r]['losses'] += 1

for regime, data in sorted(regimes.items()):
    total = data['wins'] + data['losses']
    wr = (data['wins'] / total * 100) if total > 0 else 0
    print(f'{regime:10} | {total:2} trades | WR: {wr:5.1f}% | PnL: {data["pnl"]:8.2f}')

# By IV bucket
print('\n=== PERFORMANCE BY IV RANK ===')
iv_bins = {'Low (<20)': [], 'Mid (20-40)': [], 'High (40-60)': [], 'Very High (>60)': []}
for t in trades:
    iv = t[6] or 0
    if iv < 20:
        iv_bins['Low (<20)'].append(t)
    elif iv < 40:
        iv_bins['Mid (20-40)'].append(t)
    elif iv < 60:
        iv_bins['High (40-60)'].append(t)
    else:
        iv_bins['Very High (>60)'].append(t)

for bucket, trades_list in iv_bins.items():
    if trades_list:
        wins = sum(1 for t in trades_list if t[2] > 0)
        pnl = sum(t[2] for t in trades_list)
        wr = wins / len(trades_list) * 100
        print(f'{bucket:18} | {len(trades_list):2} trades | WR: {wr:5.1f}% | PnL: {pnl:8.2f}')

# By VIX bucket
print('\n=== PERFORMANCE BY VIX ===')
vix_bins = {'Low (<15)': [], 'Mid (15-20)': [], 'High (20-25)': [], 'Very High (>25)': []}
for t in trades:
    vix = t[7] or 0
    if vix < 15:
        vix_bins['Low (<15)'].append(t)
    elif vix < 20:
        vix_bins['Mid (15-20)'].append(t)
    elif vix < 25:
        vix_bins['High (20-25)'].append(t)
    else:
        vix_bins['Very High (>25)'].append(t)

for bucket, trades_list in vix_bins.items():
    if trades_list:
        wins = sum(1 for t in trades_list if t[2] > 0)
        pnl = sum(t[2] for t in trades_list)
        wr = wins / len(trades_list) * 100
        print(f'{bucket:18} | {len(trades_list):2} trades | WR: {wr:5.1f}% | PnL: {pnl:8.2f}')

# FALSE SIGNALS: High score but loss
print('\n=== FALSE SIGNALS (Loss with Score >= 70) ===')
false_signals = [t for t in trades if t[2] < 0 and t[5] and t[5] >= 70]
print(f'Count: {len(false_signals)} ({len(false_signals)/len(trades)*100:.1f}% of all trades)')
if false_signals:
    print('Pattern analysis:')
    regimes_fs = {}
    ivs_fs = []
    for f in false_signals:
        r = f[4] or 'UNKNOWN'
        regimes_fs[r] = regimes_fs.get(r, 0) + 1
        if f[6]: ivs_fs.append(f[6])
    print(f'  By Regime: {regimes_fs}')
    print(f'  Avg IV: {sum(ivs_fs)/len(ivs_fs):.1f}' if ivs_fs else '  Avg IV: N/A')

# STRONG SIGNALS: High score + win
print('\n=== STRONG SIGNALS (Win with Score >= 70) ===')
strong_signals = [t for t in trades if t[2] > 0 and t[5] and t[5] >= 70]
print(f'Count: {len(strong_signals)} ({len(strong_signals)/len(trades)*100:.1f}% of all trades)')

# Exit reasons
print('\n=== EXIT REASONS ===')
reasons = {}
for t in trades:
    r = t[3]
    reasons[r] = reasons.get(r, 0) + 1
for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
    pct = count / len(trades) * 100
    print(f'{reason:15} | {count:2} ({pct:.1f}%)')

# Calculate Sharpe-like ratio (assuming 252 trading days, ~27 days = ~20 sessions)
print('\n=== RISK METRICS ===')
pnls = [t[2] for t in trades]
avg_pnl = sum(pnls) / len(pnls)
std_pnl = (sum((p - avg_pnl) ** 2 for p in pnls) / len(pnls)) ** 0.5
sharpe_like = (avg_pnl / std_pnl) * (20 ** 0.5) if std_pnl > 0 else 0
print(f'Avg PnL/Trade: {avg_pnl:.2f}')
print(f'Std Dev: {std_pnl:.2f}')
print(f'Sharpe-like (20 sessions): {sharpe_like:.2f}')

# By index
print('\n=== BY INDEX ===')
indices = {}
for t in trades:
    idx = t[0]
    if idx not in indices:
        indices[idx] = {'wins': 0, 'losses': 0, 'pnl': 0}
    indices[idx]['pnl'] += t[2]
    if t[2] > 0:
        indices[idx]['wins'] += 1
    else:
        indices[idx]['losses'] += 1

for idx, data in indices.items():
    total = data['wins'] + data['losses']
    wr = (data['wins'] / total * 100) if total > 0 else 0
    print(f'{idx:12} | {total:2} trades | WR: {wr:5.1f}% | PnL: {data["pnl"]:8.2f}')

# Signal accuracy by score band
print('\n=== SIGNAL ACCURACY BY SCORE BAND ===')
score_bands = {'60-70': [], '70-80': [], '80-90': [], '90+': []}
for t in trades:
    s = t[5]
    if s and 60 <= s < 70:
        score_bands['60-70'].append(t)
    elif s and 70 <= s < 80:
        score_bands['70-80'].append(t)
    elif s and 80 <= s < 90:
        score_bands['80-90'].append(t)
    elif s and s >= 90:
        score_bands['90+'].append(t)

for band, trades_list in score_bands.items():
    if trades_list:
        wins = sum(1 for t in trades_list if t[2] > 0)
        pnl = sum(t[2] for t in trades_list)
        wr = wins / len(trades_list) * 100
        print(f'{band:8} | {len(trades_list):2} trades | WR: {wr:5.1f}% | PnL: {pnl:8.2f}')

print('\n' + '=' * 70)
print('ANALYSIS COMPLETE')
print('=' * 70)
conn.close()