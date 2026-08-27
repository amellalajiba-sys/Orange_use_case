import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Sieg 26/8 -- two fixes, same pattern already applied to db.py's
# get_latest_scores() on 25/8 but never carried over to this standalone
# diagnostic script:
#   1. get_connection() (resolves config.DB_PATH) instead of a hardcoded
#      sqlite3.connect('radar.db') -- silently wrong the day DB_PATH changes.
#   2. `ORDER BY computed_at DESC, id DESC` instead of just `computed_at
#      DESC` -- on Windows, two insert_score() calls milliseconds apart can
#      get the identical ISO timestamp string, so `computed_at DESC` alone
#      can non-deterministically pick either the old or the new row for
#      the "latest" score. `id` (AUTOINCREMENT) never ties, so it's the
#      exact same fix db.py already applies elsewhere.
from pipeline.db import get_connection

conn = get_connection()
rows = conn.execute("""
    SELECT os.id, os.label, os.vertical,
           s.total_score, r.right_to_win_score, r.portfolio_distance
    FROM opportunity_spaces os
    LEFT JOIN scores s ON s.id = (
        SELECT id FROM scores WHERE opportunity_space_id = os.id
        ORDER BY computed_at DESC, id DESC LIMIT 1
    )
    LEFT JOIN right_to_win_scores r ON r.id = (
        SELECT id FROM right_to_win_scores WHERE opportunity_space_id = os.id
        ORDER BY computed_at DESC, id DESC LIMIT 1
    )
    WHERE os.vertical = 'Healthcare'
""").fetchall()
for row in rows:
    print(dict(row))
conn.close()