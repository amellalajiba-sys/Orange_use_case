"""
Analyze signals already collected in radar.db.

Two steps, matching the brief's "Signal Collection -> Theme Extraction" flow:

1. summary() / dump_titles()  -- fast, no LLM, no cost. Look at raw counts
   and skim actual titles by eye. Always do this FIRST before automating
   anything -- you need to know what's actually in there.

2. extract_themes(vertical)   -- LLM-assisted. Takes the signal titles for
   one vertical and asks the model to identify recurring Use Case x
   Technology combinations, i.e. candidate Opportunity Spaces.

Run directly for a full pass over all verticals:

    python -m pipeline.analyze




IRENE (Wed 19, 19:10)
=====================

    - changed THEME_EXTRACTION_SYSTEM_PROMPT (now stricted to taxonomy given);
    - implemented 'classified' and 'emerging' differentiation in extract_themes()
      and adapted return;
    - added save_emerging_themes() to make it return output for signals_discovery.py (JSON file);
    - updated run_full_analysis() to make it save emerging terms.

"""

import json
import os
import re
from collections import Counter
from difflib import SequenceMatcher
from pipeline.db import get_connection
from pipeline.config import (
    TAXONOMY_USE_CASES, TAXONOMY_TECHNOLOGIES, TAXONOMY_TECHNOLOGIES_EMERGING,
    GENERIC_TECHNOLOGY_TERMS,
)
from llm.llm_client import get_llm_json


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

THEME_EXTRACTION_SYSTEM_PROMPT = """
Identify 3-6 recurring, specific Use Case x Technology combinations, 
each supported by MULTIPLE distinct signals (minimum 3).

For each combination:
- If it fits the official lists → classify it
- If it doesn't fit → mark it as emerging

Ignore one-off signals — they are not patterns.

Official Use Cases:
{use_case_list}

Official Technologies:
{technology_list}

Respond with ONLY a JSON array:
[
    {{
        "use_case": "official_use_case or null",
        "technology": "official_technology or null",
        "emerging_use_case": "proposed new use case or null",
        "emerging_technology": "proposed new technology or null",
        "is_classified": true/false,
        "supporting_signal_count": <int>,
        "rationale": "<one sentence>"
    }}
]
"""


def _curate_themes(themes):
    """
    Phase 3 curation -- operates ONLY on candidate Opportunity Space labels
    (this function's `themes` input), never on the `signals` table. A signal
    mentioning "AI" stays in the database untouched; what gets dropped here is
    a candidate OS whose entire technology value IS just "AI" -- too vague to
    be a sellable, specific Opportunity Space (right-to-win can't map a bare
    "AI" to a specific Orange asset). Applied after the LLM proposes themes
    (defense-in-depth -- the prompt already asks it to avoid generic terms,
    but per the project's own lesson, weak LLMs pattern-match instructions
    unreliably, so never trust prompt compliance alone):

    1. Drop themes whose technology is a bare generic term (config.GENERIC_TECHNOLOGY_TERMS)
    2. Merge near-duplicate themes (same use_case, near-identical technology
       string) -- same fuzzy-match approach as dedupe_signals.py, keeping the
       one with the higher supporting_signal_count.
    """
    kept = []
    dropped_generic = 0
    for t in themes:
        tech = (t.get("technology") or "").strip().lower()
        if tech in GENERIC_TECHNOLOGY_TERMS:
            dropped_generic += 1
            continue
        kept.append(t)

    def _key(t):
        return re.sub(r"\s+", " ", f"{t.get('use_case', '')} {t.get('technology', '')}".lower()).strip()

    merged = []
    used = [False] * len(kept)
    for i, t in enumerate(kept):
        if used[i]:
            continue
        group = [t]
        used[i] = True
        for j in range(i + 1, len(kept)):
            if used[j]:
                continue
            if SequenceMatcher(None, _key(t), _key(kept[j])).ratio() >= 0.85:
                group.append(kept[j])
                used[j] = True
        best = max(group, key=lambda x: x.get("supporting_signal_count", 0) or 0)
        merged.append(best)

    if dropped_generic or len(merged) < len(themes):
        print(f"[curate_themes] {dropped_generic} generic dropped, "
              f"{len(themes) - dropped_generic - len(merged)} near-duplicates merged, "
              f"{len(merged)} themes kept")
    return merged


def extract_themes(conn, vertical, max_signals=40):
    """Asks the LLM to turn raw signal titles into candidate Opportunity
    Spaces for one vertical. 
    Returns a dict with two lists:
    {
        "classified": [...],   # terms that match the official taxonomy
        "emerging": [...]      # terms that don't match, proposed as new
    }
    Returns {"classified": [], "emerging": []} if nothing usable came back.
    """
    rows = conn.execute(
        "SELECT signal_type, title FROM signals WHERE vertical_hint = ? "
        "ORDER BY collected_at DESC LIMIT ?",
        (vertical, max_signals),
    ).fetchall()

    if len(rows) < 5:
        print(f"[{vertical}] only {len(rows)} signals -- too few for reliable theme extraction, skipping")
        return {"classified": [], "emerging": []}

    titles = "\n".join(f"- [{r['signal_type']}] {r['title']}" for r in rows)
    prompt = f"Vertical: {vertical}\n\nSignals:\n{titles}"
    system_prompt = THEME_EXTRACTION_SYSTEM_PROMPT.format(
        use_case_list="\n".join(f"- {u}" for u in TAXONOMY_USE_CASES),
        technology_list="\n".join(f"- {t}" for t in TAXONOMY_TECHNOLOGIES),
        emerging_technology_list="\n".join(f"- {t}" for t in TAXONOMY_TECHNOLOGIES_EMERGING),
    )

    result = get_llm_json(prompt, system_prompt=system_prompt)

    # DEBUG: Print raw result
    print(f"[DEBUG] Raw LLM response for {vertical}:")
    print(result)
    print("-" * 40)

    if not result or not isinstance(result, list):
        print(f"[{vertical}] theme extraction failed or returned nothing usable")
        return {"classified": [], "emerging": []}

    classified = []
    emerging = []

    for item in result:
        # check if it is classified
        if item.get("is_classified") and item.get("use_case") and item.get("technology"):
            # Build a clean dict for curation
            classified.append({
                "use_case": item["use_case"],
                "technology": item["technology"],
                "supporting_signal_count": item.get("supporting_signal_count", 0),
                "rationale": item.get("rationale", "")
            })
        elif not item.get("is_classified"):
            # This is an emerging term
            emerging.append({
                "vertical": vertical,
                "emerging_use_case": item.get("emerging_use_case"),
                "emerging_technology": item.get("emerging_technology"),
                "rationale": item.get("rationale", ""),
                "supporting_signal_count": item.get("supporting_signal_count", 0)
            })

    # Only keep themes with at least 3 signals
    classified = [t for t in classified if t.get("supporting_signal_count", 0) >= 3]
    emerging = [t for t in emerging if t.get("supporting_signal_count", 0) >= 3]

    # Apply curation ONLY to classified terms
    curated_classified = _curate_themes(classified)

    print(f"[{vertical}] {len(curated_classified)} classified themes, {len(emerging)} emerging terms")
    
    return {"classified": curated_classified, "emerging": emerging}


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

    verticals = [r["vertical_hint"] for r in conn.execute(
        "SELECT DISTINCT vertical_hint FROM signals WHERE vertical_hint IS NOT NULL"
    ).fetchall()]

    all_emerging = []  # To collect all emerging terms across verticals

    for vertical in verticals:
        print(f"\n{'=' * 60}\nTheme extraction: {vertical}\n{'=' * 60}")
        result = extract_themes(conn, vertical)

        for t in result.get("classified", []):
            print(f"  -> {vertical} x {t.get('use_case')} x {t.get('technology')} "
                  f"({t.get('supporting_signal_count')} signals)")
            print(f"     {t.get('rationale')}")

        # Collect emerging terms
        for e in result.get("emerging", []):
            print(f"  [EMERGING] {vertical} x {e.get('emerging_use_case')} x {e.get('emerging_technology')} "
                  f"({e.get('supporting_signal_count')} signals)")
            all_emerging.append(e)

    # Save all emerging terms
    if all_emerging:
        save_emerging_themes(all_emerging)

    conn.close()


if __name__ == "__main__":
    run_full_analysis()