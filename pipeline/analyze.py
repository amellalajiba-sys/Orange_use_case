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
theme_promotion.track_valid_themes() -- a recurring theme (same Vertical
x Use Case x Technology seen across separate runs) is what
`radar_cli.py promote` later turns into a real opportunity space. See
pipeline/theme_promotion.py and pipeline/db.py's recurring_themes table
for the full mechanism -- this replaces an earlier design that round-tripped
through an emerging_themes.json file.

Run directly for a full pass over all verticals:

    python -m pipeline.analyze
"""
# Sieg 24/8 -- module renamed signals_discovery.py -> theme_promotion.py,
# docstring above updated to match (pure documentation drift, no logic
# change here -- see the import below for the actual switch).

import sys
from pipeline.db import (
    get_connection, add_to_watchlist, list_watchlist, update_watchlist_status, new_run_id,
    list_promotable_themes,
)
from pipeline.config import USE_CASES_TAXONOMY, TECHNOLOGIES_TAXONOMY, RECURRING_THEME_PROMOTION_THRESHOLD
from pipeline.taxonomy_validation import is_generic_taxonomy_term
# Sieg 24/8 -- switched to pipeline.theme_promotion: that's the name in
# diff (signals_discovery.py -> theme_promotion.py), and original picked it
# as the one to keep. signals_discovery.py removed outright -- nothing else in the project referenced it once this import
# and radar_cli.py/radar_cli_top_15.py were all switched over.
from pipeline.theme_promotion import track_valid_themes
from llm.llm_client import get_llm_json

WATCHLIST_PROMOTION_THRESHOLD = 2


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


def _call_theme_extraction_llm(vertical, rows):
    """Sieg 25/8 -- pure LLM-boundary function, split out of extract_themes()
    so the classification logic below (_classify_themes) can be unit-tested
    against hand-crafted LLM outputs without needing a DB connection or a
    real LLM call. Builds the prompt from already-fetched signal rows and
    returns the raw parsed JSON dict (or None if the call/parse failed) --
    no watchlist/DB writes happen here."""
    titles = "\n".join(f"- [{r['signal_type']}] {r['title']}" for r in rows)
    prompt = f"Vertical: {vertical}\n\nSignals:\n{titles}"
    system_prompt = THEME_EXTRACTION_SYSTEM_PROMPT.format(
        use_cases=", ".join(USE_CASES_TAXONOMY), technologies=", ".join(TECHNOLOGIES_TAXONOMY)
    )
    return get_llm_json(prompt, system_prompt=system_prompt)


def _classify_themes(themes, candidates):
    """Sieg 25/8 -- pure classification logic, split out of extract_themes()
    on purpose: takes the LLM's already-parsed `themes`/`watchlist_candidates`
    lists and sorts them into what's usable vs what needs a watchlist entry,
    with NO database access and NO LLM call -- this is what makes it directly
    unit-testable against malformed/edge-case inputs (missing keys, null
    values, bare generic terms) without a live DB or a real/mocked LLM
    response wrapper, see tests/test_analyze_classification.py.

    Returns (valid_themes, watchlist_entries, skipped_generic):
      - valid_themes: themes whose use_case AND technology both match the
        closed taxonomy exactly, unchanged.
      - watchlist_entries: list of (term, category, vertical) tuples the
        caller should persist via db.add_to_watchlist().
      - skipped_generic: list of (term, category, vertical) that were
        filtered out as bare generic terms (e.g. "AI" alone) -- returned so
        the caller can log them, matching the original behavior.

    Sieg 24/8 -- bug fix, preserved: `.get("technology", "unknown")` only
    falls back to "unknown" when the KEY is missing entirely -- if the LLM
    returns the key WITH a null value (seen in practice from the Ollama/
    llama3.2:3b fallback, which is much more prone to malformed JSON than
    Groq), .get() returns None, not "unknown", and that None would go
    straight into add_to_watchlist() -> INSERT with term=None ->
    sqlite3.IntegrityError: NOT NULL constraint failed: watchlist_terms.term,
    crashing the whole --from= run mid-vertical. `x or "unknown"` catches
    both "missing" and "present but None/empty"."""
    valid_themes = []
    watchlist_entries = []
    skipped_generic = []

    for t in themes:
        use_case = t.get("use_case")
        technology = t.get("technology")
        if use_case in USE_CASES_TAXONOMY and technology in TECHNOLOGIES_TAXONOMY:
            valid_themes.append(t)
            continue
        if use_case not in USE_CASES_TAXONOMY:
            watchlist_entries.append((use_case or "unknown", "use_case"))
        if technology not in TECHNOLOGIES_TAXONOMY:
            technology = technology or "unknown"
            # Sieg 24/8 -- the prompt asks the LLM to avoid bare "AI", but
            # prompt compliance is not validation: do not let it accumulate
            # in watchlist_terms and later reach review.
            if is_generic_taxonomy_term(technology, "technology"):
                skipped_generic.append((technology, "technology"))
            else:
                watchlist_entries.append((technology, "technology"))

    for c in candidates:
        if c.get("term") and c.get("category") in ("use_case", "technology"):
            # Sieg 24/8 -- apply the same guard to the LLM's explicit
            # watchlist output, not only to malformed entries in `themes`.
            if is_generic_taxonomy_term(c["term"], c["category"]):
                skipped_generic.append((c["term"], c["category"]))
            else:
                watchlist_entries.append((c["term"], c["category"]))

    return valid_themes, watchlist_entries, skipped_generic


def extract_themes(conn, vertical, max_signals=40):
    """Ask the LLM to turn raw signal titles into candidate Opportunity
    Spaces for one vertical, constrained to the closed taxonomy. Anything
    that doesn't fit goes to watchlist_terms instead of being silently
    accepted or silently dropped. Returns (valid_themes, watchlist_candidates).

    Sieg 25/8 -- now a thin orchestrator: fetch signals (DB) -> call the LLM
    (_call_theme_extraction_llm) -> classify the result (_classify_themes,
    pure) -> persist watchlist entries (DB). Same inputs/outputs/behavior as
    before the split -- see the two helper functions above for what moved
    where and why."""
    rows = conn.execute(
        "SELECT signal_type, title FROM signals WHERE vertical_hint = ? "
        "ORDER BY collected_at DESC LIMIT ?",
        (vertical, max_signals),
    ).fetchall()

    if len(rows) < 3:
        print(f"[{vertical}] only {len(rows)} signals -- too few for reliable theme extraction, skipping")
        return [], []

    result = _call_theme_extraction_llm(vertical, rows)
    if not result or "themes" not in result:
        print(f"[{vertical}] theme extraction failed or returned nothing usable")
        return [], []

    themes = result.get("themes", [])
    candidates = result.get("watchlist_candidates", [])

    valid_themes, watchlist_entries, skipped_generic = _classify_themes(themes, candidates)

    for term, category in watchlist_entries:
        add_to_watchlist(conn, term, category, vertical)
    for term, category in skipped_generic:
        print(f"[{vertical}] skipped generic {category} candidate: {term!r}")

    return valid_themes, candidates


def run_full_analysis(from_vertical=None):
    """Sieg 23/08 -- added from_vertical: a single Groq key has a shared,
    small daily token quota (200k TPD on the free tier), and a run can burn
    through it mid-way (429 rate_limit_exceeded), stopping analysis partway
    through the vertical list. Rerunning from scratch just re-spends tokens
    on verticals that already finished before the quota was hit, for no
    new result -- track_valid_themes() upserts (bumps frequency) rather than
    duplicating, so a re-run isn't wrong, it's just wasted quota while
    already scarce. --from=<vertical> skips straight to where the previous
    run stopped, case-insensitive so `--from=energy` matches "Energy"."""
    conn = get_connection()
    summary(conn)
    run_id = new_run_id()

    verticals = [r["vertical_hint"] for r in conn.execute(
        "SELECT DISTINCT vertical_hint FROM signals WHERE vertical_hint IS NOT NULL"
    ).fetchall()]

    if from_vertical:
        before = len(verticals)
        matched = [v for v in verticals if v.lower() == from_vertical.lower()]
        if not matched:
            print(f"--from={from_vertical}: no vertical matches this name exactly "
                  f"(available: {', '.join(verticals)}). Running everything instead.")
        else:
            start_index = verticals.index(matched[0])
            verticals = verticals[start_index:]
            print(f"--from={from_vertical}: skipping {before - len(verticals)} "
                  f"vertical(s) already processed before the interruption.\n")

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
    # Sieg 23/08 -- python -m pipeline.analyze --from=Energy : resume after
    # a Groq quota/rate-limit interruption without redoing finished verticals.
    # Ignored (runs everything) if not passed, same as before.
    from_vertical = None
    for arg in sys.argv:
        if arg.startswith("--from="):
            from_vertical = arg.split("=", 1)[1]
    run_full_analysis(from_vertical=from_vertical)