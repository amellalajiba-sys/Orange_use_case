"""
Targeted tests for how the pipeline handles malformed / missing / null LLM
output -- the exact class of bug the Ollama fallback (much more prone to
malformed JSON than Groq) has hit in practice. See:
  - pipeline/analyze.py's _classify_themes() docstring (the Sieg 24/8 bug fix
    this file's TestClassifyThemes class guards against)
  - pipeline/scoring.py's llm_evidence_quality/llm_strategic_relevance/
    llm_right_to_win/llm_enrich fallback branches
  - pipeline/taxonomy_validation.py's is_generic_taxonomy_term guard

Nothing here touches a real database or makes a real LLM call: scoring.py's
LLM boundary (get_llm_json) is monkeypatched to return the malformed payload
under test, and analyze.py's _classify_themes()/taxonomy_validation's
is_generic_taxonomy_term() are pure functions tested directly against
hand-crafted inputs.

Run: pytest tests/test_malformed_llm_output.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from pipeline.analyze import _classify_themes
from pipeline.taxonomy_validation import is_generic_taxonomy_term
from pipeline.extend_taxonomy import generate_proposal
from pipeline import scoring


# ============================================================
# analyze.py -- _classify_themes() (pure, no DB/LLM)
# ============================================================

class TestClassifyThemes:
    """These mirror real malformed shapes seen from the Ollama fallback in
    practice (see pipeline/analyze.py's Sieg 24/8 comment)."""

    def test_fully_valid_theme_passes_through_unchanged(self):
        from pipeline.config import USE_CASES_TAXONOMY, TECHNOLOGIES_TAXONOMY
        theme = {
            "use_case": USE_CASES_TAXONOMY[0],
            "technology": TECHNOLOGIES_TAXONOMY[0],
            "supporting_signal_count": 5,
            "rationale": "x",
        }
        valid, watchlist, skipped = _classify_themes([theme], [])
        assert valid == [theme]
        assert watchlist == []
        assert skipped == []

    def test_missing_technology_key_entirely(self):
        from pipeline.config import USE_CASES_TAXONOMY
        theme = {"use_case": USE_CASES_TAXONOMY[0]}  # no "technology" key at all
        valid, watchlist, skipped = _classify_themes([theme], [])
        assert valid == []
        assert ("unknown", "technology") in watchlist

    def test_technology_present_but_null(self):
        """The exact Sieg 24/8 bug: key present, value None -- must NOT
        crash and must NOT insert a None term (would violate the DB's
        NOT NULL constraint on watchlist_terms.term)."""
        from pipeline.config import USE_CASES_TAXONOMY
        theme = {"use_case": USE_CASES_TAXONOMY[0], "technology": None}
        valid, watchlist, skipped = _classify_themes([theme], [])
        assert valid == []
        assert ("unknown", "technology") in watchlist
        assert all(term is not None for term, _ in watchlist)

    def test_use_case_also_missing(self):
        """Both fields malformed at once -- both should route to watchlist,
        neither should end up in valid_themes."""
        theme = {"technology": None}
        valid, watchlist, skipped = _classify_themes([theme], [])
        assert valid == []
        assert ("unknown", "use_case") in watchlist
        assert ("unknown", "technology") in watchlist

    def test_bare_generic_technology_is_skipped_not_watchlisted(self):
        from pipeline.config import USE_CASES_TAXONOMY
        theme = {"use_case": USE_CASES_TAXONOMY[0], "technology": "AI"}
        valid, watchlist, skipped = _classify_themes([theme], [])
        assert ("AI", "technology") in skipped
        assert ("AI", "technology") not in watchlist

    def test_specific_ai_compound_term_is_not_filtered(self):
        """Guard against over-filtering: 'Generative AI' is a real,
        already-taxonomy-listed technology and must NOT be treated as
        generic just because it contains 'AI'."""
        from pipeline.config import USE_CASES_TAXONOMY, TECHNOLOGIES_TAXONOMY
        assert "Generative AI" in TECHNOLOGIES_TAXONOMY
        theme = {"use_case": USE_CASES_TAXONOMY[0], "technology": "Generative AI"}
        valid, watchlist, skipped = _classify_themes([theme], [])
        assert valid == [theme]
        assert skipped == []

    def test_explicit_watchlist_candidate_with_missing_term(self):
        """watchlist_candidates entries with no 'term' or an invalid
        'category' must be silently dropped, not crash."""
        candidates = [
            {"category": "technology"},          # no "term"
            {"term": "Something", "category": "nonsense"},  # invalid category
            {"term": "Quantum Networking", "category": "technology"},  # valid
        ]
        valid, watchlist, skipped = _classify_themes([], candidates)
        assert ("Quantum Networking", "technology") in watchlist
        assert len(watchlist) == 1  # the two malformed entries produced nothing

    def test_empty_themes_and_candidates(self):
        valid, watchlist, skipped = _classify_themes([], [])
        assert valid == [] and watchlist == [] and skipped == []


# ============================================================
# taxonomy_validation.py -- is_generic_taxonomy_term()
# ============================================================

class TestIsGenericTaxonomyTerm:
    def test_bare_ai_uppercase(self):
        assert is_generic_taxonomy_term("AI", "technology") is True

    def test_bare_ai_lowercase(self):
        assert is_generic_taxonomy_term("ai", "technology") is True

    def test_whitespace_padded(self):
        assert is_generic_taxonomy_term("  ai  ", "technology") is True

    def test_compound_term_not_generic(self):
        assert is_generic_taxonomy_term("Generative AI", "technology") is False

    def test_use_case_category_never_flagged(self):
        # the guard only ever applies to category == "technology"
        assert is_generic_taxonomy_term("AI", "use_case") is False

    def test_non_string_term_does_not_crash(self):
        assert is_generic_taxonomy_term(None, "technology") is False
        assert is_generic_taxonomy_term(123, "technology") is False


# ============================================================
# extend_taxonomy.py -- generate_proposal()'s generic-term guard
# ============================================================

class TestGenerateProposalGenericGuard:
    def test_generic_term_skipped_before_touching_the_db(self):
        """conn=None on purpose: the generic-term check must short-circuit
        BEFORE any DB query, so this proves it never reaches proposal_exists()."""
        term_row = {
            "vertical": "Manufacturing", "category": "technology", "term": "AI",
            "frequency": 10, "first_seen": "2026-01-01", "last_seen": "2026-01-02",
        }
        result = generate_proposal(conn=None, term=term_row)
        assert result == "skipped"


# ============================================================
# scoring.py -- LLM fallback branches (get_llm_json monkeypatched)
# ============================================================

FAKE_SIGNALS = [{"source_name": "Test Source", "title": "A test signal title"}]


class TestLlmEvidenceQualityFallback:
    def test_no_signals_at_all(self):
        score, justification = scoring.llm_evidence_quality([])
        assert score == 0.0
        assert "No signals" in justification

    def test_llm_call_returns_none(self, monkeypatch):
        monkeypatch.setattr(scoring, "get_llm_json", lambda *a, **k: None)
        score, justification = scoring.llm_evidence_quality(FAKE_SIGNALS)
        assert score == 5.0
        assert "unavailable" in justification

    def test_llm_returns_dict_missing_score_key(self, monkeypatch):
        monkeypatch.setattr(scoring, "get_llm_json", lambda *a, **k: {"justification": "x"})
        score, justification = scoring.llm_evidence_quality(FAKE_SIGNALS)
        assert score == 5.0
        assert "unavailable" in justification


class TestLlmStrategicRelevanceFallback:
    def test_llm_call_returns_none(self, monkeypatch):
        monkeypatch.setattr(scoring, "get_llm_json", lambda *a, **k: None)
        score, justification = scoring.llm_strategic_relevance(
            "Manufacturing", "Energy Optimization", "IoT Platforms", FAKE_SIGNALS
        )
        assert score == 5.0
        assert "unavailable" in justification

    def test_llm_returns_empty_dict(self, monkeypatch):
        monkeypatch.setattr(scoring, "get_llm_json", lambda *a, **k: {})
        score, justification = scoring.llm_strategic_relevance(
            "Manufacturing", "Energy Optimization", "IoT Platforms", FAKE_SIGNALS
        )
        assert score == 5.0
        assert "unavailable" in justification


class TestLlmRightToWinFallback:
    def test_llm_call_returns_none(self, monkeypatch):
        monkeypatch.setattr(scoring, "get_llm_json", lambda *a, **k: None)
        distance, score, assets, justification = scoring.llm_right_to_win(
            "Manufacturing", "Energy Optimization", "IoT Platforms"
        )
        assert distance == "L4"
        assert score == 0.0
        assert assets == ""
        assert "unavailable" in justification

    def test_llm_returns_dict_missing_portfolio_distance_key(self, monkeypatch):
        monkeypatch.setattr(scoring, "get_llm_json", lambda *a, **k: {"right_to_win_score": 8})
        distance, score, assets, justification = scoring.llm_right_to_win(
            "Manufacturing", "Energy Optimization", "IoT Platforms"
        )
        # missing the REQUIRED key "portfolio_distance" -> full fallback,
        # even though a different key WAS present
        assert distance == "L4"
        assert score == 0.0


class TestLlmEnrichFallback:
    def test_llm_call_returns_none(self, monkeypatch):
        monkeypatch.setattr(scoring, "get_llm_json", lambda *a, **k: None)
        result = scoring.llm_enrich("Manufacturing", "Energy Optimization", "IoT Platforms", FAKE_SIGNALS)
        assert result["role"] is None
        assert result["geography"] is None
        assert result["horizon"] == "Later"
        assert "unavailable" in result["next_action_sales"]

    def test_llm_returns_dict_missing_role_key(self, monkeypatch):
        monkeypatch.setattr(scoring, "get_llm_json", lambda *a, **k: {"geography": ["Benelux"]})
        result = scoring.llm_enrich("Manufacturing", "Energy Optimization", "IoT Platforms", FAKE_SIGNALS)
        # "role" is the required key checked in llm_enrich() -- missing it
        # triggers the full fallback dict, geography included, even though
        # the LLM DID return a geography value in this malformed response.
        assert result["role"] is None
        assert result["geography"] is None

    def test_llm_invents_a_domain_not_in_the_taxonomy(self, monkeypatch):
        """Guard against the LLM hallucinating a domain name outside
        DOMAINS_TAXONOMY -- must be silently nulled, not stored as-is."""
        monkeypatch.setattr(scoring, "get_llm_json", lambda *a, **k: {
            "role": "Sales", "buyer_persona": "CIOs", "geography": ["Benelux"],
            "horizon": "Now", "domain": "Something Made Up",
            "next_action_strategist": "a", "next_action_sales": "b", "next_action_presales": "c",
        })
        result = scoring.llm_enrich("Manufacturing", "Energy Optimization", "IoT Platforms", FAKE_SIGNALS)
        assert result["domain"] is None
        assert result["role"] == "Sales"  # the rest of the payload is still used

    def test_llm_returns_geography_as_a_single_string_not_a_list(self, monkeypatch):
        """The prompt asks for a list, but defensively handle a bare string
        too instead of crashing on ', '.join()."""
        monkeypatch.setattr(scoring, "get_llm_json", lambda *a, **k: {
            "role": "Sales", "buyer_persona": "CIOs", "geography": "Benelux",
            "horizon": "Now", "domain": None,
            "next_action_strategist": "a", "next_action_sales": "b", "next_action_presales": "c",
        })
        result = scoring.llm_enrich("Manufacturing", "Energy Optimization", "IoT Platforms", FAKE_SIGNALS)
        assert result["geography"] == "Benelux"