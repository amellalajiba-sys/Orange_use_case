"""
SQLite schema + helper functions for the Innovation Radar.
Four tables: signals, opportunity_spaces, scores, right_to_win_scores (+ a
link table opportunity_signals), plus two views for BI tools.

CHANGED 2026-08-19: opportunity_spaces now carries a `run_id` (the UTC
timestamp of the create_opportunity_spaces.py run that produced it) and its
uniqueness constraint moved from UNIQUE(label) to UNIQUE(label, run_id).
Previously, re-running create_opportunity_spaces.py wiped and replaced every
opportunity space -- useful for fixing the "stale label" bug this session,
but it also meant every past run's candidates, scores, and grounding signals
were gone the moment a new run finished. Now every run's opportunity spaces
are kept side by side: labels like "OS001" repeat across runs, but each run
has its own row, its own id, and its own scores/right_to_win_scores/
opportunity_signals attached -- nothing gets overwritten or deleted anymore
just by running the pipeline again.

wipe_opportunity_spaces() still exists as a manual, explicit reset tool (e.g.
if the taxonomy changes completely and old runs are no longer meaningful to
compare against) -- it is simply no longer called automatically.
"""

import sqlite3
from datetime import datetime, timezone
from pipeline.config import DB_PATH

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
    run_id TEXT NOT NULL,           -- UTC isoformat timestamp of the create_opportunity_spaces.py run
    label TEXT NOT NULL,            -- e.g. "OS001" -- repeats across runs, unique only WITHIN a run
    vertical TEXT NOT NULL,
    use_case TEXT NOT NULL,
    technology TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_refreshed TEXT,
    UNIQUE(label, run_id)
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

CREATE TABLE IF NOT EXISTS watchlist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vertical TEXT NOT NULL,
    emerging_use_case TEXT,
    emerging_technology TEXT,
    rationale TEXT,
    supporting_signal_count INTEGER DEFAULT 0,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    frequency INTEGER DEFAULT 1,
    run_id TEXT,
    UNIQUE(vertical, emerging_use_case, emerging_technology)
);
"""


def _create_views(conn):
    """
    Views are recreated unconditionally on every init_db() call (DROP + CREATE,
    not IF NOT EXISTS) -- they hold no data, so there's nothing to lose, and
    this guarantees they always reflect the current column set even after a
    schema change like this one, instead of silently keeping a stale
    definition from before run_id existed.
    """
    conn.executescript("""
        DROP VIEW IF EXISTS latest_scores;
        DROP VIEW IF EXISTS latest_run_scores;

        -- One row per opportunity space EVER created, across every run, with
        -- its latest attractiveness + right-to-win score. Point Power BI /
        -- any external BI tool here for a browsable history of every run.
        -- Use `run_id` to filter/slice by run in your BI tool.
        CREATE VIEW latest_scores AS
        SELECT
            os.id AS opportunity_space_id,
            os.run_id,
            os.label,
            os.vertical,
            os.use_case,
            os.technology,
            os.created_at,
            os.last_refreshed,
            s.total_score AS attractiveness_score,
            s.market_signal_strength,
            s.source_diversity,
            s.evidence_quality,
            s.evidence_quality_justification,
            s.novelty_momentum,
            s.strategic_relevance,
            s.strategic_relevance_justification,
            s.computed_at AS attractiveness_computed_at,
            r.portfolio_distance,
            r.right_to_win_score,
            r.matched_assets,
            r.justification AS right_to_win_justification,
            r.computed_at AS right_to_win_computed_at,
            (SELECT COUNT(*) FROM opportunity_signals link
                WHERE link.opportunity_space_id = os.id) AS grounding_signal_count
        FROM opportunity_spaces os
        JOIN scores s ON s.opportunity_space_id = os.id
            AND s.computed_at = (SELECT MAX(computed_at) FROM scores WHERE opportunity_space_id = os.id)
        JOIN right_to_win_scores r ON r.opportunity_space_id = os.id
            AND r.computed_at = (SELECT MAX(computed_at) FROM right_to_win_scores WHERE opportunity_space_id = os.id);

        -- Same shape as latest_scores, but filtered to ONLY the most recent
        -- run -- this is the one your "Decision" report page should point
        -- to day-to-day, so it behaves exactly like the old single-run
        -- latest_scores did, without you needing to filter by run_id by hand
        -- every time you open the report.
        CREATE VIEW latest_run_scores AS
        SELECT * FROM latest_scores
        WHERE run_id = (SELECT MAX(run_id) FROM opportunity_spaces);
    """)
    conn.commit()


def _migrate_add_run_id(conn):
    """
    One-time migration for databases created before run_id existed. Checks
    whether opportunity_spaces already has a run_id column; if not, rebuilds
    the table with the new schema and copies every existing row across
    (preserving the original `id` values, so scores, right_to_win_scores,
    and opportunity_signals -- which all reference that id -- stay correctly
    linked). Safe to call on every init_db(): it's a no-op once the column
    exists.

    The legacy run_id is set to the MIN(created_at) among the old rows, not
    a literal string like "legacy-run". This matters: run_id is compared
    with plain SQL MAX()/string ordering everywhere (get_latest_run_id(),
    the latest_run_scores view), and an ISO-8601 timestamp string like
    "2026-08-17T09:12:03+00:00" sorts correctly against other ISO
    timestamps -- a hand-picked label like "legacy-run" would NOT (it
    starts with a lowercase letter, which sorts after any digit, so it
    would incorrectly look "newer" than every real run forever).
    """
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(opportunity_spaces)").fetchall()]
    if "run_id" in cols:
        return  # already migrated (or a fresh db that was created with the new schema directly)

    print("[db] Migrating opportunity_spaces to support run history (adding run_id)...")
    legacy_run_id_row = conn.execute("SELECT MIN(created_at) AS ts FROM opportunity_spaces").fetchone()
    legacy_run_id = legacy_run_id_row["ts"] or datetime.now(timezone.utc).isoformat()

    conn.executescript("ALTER TABLE opportunity_spaces RENAME TO opportunity_spaces_old;")
    conn.execute("""
        CREATE TABLE opportunity_spaces (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            label TEXT NOT NULL,
            vertical TEXT NOT NULL,
            use_case TEXT NOT NULL,
            technology TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_refreshed TEXT,
            UNIQUE(label, run_id)
        );
    """)
    conn.execute(
        """INSERT INTO opportunity_spaces (id, run_id, label, vertical, use_case, technology, created_at, last_refreshed)
           SELECT id, ?, label, vertical, use_case, technology, created_at, last_refreshed
           FROM opportunity_spaces_old""",
        (legacy_run_id,),
    )
    conn.execute("DROP TABLE opportunity_spaces_old;")
    conn.commit()
    n = conn.execute("SELECT COUNT(*) AS n FROM opportunity_spaces").fetchone()["n"]
    print(f"[db] Migration complete -- {n} existing opportunity space(s) preserved under run_id='{legacy_run_id}'")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    conn.executescript(SCHEMA)  # CREATE TABLE IF NOT EXISTS only -- never drops/loses data
    _migrate_add_run_id(conn)   # no-op unless upgrading a pre-run_id database
    _create_views(conn)         # always refreshed, holds no data
    conn.commit()
    conn.close()


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
    Signals explicitly tagged with this vertical, PLUS untagged signals
    (vendor blogs, Hacker News -- sources that are cross-cutting by nature
    and never get a vertical_hint at ingest time). Untagged signals count
    as shared evidence across every vertical rather than being invisible.
    """
    query = "SELECT * FROM signals WHERE (vertical_hint = ? OR vertical_hint IS NULL)"
    params = [vertical_hint]
    if since_iso:
        query += " AND collected_at >= ?"
        params.append(since_iso)
    return conn.execute(query, params).fetchall()


def new_run_id():
    """
    Generates a fresh run_id for a new create_opportunity_spaces.py pass --
    just the current UTC timestamp. String-sortable (ISO 8601), so
    `MAX(run_id)` in SQL always finds the most recent run.
    """
    return datetime.now(timezone.utc).isoformat()


def get_latest_run_id(conn):
    """Returns the run_id of the most recent create_opportunity_spaces.py run, or None if none exist yet."""
    row = conn.execute("SELECT MAX(run_id) AS run_id FROM opportunity_spaces").fetchone()
    return row["run_id"] if row else None


def get_opportunity_spaces(conn, run_id=None):
    """
    Opportunity spaces for one run. Defaults to the LATEST run so
    scoring.py / link_signals.py behave exactly as before when called with
    no arguments -- pass an explicit run_id to work with (or compare
    against) an older run instead.
    """
    if run_id is None:
        run_id = get_latest_run_id(conn)
    if run_id is None:
        return []
    return conn.execute(
        "SELECT * FROM opportunity_spaces WHERE run_id = ? ORDER BY label", (run_id,)
    ).fetchall()


def list_runs(conn):
    """
    All distinct run_ids on file, most recent first, with a count of how
    many opportunity spaces each run produced. Handy for a quick console
    check of what history exists before picking a run_id to pass around.
    """
    return conn.execute("""
        SELECT run_id, COUNT(*) AS opportunity_space_count, MIN(created_at) AS run_started_at
        FROM opportunity_spaces
        GROUP BY run_id
        ORDER BY run_id DESC
    """).fetchall()


def insert_opportunity_space(conn, run_id, label, vertical, use_case, technology):
    """
    Inserts a new opportunity space row under the given run_id. Pure insert,
    never an update -- since uniqueness is now (label, run_id) rather than
    just (label), every run gets its own independent set of rows and never
    overwrites a previous run's data. If you call this twice with the same
    (label, run_id) it will raise sqlite3.IntegrityError, which is
    intentional: within a single run, create_opportunity_spaces.py should
    never generate the same label twice.
    """
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        """INSERT INTO opportunity_spaces (run_id, label, vertical, use_case, technology, created_at, last_refreshed)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (run_id, label, vertical, use_case, technology, now, now),
    )
    conn.commit()
    return cur.lastrowid


def wipe_opportunity_spaces(conn):
    """
    MANUAL RESET TOOL -- no longer called automatically by
    create_opportunity_spaces.py. Deletes EVERY run's opportunity spaces and
    everything that references them (opportunity_signals, scores,
    right_to_win_scores), not just the latest one. Use this only when you
    deliberately want to erase all history (e.g. the taxonomy changed so
    fundamentally that old runs are no longer meaningful to compare against).
    For normal use, just re-run create_opportunity_spaces.py -- it now adds a
    new run alongside old ones instead of replacing them.
    """
    conn.execute("DELETE FROM opportunity_signals")
    conn.execute("DELETE FROM scores")
    conn.execute("DELETE FROM right_to_win_scores")
    conn.execute("DELETE FROM opportunity_spaces")
    conn.commit()


def link_signal_to_opportunity(conn, opportunity_space_id, signal_id):
    conn.execute(
        """INSERT OR IGNORE INTO opportunity_signals (opportunity_space_id, signal_id)
           VALUES (?, ?)""",
        (opportunity_space_id, signal_id),
    )
    conn.commit()


def insert_score(conn, opportunity_space_id, sub_scores: dict, total_score: float,
                  evidence_quality_justification=None, strategic_relevance_justification=None):
    conn.execute(
        """INSERT INTO scores
           (opportunity_space_id, market_signal_strength, source_diversity,
            evidence_quality, evidence_quality_justification, novelty_momentum,
            strategic_relevance, strategic_relevance_justification,
            total_score, computed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            opportunity_space_id,
            sub_scores.get("market_signal_strength"),
            sub_scores.get("source_diversity"),
            sub_scores.get("evidence_quality"),
            evidence_quality_justification,
            sub_scores.get("novelty_momentum"),
            sub_scores.get("strategic_relevance"),
            strategic_relevance_justification,
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


if __name__ == "__main__":
    init_db()
    print(f"Database initialized at {DB_PATH}")