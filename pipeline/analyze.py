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

from collections import Counter
from pipeline.db import get_connection
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

Read the signal titles below and identify 3-6 recurring, specific Use Case x
Technology combinations. Reject anything too generic or supported by only one
vague signal.

Respond with ONLY a JSON array, no preamble, no markdown fences:
[
  {"use_case": "...", "technology": "...", "supporting_signal_count": <int>,
   "rationale": "<one sentence: why this is a real, specific pattern>"}
]"""


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

    result = get_llm_json(prompt, system_prompt=THEME_EXTRACTION_SYSTEM_PROMPT)
    if not result or not isinstance(result, list):
        print(f"[{vertical}] theme extraction failed or returned nothing usable")
        return []
    return result


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