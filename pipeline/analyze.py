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
"""

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

THEME_EXTRACTION_SYSTEM_PROMPT = """You are analyzing market signals (news, research
papers, vendor announcements, regulation) collected for one business vertical, to spot
candidate Opportunity Spaces for a B2B telecom/cloud provider (Orange Business).

An Opportunity Space = Vertical x Use Case x Technology, and must be SPECIFIC
(e.g. "Manufacturing x Energy Optimization x Computer Vision"), never a generic
theme like "AI in industry" or "Cloud adoption".

Here are example Use Case and Technology values already validated for Orange
Business -- prefer these when a signal clearly fits one. They are a starting
point, not an exhaustive list: if a recurring pattern across signals is real
and specific but doesn't fit any of these well, propose a new specific label
instead of forcing a bad-fit match.

Use Case (examples):
{use_case_list}

Technology (examples, established):
{technology_list}

Emerging technologies (less proven, but real if the signals actually support
them -- actively watch for these rather than defaulting to the established
list above just because it's more familiar):
{emerging_technology_list}

Read the signal titles below and identify 3-6 recurring, specific Use Case x
Technology combinations, each one supported by multiple distinct signals.

Respond with ONLY a JSON array, no preamble, no markdown fences:
[
  {{"use_case": "...", "technology": "...", "supporting_signal_count": <int>,
   "rationale": "<one sentence: why this is a real, specific pattern>"}}
]"""


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
    """Ask the LLM to turn raw signal titles into candidate Opportunity
    Spaces for one vertical. Returns a list of dicts, or [] if nothing
    usable came back (e.g. LLM unreachable, or too few signals)."""
    rows = conn.execute(
        "SELECT signal_type, title FROM signals WHERE vertical_hint = ? "
        "ORDER BY collected_at DESC LIMIT ?",
        (vertical, max_signals),
    ).fetchall()

    if len(rows) < 5:
        print(f"[{vertical}] only {len(rows)} signals -- too few for reliable theme extraction, skipping")
        return []

    titles = "\n".join(f"- [{r['signal_type']}] {r['title']}" for r in rows)
    prompt = f"Vertical: {vertical}\n\nSignals:\n{titles}"
    system_prompt = THEME_EXTRACTION_SYSTEM_PROMPT.format(
        use_case_list="\n".join(f"- {u}" for u in TAXONOMY_USE_CASES),
        technology_list="\n".join(f"- {t}" for t in TAXONOMY_TECHNOLOGIES),
        emerging_technology_list="\n".join(f"- {t}" for t in TAXONOMY_TECHNOLOGIES_EMERGING),
    )

    result = get_llm_json(prompt, system_prompt=system_prompt)
    if not result or not isinstance(result, list):
        print(f"[{vertical}] theme extraction failed or returned nothing usable")
        return []
    return _curate_themes(result)


def run_full_analysis():
    conn = get_connection()
    summary(conn)

    verticals = [r["vertical_hint"] for r in conn.execute(
        "SELECT DISTINCT vertical_hint FROM signals WHERE vertical_hint IS NOT NULL"
    ).fetchall()]

    for vertical in verticals:
        print(f"\n{'=' * 60}\nTheme extraction: {vertical}\n{'=' * 60}")
        themes = extract_themes(conn, vertical)
        for t in themes:
            print(f"  -> {vertical} x {t.get('use_case')} x {t.get('technology')} "
                  f"({t.get('supporting_signal_count')} signals)")
            print(f"     {t.get('rationale')}")

    conn.close()


if __name__ == "__main__":
    run_full_analysis()