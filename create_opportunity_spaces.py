"""
Register the candidate Opportunity Spaces (Vertical x Use Case x Technology)
picked after theme extraction / curation, so scoring.py has something to score.

Run once (safe to re-run -- upsert_opportunity_space just refreshes timestamps
on existing labels instead of duplicating):

    python create_opportunity_spaces.py
"""

from pipeline.db import init_db, get_connection, upsert_opportunity_space

CANDIDATES = [
    ("OS001", "Public Sector", "Sovereign citizen data hosting", "Sovereign cloud + GPU inference"),
    ("OS002", "Manufacturing", "Fire and hazard detection", "Edge computer vision (Raspberry Pi class)"),
    ("OS003", "Finance & Insurance", "Conduct-risk / compliance monitoring", "AI surveillance of communications"),
    ("OS004", "Manufacturing", "Remote-controlled industrial robots", "Vision-guided teleoperation"),
]

if __name__ == "__main__":
    init_db()  # safe to re-run -- CREATE TABLE IF NOT EXISTS only, no data loss
    conn = get_connection()
    for label, vertical, use_case, technology in CANDIDATES:
        os_id = upsert_opportunity_space(conn, label, vertical, use_case, technology)
        print(f"{label} (id={os_id}): {vertical} x {use_case} x {technology}")
    conn.close()