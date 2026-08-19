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

Wipes opportunity_spaces, opportunity_signals, scores and right_to_win_scores
before repopulating (db.wipe_opportunity_spaces()). FIXED 2026-08-19: this
used to only upsert by label, which silently reused the same row id for a
different theme across runs -- a label like "OS005" could go from e.g.
Finance & Insurance x Agentic AI in one run to Public Sector x IoT Platforms
in the next, while link_signals.py's OLD links (grounding signals for the
FIRST theme) and old scores stayed attached to that same id. That
contaminated opportunity_spaces_summary.md with mismatched "grounding
signals" -- e.g. insurance-claims articles listed as evidence for a Public
Sector IoT opportunity. Wiping first means every full run (this script ->
scoring.py -> link_signals.py -> export_summary.py) starts from a clean
slate, so labels are simple sequential ids with no cross-run history to go
stale.

Labels are assigned sequentially (OS001, OS002, ...) in the order verticals
and themes come back -- NOT guaranteed to mean the same Vertical x Use Case x
Technology across runs, since a run with different signals can return themes
in a different order/count. If you need stable labels across ingests, freeze
the list once the team has reviewed candidate_opportunity_spaces.md, and
**stop re-running this script** -- re-running it always wipes and replaces
whatever was there, including a frozen selection.

Run:
    python create_opportunity_spaces.py
"""

from pipeline.db import init_db, get_connection, upsert_opportunity_space, wipe_opportunity_spaces
from pipeline.analyze import extract_themes

if __name__ == "__main__":
    init_db()  # safe to re-run -- CREATE TABLE IF NOT EXISTS only, no data loss
    conn = get_connection()
    wipe_opportunity_spaces(conn)

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