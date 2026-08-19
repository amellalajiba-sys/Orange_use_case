"""
SQLite schema + helper functions for the Innovation Radar.
Three tables: signals, opportunity_spaces, scores (+ a link table).
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
    label TEXT UNIQUE,              -- e.g. "OS001"
    vertical TEXT NOT NULL,
    use_case TEXT NOT NULL,
    technology TEXT NOT NULL,
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
"""


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    conn.executescript(SCHEMA)
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


def upsert_opportunity_space(conn, label, vertical, use_case, technology):
    """
    Insert a new opportunity space, or refresh an existing one under the same
    label. FIXED 2026-08-19: previously only touched `last_refreshed` on an
    existing label, silently leaving stale vertical/use_case/technology in
    place -- so re-running create_opportunity_spaces.py with fresh themes
    updated the console output but not what was actually stored/scored.
    Now updates all four fields, so a label always reflects the theme it was
    last assigned to.
    """
    now = datetime.now(timezone.utc).isoformat()
    existing = conn.execute(
        "SELECT id FROM opportunity_spaces WHERE label = ?", (label,)
    ).fetchone()
    if existing:
        conn.execute(
            """UPDATE opportunity_spaces
               SET vertical = ?, use_case = ?, technology = ?, last_refreshed = ?
               WHERE id = ?""",
            (vertical, use_case, technology, now, existing["id"]),
        )
        conn.commit()
        return existing["id"]
    cur = conn.execute(
        """INSERT INTO opportunity_spaces (label, vertical, use_case, technology, created_at, last_refreshed)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (label, vertical, use_case, technology, now, now),
    )
    conn.commit()
    return cur.lastrowid


def wipe_opportunity_spaces(conn):
    """
    Deletes every row from opportunity_spaces and everything that references
    it (opportunity_signals, scores, right_to_win_scores). Called by
    create_opportunity_spaces.py before repopulating, so a label (e.g.
    "OS005") can never end up reused for a different Vertical x Use Case x
    Technology while old grounding links / scores from the PREVIOUS theme
    under that same id are still attached -- that silent mismatch is what
    contaminated opportunity_spaces_summary.md's "grounding signals" before
    this existed. Every full re-run (create_opportunity_spaces.py ->
    scoring.py -> link_signals.py -> export_summary.py) now starts clean.
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