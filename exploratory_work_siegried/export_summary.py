"""
Exports a one-page markdown summary of all opportunity spaces: latest scores,
right-to-win, matched assets, and the signals grounding each one. Meant to be
printed or pasted for tomorrow's team meeting -- one file, no digging through
console output.

Run (after scoring.py and link_signals.py have both been run at least once):
    python export_summary.py
"""

from datetime import datetime, timezone
from exploratory_work_siegried.pipeline.db import get_connection

OUTPUT_PATH = "opportunity_spaces_summary.md"

conn = get_connection()

spaces = conn.execute("""
    SELECT os.*, s.total_score, s.market_signal_strength, s.source_diversity,
           s.evidence_quality, s.evidence_quality_justification,
           s.novelty_momentum, s.strategic_relevance, s.strategic_relevance_justification,
           r.portfolio_distance, r.right_to_win_score, r.matched_assets, r.justification AS rtw_justification
    FROM opportunity_spaces os
    JOIN scores s ON s.opportunity_space_id = os.id
        AND s.computed_at = (SELECT MAX(computed_at) FROM scores WHERE opportunity_space_id = os.id)
    JOIN right_to_win_scores r ON r.opportunity_space_id = os.id
        AND r.computed_at = (SELECT MAX(computed_at) FROM right_to_win_scores WHERE opportunity_space_id = os.id)
    ORDER BY s.total_score DESC
""").fetchall()

lines = [
    "# Innovation Radar — Opportunity Spaces Summary",
    f"_Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_",
    "",
    "| OS | Attractiveness | Right-to-win | Distance |",
    "|---|---|---|---|",
]
for os_row in spaces:
    lines.append(
        f"| {os_row['label']} | {os_row['total_score']}/10 | {os_row['right_to_win_score']}/10 | {os_row['portfolio_distance']} |"
    )
lines.append("")

for os_row in spaces:
    lines.append(f"## {os_row['label']} — {os_row['vertical']} × {os_row['use_case']} × {os_row['technology']}")
    lines.append("")
    lines.append(f"**Attractiveness: {os_row['total_score']}/10**")
    lines.append(f"- Market signal strength: {os_row['market_signal_strength']}")
    lines.append(f"- Source diversity: {os_row['source_diversity']}")
    lines.append(f"- Evidence quality: {os_row['evidence_quality']} — {os_row['evidence_quality_justification']}")
    lines.append(f"- Novelty / momentum: {os_row['novelty_momentum']}")
    lines.append(f"- Strategic relevance: {os_row['strategic_relevance']} — {os_row['strategic_relevance_justification']}")
    lines.append("")
    lines.append(f"**Right-to-win: {os_row['right_to_win_score']}/10 [{os_row['portfolio_distance']}]**")
    lines.append(f"- Matched assets: {os_row['matched_assets'] or 'none'}")
    lines.append(f"- {os_row['rtw_justification']}")
    lines.append("")

    grounding = conn.execute("""
        SELECT sig.source_name, sig.title, sig.signal_type, sig.published_date
        FROM opportunity_signals link
        JOIN signals sig ON sig.id = link.signal_id
        WHERE link.opportunity_space_id = ?
    """, (os_row["id"],)).fetchall()
    lines.append(f"**Grounding signals ({len(grounding)}):**")
    if grounding:
        for g in grounding:
            date = f" ({g['published_date']})" if g["published_date"] else ""
            lines.append(f"- [{g['signal_type']}] {g['source_name']}: {g['title']}{date}")
    else:
        lines.append("- _none linked yet — run link_signals.py first_")
    lines.append("")

with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

conn.close()
print(f"Written: {OUTPUT_PATH}")