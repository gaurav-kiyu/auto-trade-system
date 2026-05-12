import sqlite3

conn = sqlite3.connect('trades.db')
cur = conn.cursor()
cur.execute('SELECT COUNT(*) FROM trades')
print('Total trades:', cur.fetchone()[0])
cur.execute('SELECT name FROM sqlite_master WHERE type="table"')
print('Tables:', [r[0] for r in cur.fetchall()])
conn.close()