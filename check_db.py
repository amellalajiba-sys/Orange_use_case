import sqlite3

conn = sqlite3.connect("radar.db")
cursor = conn.cursor()


print("\n=== 1. NOMBRE DE DONNÉES ===")

cursor.execute("SELECT COUNT(*) FROM opportunity_spaces")
print("Opportunity Spaces :", cursor.fetchone()[0])

cursor.execute("SELECT COUNT(*) FROM signals")
print("Signals :", cursor.fetchone()[0])

cursor.execute("SELECT COUNT(*) FROM opportunity_signals")
print("Opportunity-Signal links :", cursor.fetchone()[0])


print("\n=== 2. OPPORTUNITY SPACES ===")

cursor.execute("""
    SELECT id, label, vertical, use_case
    FROM opportunity_spaces
    ORDER BY id
""")

for row in cursor.fetchall():
    print(row)


print("\n=== 3. SIGNALS ===")

cursor.execute("""
    SELECT id, source_name, signal_type, title
    FROM signals
    ORDER BY id
    LIMIT 20
""")

for row in cursor.fetchall():
    print(row)


print("\n=== 4. OPPORTUNITY ↔ SIGNAL LINKS ===")

cursor.execute("""
    SELECT
        os.id,
        os.label,
        s.id,
        s.source_name,
        s.signal_type,
        s.title

    FROM opportunity_signals link

    JOIN opportunity_spaces os
        ON os.id = link.opportunity_space_id

    JOIN signals s
        ON s.id = link.signal_id

    ORDER BY os.id
""")

rows = cursor.fetchall()

if not rows:
    print("❌ AUCUN LIEN TROUVÉ")

else:
    for row in rows:
        print(row)


print("\n=== 5. NOMBRE DE SIGNAL PAR OPPORTUNITY ===")

cursor.execute("""
    SELECT
        os.label,
        COUNT(s.id) AS number_of_signals

    FROM opportunity_spaces os

    LEFT JOIN opportunity_signals link
        ON os.id = link.opportunity_space_id

    LEFT JOIN signals s
        ON s.id = link.signal_id

    GROUP BY os.id

    ORDER BY os.id
""")

for row in cursor.fetchall():
    print(row)


conn.close()