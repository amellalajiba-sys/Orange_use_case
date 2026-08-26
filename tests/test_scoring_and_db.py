"""
Regression tests for the bugs fixed on 23/08:

1. scoring.novelty_momentum() -- used to measure recency against the END OF
   ITS OWN SAMPLE, not against today, so a burst of old signals and the same
   signals spread out evenly scored identically. Fixed to measure against
   datetime.now(), and to parse dates defensively instead of crashing on a
   malformed collected_at.

2. db.get_latest_scores() -- used an INNER JOIN against right_to_win_scores,
   so an opportunity space with an attractiveness score but no right-to-win
   score yet (e.g. scoring interrupted by a Groq quota error) silently
   disappeared from every result. Fixed to LEFT JOIN.

3. db.delete_opportunity_spaces() -- targeted delete (as opposed to
   wipe_opportunity_spaces(), which deletes everything). Used to resolve the
   OS001/OS013/OS024 duplicate. Checked here for basic correctness: it
   removes exactly the requested labels and nothing else, and cleans up the
   rows that reference them (scores, right_to_win_scores, opportunity_signals)
   so no orphaned rows are left behind.

Sieg 24/8 -- added a second batch of tests covering everything built since
23/08 (see class docstrings below for what each one checks):

4. scoring.compute_urgency_scaling_point() / _urgency_weighted() -- the
   dynamic 95th-percentile urgency scaling point that replaced the fixed
   URGENCY_CAP, including the small-sample percentile-extrapolation bug
   found while building it (a naive percentile returned a value HIGHER
   than the actual maximum in the data).
5. scoring._urgency_weighted()'s novelty contribution -- novelty_momentum()
   folded into urgency too (team decision, 24/8), with the >=3-signal guard
   that stops novelty_momentum()'s own neutral 5.0 fallback from leaking a
   fake boost into small OS.
6. scoring.recalibrate_deterministic_scores() (`--refresh`) -- the
   "Refresh Logic for already existing OSs" gap: recomputes the 4
   deterministic sub-scores against an OS's CURRENT linked signals,
   without touching the LLM-based ones, without any LLM call.
7. db.add_to_watchlist()'s None-term guard -- the crash seen in practice
   (`sqlite3.IntegrityError: NOT NULL constraint failed`) when the LLM
   fallback (Ollama) returns a field present but explicitly null.

Run with:
    pip install pytest --break-system-packages   # if not already installed
    pytest tests/test_scoring_and_db.py -v

Run from the project root (the same folder as radar_cli.py) so the
`pipeline.*` imports resolve correctly.
"""

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from pipeline.scoring import (
    novelty_momentum, _urgency_weighted, urgency_score,
    compute_urgency_scaling_point, recalibrate_deterministic_scores,
    URGENCY_CAP, NOVELTY_URGENCY_WEIGHT,
)
from pipeline.db import (
    SCHEMA, get_latest_scores, delete_opportunity_spaces,
    get_unscored_opportunity_spaces, get_opportunity_spaces_missing_right_to_win,
    add_to_watchlist, insert_signal, link_signal_to_opportunity,
    get_linked_signals_for_opportunity_space,
)


# ---------- helpers ----------

def _signal(days_ago, now):
    """Builds one fake signal dict with a collected_at timestamp `days_ago`
    days before `now`. novelty_momentum() only reads this one field."""
    return {"collected_at": (now - timedelta(days=days_ago)).isoformat()}


@pytest.fixture
def db_conn():
    """In-memory SQLite database with the real schema, so get_latest_scores()
    and delete_opportunity_spaces() run against the actual table structure
    instead of a hand-rolled stand-in."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    yield conn
    conn.close()


def _insert_opportunity_space(conn, label, vertical="Manufacturing",
                               use_case="Energy Optimization", technology="IoT Platforms"):
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        "INSERT INTO opportunity_spaces (label, run_id, vertical, use_case, technology, created_at) "
        "VALUES (?, 'test-run', ?, ?, ?, ?)",
        (label, vertical, use_case, technology, now),
    )
    conn.commit()
    return cur.lastrowid


def _insert_score(conn, os_id, total_score=7.0):
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO scores (opportunity_space_id, market_signal_strength, source_diversity, "
        "evidence_quality, novelty_momentum, strategic_relevance, urgency_score, total_score, computed_at) "
        "VALUES (?, 5, 5, 5, 5, 5, 5, ?, ?)",
        (os_id, total_score, now),
    )
    conn.commit()


def _insert_right_to_win(conn, os_id, right_to_win_score=6.0):
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO right_to_win_scores (opportunity_space_id, portfolio_distance, "
        "right_to_win_score, matched_assets, justification, computed_at) "
        "VALUES (?, 'L1', ?, 'API X', 'test', ?)",
        (os_id, right_to_win_score, now),
    )
    conn.commit()


# ---------- 1. novelty_momentum() ----------

class TestNoveltyMomentum:

    def test_empty_signals_returns_zero(self):
        assert novelty_momentum([]) == 0.0

    def test_fewer_than_three_signals_returns_neutral(self):
        now = datetime.now(timezone.utc)
        signals = [_signal(1, now), _signal(2, now)]
        assert novelty_momentum(signals) == 5.0

    def test_recent_burst_scores_higher_than_even_spread(self):
        """The core bug: a burst of signals close to today must score
        noticeably higher than the same count spread evenly over the same
        observed window (both windows start at the same 'oldest' date so the
        comparison is fair)."""
        now = datetime.now(timezone.utc)
        spread_even = [_signal(d, now) for d in (90, 80, 70, 60, 50, 40, 30, 20, 10, 5, 2, 1)]
        burst_recent = [_signal(d, now) for d in (90, 3, 2, 2, 1, 1, 1, 1, 1, 1, 1, 1)]

        spread_score = novelty_momentum(spread_even)
        burst_score = novelty_momentum(burst_recent)

        assert burst_score > spread_score

    def test_all_signals_stale_scores_low(self):
        """Nothing recent at all -- momentum should be near zero, not the
        old count-based ~3.33 artifact."""
        now = datetime.now(timezone.utc)
        stale = [_signal(d, now) for d in (200, 201, 202, 203, 204, 205)]
        assert novelty_momentum(stale) < 2.0

    def test_malformed_date_is_skipped_not_fatal(self):
        """A single bad collected_at value (bad data, not a code bug) must
        not crash the whole scoring run."""
        now = datetime.now(timezone.utc)
        signals = [
            _signal(1, now), _signal(2, now), _signal(3, now),
            {"collected_at": "not-a-real-date"},
            {"collected_at": None},
        ]
        # Should not raise -- and should still compute from the 3 good dates.
        result = novelty_momentum(signals)
        assert isinstance(result, float)

    def test_clock_skew_returns_neutral(self):
        """Oldest signal somehow in the future (bad clock somewhere) -- must
        not raise a ZeroDivisionError or return a negative score."""
        now = datetime.now(timezone.utc)
        future_signals = [_signal(-5, now), _signal(-4, now), _signal(-3, now)]
        assert novelty_momentum(future_signals) == 5.0


# ---------- 2. get_latest_scores() LEFT JOIN ----------

class TestGetLatestScores:

    def test_fully_scored_os_appears_with_both_scores(self, db_conn):
        os_id = _insert_opportunity_space(db_conn, "OS001")
        _insert_score(db_conn, os_id, total_score=7.5)
        _insert_right_to_win(db_conn, os_id, right_to_win_score=6.5)

        rows = get_latest_scores(db_conn)

        assert len(rows) == 1
        assert rows[0]["label"] == "OS001"
        assert rows[0]["total_score"] == 7.5
        assert rows[0]["right_to_win_score"] == 6.5

    def test_partially_scored_os_still_appears(self, db_conn):
        """The actual bug: an OS with only an attractiveness score (scoring
        interrupted before right-to-win ran) used to vanish entirely under
        the old INNER JOIN. It must now still show up, with right_to_win
        fields as None."""
        os_id = _insert_opportunity_space(db_conn, "OS002")
        _insert_score(db_conn, os_id, total_score=8.0)
        # deliberately no _insert_right_to_win() call

        rows = get_latest_scores(db_conn)

        assert len(rows) == 1
        assert rows[0]["label"] == "OS002"
        assert rows[0]["total_score"] == 8.0
        assert rows[0]["right_to_win_score"] is None

    def test_mix_of_fully_and_partially_scored(self, db_conn):
        full_id = _insert_opportunity_space(db_conn, "OS003")
        _insert_score(db_conn, full_id, total_score=6.0)
        _insert_right_to_win(db_conn, full_id, right_to_win_score=4.0)

        partial_id = _insert_opportunity_space(db_conn, "OS004")
        _insert_score(db_conn, partial_id, total_score=9.0)

        rows = {r["label"]: r for r in get_latest_scores(db_conn)}

        assert set(rows.keys()) == {"OS003", "OS004"}
        assert rows["OS004"]["right_to_win_score"] is None

    def test_unscored_os_does_not_appear(self, db_conn):
        """An OS with no scores row at all is correctly still excluded --
        the fix only widens the right_to_win_scores join, the scores join
        stays a normal (inner) JOIN."""
        _insert_opportunity_space(db_conn, "OS005")

        rows = get_latest_scores(db_conn)

        assert rows == []


# ---------- 3. delete_opportunity_spaces() ----------

class TestDeleteOpportunitySpaces:

    def test_deletes_only_requested_labels(self, db_conn):
        keep_id = _insert_opportunity_space(db_conn, "OS013")
        drop1_id = _insert_opportunity_space(db_conn, "OS001")
        drop2_id = _insert_opportunity_space(db_conn, "OS024")
        for os_id in (keep_id, drop1_id, drop2_id):
            _insert_score(db_conn, os_id)
            _insert_right_to_win(db_conn, os_id)

        deleted = delete_opportunity_spaces(db_conn, ["OS001", "OS024"])

        assert set(deleted) == {"OS001", "OS024"}
        remaining = [r["label"] for r in db_conn.execute("SELECT label FROM opportunity_spaces")]
        assert remaining == ["OS013"]

    def test_cleans_up_referencing_rows(self, db_conn):
        os_id = _insert_opportunity_space(db_conn, "OS006")
        _insert_score(db_conn, os_id)
        _insert_right_to_win(db_conn, os_id)

        delete_opportunity_spaces(db_conn, ["OS006"])

        assert db_conn.execute("SELECT COUNT(*) c FROM scores WHERE opportunity_space_id = ?",
                                (os_id,)).fetchone()["c"] == 0
        assert db_conn.execute("SELECT COUNT(*) c FROM right_to_win_scores WHERE opportunity_space_id = ?",
                                (os_id,)).fetchone()["c"] == 0

    def test_unknown_label_is_silently_skipped(self, db_conn):
        _insert_opportunity_space(db_conn, "OS007")

        deleted = delete_opportunity_spaces(db_conn, ["OS999"])

        assert deleted == []
        remaining = [r["label"] for r in db_conn.execute("SELECT label FROM opportunity_spaces")]
        assert remaining == ["OS007"]


# ---------- 4. get_opportunity_spaces_missing_right_to_win() ----------
# Sieg 23/08 -- regression test for the "stuck after interrupted run" bug:
# an OS with a scores row but no right_to_win_scores row (Groq quota ran out
# between the two insert steps) used to be permanently invisible to
# get_unscored_opportunity_spaces(), so a normal (non --force) re-run never
# repaired it.

class TestGetOpportunitySpacesMissingRightToWin:

    def test_fully_scored_os_is_not_flagged(self, db_conn):
        os_id = _insert_opportunity_space(db_conn, "OS001")
        _insert_score(db_conn, os_id)
        _insert_right_to_win(db_conn, os_id)

        assert get_opportunity_spaces_missing_right_to_win(db_conn) == []

    def test_unscored_os_is_not_flagged_either(self, db_conn):
        """No scores row at all -- that's get_unscored_opportunity_spaces()'s
        job, not this function's."""
        _insert_opportunity_space(db_conn, "OS002")

        assert get_opportunity_spaces_missing_right_to_win(db_conn) == []

    def test_partially_scored_os_is_flagged(self, db_conn):
        os_id = _insert_opportunity_space(db_conn, "OS003")
        _insert_score(db_conn, os_id)
        # no _insert_right_to_win() call -- this is the interrupted-run case

        flagged = get_opportunity_spaces_missing_right_to_win(db_conn)

        assert len(flagged) == 1
        assert flagged[0]["label"] == "OS003"

    def test_unscored_and_partially_scored_are_mutually_exclusive(self, db_conn):
        """Every OS must show up in exactly one of the two "needs work"
        lists, never both and never neither (unless it's fully done)."""
        unscored_id = _insert_opportunity_space(db_conn, "OS004")
        partial_id = _insert_opportunity_space(db_conn, "OS005")
        _insert_score(db_conn, partial_id)
        done_id = _insert_opportunity_space(db_conn, "OS006")
        _insert_score(db_conn, done_id)
        _insert_right_to_win(db_conn, done_id)

        unscored_labels = {r["label"] for r in get_unscored_opportunity_spaces(db_conn)}
        partial_labels = {r["label"] for r in get_opportunity_spaces_missing_right_to_win(db_conn)}

        assert unscored_labels == {"OS004"}
        assert partial_labels == {"OS005"}
        assert unscored_labels & partial_labels == set()  # no overlap
        assert "OS006" not in unscored_labels and "OS006" not in partial_labels


# ---------- helpers for the new tests below ----------

def _signal_row(days_ago, now, signal_type="market_move"):
    """Like _signal() above but with a real signal_type -- the earlier
    helper only ever produces a bare {"collected_at": ...} dict, which is
    fine for novelty_momentum() alone but not enough for _urgency_weighted()
    (needs "signal_type" to decide regulation/buying_signal/other)."""
    return {
        "signal_type": signal_type,
        "collected_at": (now - timedelta(days=days_ago)).isoformat(),
    }


def _insert_and_link_signal(conn, os_id, url, signal_type, days_ago, now):
    """Real DB round-trip version of _signal_row() -- inserts an actual row
    in `signals` and links it to the OS, for tests that go through
    get_linked_signals_for_opportunity_space() rather than hand-built dicts."""
    published = (now - timedelta(days=days_ago)).isoformat()
    insert_signal(conn, source_name="Test Source", source_url=url, signal_type=signal_type,
                  title="t", summary=None, published_date=published, vertical_hint="Manufacturing")
    row = conn.execute("SELECT id FROM signals WHERE source_url = ?", (url,)).fetchone()
    link_signal_to_opportunity(conn, os_id, row["id"])


# ---------- 4. compute_urgency_scaling_point() / _urgency_weighted() ----------

class TestUrgencyScalingPoint:

    def test_regulation_signal_contributes_full_weight(self):
        signals = [{"signal_type": "regulation", "collected_at": datetime.now(timezone.utc).isoformat()}]
        assert _urgency_weighted(signals) == 1.0

    def test_non_urgent_signal_type_contributes_nothing(self):
        signals = [_signal_row(1, datetime.now(timezone.utc), signal_type="market_move")]
        # only 1 signal -- below the novelty guard too, so this must be exactly 0.0
        assert _urgency_weighted(signals) == 0.0

    def test_scaling_point_never_exceeds_the_real_maximum(self, db_conn):
        """The actual bug found while building this: statistics.quantiles'
        default ('exclusive') interpolation extrapolates PAST the highest
        real value for small samples -- a 4-point batch [1,2,3,10] returned
        a "95th percentile" of 15.25, higher than anything actually
        observed. Fixed with method="inclusive" + a hard clamp; this test
        pins that fix so a future refactor can't silently reintroduce it."""
        now = datetime.now(timezone.utc)
        for i, n_regs in enumerate([0, 1, 2, 3, 10]):
            os_id = _insert_opportunity_space(db_conn, f"OS{i:03d}")
            for j in range(n_regs):
                _insert_and_link_signal(db_conn, os_id, f"http://x/{i}/{j}", "regulation", 1, now)
            _insert_score(db_conn, os_id)
        db_conn.commit()

        scaling_point = compute_urgency_scaling_point(db_conn)

        assert scaling_point <= 10.0, "scaling point must never exceed the real observed maximum"

    def test_scaling_point_falls_back_to_static_cap_when_population_is_flat(self, db_conn):
        """Every OS at 0 urgent signals -- must not divide by ~0 or crash,
        must fall back to the documented static URGENCY_CAP."""
        os_id = _insert_opportunity_space(db_conn, "OS001")
        _insert_score(db_conn, os_id)
        db_conn.commit()

        assert compute_urgency_scaling_point(db_conn) == URGENCY_CAP

    def test_higher_weighted_signals_score_higher_urgency_at_a_fixed_scaling_point(self):
        now = datetime.now(timezone.utc)
        few = [{"signal_type": "regulation", "collected_at": now.isoformat()}]
        many = [{"signal_type": "regulation", "collected_at": now.isoformat()} for _ in range(5)]

        assert urgency_score(many, scaling_point=6.0) > urgency_score(few, scaling_point=6.0)

    def test_urgency_score_is_capped_at_ten(self):
        now = datetime.now(timezone.utc)
        way_more_than_scaling_point = [
            {"signal_type": "regulation", "collected_at": now.isoformat()} for _ in range(50)
        ]
        assert urgency_score(way_more_than_scaling_point, scaling_point=6.0) == 10.0


# ---------- 5. novelty folded into urgency (team decision, 24/8) ----------

class TestNoveltyInUrgency:

    def test_trending_os_scores_higher_urgency_than_flat_os_with_same_signal_count(self, db_conn):
        """The actual scenario tested manually before shipping this: same
        number of signals, same signal type (no regulation/buying_signal at
        all), but one OS's signals are bunched near today (trending) and
        the other's are spread evenly (flat). Trending must score higher."""
        now = datetime.now(timezone.utc)
        trending_id = _insert_opportunity_space(db_conn, "OS_TRENDING")
        for i, age in enumerate([90, 5, 3, 2, 1]):
            _insert_and_link_signal(db_conn, trending_id, f"http://t/{i}", "market_move", age, now)

        flat_id = _insert_opportunity_space(db_conn, "OS_FLAT")
        for i, age in enumerate([90, 72, 54, 36, 18]):
            _insert_and_link_signal(db_conn, flat_id, f"http://f/{i}", "market_move", age, now)
        db_conn.commit()

        trending_signals = get_linked_signals_for_opportunity_space(db_conn, trending_id)
        flat_signals = get_linked_signals_for_opportunity_space(db_conn, flat_id)

        assert _urgency_weighted(trending_signals) > _urgency_weighted(flat_signals)

    def test_novelty_contribution_requires_at_least_three_signals(self, db_conn):
        """The guard that stops novelty_momentum()'s own neutral 5.0
        fallback (returned below ITS 3-signal threshold) from injecting a
        fake, identical urgency boost into every small/sparse OS."""
        now = datetime.now(timezone.utc)
        os_id = _insert_opportunity_space(db_conn, "OS_SMALL")
        for i, age in enumerate([5, 1]):  # only 2 signals -- below the guard
            _insert_and_link_signal(db_conn, os_id, f"http://s/{i}", "market_move", age, now)
        db_conn.commit()

        signals = get_linked_signals_for_opportunity_space(db_conn, os_id)

        assert _urgency_weighted(signals) == 0.0, (
            "2 non-urgent signals must contribute exactly 0 -- the novelty "
            "term must not fire below the 3-signal guard"
        )

    def test_novelty_and_regulation_contributions_add_up(self, db_conn):
        """A signal set with both a regulation hit AND a genuine recent
        burst (not just non-urgent filler) should score higher than the
        same regulation hit with flat/evenly-spread filler -- confirms the
        two contributions are additive, not one overriding the other.
        Reuses the exact bursty-vs-flat date pattern validated manually
        before this was shipped (8.0/10 vs 2.0/10 novelty_momentum)."""
        now = datetime.now(timezone.utc)
        reg_plus_burst_id = _insert_opportunity_space(db_conn, "OS_REG_BURST")
        _insert_and_link_signal(db_conn, reg_plus_burst_id, "http://rb/reg", "regulation", 1, now)
        for i, age in enumerate([90, 5, 3, 2, 1]):
            _insert_and_link_signal(db_conn, reg_plus_burst_id, f"http://rb/{i}", "market_move", age, now)

        reg_plus_flat_id = _insert_opportunity_space(db_conn, "OS_REG_FLAT")
        _insert_and_link_signal(db_conn, reg_plus_flat_id, "http://rf/reg", "regulation", 1, now)
        for i, age in enumerate([90, 72, 54, 36, 18]):
            _insert_and_link_signal(db_conn, reg_plus_flat_id, f"http://rf/{i}", "market_move", age, now)
        db_conn.commit()

        burst_signals = get_linked_signals_for_opportunity_space(db_conn, reg_plus_burst_id)
        flat_signals = get_linked_signals_for_opportunity_space(db_conn, reg_plus_flat_id)

        assert _urgency_weighted(burst_signals) > _urgency_weighted(flat_signals)


# ---------- 6. recalibrate_deterministic_scores() (`--refresh`) ----------

class TestRefreshDeterministicScores:

    def test_score_moves_when_new_signals_are_linked(self, db_conn):
        """The exact scenario from current_project_state_overview.md's
        "Refresh Logic for already existing OSs" gap: OS scored Monday with
        few signals, more arrive (get linked) later, --refresh must move
        the total -- before this existed, the score stayed frozen until a
        full --force re-score."""
        now = datetime.now(timezone.utc)
        os_id = _insert_opportunity_space(db_conn, "OS001")
        for i in range(3):
            _insert_and_link_signal(db_conn, os_id, f"http://r/{i}", "market_move", 1, now)
        _insert_score(db_conn, os_id, total_score=5.9)
        db_conn.commit()
        before = get_latest_scores(db_conn)[0]

        for i in range(3, 53):  # 50 more signals arrive
            _insert_and_link_signal(db_conn, os_id, f"http://r/{i}", "market_move", 1, now)
        db_conn.commit()

        recalibrate_deterministic_scores(db_conn)

        after = get_latest_scores(db_conn)[0]
        assert after["total_score"] != before["total_score"]

    def test_llm_fields_are_never_touched(self, db_conn):
        """The other half of the same guarantee: evidence_quality and
        strategic_relevance (the expensive, LLM-based half of the score)
        must survive --refresh completely unchanged -- that's what makes
        it free in Groq quota terms."""
        now = datetime.now(timezone.utc)
        os_id = _insert_opportunity_space(db_conn, "OS002")
        for i in range(3):
            _insert_and_link_signal(db_conn, os_id, f"http://l/{i}", "market_move", 1, now)
        _insert_score(db_conn, os_id)
        db_conn.commit()
        before = get_latest_scores(db_conn)[0]

        recalibrate_deterministic_scores(db_conn)

        after = get_latest_scores(db_conn)[0]
        assert after["evidence_quality"] == before["evidence_quality"]
        assert after["strategic_relevance"] == before["strategic_relevance"]

    def test_no_scored_os_is_a_no_op_not_a_crash(self, db_conn):
        """Nothing in `scores` yet -- must print a message and return
        cleanly, not raise (e.g. on an empty/fresh database)."""
        recalibrate_deterministic_scores(db_conn)  # must not raise

    def test_inserts_a_new_row_rather_than_overwriting(self, db_conn):
        """Respects the project's own "always INSERT, never UPDATE" audit-
        trail rule -- refreshing must not shrink the history."""
        now = datetime.now(timezone.utc)
        os_id = _insert_opportunity_space(db_conn, "OS003")
        for i in range(3):
            _insert_and_link_signal(db_conn, os_id, f"http://n/{i}", "market_move", 1, now)
        _insert_score(db_conn, os_id)
        db_conn.commit()
        count_before = db_conn.execute("SELECT COUNT(*) c FROM scores").fetchone()["c"]

        recalibrate_deterministic_scores(db_conn)

        count_after = db_conn.execute("SELECT COUNT(*) c FROM scores").fetchone()["c"]
        assert count_after == count_before + 1


# ---------- 7. add_to_watchlist()'s None-term guard ----------

class TestAddToWatchlistNoneGuard:

    def test_none_term_is_skipped_not_a_crash(self, db_conn):
        """The exact crash seen in practice: `sqlite3.IntegrityError: NOT
        NULL constraint failed: watchlist_terms.term` when Ollama (the
        Groq-quota fallback) returns a theme with e.g. "technology": null
        -- present key, None value, so `.get(key, "unknown")` doesn't help
        (it only substitutes when the key is MISSING). Interrupted a whole
        `--from=` analyze run mid-vertical before this guard existed."""
        add_to_watchlist(db_conn, None, "technology", "Natural Resources")  # must not raise

        rows = db_conn.execute("SELECT * FROM watchlist_terms").fetchall()
        assert rows == [], "a None term must not be inserted at all"

    def test_empty_string_term_is_also_skipped(self, db_conn):
        add_to_watchlist(db_conn, "", "use_case", "Energy")  # must not raise
        rows = db_conn.execute("SELECT * FROM watchlist_terms").fetchall()
        assert rows == []

    def test_normal_term_still_gets_inserted(self, db_conn):
        """The guard must not swallow legitimate terms along with None ones."""
        add_to_watchlist(db_conn, "Quantum Networking", "technology", "Natural Resources")

        rows = db_conn.execute("SELECT * FROM watchlist_terms").fetchall()
        assert len(rows) == 1
        assert rows[0]["term"] == "Quantum Networking"

    def test_repeat_term_bumps_frequency_not_a_duplicate_row(self, db_conn):
        add_to_watchlist(db_conn, "Quantum Networking", "technology", "Natural Resources")
        add_to_watchlist(db_conn, "Quantum Networking", "technology", "Natural Resources")

        rows = db_conn.execute("SELECT * FROM watchlist_terms").fetchall()
        assert len(rows) == 1
        assert rows[0]["frequency"] == 2