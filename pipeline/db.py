"""
SQLite schema + helper functions for the Innovation Radar.
Tables: signals, opportunity_spaces, opportunity_signals (link), scores,
right_to_win_scores, watchlist_terms, recurring_themes.

CHANGES IN THIS REVISION
-------------------------
- get_all_opportunity_spaces(): a teammate's contribution, adopted as-is.
  Scoring used to only ever look at "the latest run_id's" opportunity
  spaces (get_latest_opportunity_spaces). Once opportunity spaces can be
  auto-promoted from recurring_themes over many separate runs (see
  radar_cli.py's `promote` command), "latest run only" stops making sense
  -- you want to score every OS that doesn't have a score yet, regardless
  of which run created it. get_all_opportunity_spaces() is that: no run_id
  filter, just everything.
- wipe_opportunity_spaces() now also resets the SQLITE_SEQUENCE counters
  after deleting -- another teammate's contribution, adopted as-is. Without
  it, a wipe + recreate would jump straight to whatever autoincrement value
  was already reached (e.g. id 47) instead of starting fresh at 1, which is
  confusing when you're trying to start clean for a demo. Wrapped in
  try/except because the sqlite_sequence table itself only exists once at
  least one AUTOINCREMENT table has had a row inserted -- deleting from it
  before that would error.
- recurring_themes: NEW table. 
"""

import sqlite3
from datetime import datetime, timezone
from pipeline.config import DB_PATH, VERTICALS

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_name TEXT NOT NULL,
    source_url TEXT,
    signal_type TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT,
    published_date TEXT,
    collected_at TEXT NOT NULL,
    vertical_hint TEXT,
    UNIQUE(source_url, title)
);

CREATE TABLE IF NOT EXISTS opportunity_spaces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT UNIQUE,              -- e.g. "OS001" -- stays globally unique
    run_id TEXT,                    -- which run registered/last touched this OS
    vertical TEXT NOT NULL,
    use_case TEXT NOT NULL,
    technology TEXT NOT NULL,
    persona TEXT,                   -- see config.ROLES (which Orange Business team owns this)
    buyer_persona TEXT,             -- see config.BUYER_PERSONAS (who the customer-side contact is)
    geography TEXT,                 -- see config.GEOS
    horizon TEXT,                   -- Now / Next / Later, see config.HORIZONS
    domain TEXT,                    -- see config.DOMAINS_TAXONOMY
    next_action TEXT,               -- LLM-generated recommended next step
    created_at TEXT NOT NULL,
    last_refreshed TEXT
);

CREATE TABLE IF NOT EXISTS opportunity_signals (
    opportunity_space_id INTEGER NOT NULL,
    signal_id INTEGER NOT NULL,
    PRIMARY KEY (opportunity_space_id, signal_id),
    FOREIGN KEY (opportunity_space_id) REFERENCES opportunity_spaces(id),
    FOREIGN KEY (signal_id) REFERENCES signals(id)
);

CREATE TABLE IF NOT EXISTS scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    opportunity_space_id INTEGER NOT NULL,
    market_signal_strength REAL,
    source_diversity REAL,
    evidence_quality REAL,
    evidence_quality_justification TEXT,
    novelty_momentum REAL,
    strategic_relevance REAL,
    strategic_relevance_justification TEXT,
    urgency_score REAL,             -- 0-10, time pressure from regulation/buying-signal density
    total_score REAL,
    computed_at TEXT NOT NULL,
    FOREIGN KEY (opportunity_space_id) REFERENCES opportunity_spaces(id)
);

CREATE TABLE IF NOT EXISTS right_to_win_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    opportunity_space_id INTEGER NOT NULL,
    portfolio_distance TEXT,          -- L0 to L4, see config.PORTFOLIO_DISTANCE
    right_to_win_score REAL,          -- 0-10, separate from attractiveness
    matched_assets TEXT,              -- comma-separated Orange Business asset names cited
    justification TEXT,
    computed_at TEXT NOT NULL,
    FOREIGN KEY (opportunity_space_id) REFERENCES opportunity_spaces(id)
);

CREATE TABLE IF NOT EXISTS watchlist_terms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    term TEXT NOT NULL,               -- the candidate use_case or technology name
    category TEXT NOT NULL,           -- 'use_case' or 'technology'
    vertical TEXT,                    -- which vertical it showed up in
    frequency INTEGER NOT NULL DEFAULT 1,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending / proposed / approved / rejected
    UNIQUE(term, category, vertical)
);

-- Tracks VALID (in-taxonomy) Vertical x Use Case x Technology themes across
-- successive analyze.py runs. Once frequency crosses
-- config.RECURRING_THEME_PROMOTION_THRESHOLD, `radar_cli.py promote` turns
-- it into a real opportunity space. See module docstring above for how
-- this differs from watchlist_terms.
CREATE TABLE IF NOT EXISTS recurring_themes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vertical TEXT NOT NULL,
    use_case TEXT,
    technology TEXT,
    rationale TEXT,
    supporting_signal_count INTEGER DEFAULT 0,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    frequency INTEGER DEFAULT 1,
    promoted INTEGER NOT NULL DEFAULT 0,   -- 0/1 -- already turned into an opportunity space?
    run_id TEXT,
    UNIQUE(vertical, use_case, technology)
);

-- Sieg 24/8 -- added to the central SCHEMA to match the diff, which
-- declares this table here too, not only via extend_taxonomy.py's own
-- init_proposals_table() (kept, called from radar_cli.py's cmd_review as a
-- safety net -- both are CREATE TABLE IF NOT EXISTS, so having it in both
-- places is harmless, just belt-and-suspenders: `python -m pipeline.db`
-- alone is now enough to have this table ready, without needing
-- extend_taxonomy.py to have run first).
-- One row per proposed taxonomy term (use_case OR technology, never both),
-- generated by extend_taxonomy.py from a watchlist_terms entry that
-- crossed the frequency threshold. `radar_cli.py review` approves/rejects.
CREATE TABLE IF NOT EXISTS proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vertical TEXT NOT NULL,
    proposed_use_case TEXT,
    proposed_technology TEXT,
    frequency INTEGER NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    reviewed_at TEXT,
    reviewed_by TEXT,
    run_id TEXT,
    UNIQUE(vertical, proposed_use_case, proposed_technology)
);
"""


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# Columns added after the initial schema. CREATE TABLE IF NOT EXISTS does NOT
# add columns to a table that already exists -- this migrates existing
# databases without losing any data.
MIGRATIONS = [
    ("opportunity_spaces", "persona", "TEXT"),
    ("opportunity_spaces", "buyer_persona", "TEXT"),
    ("opportunity_spaces", "geography", "TEXT"),
    ("opportunity_spaces", "horizon", "TEXT"),
    ("opportunity_spaces", "next_action", "TEXT"),
    ("opportunity_spaces", "domain", "TEXT"),
    ("opportunity_spaces", "run_id", "TEXT"),
    ("scores", "urgency_score", "REAL"),
    ("recurring_themes", "promoted", "INTEGER NOT NULL DEFAULT 0"),
    # --- Next action broken out per role (Strategist / Sales / Presales),
    # instead of one generic `next_action` shared by everyone. The old
    # `next_action` column is kept as-is (nothing reads it exclusively
    # anymore, but nothing breaks either -- old rows just show blank on
    # the 3 new columns until rescored).
    ("opportunity_spaces", "next_action_strategist", "TEXT"),
    ("opportunity_spaces", "next_action_sales", "TEXT"),
    ("opportunity_spaces", "next_action_presales", "TEXT"),
]


def migrate_schema(conn):
    for table, column, coltype in MIGRATIONS:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")
        except sqlite3.OperationalError as e:
            if "duplicate column name" not in str(e):
                raise  # anything else is a real problem, don't swallow it
    conn.commit()


def dedupe_opportunity_spaces(conn):
    """Sieg 25/8 -- fix for the OS026/OS052 (and OS036/OS053) duplicate bug:
    cmd_create()'s duplicate check only ever WARNED, it never blocked the
    insert, so the same (vertical, use_case, technology) triple could end up
    registered twice under two different labels. This cleans up any
    duplicates already sitting in the DB: for each triple registered more
    than once, keep the OLDEST row (lowest id = first ever created, so the
    one with the longest signal-linking history) and delete the newer
    duplicate(s) -- including their scores, right-to-win scores, and signal
    links, same as delete_opportunity_spaces() does for a manual delete.
    Safe to call every time init_db() runs: once no duplicates remain, the
    GROUP BY ... HAVING c > 1 below returns nothing and this is a no-op."""
    dup_groups = conn.execute(
        """SELECT vertical, use_case, technology, MIN(id) AS keep_id, COUNT(*) AS c
           FROM opportunity_spaces
           GROUP BY vertical, use_case, technology
           HAVING c > 1"""
    ).fetchall()
    for g in dup_groups:
        losers = conn.execute(
            """SELECT id, label FROM opportunity_spaces
               WHERE vertical = ? AND use_case = ? AND technology = ? AND id != ?""",
            (g["vertical"], g["use_case"], g["technology"], g["keep_id"]),
        ).fetchall()
        for loser in losers:
            print(f"[dedupe_opportunity_spaces] removing duplicate {loser['label']} -- "
                  f"same triple ({g['vertical']} x {g['use_case']} x {g['technology']}) "
                  f"already registered under an earlier OS.")
            conn.execute("DELETE FROM opportunity_signals WHERE opportunity_space_id = ?", (loser["id"],))
            conn.execute("DELETE FROM scores WHERE opportunity_space_id = ?", (loser["id"],))
            conn.execute("DELETE FROM right_to_win_scores WHERE opportunity_space_id = ?", (loser["id"],))
            conn.execute("DELETE FROM opportunity_spaces WHERE id = ?", (loser["id"],))
    conn.commit()


def ensure_opportunity_space_uniqueness(conn):
    """Sieg 25/8 -- the actual root fix, not just the cleanup above: without
    this, duplicate creation was only ever prevented by an application-level
    check-then-insert (find_opportunity_space_by_triple() before upsert),
    which is not race-proof and -- as create()'s warn-only version proved --
    easy to leave non-blocking by mistake. A DB-level UNIQUE index makes a
    duplicate triple impossible to insert at all, no matter which code path
    tries it. Must run AFTER dedupe_opportunity_spaces(), otherwise creating
    the index would fail on the duplicates that still exist."""
    try:
        conn.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_opportunity_spaces_triple
               ON opportunity_spaces (vertical, use_case, technology)"""
        )
        conn.commit()
    except sqlite3.IntegrityError as e:
        # Belt and suspenders: if dedupe somehow missed a pair (e.g. a new
        # duplicate slipped in between dedupe and this call), don't crash
        # init_db() over it -- surface it loudly instead so it gets noticed.
        print(f"[!] Could not enforce opportunity_spaces triple uniqueness -- "
              f"duplicates still present: {e}")


def init_db():
    conn = get_connection()
    conn.executescript(SCHEMA)
    migrate_schema(conn)  # safe no-op on a fresh DB, adds columns on an existing one
    dedupe_opportunity_spaces(conn)  # clean up any pre-existing duplicate triples
    ensure_opportunity_space_uniqueness(conn)  # then make new ones impossible
    conn.commit()
    conn.close()


def new_run_id():
    """A sortable, human-readable run identifier -- generate ONCE per script
    execution and pass the same value to every upsert_opportunity_space()
    call in that run, so they're all grouped together."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# ---------- watchlist_terms: single out-of-taxonomy terms ----------

def add_to_watchlist(conn, term, category, vertical=None):
    """Record a candidate term that didn't fit the closed taxonomy. If it's
    been seen before (same term+category+vertical), bump its frequency
    instead of duplicating -- lets a term cross the promotion threshold
    over time.

    Sieg 24/8 -- defensive guard: `term` is NOT NULL in the schema, but a
    caller passing None (seen in practice: analyze.py's belt-and-suspenders
    fallback, when the LLM returns a field present but explicitly null --
    fixed there too, but this guard means a future caller making the same
    mistake gets a clear message instead of crashing the whole run on a
    sqlite3.IntegrityError deep in a loop."""
    if not term:
        print(f"[add_to_watchlist] skipped -- empty/None term (category={category}, vertical={vertical})")
        return
    now = datetime.now(timezone.utc).isoformat()
    existing = conn.execute(
        "SELECT id, frequency FROM watchlist_terms WHERE term = ? AND category = ? AND vertical IS ?",
        (term, category, vertical),
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE watchlist_terms SET frequency = frequency + 1, last_seen = ? WHERE id = ?",
            (now, existing["id"]),
        )
    else:
        conn.execute(
            """INSERT INTO watchlist_terms (term, category, vertical, frequency, first_seen, last_seen)
               VALUES (?, ?, ?, 1, ?, ?)""",
            (term, category, vertical, now, now),
        )
    conn.commit()


def list_watchlist(conn, min_frequency=None, status="pending"):
    query = "SELECT * FROM watchlist_terms WHERE status = ?"
    params = [status]
    if min_frequency is not None:
        query += " AND frequency >= ?"
        params.append(min_frequency)
    query += " ORDER BY frequency DESC"
    return conn.execute(query, params).fetchall()


def update_watchlist_status(conn, watchlist_id, status):
    """status: 'proposed' / 'approved' / 'rejected'."""
    conn.execute("UPDATE watchlist_terms SET status = ? WHERE id = ?", (status, watchlist_id))
    conn.commit()


# ---------- recurring_themes: valid Vertical x Use Case x Technology combos ----------

def add_or_update_recurring_theme(conn, vertical, use_case, technology, rationale="",
                                   supporting_signal_count=0, run_id=None):
    """Upsert a valid theme extract_themes() found this run. Bumps frequency
    if the exact (vertical, use_case, technology) triple was already seen
    in an earlier run. Returns ('inserted' | 'updated', new_frequency)."""
    now = datetime.now(timezone.utc).isoformat()
    existing = conn.execute(
        "SELECT id, frequency FROM recurring_themes WHERE vertical = ? AND use_case = ? AND technology = ?",
        (vertical, use_case, technology),
    ).fetchone()
    if existing:
        new_freq = existing["frequency"] + 1
        conn.execute(
            """UPDATE recurring_themes
               SET frequency = ?, last_seen = ?, supporting_signal_count = ?, run_id = COALESCE(?, run_id)
               WHERE id = ?""",
            (new_freq, now, supporting_signal_count, run_id, existing["id"]),
        )
        conn.commit()
        return "updated", new_freq
    conn.execute(
        """INSERT INTO recurring_themes
           (vertical, use_case, technology, rationale, supporting_signal_count,
            first_seen, last_seen, frequency, promoted, run_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, 1, 0, ?)""",
        (vertical, use_case, technology, rationale, supporting_signal_count, now, now, run_id),
    )
    conn.commit()
    return "inserted", 1


def list_promotable_themes(conn, min_frequency):
    """Recurring themes that have hit the promotion threshold and haven't
    been promoted to an opportunity space yet."""
    return conn.execute(
        "SELECT * FROM recurring_themes WHERE frequency >= ? AND promoted = 0 ORDER BY frequency DESC",
        (min_frequency,),
    ).fetchall()


def mark_theme_promoted(conn, theme_id):
    conn.execute("UPDATE recurring_themes SET promoted = 1 WHERE id = ?", (theme_id,))
    conn.commit()


# ---------- signals ----------

def insert_signal(conn, source_name, source_url, signal_type, title,
                   summary=None, published_date=None, vertical_hint=None):
    """Insert a signal. Silently skips duplicates (same source_url + title)."""
    try:
        conn.execute(
            """INSERT INTO signals
               (source_name, source_url, signal_type, title, summary,
                published_date, collected_at, vertical_hint)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (source_name, source_url, signal_type, title, summary,
             published_date, datetime.now(timezone.utc).isoformat(), vertical_hint),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False  # duplicate, already collected


def get_signals_for_vertical(conn, vertical_hint, since_iso=None):
    """
    Signals explicitly tagged with this vertical, PLUS:
      - untagged signals (vendor blogs, Hacker News -- cross-cutting by
        nature and never get a vertical_hint at ingest time)
      - signals tagged with a vertical_hint outside config.VERTICALS (e.g. a
        stray manual tag) -- folded in as cross-cutting evidence rather than
        silently invisible to every vertical's scoring.
    """
    unknown_vertical_placeholders = ",".join("?" for _ in VERTICALS)
    query = (
        "SELECT * FROM signals WHERE "
        "(vertical_hint = ? OR vertical_hint IS NULL "
        f"OR vertical_hint NOT IN ({unknown_vertical_placeholders}))"
    )
    params = [vertical_hint] + list(VERTICALS)
    if since_iso:
        query += " AND collected_at >= ?"
        params.append(since_iso)
    return conn.execute(query, params).fetchall()


# Sieg 23/08 -- new function, part of the link-before-score change.
# WHY: scoring.py used to score every OS on get_signals_for_vertical() --
# ALL signals of the whole vertical, identical pool for every OS in that
# vertical. Two different OS in the same vertical (e.g. "Manufacturing x IoT"
# vs "Manufacturing x Computer Vision") ended up with the exact same
# market_signal_strength/source_diversity/novelty_momentum, even though
# they're about different things -- the deterministic sub-scores weren't
# actually OS-specific, just vertical-specific.
# `cmd_link` (radar_cli.py) already computes, independently, which signals
# are actually about a given OS (keyword overlap on use_case/technology vs
# signal title) and stores that in opportunity_signals. This function reads
# that existing link table instead of re-deriving relevance -- so scoring
# now reuses the same "which signals belong to this OS" answer that the
# client-facing summary already shows as evidence, instead of contradicting
# it with a vertical-wide score computed on a different signal set.
def get_linked_signals_for_opportunity_space(conn, opportunity_space_id):
    """All signals already linked to this specific OS via `radar_cli.py link`
    (the opportunity_signals join table). Returns an empty list -- not an
    error -- for an OS that hasn't been linked yet (e.g. `link` was never
    run, or found zero keyword overlap for it): scoring.py's sub-score
    functions already treat "no signals" as a defined case (0.0 or a neutral
    default), same as they always have for a vertical with nothing ingested
    yet, so no new fallback logic was needed here."""
    return conn.execute(
        """SELECT signals.* FROM signals
           JOIN opportunity_signals ON signals.id = opportunity_signals.signal_id
           WHERE opportunity_signals.opportunity_space_id = ?""",
        (opportunity_space_id,),
    ).fetchall()


# ---------- opportunity_spaces ----------

def update_opportunity_space_enrichment(conn, opportunity_space_id, role=None, buyer_persona=None,
                                         geography=None, horizon=None, domain=None, next_action=None,
                                         next_action_strategist=None, next_action_sales=None,
                                         next_action_presales=None):
    """Write the LLM-generated role/buyer_persona/geography/horizon/domain/next_action(s)
    back onto an existing opportunity space. Only overwrites fields that are provided.
    NOTE: `role` is stored in the `persona` column for backward compatibility with
    existing data (rows scored before the ROLES/BUYER_PERSONAS split still have the
    old mixed value there until rescored with --force).
    next_action_strategist/sales/presales are the NEW per-role next actions (one each,
    since different roles need to do different things with the same opportunity space);
    `next_action` itself is kept for backward compat but no longer the main display field."""
    conn.execute(
        """UPDATE opportunity_spaces
           SET persona = COALESCE(?, persona),
               buyer_persona = COALESCE(?, buyer_persona),
               geography = COALESCE(?, geography),
               horizon = COALESCE(?, horizon),
               domain = COALESCE(?, domain),
               next_action = COALESCE(?, next_action),
               next_action_strategist = COALESCE(?, next_action_strategist),
               next_action_sales = COALESCE(?, next_action_sales),
               next_action_presales = COALESCE(?, next_action_presales)
           WHERE id = ?""",
        (role, buyer_persona, geography, horizon, domain, next_action,
         next_action_strategist, next_action_sales, next_action_presales,
         opportunity_space_id),
    )
    conn.commit()


def find_opportunity_space_by_triple(conn, vertical, use_case, technology, exclude_label=None):
    """Returns the existing OS row for this exact (vertical, use_case,
    technology) triple, if any, optionally excluding one label -- used to
    warn about duplicates like OS001/OS013 when creating/promoting new OS
    under a different label. Always parameterized (no string-built SQL)."""
    if exclude_label:
        return conn.execute(
            "SELECT * FROM opportunity_spaces WHERE vertical = ? AND use_case = ? AND technology = ? AND label != ?",
            (vertical, use_case, technology, exclude_label),
        ).fetchone()
    return conn.execute(
        "SELECT * FROM opportunity_spaces WHERE vertical = ? AND use_case = ? AND technology = ?",
        (vertical, use_case, technology),
    ).fetchone()


def next_opportunity_space_label(conn, prefix="OS", width=3):
    """Next free OSxxx label, based on the highest existing numeric suffix
    (not just row count -- stays correct even after a wipe or manual
    deletion left a gap)."""
    rows = conn.execute("SELECT label FROM opportunity_spaces WHERE label LIKE ?", (f"{prefix}%",)).fetchall()
    max_n = 0
    for r in rows:
        suffix = r["label"][len(prefix):]
        if suffix.isdigit():
            max_n = max(max_n, int(suffix))
    return f"{prefix}{max_n + 1:0{width}d}"


def upsert_opportunity_space(conn, run_id, label, vertical, use_case, technology):
    """label stays the unique key (so re-running with the same label always
    updates the same row rather than duplicating it); run_id is stamped on
    every upsert so get_latest_opportunity_spaces() can tell which OS were
    part of the most recent run.

    If vertical/use_case/technology changed under the same label, the old
    persona/geography/horizon/domain/next_action no longer describe this OS
    -- they're cleared here so scoring.py's "skip enrichment if domain is
    already set" check naturally re-triggers real enrichment on the next
    scoring pass, without anyone needing to remember --force."""
    now = datetime.now(timezone.utc).isoformat()
    existing = conn.execute(
        "SELECT id, vertical, use_case, technology FROM opportunity_spaces WHERE label = ?",
        (label,),
    ).fetchone()
    if existing:
        definition_changed = (
            existing["vertical"] != vertical
            or existing["use_case"] != use_case
            or existing["technology"] != technology
        )
        if definition_changed:
            # Sieg 23/08 -- bug fix: this reset was missing the 3 per-role
            # next_action fields (next_action_strategist/sales/presales),
            # added after this function was written. A redefined OS kept
            # showing recommendations written for its OLD vertical/use_case/
            # technology on the dashboard until someone happened to re-run
            # scoring --force. Now reset alongside the rest of the stale
            # enrichment fields, same COALESCE-on-write behavior as before.
            conn.execute(
                """UPDATE opportunity_spaces
                   SET run_id = ?, vertical = ?, use_case = ?, technology = ?, last_refreshed = ?,
                       persona = NULL, buyer_persona = NULL, geography = NULL, horizon = NULL,
                       domain = NULL, next_action = NULL, next_action_strategist = NULL,
                       next_action_sales = NULL, next_action_presales = NULL
                   WHERE id = ?""",
                (run_id, vertical, use_case, technology, now, existing["id"]),
            )
        else:
            conn.execute(
                "UPDATE opportunity_spaces SET run_id = ?, last_refreshed = ? WHERE id = ?",
                (run_id, now, existing["id"]),
            )
        conn.commit()
        return existing["id"]
    cur = conn.execute(
        """INSERT INTO opportunity_spaces
           (label, run_id, vertical, use_case, technology, created_at, last_refreshed)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (label, run_id, vertical, use_case, technology, now, now),
    )
    conn.commit()
    return cur.lastrowid


def get_latest_opportunity_spaces(conn):
    """Returns only the opportunity spaces stamped with the most recent
    run_id. Kept for anything that specifically wants "just this run's
    batch" -- most of the pipeline now uses get_all_opportunity_spaces()
    instead (see module docstring)."""
    latest = conn.execute(
        "SELECT MAX(run_id) as latest FROM opportunity_spaces WHERE run_id IS NOT NULL"
    ).fetchone()["latest"]
    if latest is None:
        return conn.execute("SELECT * FROM opportunity_spaces").fetchall()
    return conn.execute(
        "SELECT * FROM opportunity_spaces WHERE run_id = ?", (latest,)
    ).fetchall()


def get_all_opportunity_spaces(conn):
    """Every opportunity space ever registered, regardless of which run
    created it. Adopted from a teammate's contribution -- see module
    docstring for why this replaced "latest run only" as the default."""
    return conn.execute("SELECT * FROM opportunity_spaces ORDER BY label").fetchall()


def get_unscored_opportunity_spaces(conn):
    """Opportunity spaces with no row in `scores` yet -- what
    pipeline.scoring processes by default now, instead of rescoring
    everything (and re-spending LLM quota) on every run. Inspired by a
    teammate's per-row "already scored?" check, implemented here as one
    query instead of one COUNT(*) per opportunity space."""
    return conn.execute(
        """SELECT * FROM opportunity_spaces
           WHERE id NOT IN (SELECT opportunity_space_id FROM scores)
           ORDER BY label"""
    ).fetchall()


def get_opportunity_spaces_missing_right_to_win(conn):
    """Sieg 23/08 -- new function, bug fix. Opportunity spaces that DO have a
    `scores` row but no `right_to_win_scores` row yet -- i.e. scoring got
    interrupted (Groq quota, crash) between the two insert steps in
    score_all_opportunity_spaces(). These used to be invisible to a default
    (non --force) `python -m pipeline.scoring` run forever, because
    get_unscored_opportunity_spaces() only checks `scores`, not
    `right_to_win_scores` -- so a partially-scored OS was never picked up
    again unless someone noticed and manually ran `--force --from=OSxxx`.
    Kept as a separate query (not folded into get_unscored_opportunity_spaces)
    so the caller can skip the expensive evidence_quality/strategic_relevance
    LLM calls for these OS and only redo the missing right-to-win step."""
    return conn.execute(
        """SELECT * FROM opportunity_spaces
           WHERE id IN (SELECT opportunity_space_id FROM scores)
             AND id NOT IN (SELECT opportunity_space_id FROM right_to_win_scores)
           ORDER BY label"""
    ).fetchall()


def get_opportunity_spaces_with_fallback_scores(conn):
    """Sieg 24/8 -- OS that DO have a `scores` row and a `right_to_win_scores`
    row (so get_unscored_opportunity_spaces / get_opportunity_spaces_missing_
    right_to_win above both consider them "done"), but where the LLM call
    actually failed at the time (Groq quota exhausted) and a neutral
    fallback (evidence_quality/strategic_relevance = 5.0, right_to_win =
    0.0/L4 -- see llm_evidence_quality()/llm_strategic_relevance()/
    llm_right_to_win() in scoring.py) got stored instead of a real judgment.
    These are silently indistinguishable from a genuinely-scored OS unless
    you read the justification text, which is exactly why they went
    unnoticed until now -- found by grepping the fixed "LLM scoring
    unavailable" / "LLM scoring unavailable -- defaulted to L4/0" strings
    those fallback paths always write.
    Written for `scoring.py`'s rescue_fallback_scores(): with the Groq quota
    exhausted, `--force --from=OSxxx` would re-spend quota on every OS from
    that label onward alphabetically, most of which are already fine --
    this targets ONLY the ones that actually need a redo, whenever quota
    is available again (a fresh key, tomorrow's reset, Ollama)."""
    return conn.execute(
        """SELECT os.* FROM opportunity_spaces os
           JOIN scores s ON s.id = (
               SELECT id FROM scores WHERE opportunity_space_id = os.id
               ORDER BY computed_at DESC, id DESC LIMIT 1
           )
           JOIN right_to_win_scores r ON r.id = (
               SELECT id FROM right_to_win_scores WHERE opportunity_space_id = os.id
               ORDER BY computed_at DESC, id DESC LIMIT 1
           )
           WHERE s.evidence_quality_justification LIKE '%unavailable%'
              OR s.strategic_relevance_justification LIKE '%unavailable%'
              OR r.justification LIKE '%unavailable%'
           ORDER BY os.label"""
    ).fetchall()


def get_opportunity_spaces_with_old_scores(conn):
    """Sieg 25/8 -- teammate's contribution, adopted as-is: opportunity
    spaces whose latest score is more than 3 days old. Not currently wired
    into score_all_opportunity_spaces()'s default run (see scoring.py's
    comment at the call site for why) -- kept here as available infra for
    whoever wants to build a scheduled/opt-in staleness refresh later,
    e.g. feeding these into the free `--refresh` (recalibrate_deterministic_
    scores()) instead of a full paid LLM rescore."""
    return conn.execute(
        """SELECT * FROM opportunity_spaces
           WHERE id IN (SELECT opportunity_space_id FROM scores WHERE datetime(computed_at) < datetime('now', '-3 days'))
           ORDER BY label"""
    ).fetchall()


def get_latest_scores(conn):
    """One row per opportunity space: its most recent attractiveness score
    joined with its most recent right-to-win score. Both `scores` and
    `right_to_win_scores` always INSERT a fresh row rather than overwriting
    (audit trail) the first time an OS is scored, so this always picks the
    latest of each per OS.

    Sieg 23/08 -- bug fix: both joins were plain `JOIN` (=INNER JOIN in
    SQLite). scoring.py writes `scores` and `right_to_win_scores` as two
    separate steps for the same OS; if the pipeline is interrupted between
    them (e.g. Groq quota runs out mid-run), that OS has a `scores` row but
    no `right_to_win_scores` row yet -- the INNER JOIN silently drops it
    from every result, so it never appears in the summary or dashboard, with
    no error anywhere. Switched to LEFT JOIN on right_to_win_scores so a
    partially-scored OS still shows up, with NULL right-to-win fields the
    UI/summary can flag ("not yet scored") instead of just vanishing.

    Sieg 25/8 -- bug fix: "latest per OS" used to be `s.computed_at =
    (SELECT MAX(computed_at) ...)`. On Windows, datetime.now()'s clock
    resolution can return the IDENTICAL timestamp string for two inserts
    that happen within the same tick (confirmed: two insert_score() calls
    milliseconds apart in a test both got the same ISO string) -- when that
    happens, MAX(computed_at) ties, the equality join matches BOTH rows
    (old and new score) for that one OS, get_latest_scores() silently
    returns 2 rows instead of 1, and whichever one the caller happens to
    read first can be the STALE one -- exactly what broke `--refresh`
    (recalibrate_deterministic_scores()) in test_score_moves_when_new_
    signals_are_linked: the new total was computed and inserted correctly,
    but the old total kept being read back. Now selects by `id` (AUTOINCREMENT,
    always monotonically increasing, never ties) as the tiebreaker after
    computed_at, via a correlated subquery that returns exactly one row's
    id per OS regardless of timestamp collisions -- ORDER BY ... LIMIT 1
    instead of an equality match on a value that can repeat."""
    return conn.execute("""
        SELECT os.id, os.label, os.vertical, os.use_case, os.technology,
               s.market_signal_strength, s.source_diversity, s.evidence_quality,
               s.evidence_quality_justification, s.novelty_momentum,
               s.strategic_relevance, s.strategic_relevance_justification,
               s.urgency_score, s.total_score,
               r.portfolio_distance, r.right_to_win_score, r.matched_assets, r.justification
        FROM opportunity_spaces os
        JOIN scores s ON s.id = (
            SELECT id FROM scores WHERE opportunity_space_id = os.id
            ORDER BY computed_at DESC, id DESC LIMIT 1
        )
        LEFT JOIN right_to_win_scores r ON r.id = (
            SELECT id FROM right_to_win_scores WHERE opportunity_space_id = os.id
            ORDER BY computed_at DESC, id DESC LIMIT 1
        )
        ORDER BY os.label
    """).fetchall()


def get_scores_ranked_by_persona_vertical(conn, persona=None, vertical=None):
    """Sieg 25/8 -- closes the "Persona + vertical ranking" backend gap from
    current_project_state_overview.md: "The logic for sorting OSs based on
    the persona + vertical combination. Currently, the backend returns all
    OSs without role-specific sorting." That doc suggested either frontend
    sorting (already fine for a demo) OR "a backend endpoint/query that
    accepts persona and vertical parameters and returns a sorted list" --
    this is that query. `persona` here is the OWNING team column
    (opportunity_spaces.persona, i.e. config.ROLES: Strategist/Sales/
    Presales -- who should ACT on this OS), not buyer_persona (who the
    customer-side contact is, already filterable in the dashboard) and not
    the dashboard's top "Role" selector (which is the VIEWER's own role,
    used only to hide L3/L4 opportunities from Presales).

    Same "latest score per OS" join as get_latest_scores() (including the
    Sieg 25/8 timestamp-tie fix -- ORDER BY ... LIMIT 1, not an equality
    match on computed_at), plus the persona/vertical columns and an
    explicit ranking: persona first (groups each team's opportunities
    together), then vertical, then total_score DESC within that group --
    matches how a Strategist or Sales lead would actually want to scan
    the list ("show me MY team's opportunities, best market first").

    Both args optional and independently combinable:
      - persona=None, vertical=None  -> every OS, still ranked this way
      - persona="Sales"              -> only Sales-owned OS, ranked
      - vertical="Manufacturing"     -> only Manufacturing, ranked
      - both                         -> both filters applied together

    Callable directly from Power BI's SQLite connector too (same DB file,
    same query) -- not Streamlit-only."""
    query = """
        SELECT os.id, os.label, os.vertical, os.use_case, os.technology,
               os.persona, os.buyer_persona, os.horizon, os.domain,
               s.total_score, s.urgency_score,
               r.portfolio_distance, r.right_to_win_score
        FROM opportunity_spaces os
        JOIN scores s ON s.id = (
            SELECT id FROM scores WHERE opportunity_space_id = os.id
            ORDER BY computed_at DESC, id DESC LIMIT 1
        )
        LEFT JOIN right_to_win_scores r ON r.id = (
            SELECT id FROM right_to_win_scores WHERE opportunity_space_id = os.id
            ORDER BY computed_at DESC, id DESC LIMIT 1
        )
        WHERE 1=1
    """
    params = []
    if persona:
        query += " AND os.persona = ?"
        params.append(persona)
    if vertical:
        query += " AND os.vertical = ?"
        params.append(vertical)
    # Sieg 25/8 -- persona first (NULLS LAST so unassigned OS sort to the
    # bottom of each vertical group instead of alphabetically ahead of
    # "Presales"/"Sales"/"Strategist"), then vertical, then best score first.
    query += """
        ORDER BY (os.persona IS NULL), os.persona, os.vertical, s.total_score DESC
    """
    return conn.execute(query, params).fetchall()


def link_signal_to_opportunity(conn, opportunity_space_id, signal_id):
    conn.execute(
        """INSERT OR IGNORE INTO opportunity_signals (opportunity_space_id, signal_id)
           VALUES (?, ?)""",
        (opportunity_space_id, signal_id),
    )
    conn.commit()


def insert_score(conn, opportunity_space_id, sub_scores: dict, total_score: float,
                  evidence_quality_justification=None, strategic_relevance_justification=None,
                  urgency_score=None):
    """Sieg 26/08 -- restored Irene's check-then-UPDATE-else-INSERT version
    (team decision with Gaetan/Irene, 28/08 morning), with the bug in its
    right_to_win_scores twin fixed -- see insert_right_to_win_score() below.
    Tradeoff going into this on purpose: this keeps ONE row per OS instead
    of an audit trail of every scoring run (scores/right_to_win_scores no
    longer accumulate rows after repeated --refresh/--recalibrate-*/--force
    runs), which was real (some OS had 30+ rows) -- get_latest_scores()
    still works the same either way, it just has less history to pick from."""
    existing_os = conn.execute(
        "SELECT COUNT(*) FROM scores WHERE opportunity_space_id = ?",
        (opportunity_space_id,)
    ).fetchone()[0]
    if existing_os > 0:
        conn.execute(
            """
            UPDATE scores
            SET
                market_signal_strength = ?,
                source_diversity = ?,
                evidence_quality = ?,
                evidence_quality_justification = ?,
                novelty_momentum = ?,
                strategic_relevance = ?,
                strategic_relevance_justification = ?,
                urgency_score = ?,
                total_score = ?,
                computed_at = ?
            WHERE opportunity_space_id = ?
            """,
            (
                sub_scores.get("market_signal_strength"),
                sub_scores.get("source_diversity"),
                sub_scores.get("evidence_quality"),
                evidence_quality_justification,
                sub_scores.get("novelty_momentum"),
                sub_scores.get("strategic_relevance"),
                strategic_relevance_justification,
                urgency_score,
                total_score,
                datetime.now(timezone.utc).isoformat(),
                opportunity_space_id,
            ),
        )
    else:
        conn.execute(
            """
            INSERT INTO scores
            (
                opportunity_space_id,
                market_signal_strength,
                source_diversity,
                evidence_quality,
                evidence_quality_justification,
                novelty_momentum,
                strategic_relevance,
                strategic_relevance_justification,
                urgency_score,
                total_score,
                computed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                opportunity_space_id,
                sub_scores.get("market_signal_strength"),
                sub_scores.get("source_diversity"),
                sub_scores.get("evidence_quality"),
                evidence_quality_justification,
                sub_scores.get("novelty_momentum"),
                sub_scores.get("strategic_relevance"),
                strategic_relevance_justification,
                urgency_score,
                total_score,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
    conn.commit()


def insert_right_to_win_score(conn, opportunity_space_id, portfolio_distance,
                               right_to_win_score: float, matched_assets, justification):
    """Sieg 26/08 -- restored Irene's check-then-UPDATE-else-INSERT version,
    same team decision as insert_score() above -- BUT with the one real bug
    in her original fixed: her version checked `SELECT COUNT(*) FROM scores`
    to decide UPDATE-vs-INSERT for THIS table (right_to_win_scores). Since a
    `scores` row always exists by the time right-to-win is computed (see
    scoring.py's score_opportunity_space, which calls insert_score() before
    this), that check was always > 0 -- so it took the UPDATE branch even on
    an OS's very FIRST right-to-win score, silently updating 0 rows and
    leaving right_to_win_scores permanently empty for that OS. Fixed by
    checking `right_to_win_scores` itself instead, same table this function
    actually writes to."""
    existing_rtw = conn.execute(
        "SELECT COUNT(*) FROM right_to_win_scores WHERE opportunity_space_id = ?",
        (opportunity_space_id,)
    ).fetchone()[0]
    if existing_rtw > 0:
        conn.execute(
            """
            UPDATE right_to_win_scores
            SET
                portfolio_distance = ?,
                right_to_win_score = ?,
                matched_assets = ?,
                justification = ?,
                computed_at = ?
            WHERE opportunity_space_id = ?
            """,
            (
                portfolio_distance,
                right_to_win_score,
                matched_assets,
                justification,
                datetime.now(timezone.utc).isoformat(),
                opportunity_space_id,
            ),
        )
    else:
        conn.execute(
            """INSERT INTO right_to_win_scores
            (opportunity_space_id, portfolio_distance, right_to_win_score,
                matched_assets, justification, computed_at)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (
                opportunity_space_id,
                portfolio_distance,
                right_to_win_score,
                matched_assets,
                justification,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
    conn.commit()


def delete_opportunity_spaces(conn, labels):
    """Deletes specific opportunity spaces by label, and everything that
    references them (scores, right_to_win_scores, opportunity_signals links).
    Unlike wipe_opportunity_spaces(), this only touches the given labels --
    use this to resolve duplicates like OS001/OS013/OS024 instead of wiping
    the whole table. Labels not found are silently skipped (not an error).
    Returns the list of labels that were actually found and deleted."""
    deleted = []
    for label in labels:
        row = conn.execute(
            "SELECT id FROM opportunity_spaces WHERE label = ?", (label,)
        ).fetchone()
        if not row:
            continue
        os_id = row["id"]
        conn.execute("DELETE FROM opportunity_signals WHERE opportunity_space_id = ?", (os_id,))
        conn.execute("DELETE FROM scores WHERE opportunity_space_id = ?", (os_id,))
        conn.execute("DELETE FROM right_to_win_scores WHERE opportunity_space_id = ?", (os_id,))
        conn.execute("DELETE FROM opportunity_spaces WHERE id = ?", (os_id,))
        deleted.append(label)
    conn.commit()
    return deleted


def wipe_opportunity_spaces(conn):
    """Deletes ALL opportunity spaces and everything that references them
    (scores, right_to_win_scores, opportunity_signals links). NEVER touches
    signals, watchlist_terms, or recurring_themes -- those stay valid
    regardless. Also resets the autoincrement counters (adopted from a
    teammate's contribution) so a fresh `create` after a wipe starts
    labels/ids clean instead of continuing from wherever they left off --
    guarded with try/except since sqlite_sequence only exists once at least
    one AUTOINCREMENT table has a row in it."""
    conn.execute("DELETE FROM opportunity_signals")
    conn.execute("DELETE FROM scores")
    conn.execute("DELETE FROM right_to_win_scores")
    conn.execute("DELETE FROM opportunity_spaces")
    for table in ("opportunity_signals", "scores", "right_to_win_scores", "opportunity_spaces"):
        try:
            conn.execute("DELETE FROM sqlite_sequence WHERE name = ?", (table,))
        except sqlite3.OperationalError:
            pass  # sqlite_sequence doesn't exist yet -- nothing to reset
    conn.commit()


if __name__ == "__main__":
    init_db()
    print(f"Database initialized at {DB_PATH}")