"""
Register ALL candidate Opportunity Spaces (Vertical x Use Case x Technology)
found by theme extraction, across every vertical present in `signals` -- not
a hand-picked subset.

CHANGED 2026-08-19: this used to wipe opportunity_spaces (and everything
that references it) before every run, so only the LATEST run's candidates
ever existed -- fine for smoke-testing the pipeline, but it meant you could
never look back at what a previous run surfaced once you'd re-run this
script. Now every run gets its own run_id (see db.py) and is simply added
alongside previous runs -- nothing is deleted. Re-run this as many times as
you like (e.g. after a fresh ingest, or after tweaking the taxonomy) and
compare runs side by side in Power BI via the `run_id` column on
`latest_scores`, or day-to-day just use `latest_run_scores`, which always
points at the most recent run only.

Labels are assigned sequentially (OS001, OS002, ...) within THIS run, in the
order verticals and themes come back -- NOT guaranteed to mean the same
Vertical x Use Case x Technology as "OS001" from a different run. Always
pair a label with its run_id (or just work within `latest_run_scores`,
which already scopes to one run) rather than assuming "OS001" means the
same thing everywhere.

If you ever want to erase all history and start completely clean (e.g. the
taxonomy changed so fundamentally that old runs aren't worth comparing
against), call pipeline.db.wipe_opportunity_spaces(conn) yourself -- it
still exists, it's just no longer called automatically here.

Run:
    python create_opportunity_spaces.py
"""

from pipeline.db import init_db, get_connection, insert_opportunity_space, new_run_id
from pipeline.analyze import extract_themes

if __name__ == "__main__":
    init_db()  # safe to re-run -- CREATE TABLE IF NOT EXISTS + a one-time migration only, no data loss
    conn = get_connection()

    run_id = new_run_id()
    print(f"Starting new run: {run_id}")

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
            os_id = insert_opportunity_space(conn, run_id, label, vertical, use_case, technology)
            print(f"  {label} (id={os_id}): {vertical} x {use_case} x {technology}")
            counter += 1
            total += 1

    conn.close()
    print(f"\n{total} opportunity spaces registered across {len(verticals)} verticals.")
    print(f"Run id: {run_id}")
    print("Next: run scoring.py and link_signals.py (they default to this latest run automatically).")