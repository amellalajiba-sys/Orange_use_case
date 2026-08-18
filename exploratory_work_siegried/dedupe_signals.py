"""
Finds near-duplicate signals -- the same real-world story picked up by
multiple sources (e.g. Google News + GDELT + Competitor watch all catching
the same article) with slightly different titles. Exact duplicates are
already blocked by db.py's UNIQUE(source_url, title) constraint; this catches
the ones that constraint can't -- different URL, near-identical title.

Matters because near-duplicates inflate market_signal_strength without adding
real new evidence.

DRY RUN BY DEFAULT -- only reports what it would remove, changes nothing.
Review the groups printed, then re-run with --apply to actually delete.
Within each duplicate group, keeps the OLDEST signal (first one collected)
and removes the rest.

Run:
    python dedupe_signals.py           # report only, safe
    python dedupe_signals.py --apply   # actually deletes the near-duplicates
"""

import sys
import re
from difflib import SequenceMatcher
from exploratory_work_siegried.pipeline.db import get_connection

SIMILARITY_THRESHOLD = 0.85  # 0-1, higher = stricter match required


def _normalize(title):
    # Lowercase, strip trailing " - Source Name" that RSS feeds often append,
    # collapse whitespace -- makes titles from different feeds comparable.
    t = title.lower()
    t = re.sub(r"\s*-\s*[a-z0-9 .]+$", "", t)  # strip trailing " - Some Source"
    t = re.sub(r"\s+", " ", t).strip()
    return t


def find_duplicate_groups(conn):
    """Returns a list of groups; each group is a list of signal rows that are
    near-duplicates of each other (same normalized/fuzzy-matched title)."""
    signals = conn.execute(
        "SELECT id, source_name, title, collected_at FROM signals ORDER BY collected_at ASC"
    ).fetchall()

    normalized = [(s, _normalize(s["title"] or "")) for s in signals]
    used = set()
    groups = []

    for i, (sig_a, norm_a) in enumerate(normalized):
        if sig_a["id"] in used or not norm_a:
            continue
        group = [sig_a]
        used.add(sig_a["id"])
        for sig_b, norm_b in normalized[i + 1:]:
            if sig_b["id"] in used or not norm_b:
                continue
            ratio = SequenceMatcher(None, norm_a, norm_b).ratio()
            if ratio >= SIMILARITY_THRESHOLD:
                group.append(sig_b)
                used.add(sig_b["id"])
        if len(group) > 1:
            groups.append(group)

    return groups


def report(groups):
    if not groups:
        print("No near-duplicate signals found.")
        return
    total_removable = sum(len(g) - 1 for g in groups)
    print(f"Found {len(groups)} duplicate groups, {total_removable} removable signals:\n")
    for group in groups:
        print(f"  KEEP: [{group[0]['source_name']}] {group[0]['title']}  ({group[0]['collected_at']})")
        for dup in group[1:]:
            print(f"  DROP: [{dup['source_name']}] {dup['title']}  ({dup['collected_at']})")
        print()
    print(f"Total: {total_removable} signals would be removed. Re-run with --apply to actually delete them.")


def apply_deletions(conn, groups):
    total = 0
    for group in groups:
        for dup in group[1:]:
            conn.execute("DELETE FROM signals WHERE id = ?", (dup["id"],))
            conn.execute("DELETE FROM opportunity_signals WHERE signal_id = ?", (dup["id"],))
            total += 1
    conn.commit()
    print(f"Deleted {total} near-duplicate signals.")


if __name__ == "__main__":
    conn = get_connection()
    groups = find_duplicate_groups(conn)

    if "--apply" in sys.argv:
        report(groups)
        apply_deletions(conn, groups)
        print("\nRe-run calibrate_caps.py, pipeline.scoring, link_signals.py and export_summary.py "
              "to refresh scores with the cleaned data.")
    else:
        report(groups)

    conn.close()