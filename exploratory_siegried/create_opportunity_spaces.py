"""
Register ALL candidate Opportunity Spaces (Vertical x Use Case x Technology)
found by theme extraction, across every vertical present in `signals` -- not
a hand-picked subset.

Change from the previous version: this used to hardcode a CANDIDATES list of
4 OS picked to smoke-test the pipeline end-to-end. That was a deliberate
starting point (see README "Opportunity spaces are not decided yet"), not a
final scope. This version registers every theme extract_themes() returns
(already passed through analyze.py's Phase 3 curation: generic terms like
bare "AI" dropped, near-duplicates merged), so scoring.py and
export_summary.py -- which already iterate over the full opportunity_spaces
table with no limit -- naturally cover all of them.

Labels are assigned sequentially (OS001, OS002, ...) in the order verticals
and themes come back. Safe to re-run: upsert_opportunity_space() only
refreshes the timestamp on a label that already exists, it never duplicates
-- but note that a *new* run of extract_themes() (e.g. after fresh ingest)
can return themes in a different order/count than last time, so a label like
"OS003" is not guaranteed to always mean the same Vertical x Use Case x
Technology across runs. If you need stable labels across ingests, freeze the
list once the team has reviewed candidate_opportunity_spaces.md rather than
re-running this script blindly.

Run:
    python create_opportunity_spaces.py
"""

from pipeline.db import init_db, get_connection, upsert_opportunity_space
from pipeline.analyze import extract_themes

if __name__ == "__main__":
    init_db()  # safe to re-run -- CREATE TABLE IF NOT EXISTS only, no data loss
    conn = get_connection()

    verticals = [r["vertical_hint"] for r in conn.execute(
        "SELECT DISTINCT vertical_hint FROM signals WHERE vertical_hint IS NOT NULL"
    ).fetchall()]

    counter = 1
    total = 0
    for vertical in verticals:
        print(f"\nExtracting themes for {vertical}...")
        themes = extract_themes(conn, vertical)
        if not themes:
            print(f"[{vertical}] no themes extracted (too few signals, or LLM call failed) -- skipping")
            continue
        for t in themes:
            label = f"OS{counter:03d}"
            use_case = t.get("use_case", "?")
            technology = t.get("technology", "?")
            os_id = upsert_opportunity_space(conn, label, vertical, use_case, technology)
            print(f"  {label} (id={os_id}): {vertical} x {use_case} x {technology}")
            counter += 1
            total += 1

    conn.close()
    print(f"\n{total} opportunity spaces registered across {len(verticals)} verticals.")