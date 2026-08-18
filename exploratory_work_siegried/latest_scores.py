"""
Prints only the MOST RECENT score per opportunity space -- useful if you ran
scoring.py more than once (e.g. once on Ollama, once on Groq), since
insert_score() / insert_right_to_win_score() always INSERT, never overwrite.

Run:
    python latest_scores.py
"""

from exploratory_work_siegried.pipeline.db import get_connection

conn = get_connection()
rows = conn.execute("""
    SELECT os.label, os.vertical, os.use_case, os.technology,
           s.total_score, s.strategic_relevance, s.evidence_quality,
           r.portfolio_distance, r.right_to_win_score, r.matched_assets, r.justification
    FROM opportunity_spaces os
    JOIN scores s ON s.opportunity_space_id = os.id
        AND s.computed_at = (SELECT MAX(computed_at) FROM scores WHERE opportunity_space_id = os.id)
    JOIN right_to_win_scores r ON r.opportunity_space_id = os.id
        AND r.computed_at = (SELECT MAX(computed_at) FROM right_to_win_scores WHERE opportunity_space_id = os.id)
    ORDER BY os.label
""").fetchall()

for r in rows:
    print(f"{r['label']} ({r['vertical']} x {r['use_case']} x {r['technology']})")
    print(f"  Attractiveness: {r['total_score']}/10  (strategic_relevance={r['strategic_relevance']}, evidence_quality={r['evidence_quality']})")
    print(f"  Right-to-win:   {r['right_to_win_score']}/10  [{r['portfolio_distance']}]  assets: {r['matched_assets'] or 'none'}")
    print(f"  -> {r['justification']}")
    print()

conn.close()