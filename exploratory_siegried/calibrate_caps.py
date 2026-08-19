"""
Shows, for each vertical that has an opportunity space, the exact numbers
scoring.py's market_signal_strength() and source_diversity() see -- including
the untagged signals that get_signals_for_vertical() folds in. Use this to
pick sane values for MARKET_SIGNAL_CAP / SOURCE_DIVERSITY_CAP in scoring.py
instead of guessing.

Run:
    python calibrate_caps.py
"""

from pipeline.db import get_connection, get_signals_for_vertical

conn = get_connection()
verticals = [r["vertical"] for r in conn.execute("SELECT DISTINCT vertical FROM opportunity_spaces").fetchall()]

print(f"{'Vertical':<25} {'Signal count':<15} {'Distinct sources':<18}")
print("-" * 60)
for v in verticals:
    signals = get_signals_for_vertical(conn, v)
    distinct_sources = {s["source_name"] for s in signals}
    print(f"{v:<25} {len(signals):<15} {len(distinct_sources):<18}")

conn.close()