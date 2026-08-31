'''
extend_taxonomy.py
==================

ingest.py    →  analyze.py   →  theme_promotion.py    →  extend_taxonomy.py   →  scoring.py   →  dashboard/streamlit_app.py
                                                         ------------------
# Sieg 26/8 -- diagram corrected: theme_promotion.py is the module that
# replaced signals_discovery.py on 24/8 (see analyze.py/radar_cli.py's own
# comments), and the dashboard now lives at dashboard/streamlit_app.py.

This module is responsible for checking the watchlist for emerging terms that have reached the 
frequency threshold (≥ 5 signals) and generating proposals for the team to review. 
It also handles approving or rejecting proposals, and when approved adds the term to the official taxonomy in config.py.

UPDATED FOR NEW SCHEMA:
  - Reads from `watchlist_terms` (which replaced the old `watchlist` table)
  - The `watchlist_terms` table has columns: id, term, category ('use_case' or 'technology'), vertical, frequency, first_seen, last_seen, status.
  - Each row is a single term (use_case OR technology), not a full combination.
  - Proposals are still stored in the `proposals` table (same as before).
'''

from datetime import datetime
import json
import os

from pipeline.taxonomy_validation import is_generic_taxonomy_term
from pipeline.db import get_connection  # Sieg 26/8 -- see run_extend_taxonomy() below

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TAXONOMY_EXTENSIONS_PATH = os.path.join(BASE_DIR, "taxonomy_extensions.json")


# Database set-up (create proposals table if it doesn't exist yet)

def _add_to_extensions(term, category):
    """Adds an approved term to the extensions file."""
    # Loads existing file
    with open(TAXONOMY_EXTENSIONS_PATH, "r") as f:
        data = json.load(f)
    # Avoids duplicates
    if not any(item["term"] == term and item["category"] == category for item in data):
        data.append({"term": term, "category": category})
    # Saves
    with open(TAXONOMY_EXTENSIONS_PATH, "w") as f:
        json.dump(data, f, indent=2)


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


# First we need to query the watchlist_terms table for any terms with frequency >= threshold

def get_terms_reaching_threshold(conn, threshold=5):
    """Gets all watchlist terms (use_case or technology) that have reached the frequency threshold."""

    rows = conn.execute(
        """SELECT vertical, term, category, frequency, first_seen, last_seen
           FROM watchlist_terms
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
    # The term is either a use_case or a technology, based on 'category'
    category = term["category"]  # 'use_case' or 'technology'
    term_value = term["term"]
    frequency = term["frequency"]
    first_seen = term["first_seen"]
    last_seen = term["last_seen"]

    # Build the proposal fields accordingly
    proposed_use_case = term_value if category == 'use_case' else None
    proposed_technology = term_value if category == 'technology' else None

    # Sieg 24/8 -- do not create new review items for a term that cannot be
    # approved. Approval has the same guard for proposals created before this.
    if is_generic_taxonomy_term(term_value, category):
        return "skipped"

    # Check if already exists (with the same vertical and specific use_case/technology)
    existing = proposal_exists(conn, vertical, proposed_use_case, proposed_technology)
    if existing:
        return "exists"
    conn.execute(
    """INSERT INTO proposals 
        (vertical, proposed_use_case, proposed_technology, 
        frequency, first_seen, last_seen, status, run_id)
        VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)""",
    (vertical, proposed_use_case, proposed_technology, frequency, first_seen, last_seen, run_id)
    )
    conn.commit()
    return "inserted"


# Then we loop through all terms that reached the threshold and generate proposals for each
# (uses get_terms_reaching_threshold() and generate_proposal() functions)

def generate_all_proposals(conn, threshold=3, run_id=None):
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
#   - Add the term to the official taxonomy in config.py

def approve_proposal(conn, proposal_id, reviewed_by="team"):
    """Updates approval of a proposal and adds it to the taxonomy."""
    
    # Get the proposal details
    proposal = conn.execute(
        "SELECT * FROM proposals WHERE id = ?", (proposal_id,)
    ).fetchone()
    
    if not proposal:
        return False

    term = proposal["proposed_use_case"] or proposal["proposed_technology"]
    category = "use_case" if proposal["proposed_use_case"] else "technology"
    # Sieg 24/8 -- final guard for historical/manual proposals that bypassed
    # generate_proposal() before the generic-term rule existed.
    if is_generic_taxonomy_term(term, category):
        print(f"[!] Proposal {proposal_id} was not approved: {term!r} is too generic for the taxonomy.")
        return False

    # Sieg 24/8 -- write JSON before changing proposal status. A JSON error
    # must leave the proposal pending rather than falsely marked approved.
    # Persist the extension before recording the approval. If the JSON write
    # fails, the proposal remains pending instead of falsely appearing approved.
    _add_to_extensions(term, category)
    
    # Update status
    conn.execute(
        """UPDATE proposals 
           SET status = 'approved', reviewed_at = ?, reviewed_by = ?
           WHERE id = ?""",
        (datetime.now().isoformat(), reviewed_by, proposal_id)
    )
    conn.commit()
    
    # The JSON extension was persisted above; now clear the source watchlist
    # entry and commit the database audit trail together.
    if proposal["proposed_use_case"]:
        conn.execute("DELETE FROM watchlist_terms WHERE term = ? AND category = 'use_case' AND vertical = ?", 
                     (proposal["proposed_use_case"], proposal["vertical"]))
    elif proposal["proposed_technology"]:
        conn.execute("DELETE FROM watchlist_terms WHERE term = ? AND category = 'technology' AND vertical = ?",
                     (proposal["proposed_technology"], proposal["vertical"]))
    conn.commit()
    
    print(f"[+] Proposal {proposal_id} approved and taxonomy updated automatically.")

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
    
    print(f"{'='*20} Proposals Summary {'='*20}")
    print(f"   Pending: {len(pending)}")
    print(f"   Approved: {len(approved)}")
    print(f"   Rejected: {len(rejected)}")
    
    if pending:
        print("\nPending Proposals:")
        for p in pending:
            print(f"   {p['vertical']} × {p['proposed_use_case']} × {p['proposed_technology']} (freq: {p['frequency']})")


# Manage team approval (interactive feature)
def run_review(conn):
    """Displays pending proposals and asks the user to approve or reject them."""
    pending = get_proposals(conn, status="pending")
    if not pending:
        print("No proposals pending for review.")
        return
    
    print(f"{len(pending)} pending proposals found.\n")
    
    for p in pending:
        # Draft a description for the proposed term.
        term_desc = p['proposed_use_case'] if p['proposed_use_case'] else p['proposed_technology']
        category = "use_case" if p['proposed_use_case'] else "technology"
        
        print(f"ID {p['id']}: {p['vertical']} × {term_desc} (frequency: {p['frequency']})")
        print(f"  Category: {category}")
        print("  1 = Approve, 2 = Reject, 0 = Skip")
        choice = input("> ").strip()
        
        if choice == "1":
            approve_proposal(conn, p['id'])
        elif choice == "2":
            reject_proposal(conn, p['id'])
        elif choice == "0":
            continue
        else:
            print("Invalid choice, skipping.")


def run_extend_taxonomy(run_id=None):
    """
    Main function: checks watchlist, generates proposals.
    """
    # 1. Connect to database
    # Sieg 26/8 -- was sqlite3.connect("radar.db") directly, bypassing
    # config.DB_PATH: every other module (db.py, ingest.py, scoring.py,
    # radar_cli.py) reads/writes via get_connection(), which resolves
    # DB_PATH from config.py. Harmless today only because DB_PATH's value
    # happens to still be "radar.db" -- if that ever changes, this was the
    # one function left silently pointed at the wrong file, with no error.
    # radar_cli.py `all` runs this file as its own subprocess (see
    # radar_cli.py's `python -m pipeline.extend_taxonomy` call), so this
    # path is hit on every full pipeline run, not just a standalone call.
    conn = get_connection()
    
    # 2. Create proposals table if it doesn't exist
    init_proposals_table(conn)
    
    # 3. Generate proposals for terms that reached threshold
    inserted, exists = generate_all_proposals(conn, threshold=5, run_id=run_id)
    
    # 4. Print summary
    print("[OK] Extend taxonomy complete:")
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