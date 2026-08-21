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
- recurring_themes: NEW table, adapted from a teammate's signals_discovery
  module. Original version created its own table (called `watchlist`),
  read/wrote an emerging_themes.json file as the hand-off from analyze.py,
  and connected to the database directly via `sqlite3.connect("radar.db")`
  instead of this module's get_connection(). We kept the schema and the
  upsert-or-bump-frequency logic (it's good), but:
    1. Dropped the JSON file entirely -- analyze.py now calls
       add_or_update_recurring_theme() directly, in-memory, right after
       extract_themes() returns. One less file to go stale or get lost.
    2. Renamed watchlist -> recurring_themes and repurposed it to track
       VALID (in-taxonomy) themes across runs, not out-of-taxonomy ones --
       watchlist_terms (below) already owns "out-of-taxonomy single term,
       track until it deserves a taxonomy slot". Both tables existing with
       the same job would have been confusing; giving them clearly
       different jobs (single-term taxonomy candidates vs. recurring valid
       Vertical x Use Case x Technology combos worth promoting to a real
       opportunity space) means neither is redundant.
    3. Uses get_connection() like everything else, not a hardcoded path.
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
]


def migrate_schema(conn):
    for table, column, coltype in MIGRATIONS:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")
        except sqlite3.OperationalError as e:
            if "duplicate column name" not in str(e):
                raise  # anything else is a real problem, don't swallow it
    conn.commit()


def init_db():
    conn = get_connection()
    conn.executescript(SCHEMA)
    migrate_schema(conn)  # safe no-op on a fresh DB, adds columns on an existing one
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
    over time."""
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
    """status: 'proposed' (hit the threshold, shown to the team) / 'approved' / 'rejected'."""
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


# ---------- opportunity_spaces ----------

def update_opportunity_space_enrichment(conn, opportunity_space_id, role=None, buyer_persona=None,
                                         geography=None, horizon=None, domain=None, next_action=None):
    """Write the LLM-generated role/buyer_persona/geography/horizon/domain/next_action
    back onto an existing opportunity space. Only overwrites fields that are provided.
    NOTE: `role` is stored in the `persona` column for backward compatibility with
    existing data (rows scored before the ROLES/BUYER_PERSONAS split still have the
    old mixed value there until rescored with --force)."""
    conn.execute(
        """UPDATE opportunity_spaces
           SET persona = COALESCE(?, persona),
               buyer_persona = COALESCE(?, buyer_persona),
               geography = COALESCE(?, geography),
               horizon = COALESCE(?, horizon),
               domain = COALESCE(?, domain),
               next_action = COALESCE(?, next_action)
           WHERE id = ?""",
        (role, buyer_persona, geography, horizon, domain, next_action, opportunity_space_id),
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
            conn.execute(
                """UPDATE opportunity_spaces
                   SET run_id = ?, vertical = ?, use_case = ?, technology = ?, last_refreshed = ?,
                       persona = NULL, buyer_persona = NULL, geography = NULL, horizon = NULL,
                       domain = NULL, next_action = NULL
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


def get_latest_scores(conn):
    """One row per opportunity space: its most recent attractiveness score
    joined with its most recent right-to-win score. Both `scores` and
    `right_to_win_scores` always INSERT a fresh row rather than overwriting
    (audit trail) the first time an OS is scored, so this always picks the
    latest of each per OS."""
    return conn.execute("""
        SELECT os.id, os.label, os.vertical, os.use_case, os.technology,
               s.market_signal_strength, s.source_diversity, s.evidence_quality,
               s.evidence_quality_justification, s.novelty_momentum,
               s.strategic_relevance, s.strategic_relevance_justification,
               s.urgency_score, s.total_score,
               r.portfolio_distance, r.right_to_win_score, r.matched_assets, r.justification
        FROM opportunity_spaces os
        JOIN scores s ON s.opportunity_space_id = os.id
            AND s.computed_at = (SELECT MAX(computed_at) FROM scores WHERE opportunity_space_id = os.id)
        JOIN right_to_win_scores r ON r.opportunity_space_id = os.id
            AND r.computed_at = (SELECT MAX(computed_at) FROM right_to_win_scores WHERE opportunity_space_id = os.id)
        ORDER BY os.label
    """).fetchall()


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
    conn.execute(
        """INSERT INTO scores
           (opportunity_space_id, market_signal_strength, source_diversity,
            evidence_quality, evidence_quality_justification, novelty_momentum,
            strategic_relevance, strategic_relevance_justification, urgency_score,
            total_score, computed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                               right_to_win_score, matched_assets, justification):
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