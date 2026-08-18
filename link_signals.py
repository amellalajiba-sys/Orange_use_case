"""
Links the most relevant real signals to each opportunity space, using
keyword overlap between the signal title and the OS's use_case/technology.
This is what makes "why it's hot" claims traceable to real evidence instead
of floating unsupported (see db.py's opportunity_signals table, unused until now).

Deliberately simple (keyword overlap, no LLM) -- good enough to ground a
handful of signals per OS for tomorrow, cheap to re-run, no API cost.

Run:
    python link_signals.py
"""

import re
from pipeline.db import get_connection, get_signals_for_vertical, link_signal_to_opportunity

STOPWORDS = {"and", "the", "for", "with", "of", "in", "on", "a", "an", "to", "x"}


def _keywords(text):
    words = re.findall(r"[a-zA-Z]+", text.lower())
    return {w for w in words if len(w) > 2 and w not in STOPWORDS}


def link_top_signals(conn, os_row, top_n=8):
    target_keywords = _keywords(f"{os_row['use_case']} {os_row['technology']}")
    signals = get_signals_for_vertical(conn, os_row["vertical"])

    scored = []
    for s in signals:
        sig_keywords = _keywords(s["title"] or "")
        overlap = len(target_keywords & sig_keywords)
        if overlap > 0:
            scored.append((overlap, s))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:top_n]
    for _, s in top:
        link_signal_to_opportunity(conn, os_row["id"], s["id"])
    return top


if __name__ == "__main__":
    conn = get_connection()
    spaces = conn.execute("SELECT * FROM opportunity_spaces").fetchall()
    for os_row in spaces:
        top = link_top_signals(conn, os_row)
        print(f"{os_row['label']} ({os_row['use_case']} x {os_row['technology']}): linked {len(top)} signals")
        for overlap, s in top:
            print(f"  [{overlap} kw match] ({s['source_name']}) {s['title']}")
        if not top:
            print("  -- no keyword overlap found, this OS has no grounded evidence yet")
        print()
    conn.close()