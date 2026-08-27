"""
radar_cli.py 

Single entry point for every one-off Innovation Radar pipeline tool.

Run:
    python radar_cli.py all [--force]        # runs the entire pipeline in order, one command
    python radar_cli.py create [--wipe]     # register CANDIDATES (pipeline/config.py) as opportunity spaces
    python radar_cli.py delete OS001 OS024  # permanently delete specific opportunity spaces (asks to confirm)
    python radar_cli.py promote             # auto-register recurring themes that hit the promotion threshold
    python radar_cli.py calibrate           # signal counts / source diversity, for tuning scoring.py's caps
    python radar_cli.py dedupe [--apply]    # find/remove near-duplicate signals (dry-run by default)
    python radar_cli.py watchlist           # show out-of-taxonomy terms + recurring themes, read-only
    python radar_cli.py link                # link the strongest real signals to each opportunity space
    python radar_cli.py themes              # regenerate candidate_opportunity_spaces.md, unfiltered
    python radar_cli.py scores              # print latest scores to console
    python radar_cli.py summary             # write opportunity_spaces_summary.md -- the file to bring to a meeting

WHAT CHANGED IN THIS REVISION
-------------------------------
- `create` now warns (doesn't block) when the vertical+use_case+technology
  triple you're about to register already exists under a different label --
  the exact class of bug behind the OS001/OS013 duplicate. Adapted from a
  teammate's duplicate-check idea; reimplemented as a parameterized query
  (db.find_opportunity_space_by_triple) instead of an f-string-built SQL
  query, since the original interpolated vertical/use_case/technology
  straight into the SQL text.
- `discover` (which read emerging_themes.json) is integrated. Replaced by
  `promote`, which reads pipeline/db.py's recurring_themes table directly
  -- no JSON file involved anywhere anymore. This is also the mechanism
  that grows the opportunity space list past a fixed, hand-picked 15 (see
  pipeline/config.py's CANDIDATES docstring).
- `watchlist` is a new read-only command to see what's pending/promotable
  in both watchlist_terms (out-of-taxonomy single terms) and
  recurring_themes (recurring valid themes) without re-running analyze.py.
"""

import argparse
import inspect
import re
import sqlite3  # Sieg 25/8 -- needed to catch the new UNIQUE-index IntegrityError (see cmd_create/cmd_promote)
import subprocess
import sys
from datetime import datetime, timezone
from difflib import SequenceMatcher

from pipeline.db import (
    get_connection, init_db, get_signals_for_vertical,
    get_linked_signals_for_opportunity_space, get_all_opportunity_spaces,
    get_latest_scores, upsert_opportunity_space, new_run_id, wipe_opportunity_spaces,
    delete_opportunity_spaces, link_signal_to_opportunity, find_opportunity_space_by_triple,
    next_opportunity_space_label, list_watchlist, list_promotable_themes, mark_theme_promoted,
)
from pipeline.config import CANDIDATES, RECURRING_THEME_PROMOTION_THRESHOLD, CAPABILITY_STATS
from pipeline.analyze import extract_themes
# Sieg 24/8 -- switched to pipeline.theme_promotion (her chosen name,
# signals_discovery.py removed -- nothing else referenced it once this
# import and analyze.py were both switched).
from pipeline.theme_promotion import track_valid_themes
# Sieg 24/8 -- re-wired back in: a teammate's taxonomy-extension mechanism
# (pipeline/extend_taxonomy.py, untouched below), separate from the
# recurring_themes/promote growth path above. watchlist_terms that hit a
# frequency threshold become a `proposals` row; `radar_cli.py review` lets
# the team approve/reject them; an approved term is written to
# taxonomy_extensions.json, which config.py now loads into
# USE_CASES_TAXONOMY/TECHNOLOGIES_TAXONOMY on the next run (loading logic
# added to config.py today too -- see that file). Not touching a single
# line of her file -- just making sure this CLI and config.py actually
# call into it again.
import pipeline.extend_taxonomy as ext


# ---------- create ----------

def cmd_create(conn, wipe=False):
    init_db()  # safe to re-run -- CREATE TABLE IF NOT EXISTS only, no data loss

    if wipe:
        existing_count = conn.execute("SELECT COUNT(*) as c FROM opportunity_spaces").fetchone()["c"]
        if existing_count > 0:
            print(f"--wipe: this will permanently delete {existing_count} existing opportunity space(s), "
                  f"their scores, right-to-win scores, and signal links.")
            print("Signals, watchlist_terms, and recurring_themes are NOT affected.")
            confirm = input('Type "yes" to confirm: ')
            if confirm.strip().lower() == "yes":
                wipe_opportunity_spaces(conn)
                print("Wiped (autoincrement counters reset too).\n")
            else:
                print("Wipe cancelled -- continuing without wiping.\n")
        else:
            print("--wipe: nothing to wipe, already clean.\n")

    run_id = new_run_id()
    print(f"Registering seed opportunity spaces under run_id={run_id}\n")
    for label, vertical, use_case, technology in CANDIDATES:
        # Sieg 25/8 -- bug fix: this used to only WARN on a duplicate triple
        # and then create it anyway -- that's exactly how OS026/OS052 and
        # OS036/OS053 ended up as real duplicates in the delivered summary
        # (same triple, same 43 grounding signals, twice). Now it actually
        # skips the insert, same as promote() already does below -- the
        # "team can decide which to keep" idea still works, but by editing
        # CANDIDATES in config.py, not by silently doubling the DB/summary.
        dup = find_opportunity_space_by_triple(conn, vertical, use_case, technology, exclude_label=label)
        if dup:
            print(f"  SKIPPED {label}: {vertical} x {use_case} x {technology} is already "
                  f"registered as {dup['label']} -- not creating a duplicate OS for the same triple.")
            continue
        try:
            os_id = upsert_opportunity_space(conn, run_id, label, vertical, use_case, technology)
        except sqlite3.IntegrityError:
            # Belt and suspenders: the DB now has a UNIQUE index on
            # (vertical, use_case, technology) (see pipeline/db.py), so even
            # if the check above is ever raced or bypassed, this can no
            # longer silently duplicate -- it just can't insert.
            print(f"  SKIPPED {label}: duplicate triple rejected by the database.")
            continue
        print(f"{label} (id={os_id}): {vertical} x {use_case} x {technology}")


# ---------- delete (targeted, unlike create --wipe which deletes everything) ----------

def cmd_delete(conn, labels):
    """Deletes specific opportunity spaces by label -- e.g. to resolve the
    OS001/OS013/OS024 duplicate without wiping the other 24. Asks for
    confirmation first since this is not undoable (no soft-delete)."""
    print(f"About to permanently delete {len(labels)} opportunity space(s): {', '.join(labels)}")
    print("This also removes their scores, right-to-win scores, and signal links. "
          "Signals themselves are NOT deleted.")
    confirm = input('Type "yes" to confirm: ')
    if confirm.strip().lower() != "yes":
        print("Cancelled -- nothing deleted.")
        return
    deleted = delete_opportunity_spaces(conn, labels)
    not_found = [l for l in labels if l not in deleted]
    if deleted:
        print(f"Deleted: {', '.join(deleted)}")
    if not_found:
        print(f"Not found, skipped: {', '.join(not_found)}")


# ---------- promote (replaces the old JSON-based `discover`) ----------

def cmd_promote(conn):
    """Auto-registers every recurring theme that has hit
    RECURRING_THEME_PROMOTION_THRESHOLD as a new opportunity space. This is
    the growth mechanism for going past config.CANDIDATES' hand-picked
    list -- run this periodically as `radar_cli.py themes` (or
    `python -m pipeline.analyze`) keeps feeding recurring_themes."""
    promotable = list_promotable_themes(conn, RECURRING_THEME_PROMOTION_THRESHOLD)
    if not promotable:
        print(f"Nothing to promote yet (need frequency >= {RECURRING_THEME_PROMOTION_THRESHOLD}). "
              "Run `python -m pipeline.analyze` a few more times as new signals come in, "
              "or lower RECURRING_THEME_PROMOTION_THRESHOLD in pipeline/config.py.")
        return

    run_id = new_run_id()
    promoted_count = 0
    for theme in promotable:
        vertical, use_case, technology = theme["vertical"], theme["use_case"], theme["technology"]

        dup = find_opportunity_space_by_triple(conn, vertical, use_case, technology)
        if dup:
            # Already registered (e.g. via `create`'s CANDIDATES seed) --
            # mark promoted so it stops showing up here, but don't duplicate it.
            print(f"  {vertical} x {use_case} x {technology} already exists as {dup['label']} -- marking promoted, no new OS created.")
            mark_theme_promoted(conn, theme["id"])
            continue

        label = next_opportunity_space_label(conn)
        try:
            os_id = upsert_opportunity_space(conn, run_id, label, vertical, use_case, technology)
        except sqlite3.IntegrityError:
            # Sieg 25/8 -- same belt-and-suspenders as cmd_create: the
            # find_opportunity_space_by_triple() check above already should
            # have caught this, but the new UNIQUE index on
            # (vertical, use_case, technology) in pipeline/db.py is what
            # actually guarantees it can't happen -- mark it promoted so it
            # stops resurfacing here instead of retrying forever.
            print(f"  SKIPPED: {vertical} x {use_case} x {technology} rejected by the database "
                  f"as a duplicate triple -- marking promoted, no new OS created.")
            mark_theme_promoted(conn, theme["id"])
            continue
        mark_theme_promoted(conn, theme["id"])
        promoted_count += 1
        print(f"  PROMOTED {label} (id={os_id}): {vertical} x {use_case} x {technology} "
              f"(recurred {theme['frequency']}x)")

    print(f"\n{promoted_count} new opportunity space(s) promoted. "
          f"Run `python -m pipeline.scoring` to score them.")


# ---------- watchlist (read-only status) ----------

def cmd_watchlist(conn):
    print("=== Out-of-taxonomy terms (watchlist_terms) ===")
    pending = list_watchlist(conn, status="pending")
    proposed = list_watchlist(conn, status="proposed")
    if not pending and not proposed:
        print("  Nothing tracked yet.")
    for t in proposed:
        print(f"  [PROPOSED] [{t['category']}] \"{t['term']}\" -- seen {t['frequency']}x (vertical: {t['vertical']})")
    for t in pending:
        print(f"  [pending]  [{t['category']}] \"{t['term']}\" -- seen {t['frequency']}x (vertical: {t['vertical']})")

    print(f"\n=== Recurring themes (recurring_themes, promotion threshold = {RECURRING_THEME_PROMOTION_THRESHOLD}) ===")
    rows = conn.execute("SELECT * FROM recurring_themes ORDER BY frequency DESC").fetchall()
    if not rows:
        print("  Nothing tracked yet -- run `python -m pipeline.analyze` first.")
    for r in rows:
        status = "[already promoted]" if r["promoted"] else (
            "[PROMOTABLE -- run `radar_cli.py promote`]" if r["frequency"] >= RECURRING_THEME_PROMOTION_THRESHOLD
            else "[accumulating]"
        )
        print(f"  {r['vertical']} x {r['use_case']} x {r['technology']} -- seen {r['frequency']}x {status}")


# ---------- taxonomy proposal review (teammate's mechanism) ----------

def cmd_review(conn):
    """Sieg 24/8 -- re-added: shows pending taxonomy-extension proposals
    (pipeline/extend_taxonomy.py's `proposals` table) and lets the team
    approve/reject them interactively. The JSON file it writes to
    (taxonomy_extensions.json) is now read by config.py on every run (see
    config.py). If the team decides this mechanism should be retired in
    favor of hand-editing config.py's taxonomy lists directly, that's a
    real option too -- but it's a team call, not something to silently
    drop by leaving the CLI command out.

    Sieg 24/8 -- bug fix: run_review() reads the `proposals` table, but
    that table is only ever CREATEd inside run_extend_taxonomy() (her
    module's own __main__ entrypoint) -- if you run `radar_cli.py review`
    before `python -m pipeline.extend_taxonomy` has run at least once,
    review crashed with "no such table: proposals" instead of just saying
    "nothing pending". init_proposals_table() is idempotent (CREATE TABLE
    IF NOT EXISTS) so calling it here every time is free and safe."""
    ext.init_proposals_table(conn)
    ext.run_review(conn)


# ---------- calibrate ----------

def cmd_calibrate(conn):
    print("Raw signal counts by vertical_hint (quick sanity check)")
    for r in conn.execute(
        "SELECT vertical_hint, COUNT(*) as n FROM signals GROUP BY vertical_hint ORDER BY n DESC"
    ):
        print(f"  {r['vertical_hint'] or '(untagged)'}: {r['n']}")
    total = conn.execute("SELECT COUNT(*) as n FROM signals").fetchone()["n"]
    print(f"  TOTAL: {total}")

    # Sieg 23/08 -- rewritten for the link-before-score change. Used to print
    # get_signals_for_vertical() counts (whole vertical) as "what scoring.py
    # sees" -- true before, but scoring.py now scores each OS on its OWN
    # linked signals (get_linked_signals_for_opportunity_space, capped by
    # `link`'s top_n=15 per OS), so a vertical-wide count like "Public Sector:
    # 441 signals" is no longer the right number to base MARKET_SIGNAL_CAP /
    # SOURCE_DIVERSITY_CAP on -- using it would push the caps back up near
    # the pre-fix values and undo the whole point of scoring per OS instead
    # of per vertical (every OS would sit near 0/10 again, since none of
    # them will ever have anywhere close to 441 LINKED signals). Reports
    # per-OS linked counts instead -- run `radar_cli.py link` first, or
    # every OS shows 0 here (not an error, just means link hasn't run yet).
    print("\n=== What scoring.py actually sees per OS, via its linked signals "
          "(use this to set caps -- run `radar_cli.py link` first) ===")
    spaces = get_all_opportunity_spaces(conn)
    print(f"{'OS':<8} {'Vertical':<30} {'Linked signals':<16} {'Distinct sources':<18}")
    print("-" * 75)
    signal_counts, source_counts = [], []
    for os_row in spaces:
        linked = get_linked_signals_for_opportunity_space(conn, os_row["id"])
        distinct_sources = {s["source_name"] for s in linked}
        signal_counts.append(len(linked))
        source_counts.append(len(distinct_sources))
        print(f"{os_row['label']:<8} {os_row['vertical']:<30} {len(linked):<16} {len(distinct_sources):<18}")

    if signal_counts:
        print(f"\nAcross {len(spaces)} OS: signal count min={min(signal_counts)} "
              f"max={max(signal_counts)} avg={sum(signal_counts)/len(signal_counts):.1f}  |  "
              f"distinct sources min={min(source_counts)} max={max(source_counts)} "
              f"avg={sum(source_counts)/len(source_counts):.1f}")
        print("Set MARKET_SIGNAL_CAP near the high end of the linked-signal-count range "
              "(not the average -- a cap at the average would already saturate half the OS "
              "at 10/10) and SOURCE_DIVERSITY_CAP the same way, using distinct sources.")

    # Sieg 23/08 -- new section: `link`'s top_n was an arbitrary, undocumented
    # number (was 15), same issue as the old scoring caps had -- nobody had
    # measured how many signals actually keyword-match an OS before picking
    # a cutoff. This recomputes the SAME keyword-overlap logic cmd_link()
    # uses (_keywords / STOPWORDS, kept identical on purpose so this
    # measures exactly what link would keep/cut, not an approximation of
    # it) but WITHOUT applying the top_n cutoff, so we can see the real
    # pre-cutoff distribution. Reads the CURRENT top_n from cmd_link's own
    # default (inspected below) instead of a second hardcoded number here --
    # otherwise this diagnostic would itself go stale the next time top_n
    # changes, exactly like the thing it's meant to catch.
    current_top_n = inspect.signature(cmd_link).parameters["top_n"].default
    print(f"\n=== Signals with keyword overlap > 0, per OS, BEFORE link's top_n cutoff "
          f"(current top_n={current_top_n}) ===")
    overlap_counts = []
    for os_row in spaces:
        target_keywords = _keywords(f"{os_row['use_case']} {os_row['technology']}")
        vertical_signals = get_signals_for_vertical(conn, os_row["vertical"])
        # Sieg 26/08 -- kept in sync with cmd_link()'s NON_TECH_SOURCES
        # filter, same "identical on purpose" reasoning as this whole
        # diagnostic already follows (see comment above current_top_n).
        vertical_signals = [
            s for s in vertical_signals
            if (s["source_name"] or "").strip().lower() not in NON_TECH_SOURCES
        ]
        matching = sum(
            1 for s in vertical_signals
            if len(target_keywords & _keywords(s["title"] or "")) > 0
        )
        overlap_counts.append(matching)
        flag = f"  <-- exceeds current top_n={current_top_n}, signals ARE being cut" if matching > current_top_n else ""
        print(f"{os_row['label']:<8} {os_row['vertical']:<30} {matching:<16}{flag}")

    if overlap_counts:
        overlap_counts.sort()
        n = len(overlap_counts)
        p50 = overlap_counts[n // 2]
        p90 = overlap_counts[min(n - 1, int(n * 0.9))]
        exceeding = sum(1 for c in overlap_counts if c > current_top_n)
        print(f"\nAcross {n} OS: median={p50}  90th percentile={p90}  max={max(overlap_counts)}  |  "
              f"{exceeding} OS ({exceeding / n * 100:.0f}%) exceed the current top_n={current_top_n} "
              f"and are having relevant signals cut.")
        print("A defensible top_n covers most real OS without keeping near-irrelevant, low-overlap "
              "signals just to hit a round number -- e.g. the 90th percentile above, not a guess.")


# ---------- dedupe ----------

SIMILARITY_THRESHOLD = 0.85  # 0-1, higher = stricter match required


def _normalize_title(title):
    t = title.lower()
    t = re.sub(r"\s*-\s*[a-z0-9 .]+$", "", t)  # strip trailing " - Some Source"
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _find_duplicate_groups(conn):
    signals = conn.execute(
        "SELECT id, source_name, title, collected_at FROM signals ORDER BY collected_at ASC"
    ).fetchall()
    normalized = [(s, _normalize_title(s["title"] or "")) for s in signals]
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


def cmd_dedupe(conn, apply=False):
    groups = _find_duplicate_groups(conn)
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

    if apply:
        total = 0
        for group in groups:
            for dup in group[1:]:
                conn.execute("DELETE FROM signals WHERE id = ?", (dup["id"],))
                conn.execute("DELETE FROM opportunity_signals WHERE signal_id = ?", (dup["id"],))
                total += 1
        conn.commit()
        print(f"Deleted {total} near-duplicate signals.")
        print("\nRe-run `radar_cli.py calibrate`, `python -m pipeline.scoring`, "
              "`radar_cli.py link` and `radar_cli.py summary` to refresh with the cleaned data.")
    else:
        print(f"Total: {total_removable} signals would be removed. Re-run with --apply to actually delete them.")


# ---------- link ----------

STOPWORDS = {"and", "the", "for", "with", "of", "in", "on", "a", "an", "to", "x"}

# Sieg 26/08 -- observed via `radar_cli.py link`'s own printed output: a
# handful of signals get linked purely because a proper noun (a person's
# surname, a place name, a media outlet's own name) happens to collide with
# a keyword shared by a use_case/technology pair -- "Cloud" (Natasha Cloud,
# a WNBA player; St. Cloud, a city), "Excellence" (a generic awards-show
# word). This is a source-level fix, not a keyword-matching fix: an earlier
# attempt at fixing this by requiring 2+ overlapping keywords whenever the
# only shared word is generic was tested against every OS in tonight's
# `link` output and REJECTED -- it gutted genuinely relevant single-
# generic-keyword matches across almost every OS (e.g. OS120 24->0, OS127
# 29->1, OS122 11->2), because many use_case/technology names are
# themselves built from generic words ("Cloud", "Network Modernization"),
# so a real match and a proper-noun collision are lexically indistinguishable
# by keyword count alone. This denylist instead targets the exact
# sports/entertainment/hyper-local source outlets observed producing these
# collisions -- it can only ever REMOVE a signal, never change which
# keywords match, so it carries none of that regression risk. Deliberately
# NOT including "The Citizen" (the source behind one other observed
# collision, a Knysna crime story matching on "network") -- it's a general
# newspaper, not a sports/entertainment outlet, so blanket-excluding it on
# the strength of one bad article risks losing real content later; delete
# that one signal by hand instead if it's still linked before the demo.
# Extend this set if `link`'s output surfaces another offending source.
NON_TECH_SOURCES = {
    "latestly", "yahoo sports", "mix 94.9", "narooma news",
}


def _keywords(text):
    words = re.findall(r"[a-zA-Z]+", text.lower())
    return {w for w in words if len(w) > 2 and w not in STOPWORDS}


# Sieg 23/08 -- top_n raised from 15 to 45, based on real data instead of a
# guess: `radar_cli.py calibrate`'s overlap-before-cutoff diagnostic showed
# median=21, 90th percentile=45, max=93 matching signals per OS across 93
# OS, with 58 OS (62%) already having relevant signals silently cut at the
# old top_n=15. Picked the 90th percentile rather than the max (93) so a
# small number of unusually signal-heavy OS don't force every other OS's
# LLM prompt (evidence_quality/enrichment) to pay for irrelevant, low-
# overlap signals just to cover them -- see EVIDENCE_QUALITY_MAX_SIGNALS /
# ENRICHMENT_SAMPLE_SIZE in scoring.py, which cap the LLM-facing slice
# separately from this for exactly that cost reason.
#
# Sieg 26/08 (2h du matin, veille de la présentation) -- 45 -> 56. La valeur
# de 45 avait été calibrée le 23/08 avec GDELT cassé (rate-limit non
# résolu) et un keyword-matching qui laissait passer du bruit non filtré
# (voir NON_TECH_SOURCES ci-dessus) -- donc calibrée sur MOINS de signaux
# que ce que le pipeline collecte réellement maintenant. Après le fix GDELT
# ("AI"/"EU" trop courts, voir config.py) et le filtre NON_TECH_SOURCES,
# relancé `radar_cli.py calibrate` sur 125 OS réels : le bloc "Signals with
# keyword overlap > 0, per OS, BEFORE link's top_n cutoff" a donné
# median=23, 90th percentile=56, max=117, avec 25 OS (20%) qui se faisaient
# encore couper des signaux pertinents par l'ancien top_n=45. Même logique
# que le 23/08 : 90e percentile, pas le max (117 ferait payer un prompt LLM
# énorme à toutes les OS pour couvrir une poignée de cas extrêmes) ni la
# moyenne (saturerait la moitié des OS à 10/10 sur market_signal_strength).
# Pour reproduire ce calcul sur de nouvelles données :
#   python -m pipeline.ingest
#   python radar_cli.py link
#   python radar_cli.py calibrate > calibrate_output.txt
# -- lire le bloc "Across N OS: median=X 90th percentile=Y max=Z" en bas du
# fichier, prendre le 90th percentile comme nouveau top_n.
# Re-run `calibrate` after any meaningful change in ingest/promote volume --
# this number will go stale the same way the old MARKET_SIGNAL_CAP did.
def cmd_link(conn, top_n=56):
    spaces = get_all_opportunity_spaces(conn)
    for os_row in spaces:
        target_keywords = _keywords(f"{os_row['use_case']} {os_row['technology']}")
        signals = get_signals_for_vertical(conn, os_row["vertical"])
        # Sieg 26/08 -- see NON_TECH_SOURCES above for why this filter exists
        # and why it's source-based rather than a keyword-count change.
        signals = [s for s in signals if (s["source_name"] or "").strip().lower() not in NON_TECH_SOURCES]

        scored = []
        for s in signals:
            overlap = len(target_keywords & _keywords(s["title"] or ""))
            if overlap > 0:
                scored.append((overlap, s))
        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:top_n]
        for _, s in top:
            link_signal_to_opportunity(conn, os_row["id"], s["id"])

        print(f"{os_row['label']} ({os_row['use_case']} x {os_row['technology']}): linked {len(top)} signals")
        for overlap, s in top:
            print(f"  [{overlap} kw match] ({s['source_name']}) {s['title']}")
        if not top:
            print("  -- no keyword overlap found, this OS has no grounded evidence yet")
        print()


# ---------- themes ----------

def cmd_themes(conn, output_path="candidate_opportunity_spaces.md"):
    verticals = [r["vertical_hint"] for r in conn.execute(
        "SELECT DISTINCT vertical_hint FROM signals WHERE vertical_hint IS NOT NULL"
    ).fetchall()]
    already_registered = {
        (r["vertical"], r["use_case"], r["technology"])
        for r in conn.execute("SELECT vertical, use_case, technology FROM opportunity_spaces").fetchall()
    }

    run_id = new_run_id()
    lines = [
        "# Candidate Opportunity Spaces — unfiltered",
        f"_Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} from current signals, "
        f"no pre-selection applied._",
    ]
    for vertical in verticals:
        print(f"Extracting themes for {vertical}...")
        themes, candidates = extract_themes(conn, vertical)
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
            tag = " **[already registered]**" if (vertical, use_case, technology) in already_registered else ""
            lines.append(f"- **{use_case} × {technology}**{tag} ({count} signals)")
            lines.append(f"  {rationale}")
        lines.append("")

        # Track valid themes in-memory (no JSON file) so recurring ones can
        # later be auto-registered with `radar_cli.py promote`.
        if themes:
            track_valid_themes(conn, vertical, themes, run_id=run_id)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\nWritten: {output_path}")
    print("Recurring themes updated -- run `radar_cli.py watchlist` to see what's promotable, "
          "or `radar_cli.py promote` to register anything that's ready.")


# ---------- scores ----------

def cmd_scores(conn):
    rows = get_latest_scores(conn)
    if not rows:
        print("No scored opportunity spaces yet -- run `radar_cli.py create` then `python -m pipeline.scoring`.")
        return
    for r in rows:
        print(f"{r['label']} ({r['vertical']} x {r['use_case']} x {r['technology']})")
        print(f"  Attractiveness: {r['total_score']}/10  "
              f"(strategic_relevance={r['strategic_relevance']}, evidence_quality={r['evidence_quality']})")
        print(f"  Urgency:        {r['urgency_score']}/10")
        print(f"  Right-to-win:   {r['right_to_win_score']}/10  [{r['portfolio_distance']}]  "
              f"assets: {r['matched_assets'] or 'none'}")
        print(f"  -> {r['justification']}")
        print()


# ---------- summary ----------

# Sieg 24/8 -- merged in radar_cli_top_15.py's --top N (that file's ONLY
# genuinely different contribution vs this one -- its cmd_calibrate/cmd_link
# were an older, already-superseded state, not brought over). Original
# rationale kept from that file: summary was dumping every scored OS into
# the client-facing doc; --top N keeps a short pitch from scrolling past
# all of them. None (default) keeps "show everything", for internal use.
def cmd_summary(conn, output_path="opportunity_spaces_summary.md", top_n=None):
    rows = get_latest_scores(conn)
    if not rows:
        print("No scored opportunity spaces yet -- run `radar_cli.py create` then `python -m pipeline.scoring`.")
        return

    if top_n:
        rows = sorted(rows, key=lambda r: r["total_score"], reverse=True)[:top_n]
        print(f"--top {top_n}: keeping the {len(rows)} highest-attractiveness opportunity space(s) "
              f"out of {len(get_latest_scores(conn))} scored.")

    # Sieg 24/8 -- bug fix: get_latest_scores() INNER JOINs on `scores`, so any
    # OS with zero rows there (scoring never ran on it, or was interrupted by
    # a Groq quota before insert_score()) was just missing from this file --
    # no error, no mention, nothing. On the live DB this was 93 total OS vs
    # 63 actually appearing here, a 30-OS gap nobody could see just by reading
    # the summary. Now diffed against get_all_opportunity_spaces() (every OS
    # ever registered) and listed explicitly below instead of vanishing.
    all_spaces = get_all_opportunity_spaces(conn)
    scored_ids = {r["id"] for r in rows}
    unscored = [s for s in all_spaces if s["id"] not in scored_ids]

    lines = [
        "# Innovation Radar — Opportunity Spaces Summary",
        f"_Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_",
        "",
        f"_{len(rows)}/{len(all_spaces)} opportunity spaces scored"
        + (f" -- {len(unscored)} not yet scored, see bottom of file" if unscored else "")
        + "._",
        "",
        "| OS | Attractiveness | Right-to-win | Distance | Urgency |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(f"| {r['label']} | {r['total_score']}/10 | {r['right_to_win_score']}/10 | "
                      f"{r['portfolio_distance']} | {r['urgency_score']}/10 |")
    lines.append("")

    # --- Orange Business at a glance -- previously CAPABILITY_STATS only ever
    # fed the right-to-win LLM prompt and never appeared in this client-facing
    # document at all. Surfaced here once, up front, as shared reference facts
    # rather than repeated inside every single OS section below.
    lines.append("## Orange Business at a glance")
    lines.append("")
    for stat in CAPABILITY_STATS:
        lines.append(f"- **{stat['stat']}** _(source: {stat['source']})_")
    lines.append("")

    for r in rows:
        lines.append(f"## {r['label']} — {r['vertical']} × {r['use_case']} × {r['technology']}")
        lines.append("")
        lines.append(f"**Attractiveness: {r['total_score']}/10**")
        lines.append(f"- Market signal strength: {r['market_signal_strength']}")
        lines.append(f"- Source diversity: {r['source_diversity']}")
        lines.append(f"- Evidence quality: {r['evidence_quality']} — {r['evidence_quality_justification']}")
        lines.append(f"- Novelty / momentum: {r['novelty_momentum']}")
        lines.append(f"- Strategic relevance: {r['strategic_relevance']} — {r['strategic_relevance_justification']}")
        lines.append("")
        lines.append(f"**Urgency: {r['urgency_score']}/10** — deterministic, +2 per regulation/buying_signal "
                      f"signal linked to this OS (is there a real deadline, separate from attractiveness).")
        lines.append("")
        lines.append(f"**Right-to-win: {r['right_to_win_score']}/10 [{r['portfolio_distance']}]**")
        lines.append(f"- Matched assets: {r['matched_assets'] or 'none'}")
        lines.append(f"- {r['justification']}")
        lines.append("")

        signals = conn.execute(
            """SELECT s.source_name, s.title FROM opportunity_signals link
               JOIN signals s ON s.id = link.signal_id
               WHERE link.opportunity_space_id = ?""",
            (r["id"],),
        ).fetchall()
        lines.append(f"**Grounding signals ({len(signals)}):**")
        if signals:
            for s in signals:
                lines.append(f"- [{s['source_name']}] {s['title']}")
        else:
            lines.append("- _none linked yet — run `radar_cli.py link` first_")
        lines.append("")

    # Sieg 24/8 -- see bug-fix comment above: these OS exist in the DB but
    # were previously left out of this file with no trace at all.
    if unscored:
        lines.append("## Not yet scored")
        lines.append("")
        lines.append(f"{len(unscored)} opportunity space(s) have no score yet -- usually an interrupted "
                      f"`python -m pipeline.scoring` run (Groq quota). Run it again (unscored-only mode, "
                      f"safe to re-run) to fill these in before the next `summary`.")
        lines.append("")
        for s in unscored:
            lines.append(f"- {s['label']} — {s['vertical']} × {s['use_case']} × {s['technology']}")
        lines.append("")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"Written: {output_path}")


# ---------- all (runs the full pipeline in one command) ----------

def cmd_all(force=False):
    """Runs the full pipeline end to end, in order -- same steps as
    run_pipeline.ps1, but as a real subcommand so there's nothing extra to
    maintain. Each step is a separate process (mirrors running them by hand),
    and the whole thing stops at the first failure instead of silently
    continuing with stale or partial data."""
    steps = [
        [sys.executable, "-m", "pipeline.db"],
        [sys.executable, "-m", "pipeline.ingest"],
        [sys.executable, "-m", "pipeline.analyze"],
        # Sieg 24/8 -- re-added (was silently missing): generates taxonomy
        # proposals from watchlist_terms that hit the frequency threshold.
        # Non-interactive by design (`review` is the interactive step, run
        # separately, on purpose -- approving a taxonomy change isn't
        # something `all` should ever do unattended).
        [sys.executable, "-m", "pipeline.extend_taxonomy"],
        [sys.executable, __file__, "create"],
        [sys.executable, __file__, "promote"],
        [sys.executable, __file__, "link"],
        [sys.executable, "-m", "pipeline.scoring"] + (["--force"] if force else []),
        [sys.executable, __file__, "summary"],
    ]
    for i, step in enumerate(steps, 1):
        label = " ".join(step[1:])
        print(f"\n{'=' * 60}\nStep {i}/{len(steps)}: {label}\n{'=' * 60}")
        result = subprocess.run(step)
        if result.returncode != 0:
            print(f"\nStep {i} failed (exit code {result.returncode}) -- stopping.")
            sys.exit(result.returncode)
    print("\nDone. See opportunity_spaces_summary.md")


# ---------- dispatch ----------

def main():
    parser = argparse.ArgumentParser(description="Innovation Radar pipeline tools")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("create").add_argument("--wipe", action="store_true")
    p_delete = sub.add_parser("delete")
    p_delete.add_argument("labels", nargs="+", help='OS labels to delete, e.g. "OS001 OS024"')
    sub.add_parser("promote")
    sub.add_parser("watchlist")
    sub.add_parser("calibrate")
    sub.add_parser("dedupe").add_argument("--apply", action="store_true")
    sub.add_parser("link")
    sub.add_parser("themes")
    sub.add_parser("scores")
    # Sieg 24/8 -- --top N merged in from radar_cli_top_15.py (see cmd_summary).
    sub.add_parser("summary").add_argument("--top", type=int, default=None,
        help="keep only the N highest-attractiveness opportunity spaces (default: all)")
    sub.add_parser("all").add_argument("--force", action="store_true")
    # Sieg 24/8 -- re-added: interactive taxonomy-proposal review (see cmd_review).
    sub.add_parser("review")

    args = parser.parse_args()

    if args.command == "all":
        cmd_all(force=args.force)
        return

    conn = get_connection()

    if args.command == "create":
        cmd_create(conn, wipe=args.wipe)
    elif args.command == "delete":
        cmd_delete(conn, args.labels)
    elif args.command == "promote":
        cmd_promote(conn)
    elif args.command == "watchlist":
        cmd_watchlist(conn)
    elif args.command == "calibrate":
        cmd_calibrate(conn)
    elif args.command == "dedupe":
        cmd_dedupe(conn, apply=args.apply)
    elif args.command == "link":
        cmd_link(conn)
    elif args.command == "themes":
        cmd_themes(conn)
    elif args.command == "scores":
        cmd_scores(conn)
    elif args.command == "summary":
        cmd_summary(conn, top_n=args.top)
    elif args.command == "review":
        cmd_review(conn)

    conn.close()


if __name__ == "__main__":
    main()