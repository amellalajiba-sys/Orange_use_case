"""
Analyze signals already collected in radar.db.

Two steps, matching the brief's "Signal Collection -> Theme Extraction" flow:

1. summary() / dump_titles()  -- fast, no LLM, no cost. Look at raw counts
   and skim actual titles by eye. Always do this FIRST before automating
   anything -- you need to know what's actually in there.

2. extract_themes(vertical)   -- LLM-assisted. Takes the signal titles for
   one vertical and asks the model to identify recurring Use Case x
   Technology combinations, i.e. candidate Opportunity Spaces.

Every valid theme extract_themes() finds is also tracked in-memory via
signals_discovery.track_valid_themes() -- a recurring theme (same Vertical
x Use Case x Technology seen across separate runs) is what
`radar_cli.py promote` later turns into a real opportunity space. See
pipeline/signals_discovery.py and pipeline/db.py's recurring_themes table
for the full mechanism -- this replaces an earlier design that round-tripped
through an emerging_themes.json file.

Run directly for a full pass over all verticals:

    python -m pipeline.analyze




IRENE:
======

    - Added detect_emerging_from_themes(): detects themes with Use Cases or
      Technologies not in the official taxonomy lists.
    - Added save_emerging_themes(): saves emerging terms to emerging_themes.json
      for signals_discovery.py to process.
    - Modified run_full_analysis(): now collects and saves emerging terms
      alongside the standard theme extraction output.
    - Kept THEME_EXTRACTION_SYSTEM_PROMPT unchanged (Siegried's original open prompt).
    - extract_themes() unchanged — still returns a list of dicts.

"""

from pipeline.db import (
    get_connection, add_to_watchlist, list_watchlist, update_watchlist_status, new_run_id,
    list_promotable_themes,
)
from pipeline.config import USE_CASES_TAXONOMY, TECHNOLOGIES_TAXONOMY, RECURRING_THEME_PROMOTION_THRESHOLD
from pipeline.signals_discovery import track_valid_themes
from llm.llm_client import get_llm_json

WATCHLIST_PROMOTION_THRESHOLD = 3


# ---------- Step 1: quick exploration, no LLM ----------

def summary(conn):
    """Print counts by vertical, by signal type, and total -- the first
    thing to check after every ingest run."""
    print("=== Signals by vertical ===")
    rows = conn.execute(
        "SELECT vertical_hint, COUNT(*) as n FROM signals GROUP BY vertical_hint ORDER BY n DESC"
    ).fetchall()
    for r in rows:
        print(f"  {r['vertical_hint'] or '(no vertical)'}: {r['n']}")

    print("\n=== Signals by type ===")
    rows = conn.execute(
        "SELECT signal_type, COUNT(*) as n FROM signals GROUP BY signal_type ORDER BY n DESC"
    ).fetchall()
    for r in rows:
        print(f"  {r['signal_type']}: {r['n']}")

    print("\n=== Signals by source ===")
    rows = conn.execute(
        "SELECT source_name, COUNT(*) as n FROM signals GROUP BY source_name ORDER BY n DESC LIMIT 15"
    ).fetchall()
    for r in rows:
        print(f"  {r['source_name']}: {r['n']}")

    total = conn.execute("SELECT COUNT(*) as n FROM signals").fetchone()["n"]
    print(f"\nTOTAL signals in database: {total}")


def dump_titles(conn, vertical=None, signal_type=None, limit=100):
    """Print raw titles so you can skim them by eye -- this is how you
    manually spot recurring themes before trusting the LLM to do it."""
    query = "SELECT source_name, signal_type, title FROM signals WHERE 1=1"
    params = []
    if vertical:
        query += " AND vertical_hint = ?"
        params.append(vertical)
    if signal_type:
        query += " AND signal_type = ?"
        params.append(signal_type)
    query += " ORDER BY signal_type, collected_at DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    for r in rows:
        print(f"[{r['signal_type']:14}] ({r['source_name']}) {r['title']}")
    print(f"\n{len(rows)} titles shown.")


# ---------- Step 2: LLM-assisted theme extraction ----------

# THEME EXTRACTION WITH ORIGINAL PROMPT

THEME_EXTRACTION_SYSTEM_PROMPT = """You are analyzing market signals (news, research
papers, vendor announcements, regulation) collected for one business vertical, to spot
candidate Opportunity Spaces for a B2B telecom/cloud provider (Orange Business).

An Opportunity Space = Vertical x Use Case x Technology, and must be SPECIFIC
(e.g. "Manufacturing x Energy Optimization x Computer Vision"), never a generic
theme like "AI in industry" or "Cloud adoption".

IMPORTANT: use_case and technology MUST be picked EXACTLY from these closed lists --
do not invent new terms, do not rephrase them:

Use cases: {use_cases}
Technologies: {technologies}

If a real, recurring pattern in the signals genuinely does NOT fit any combination
of the lists above, do NOT force it into a bad match. Instead put it in
watchlist_candidates so the team can review it for adding to the taxonomy later.

Read the signal titles below and respond with ONLY a JSON object, no preamble,
no markdown fences:
{{
  "themes": [
    {{"use_case": "<exact match from the list>", "technology": "<exact match from the list>",
      "supporting_signal_count": <int>, "rationale": "<one sentence>"}}
  ],
  "watchlist_candidates": [
    {{"term": "<the new term you couldn't classify>", "category": "use_case"|"technology",
      "rationale": "<why this looks like a real pattern despite not fitting the taxonomy>"}}
  ]
}}
themes: 3-6 items max, reject anything generic or supported by only one vague signal.
watchlist_candidates: only include genuinely recurring patterns, not one-off mentions."""

def detect_emerging_from_themes(themes, vertical):
    """
    Check which themes contain technologies/use cases not in the official taxonomy.
    These become emerging terms for the watchlist.
    """
    emerging = []
    for t in themes:
        use_case = t.get("use_case", "")
        technology = t.get("technology", "")
        rationale = t.get("rationale", "")
        support_count = t.get("supporting_signal_count", 0)
        
        # Check if either field is NOT in the official lists
        is_emerging_use_case = use_case and use_case not in TAXONOMY_USE_CASES
        is_emerging_technology = technology and technology not in TAXONOMY_TECHNOLOGIES

        if is_emerging_use_case or is_emerging_technology:
            emerging.append({
                "vertical": vertical,
                "emerging_use_case": use_case if use_case not in TAXONOMY_USE_CASES else None,
                "emerging_technology": technology if technology not in TAXONOMY_TECHNOLOGIES else None,
                "rationale": rationale,
                "supporting_signal_count": support_count
            })

    return emerging

def extract_themes(conn, vertical, max_signals=40):
    """Ask the LLM to turn raw signal titles into candidate Opportunity
    Spaces for one vertical, constrained to the closed taxonomy. Anything
    that doesn't fit goes to watchlist_terms instead of being silently
    accepted or silently dropped. Returns (valid_themes, watchlist_candidates)."""
    rows = conn.execute(
        "SELECT signal_type, title FROM signals WHERE vertical_hint = ? "
        "ORDER BY collected_at DESC LIMIT ?",
        (vertical, max_signals),
    ).fetchall()

    if len(rows) < 3:
        print(f"[{vertical}] only {len(rows)} signals -- too few for reliable theme extraction, skipping")
        return [], []

    titles = "\n".join(f"- [{r['signal_type']}] {r['title']}" for r in rows)
    prompt = f"Vertical: {vertical}\n\nSignals:\n{titles}"
    system_prompt = THEME_EXTRACTION_SYSTEM_PROMPT.format(
        use_cases=", ".join(USE_CASES_TAXONOMY), technologies=", ".join(TECHNOLOGIES_TAXONOMY)
    )

    result = get_llm_json(prompt, system_prompt=system_prompt)
    if not result or "themes" not in result:
        print(f"[{vertical}] theme extraction failed or returned nothing usable")
        return [], []

    themes = result.get("themes", [])
    candidates = result.get("watchlist_candidates", [])

    # Belt and suspenders: even if the LLM ignores the instruction and invents
    # a term, catch it here and reroute to the watchlist rather than trusting it.
    valid_themes = []
    for t in themes:
        if t.get("use_case") in USE_CASES_TAXONOMY and t.get("technology") in TECHNOLOGIES_TAXONOMY:
            valid_themes.append(t)
        else:
            if t.get("use_case") not in USE_CASES_TAXONOMY:
                add_to_watchlist(conn, t.get("use_case", "unknown"), "use_case", vertical)
            if t.get("technology") not in TECHNOLOGIES_TAXONOMY:
                add_to_watchlist(conn, t.get("technology", "unknown"), "technology", vertical)

    for c in candidates:
        if c.get("term") and c.get("category") in ("use_case", "technology"):
            add_to_watchlist(conn, c["term"], c["category"], vertical)

    return valid_themes, candidates


def save_emerging_themes(emerging_terms):
    """Save emerging terms to a JSON file for processing by signals_discovery.py."""

    output_path = "emerging_themes.json"
    
    # Load existing data if file exists
    if os.path.exists(output_path):
        with open(output_path, "r") as f:
            try:
                existing = json.load(f)
            except json.JSONDecodeError:
                existing = []
    else:
        existing = []
    
    # Add new terms (avoid duplicates)
    existing_terms = {(e.get("vertical"), e.get("emerging_use_case"), e.get("emerging_technology")) 
                      for e in existing}
    
    for term in emerging_terms:
        key = (term.get("vertical"), term.get("emerging_use_case"), term.get("emerging_technology"))
        if key not in existing_terms:
            existing.append(term)
            existing_terms.add(key)
    
    with open(output_path, "w") as f:
        json.dump(existing, f, indent=2)
    
    print(f"Saved {len(emerging_terms)} emerging terms to {output_path}")


def run_full_analysis():
    conn = get_connection()
    summary(conn)
    run_id = new_run_id()

    verticals = [r["vertical_hint"] for r in conn.execute(
        "SELECT DISTINCT vertical_hint FROM signals WHERE vertical_hint IS NOT NULL"
    ).fetchall()]

    all_themes = []      # Store all classified themes
    all_emerging = []    # Store all emerging terms

    for vertical in verticals:
        print(f"\n{'=' * 60}\nTheme extraction: {vertical}\n{'=' * 60}")
        themes, candidates = extract_themes(conn, vertical)
        for t in themes:
            print(f"  -> {vertical} x {t.get('use_case')} x {t.get('technology')} "
                  f"({t.get('supporting_signal_count')} signals)")
            print(f"     {t.get('rationale')}")
        if candidates:
            print(f"  [watchlist] {len(candidates)} out-of-taxonomy candidate(s) logged for review")

        # Track every VALID theme in-memory (no JSON round-trip) so recurring
        # ones can later be auto-promoted to a real opportunity space.
        if themes:
            inserted, updated = track_valid_themes(conn, vertical, themes, run_id=run_id)
            print(f"  [recurring_themes] {inserted} new, {updated} bumped in frequency")

    print(f"\n{'=' * 60}\nWatchlist terms ready for team review (seen >= {WATCHLIST_PROMOTION_THRESHOLD}x)\n{'=' * 60}")
    ready = list_watchlist(conn, min_frequency=WATCHLIST_PROMOTION_THRESHOLD)
    if not ready:
        print("  None yet -- check back after more ingest runs.")
    for term in ready:
        print(f"  [{term['category']}] \"{term['term']}\" -- seen {term['frequency']}x "
              f"(vertical: {term['vertical']}) -- id={term['id']}")
        update_watchlist_status(conn, term["id"], "proposed")
    print("\n  Below threshold, still accumulating:")
    for term in list_watchlist(conn, status="pending"):
        print(f"  [{term['category']}] \"{term['term']}\" -- seen {term['frequency']}x")

    print(f"\n{'=' * 60}\nRecurring themes ready for promotion (recurred >= {RECURRING_THEME_PROMOTION_THRESHOLD}x)\n{'=' * 60}")
    promotable = list_promotable_themes(conn, RECURRING_THEME_PROMOTION_THRESHOLD)
    if not promotable:
        print("  None yet -- run ingest + analyze a few more times, or lower "
              "RECURRING_THEME_PROMOTION_THRESHOLD in pipeline/config.py.")
    for theme in promotable:
        print(f"  {theme['vertical']} x {theme['use_case']} x {theme['technology']} "
              f"-- seen {theme['frequency']}x -- run `python radar_cli.py promote` to register it")

    conn.close()


if __name__ == "__main__":
    run_full_analysis()