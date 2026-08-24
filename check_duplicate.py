import sqlite3

conn = sqlite3.connect("radar.db")
cursor = conn.cursor()

print("=== DOUBLONS ===")

cursor.execute("""
    SELECT
        label,
        COUNT(*) AS number
    FROM opportunity_spaces
    GROUP BY label
    HAVING COUNT(*) > 1
    ORDER BY label
""")

duplicates = cursor.fetchall()

for label, number in duplicates:
    print(f"{label} -> {number} fois")


print("\n=== DETAILS ===")

for label, number in duplicates:

    cursor.execute("""
        SELECT
            id,
            label,
            vertical,
            use_case,
            technology
        FROM opportunity_spaces
        WHERE label = ?
        ORDER BY id
    """, (label,))

    print(f"\n{label}:")

    for row in cursor.fetchall():
        print(row)


conn.close()