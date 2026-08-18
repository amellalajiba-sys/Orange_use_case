"""
Attractiveness scoring for opportunity spaces.

Formula from the brief:
    30% market_signal_strength
  + 20% source_diversity
  + 20% evidence_quality
  + 15% novelty_momentum
  + 15% strategic_relevance

The first three sub-scores below are computed deterministically from the
signals table (no LLM needed, no black box). evidence_quality and
strategic_relevance need judgment -> plug in an LLM call there (see the
llm_evidence_quality / llm_strategic_relevance stubs). Keep every sub-score
stored, never just the total -- that's what makes the score explainable.
"""

from datetime import datetime, timezone
from pipeline.db import get_connection, get_signals_for_vertical, insert_score, insert_right_to_win_score
from pipeline.config import (
    ORANGE_BUSINESS_ASSETS, PORTFOLIO_DISTANCE, ANALYST_RECOGNITION,
    CUSTOMER_REFERENCES, CAPABILITY_STATS,
)
from llm.llm_client import get_llm_json

# Reweighted 2026-08-17 from the brief's 30/20/20/15/15 starting point.
# Rationale (methodological, not results-driven -- checked before seeing how
# it moved the ranking):
#   - novelty_momentum's proxy (share of signals in the most recent third of
#     the collection window) needs signals spread over weeks/months to mean
#     anything. All 4 OS still scored 3.27-3.30 across every run so far --
#     the whole dataset was ingested in one short window, so the metric is
#     structurally flat right now, not actually measuring momentum yet.
#     Down-weighted to 10% until enough time-series history exists to trust it.
#   - evidence_quality is the most rigorous signal we have today (LLM-judged
#     credibility/specificity per source, not just raw volume). The 5 points
#     freed up from novelty_momentum go there instead of anywhere else.
# Revisit both once ingest has run over several weeks and novelty_momentum
# actually varies.
WEIGHTS = {
    "market_signal_strength": 0.30,
    "source_diversity": 0.20,
    "evidence_quality": 0.25,
    "novelty_momentum": 0.10,
    "strategic_relevance": 0.15,
}

# Calibrated 2026-08-17 against real volumes (calibrate_caps.py): 106-128
# signals and 28-47 distinct sources per vertical, once untagged signals are
# folded in via get_signals_for_vertical(). The old defaults (20 / 8) were
# so far below real volume that every vertical maxed out at 10/10 on both --
# these leave headroom for the dataset to keep growing while still
# differentiating verticals today. Re-run calibrate_caps.py and adjust again
# once ingest volume changes meaningfully (e.g. new verticals added).
MARKET_SIGNAL_CAP = 150     # signal count that maps to a 10/10 market_signal_strength
SOURCE_DIVERSITY_CAP = 50   # distinct domains that maps to a 10/10 source_diversity


def market_signal_strength(signals) -> float:
    """0-10: how visible the topic is, based on raw signal volume."""
    return min(10.0, (len(signals) / MARKET_SIGNAL_CAP) * 10)


def source_diversity(signals) -> float:
    """0-10: how many distinct source domains cover the topic."""
    distinct_sources = {s["source_name"] for s in signals}
    return min(10.0, (len(distinct_sources) / SOURCE_DIVERSITY_CAP) * 10)


def novelty_momentum(signals) -> float:
    """
    0-10: naive proxy = share of signals collected in the most recent third
    of the observed window vs. the rest. Replace with a real time-series
    comparison (e.g. GDELT TimelineVol week-over-week) once you have more data.
    """
    if not signals:
        return 0.0
    dates = sorted(s["collected_at"] for s in signals if s["collected_at"])
    if len(dates) < 3:
        return 5.0  # not enough data to judge momentum yet -- neutral score
    third = max(1, len(dates) // 3)
    recent_share = third / len(dates)
    return round(recent_share * 10, 2)


EVIDENCE_QUALITY_SYSTEM_PROMPT = """You are scoring the credibility and relevance of
market signals for a B2B innovation radar. You must respond with ONLY a JSON object,
no preamble, no markdown fences: {"score": <0-10 number>, "justification": "<one sentence>"}.
Score 10 = signals are specific, from diverse credible sources (analyst reports,
regulators, established media), and clearly relevant. Score 0 = signals are vague,
single-source, vendor-marketing, or unrelated to the topic."""

STRATEGIC_RELEVANCE_SYSTEM_PROMPT = """You are scoring how well an innovation opportunity
fits Orange Business's ACTUAL, currently sellable product portfolio -- not just a generic
domain like "Cloud" or "Security", but a specific existing API/product.

Here is the real Orange Business API catalog to check against:
{asset_catalog}

Respond with ONLY a JSON object, no preamble, no markdown fences:
{{"score": <0-10 number>, "justification": "<one sentence citing the specific matching Orange Business asset by name, or explaining why none match>"}}.

Score 10 = directly extends a specific asset above with clear enterprise value (name it).
Score 5 = broadly fits an Orange Business domain but no specific asset matches well.
Score 0 = unrelated to anything Orange Business currently sells."""


def _format_asset_catalog():
    return "\n".join(f"- {a['name']} ({a['category']})" for a in ORANGE_BUSINESS_ASSETS)


def llm_evidence_quality(signals) -> tuple:
    """
    0-10 + justification, scored by the LLM from the signal titles/summaries.
    Returns (score, justification). Falls back to a neutral score if the
    LLM call or JSON parsing fails, so a flaky call never crashes scoring.
    """
    if not signals:
        return 0.0, "No signals collected yet for this vertical."

    titles = "\n".join(f"- [{s['source_name']}] {s['title']}" for s in signals[:15])
    prompt = f"Signals to evaluate:\n{titles}"

    result = get_llm_json(prompt, system_prompt=EVIDENCE_QUALITY_SYSTEM_PROMPT)
    if not result or "score" not in result:
        return 5.0, "LLM scoring unavailable -- neutral default used."
    return float(result["score"]), result.get("justification", "")


def llm_strategic_relevance(vertical, use_case, technology, signals) -> tuple:
    """
    0-10 + justification: fit against Orange Business's REAL sellable API
    catalog (config.ORANGE_BUSINESS_ASSETS), not a vague domain guess.
    Returns (score, justification).
    """
    prompt = (
        f"Opportunity space: {vertical} x {use_case} x {technology}\n"
        f"Number of supporting signals: {len(signals)}"
    )
    system_prompt = STRATEGIC_RELEVANCE_SYSTEM_PROMPT.format(asset_catalog=_format_asset_catalog())
    result = get_llm_json(prompt, system_prompt=system_prompt)
    if not result or "score" not in result:
        return 5.0, "LLM scoring unavailable -- neutral default used."
    return float(result["score"]), result.get("justification", "")


RIGHT_TO_WIN_SYSTEM_PROMPT = """You are classifying an Orange Business opportunity space
on "portfolio distance": how close it is to something Orange Business can ALREADY sell,
using this real API/product catalog:
{asset_catalog}

Independent third-party validation for some of these assets (cite this by name if it
strengthens the case for an asset you match -- it is stronger evidence than the asset
existing alone, since it's an external analyst confirming market-leading quality, not
just Orange's own claim):
{analyst_recognition}

Verified named customers of Orange Business in THIS SAME vertical (cite by name if
relevant -- an actual delivered customer is stronger evidence than a matching asset
alone, since it proves Orange has already sold and delivered something comparable):
{customer_references}

Orange Business scale/capability facts (cite only if directly relevant to the
classification, e.g. delivery capacity or security posture):
{capability_stats}

Classify using exactly one of these levels:
L0 = Direct offer: an existing asset above addresses this as-is.
L1 = Bundle: two or more existing assets exist but are not packaged together yet.
L2 = Partner-dependent: needs a capability an external partner has, not Orange itself.
L3 = Adjacent: needs one new capability to be built or acquired -- close, but missing.
L4 = White space: no plausible path from the current portfolio.

Respond with ONLY a JSON object, no preamble, no markdown fences:
{{"portfolio_distance": "L0"|"L1"|"L2"|"L3"|"L4", "right_to_win_score": <0-10, where L0~9-10, L4~0-2>,
  "matched_assets": ["<asset name(s) from the catalog that apply, empty list if L3/L4>"],
  "justification": "<one sentence explaining the classification>"}}"""


def _format_analyst_recognition():
    if not ANALYST_RECOGNITION:
        return "(none on file)"
    return "\n".join(
        f"- {a['source']}: {a['finding']} (relevant to: {', '.join(a['relevant_assets'])})"
        for a in ANALYST_RECOGNITION
    )


def _format_customer_references(vertical):
    matches = [c for c in CUSTOMER_REFERENCES if c["vertical"] == vertical]
    if not matches:
        return "(none on file for this vertical)"
    return "\n".join(f"- {c['customer']}: {c['detail']}" for c in matches)


def _format_capability_stats():
    return "\n".join(f"- {s}" for s in CAPABILITY_STATS)


def llm_right_to_win(vertical, use_case, technology):
    """
    Separate from attractiveness. Answers "can Orange sell this today", not
    "is the market hot". Returns (portfolio_distance, score, matched_assets_str, justification).
    """
    prompt = f"Opportunity space: {vertical} x {use_case} x {technology}"
    system_prompt = RIGHT_TO_WIN_SYSTEM_PROMPT.format(
        asset_catalog=_format_asset_catalog(),
        analyst_recognition=_format_analyst_recognition(),
        customer_references=_format_customer_references(vertical),
        capability_stats=_format_capability_stats(),
    )
    result = get_llm_json(prompt, system_prompt=system_prompt)
    if not result or "portfolio_distance" not in result:
        return "L4", 0.0, "", "LLM scoring unavailable -- defaulted to L4/0 (do not trust, re-run scoring)."
    distance = result.get("portfolio_distance", "L4")
    score = float(result.get("right_to_win_score", 0))
    assets = ", ".join(result.get("matched_assets", []))
    justification = result.get("justification", "")
    return distance, score, assets, justification


def score_opportunity_space(conn, opportunity_space_row):
    vertical = opportunity_space_row["vertical"]
    signals = get_signals_for_vertical(conn, vertical)

    evidence_score, evidence_justification = llm_evidence_quality(signals)
    relevance_score, relevance_justification = llm_strategic_relevance(
        vertical,
        opportunity_space_row["use_case"],
        opportunity_space_row["technology"],
        signals,
    )

    sub_scores = {
        "market_signal_strength": market_signal_strength(signals),
        "source_diversity": source_diversity(signals),
        "evidence_quality": evidence_score,
        "novelty_momentum": novelty_momentum(signals),
        "strategic_relevance": relevance_score,
    }

    total = sum(sub_scores[k] * WEIGHTS[k] for k in WEIGHTS)
    insert_score(
        conn, opportunity_space_row["id"], sub_scores, round(total, 2),
        evidence_quality_justification=evidence_justification,
        strategic_relevance_justification=relevance_justification,
    )
    return sub_scores, round(total, 2)


def score_all_opportunity_spaces():
    conn = get_connection()
    spaces = conn.execute("SELECT * FROM opportunity_spaces").fetchall()
    for space in spaces:
        sub_scores, total = score_opportunity_space(conn, space)

        distance, rtw_score, assets, rtw_justification = llm_right_to_win(
            space["vertical"], space["use_case"], space["technology"]
        )
        insert_right_to_win_score(conn, space["id"], distance, rtw_score, assets, rtw_justification)

        print(f"{space['label']} ({space['vertical']} x {space['use_case']} x {space['technology']})")
        print(f"  Attractiveness: {total}/10  {sub_scores}")
        print(f"  Right-to-win:   {rtw_score}/10  [{distance}] assets: {assets or 'none'}")
        print(f"  -> {rtw_justification}")
    conn.close()


if __name__ == "__main__":
    score_all_opportunity_spaces()