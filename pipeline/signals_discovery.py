'''
signals_discovery.py
====================

ingest.py    →  analyze.py   →  signals_discovery.py  →  extend_taxonomy.py   →  scoring.py   →  dashboard.py
                                --------------------

This module is responsible for processing emerging terms that were detected by analyze.py
and saved to emerging_themes.json. 
It reads these emerging terms, checks if they are already in the watchlist, puts them into the watchlist table
if they are not already, where they can be tracked for frequency over time, and adds or updates them in the database.
'''

import json
import sqlite3
from datetime import datetime


# Database set-up (if watchlist table doesn't already exist)
def init_watchlist_table(conn):
    """Create the watchlist table if it doesn't exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS watchlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vertical TEXT NOT NULL,
            emerging_use_case TEXT,
            emerging_technology TEXT,
            rationale TEXT,
            supporting_signal_count INTEGER DEFAULT 0,
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            frequency INTEGER DEFAULT 1,
            run_id TEXT,
            UNIQUE(vertical, emerging_use_case, emerging_technology)
        )
    """)
    conn.commit()



# `analyze.py` saves emerging terms to `emerging_themes.json`;
# we have to read this file

def load_emerging_terms():
    """Loads emerging terms from emerging_themes.json."""

    try:
        with open("emerging_themes.json", "r") as f:
            return json.load(f)
    except FileNotFoundError:
        print("[ERROR] emerging_themes.json not found — run analyze.py first")
        return []
    except json.JSONDecodeError:
        print("[ERROR] emerging_themes.json is malformed — check the file")
        return []


# For each emerging term, you need to check if it's already in the watchlist table. 
# If it exists, we update its frequency. If not, we insert it.

def term_exists(conn, vertical, use_case, technology):
    """Checks if a term already exists in the watchlist."""

    row = conn.execute(
        """SELECT id, frequency FROM watchlist 
           WHERE vertical = ? 
           AND (emerging_use_case = ? OR (emerging_use_case IS NULL AND ? IS NULL))
           AND (emerging_technology = ? OR (emerging_technology IS NULL AND ? IS NULL))""",
        (vertical, use_case, use_case, technology, technology)
    ).fetchone()
    return row


# If term exists: increments frequency and updates `last_seen` in watchlist table
# If term doesn't exist: inserts it with frequency = 1.

def add_to_watchlist(conn, term, run_id=None):
    """Adds an emerging term to the watchlist or update its frequency."""

    vertical = term.get("vertical")
    use_case = term.get("emerging_use_case")
    technology = term.get("emerging_technology")
    rationale = term.get("rationale", "")
    support_count = term.get("supporting_signal_count", 0)
    
    # Check if it already exists
    existing = term_exists(conn, vertical, use_case, technology)
    
    now = datetime.now().isoformat()
    
    if existing:
        # Update frequency and last_seen
        conn.execute(
            """UPDATE watchlist 
               SET frequency = frequency + 1, 
                   last_seen = ?,
                   supporting_signal_count = ?
               WHERE id = ?""",
            (now, support_count, existing["id"])
        )
        conn.commit()
        return "updated"
    else:
        # Insert new term
        conn.execute(
            """INSERT INTO watchlist 
               (vertical, emerging_use_case, emerging_technology, 
                rationale, supporting_signal_count, 
                first_seen, last_seen, frequency, run_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)""",
            (vertical, use_case, technology, rationale, 
             support_count, now, now, run_id)
        )
        conn.commit()
        return "inserted"


def add_all_to_watchlist(conn, emerging_terms, run_id=None):
    """Adds all emerging terms to the watchlist."""

    added = 0
    updated = 0
    
    for term in emerging_terms:
        result = add_to_watchlist(conn, term, run_id)
        if result == "inserted":
            added += 1
        elif result == "updated":
            updated += 1
    
    return added, updated


# ============================================
# MAIN FUNCTION
# ============================================

def run_discovery(run_id=None):
    """
    Main function: reads emerging_themes.json and updates the watchlist.
    """
    # 1. Connect to database
    conn = sqlite3.connect("radar.db")
    conn.row_factory = sqlite3.Row
    
    # 2. Create watchlist table if it doesn't exist
    init_watchlist_table(conn)
    
    # 3. Load emerging terms from JSON
    emerging_terms = load_emerging_terms()
    if not emerging_terms:
        print("No emerging terms to process.")
        conn.close()
        return
    
    # 4. Add/update each term
    added, updated = add_all_to_watchlist(conn, emerging_terms, run_id)
    
    conn.close()
    
    print(f"[OK] Discovery complete: {added} new terms added, {updated} existing terms updated.")
    print(f"   Total terms in watchlist: {added + updated}")


# ============================================
# SCRIPT ENTRY POINT
# ============================================

if __name__ == "__main__":
    # Get the current run_id from the database (optional)
    # from pipeline.db import get_latest_run_id
    # run_id = get_latest_run_id()
    run_id = None  # Or pass the current run_id
    
    run_discovery(run_id)