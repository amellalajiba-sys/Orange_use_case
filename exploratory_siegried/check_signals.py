import sqlite3

conn = sqlite3.connect("radar.db")
conn.row_factory = sqlite3.Row

print("Par vertical :")
for r in conn.execute("SELECT vertical_hint, COUNT(*) as n FROM signals GROUP BY vertical_hint ORDER BY n DESC"):
    print(f"  {r['vertical_hint'] or '(non taggé)'}: {r['n']}")

total = conn.execute("SELECT COUNT(*) as n FROM signals").fetchone()["n"]
print(f"\nTotal: {total}")
conn.close()