'''
extend_taxonomy.py
==================

ingest.py    →  analyze.py   →  signals_discovery.py  →  extend_taxonomy.py   →  scoring.py   →  dashboard.py
                                                         ------------------

This module is responsible for checking the watchlist for emerging terms that have reached the 
frequency threshold (≥ 5 signals) and generating proposals for the team to review. 
It also handles approving or rejecting proposals, and when approved adds the term to the official taxonomy in config.py.
'''

import sqlite3
from datetime import datetime


# Database set-up (create proposals table if it doesn't exist yet)

def init_proposals_table(conn):
    """Create the proposals table if it doesn't exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS proposals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vertical TEXT NOT NULL,
            proposed_use_case TEXT,
            proposed_technology TEXT,
            frequency INTEGER NOT NULL,
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            reviewed_at TEXT,
            reviewed_by TEXT,
            run_id TEXT,
            UNIQUE(vertical, proposed_use_case, proposed_technology)
        )
    """)
    conn.commit()


# First we need to query the watchlist table for any terms with frequency >= 5

def get_terms_reaching_threshold(conn, threshold=5):
    """Gets all watchlist terms that have reached the frequency threshold."""

    rows = conn.execute(
        """SELECT vertical, emerging_use_case, emerging_technology, 
                  frequency, first_seen, last_seen, rationale
           FROM watchlist
           WHERE frequency >= ?
           ORDER BY frequency DESC""",
        (threshold,)
    ).fetchall()
    return rows


# Before creating a new proposal, we need to check if a proposal for this term already exists
# (so we don't generate duplicates)

def proposal_exists(conn, vertical, use_case, technology):
    """Checks if a proposal already exists for this term."""

    row = conn.execute(
        """SELECT id, status FROM proposals 
           WHERE vertical = ? 
           AND (proposed_use_case = ? OR (proposed_use_case IS NULL AND ? IS NULL))
           AND (proposed_technology = ? OR (proposed_technology IS NULL AND ? IS NULL))""",
        (vertical, use_case, use_case, technology, technology)
    ).fetchone()
    return row


# If a term has reached the threshold and doesn't have a proposal yet, we create one
# (uses proposal_exists() function)

def generate_proposal(conn, term, run_id=None):
    """
    Generates a proposal for a term that has reached the threshold.
    Returns: 'inserted' if new, 'exists' if already exists, 'skipped' if invalid.
    """
    vertical = term["vertical"]
    use_case = term["emerging_use_case"]
    technology = term["emerging_technology"]
    frequency = term["frequency"]
    first_seen = term["first_seen"]
    last_seen = term["last_seen"]
    
    # Check if already exists
    existing = proposal_exists(conn, vertical, use_case, technology)
    if existing:
        return "exists"
    
    # Insert new proposal
    conn.execute(
        """INSERT INTO proposals 
           (vertical, proposed_use_case, proposed_technology, 
            frequency, first_seen, last_seen, status, run_id)
           VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)""",
        (vertical, use_case, technology, frequency, first_seen, last_seen, run_id)
    )
    conn.commit()
    return "inserted"


# Then we loop through all terms that reached the threshold and generate proposals for each
# (uses get_terms_reaching_threshold() and generate_proposal() functions)

def generate_all_proposals(conn, threshold=5, run_id=None):
    """Generate proposals for all terms that have reached the threshold."""
    terms = get_terms_reaching_threshold(conn, threshold)
    
    inserted = 0
    exists = 0
    
    for term in terms:
        result = generate_proposal(conn, term, run_id)
        if result == "inserted":
            inserted += 1
        elif result == "exists":
            exists += 1
    
    return inserted, exists


# When the team approves a proposal, we need to:
#   - Update the proposal status to 'approved'.
#   - Add the term to the official taxonomy in config.py.

def approve_proposal(conn, proposal_id, reviewed_by="team"):
    """Updates approval of a proposal and adds it to the taxonomy."""
    
    # Get the proposal details
    proposal = conn.execute(
        "SELECT * FROM proposals WHERE id = ?", (proposal_id,)
    ).fetchone()
    
    if not proposal:
        return False
    
    # Update status
    conn.execute(
        """UPDATE proposals 
           SET status = 'approved', reviewed_at = ?, reviewed_by = ?
           WHERE id = ?""",
        (datetime.now().isoformat(), reviewed_by, proposal_id)
    )
    conn.commit()
    
    # Add to taxonomy (you'll need to update config.py)
    # This is a manual step or you can append to the in-memory lists
    # For now, just log it
    print(f"[+] Proposal {proposal_id} approved: {proposal['vertical']} × {proposal['proposed_use_case']} × {proposal['proposed_technology']}")
    print("   ⚠️ Manually add this term to config.py's taxonomy lists.")
    
    return True


# When the team rejects a proposal, we need to update its status to 'rejected'

def reject_proposal(conn, proposal_id, reviewed_by="team"):
    """Reject a proposal."""

    conn.execute(
        """UPDATE proposals 
           SET status = 'rejected', reviewed_at = ?, reviewed_by = ?
           WHERE id = ?""",
        (datetime.now().isoformat(), reviewed_by, proposal_id)
    )
    conn.commit()
    
    print(f"[-] Proposal {proposal_id} rejected.")
    return True



def get_proposals(conn, status=None):
    """Get proposals, optionally filtered by status."""

    if status:
        query = "SELECT * FROM proposals WHERE status = ? ORDER BY frequency DESC"
        params = (status,)
    else:
        query = "SELECT * FROM proposals ORDER BY frequency DESC"
        params = ()
    
    return conn.execute(query, params).fetchall()


def print_proposals(conn):
    """Prints all proposals in a readable format."""

    pending = get_proposals(conn, "pending")
    approved = get_proposals(conn, "approved")
    rejected = get_proposals(conn, "rejected")
    
    print(f"{=*20} Proposals Summary {=*20}")
    print(f"   Pending: {len(pending)}")
    print(f"   Approved: {len(approved)}")
    print(f"   Rejected: {len(rejected)}")
    
    if pending:
        print("\nPending Proposals:")
        for p in pending:
            print(f"   {p['vertical']} × {p['proposed_use_case']} × {p['proposed_technology']} (freq: {p['frequency']})")


def run_extend_taxonomy(run_id=None):
    """
    Main function: checks watchlist, generates proposals.
    """
    # 1. Connect to database
    conn = sqlite3.connect("radar.db")
    conn.row_factory = sqlite3.Row
    
    # 2. Create proposals table if it doesn't exist
    init_proposals_table(conn)
    
    # 3. Generate proposals for terms that reached threshold
    inserted, exists = generate_all_proposals(conn, threshold=5, run_id=run_id)
    
    # 4. Print summary
    print(f"[OK] Extend taxonomy complete:")
    print(f"   New proposals: {inserted}")
    print(f"   Already exists: {exists}")
    
    # 5. Show all pending proposals
    pending = get_proposals(conn, "pending")
    if pending:
        print(f"\nPending proposals ({len(pending)}):")
        for p in pending:
            print(f"   {p['vertical']} × {p['proposed_use_case']} × {p['proposed_technology']} (freq: {p['frequency']})")
    
    conn.close()




if __name__ == "__main__":
    run_extend_taxonomy()