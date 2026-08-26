import sqlite3
conn = sqlite3.connect('radar.db')
conn.row_factory = sqlite3.Row
rows = conn.execute("""
    SELECT os.id, os.label, os.vertical,
           s.total_score, r.right_to_win_score, r.portfolio_distance
    FROM opportunity_spaces os
    LEFT JOIN scores s ON s.id = (
        SELECT id FROM scores WHERE opportunity_space_id = os.id
        ORDER BY computed_at DESC LIMIT 1
    )
    LEFT JOIN right_to_win_scores r ON r.id = (
        SELECT id FROM right_to_win_scores WHERE opportunity_space_id = os.id
        ORDER BY computed_at DESC LIMIT 1
    )
    WHERE os.vertical = 'Healthcare'
""").fetchall()
for row in rows:
    print(dict(row))
conn.close()