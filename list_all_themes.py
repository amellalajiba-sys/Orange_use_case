"""
Extracts ALL candidate opportunity spaces (Use Case x Technology) per vertical
from current signals, completely unfiltered -- no pre-selection, no judgment
about which ones are "too obvious" or "not worth it". That decision belongs to
the team, not to this script.

Writes every candidate to candidate_opportunity_spaces.md, alongside the 4
that are already registered in opportunity_spaces (so it's clear which ones
already have a score and which don't yet).

Run:
    python list_all_themes.py
"""

from datetime import datetime, timezone
from pipeline.db import get_connection
from pipeline.analyze import extract_themes

OUTPUT_PATH = "candidate_opportunity_spaces.md"

conn = get_connection()

verticals = [r["vertical_hint"] for r in conn.execute(
    "SELECT DISTINCT vertical_hint FROM signals WHERE vertical_hint IS NOT NULL"
).fetchall()]

already_registered = {
    (r["vertical"], r["use_case"], r["technology"])
    for r in conn.execute("SELECT vertical, use_case, technology FROM opportunity_spaces").fetchall()
}

lines = [
    "# Candidate Opportunity Spaces — unfiltered",
    f"_Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} from current signals, no pre-selection applied._",]

for vertical in verticals:
    print(f"Extracting themes for {vertical}...")
    themes = extract_themes(conn, vertical)
    lines.append(f"## {vertical}")
    lines.append("")
    if not themes:
        lines.append("_No themes extracted (too few signals, or LLM call failed) -- see console output._")
        lines.append("")
        continue
    for t in themes:
        use_case = t.get("use_case", "?")
        technology = t.get("technology", "?")
        count = t.get("supporting_signal_count", "?")
        rationale = t.get("rationale", "")
        is_registered = (vertical, use_case, technology) in already_registered
        tag = " **[already registered]**" if is_registered else ""
        lines.append(f"- **{use_case} × {technology}**{tag} ({count} signals)")
        lines.append(f"  {rationale}")
    lines.append("")

with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

conn.close()
print(f"\nWritten: {OUTPUT_PATH}")