"""
Scores every un-scored opportunity space on TWO separate axes
(attractiveness, right-to-win), plus enriches it with the metadata a
sales/presales team needs to act on it (persona, geography, horizon, domain,
next action) -- all in one pass, one file, no separate enrich.py.

Weights: 30% market_signal_strength, 20% source_diversity, 25% evidence_quality,
10% novelty_momentum, 15% strategic_relevance.

MARKET_SIGNAL_CAP / SOURCE_DIVERSITY_CAP -- re-run `radar_cli.py calibrate`
after any meaningful change in ingest volume and bump these if verticals are
pinned at 10.0/10.0 (saturated, no longer discriminating).

CHANGE IN THIS REVISION -- skip already-scored opportunity spaces by default
------------------------------------------------------------------------------
Previously this always scored "the latest run's" opportunity spaces
(get_latest_opportunity_spaces), inserting a fresh row every time (audit
trail) even for OS that hadn't changed. That was fine at 15 hand-picked OS,
but now that OS can be auto-promoted from recurring themes over many runs
(see radar_cli.py's `promote` command), re-running scoring after every
promote would re-score everything and burn LLM quota (Groq's free tier is
rate-limited) for OS that already have a perfectly good score.

Adapted from a teammate's "skip if already scored" idea (their version
checked this per-row with `SELECT COUNT(*) ... WHERE opportunity_space_id = '{id}'`
built via an f-string -- functionally fine here since `id` is an internal
integer, but the same pattern elsewhere with LLM-derived strings would be a
real SQL-injection risk, so it's re-implemented as one parameterized query,
db.get_unscored_opportunity_spaces()):

    python -m pipeline.scoring            # score only what has no score yet
    python -m pipeline.scoring --force    # rescore + re-enrich EVERYTHING

The audit-trail behavior (always INSERT, never UPDATE) is unchanged for
whatever actually does get scored -- --force just widens which OS that is.
"""

import sys
from pipeline.db import (
    get_connection, get_signals_for_vertical,
    get_all_opportunity_spaces, get_unscored_opportunity_spaces,
    insert_score, insert_right_to_win_score, update_opportunity_space_enrichment,
)
from pipeline.config import (
    ORANGE_BUSINESS_ASSETS, ANALYST_RECOGNITION, CAPABILITY_STATS, CUSTOMER_REFERENCES,
    ROLES, BUYER_PERSONAS, GEOS, HORIZONS, DOMAINS_TAXONOMY,
)
from llm.llm_client import get_llm_json

WEIGHTS = {
    "market_signal_strength": 0.30,
    "source_diversity": 0.20,
    "evidence_quality": 0.25,
    "novelty_momentum": 0.10,
    "strategic_relevance": 0.15,
}

MARKET_SIGNAL_CAP = 350
SOURCE_DIVERSITY_CAP = 150


# ---------- Deterministic sub-scores (no LLM, no black box) ----------

def market_signal_strength(signals) -> float:
    """0-10: how visible the topic is, based on raw signal volume."""
    return min(10.0, (len(signals) / MARKET_SIGNAL_CAP) * 10)


def source_diversity(signals) -> float:
    """0-10: how many distinct source domains cover the topic."""
    distinct_sources = {s["source_name"] for s in signals}
    return min(10.0, (len(distinct_sources) / SOURCE_DIVERSITY_CAP) * 10)


def novelty_momentum(signals) -> float:
    """0-10: naive proxy = share of signals collected in the most recent
    third of the observed window. Only meaningful once ingest has been
    running over weeks, not a single short window."""
    if not signals:
        return 0.0
    dates = sorted(s["collected_at"] for s in signals if s["collected_at"])
    if len(dates) < 3:
        return 5.0
    third = max(1, len(dates) // 3)
    recent_share = third / len(dates)
    return round(recent_share * 10, 2)


URGENT_SIGNAL_TYPES = {"regulation", "buying_signal"}


def urgency_score(signals) -> float:
    """0-10, deterministic: +2 per regulation/buying_signal signal, capped
    at 10. Answers 'is there a real deadline here', separate from
    novelty_momentum which just measures 'is coverage increasing'."""
    if not signals:
        return 0.0
    urgent_count = sum(1 for s in signals if s["signal_type"] in URGENT_SIGNAL_TYPES)
    return min(10.0, urgent_count * 2.0)


# ---------- LLM-judged sub-scores ----------

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
{analyst_recognition}

Respond with ONLY a JSON object, no preamble, no markdown fences:
{{"score": <0-10 number>, "justification": "<one sentence citing the specific matching Orange Business asset by name, or explaining why none match>"}}.

Score 10 = directly extends a specific asset above with clear enterprise value (name it).
Score 5 = broadly fits an Orange Business domain but no specific asset matches well.
Score 0 = unrelated to anything Orange Business currently sells."""

RIGHT_TO_WIN_SYSTEM_PROMPT = """You are classifying an Orange Business opportunity space
on "portfolio distance": how close it is to something Orange Business can ALREADY sell,
using this real API/product catalog:
{asset_catalog}
{analyst_recognition}
{capability_stats}
{customer_references}

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

ENRICHMENT_SYSTEM_PROMPT = """You are enriching a B2B innovation opportunity space with
the metadata a sales/presales team needs to act on it.

Valid roles (pick the ONE Orange Business team that should own this opportunity): {roles}
Valid buyer personas (pick the ONE most relevant contact on the customer side): {buyer_personas}
Valid geographies (pick 1-3 most relevant): {geos}
Valid horizons (pick exactly one): {horizons}
  Now = sellable this quarter with what Orange Business already has
  Next = sellable in 6-12 months, needs some development or partnership
  Later = exploratory, research-stage, no clear delivery path yet
Valid business domains (pick the ONE that best fits, exact match required): {domains}

Respond with ONLY a JSON object, no preamble, no markdown fences:
{{"role": "<one from the roles list>", "buyer_persona": "<one from the buyer personas list>",
  "geography": ["<1-3 from the list>"], "horizon": "Now"|"Next"|"Later",
  "domain": "<exact domain name from the list>",
  "next_action": "<one concrete sentence: what should the reader (sales/presales/strategist) do next>"}}"""


def _format_asset_catalog():
    return "\n".join(f"- {a['name']} ({a['category']})" for a in ORANGE_BUSINESS_ASSETS)


def _format_analyst_recognition():
    if not ANALYST_RECOGNITION:
        return ""
    lines = "\n".join(f"- {a['fact']} (source: {a['source']})" for a in ANALYST_RECOGNITION)
    return f"\nExternal validation (use to strengthen justifications where relevant):\n{lines}"


def _format_capability_stats():
    if not CAPABILITY_STATS:
        return ""
    lines = "\n".join(f"- {c['stat']} (source: {c['source']})" for c in CAPABILITY_STATS)
    return (f"\nOrange Business scale/capability facts (cite only if directly relevant, "
            f"e.g. delivery capacity or security posture):\n{lines}")


def _format_customer_references(vertical):
    matches = [c for c in CUSTOMER_REFERENCES if c.get("vertical") == vertical]
    if not matches:
        return ""
    lines = "\n".join(f"- {c['customer']} (source: {c['source']})" for c in matches)
    return (f"\nVerified named customers of Orange Business in THIS vertical (cite if relevant -- "
            f"an actual delivered customer is stronger evidence than a matching asset alone):\n{lines}")


def llm_evidence_quality(signals) -> tuple:
    """Returns (score, justification). Falls back to a neutral score if the
    LLM call or JSON parsing fails, so a flaky call never crashes scoring."""
    if not signals:
        return 0.0, "No signals collected yet for this vertical."
    titles = "\n".join(f"- [{s['source_name']}] {s['title']}" for s in signals[:15])
    prompt = f"Signals to evaluate:\n{titles}"
    result = get_llm_json(prompt, system_prompt=EVIDENCE_QUALITY_SYSTEM_PROMPT)
    if not result or "score" not in result:
        return 5.0, "LLM scoring unavailable -- neutral default used."
    return float(result["score"]), result.get("justification", "")


def llm_strategic_relevance(vertical, use_case, technology, signals) -> tuple:
    """Returns (score, justification), grounded in the real API catalog + analyst facts."""
    prompt = (
        f"Opportunity space: {vertical} x {use_case} x {technology}\n"
        f"Number of supporting signals: {len(signals)}"
    )
    system_prompt = STRATEGIC_RELEVANCE_SYSTEM_PROMPT.format(
        asset_catalog=_format_asset_catalog(), analyst_recognition=_format_analyst_recognition(),
    )
    result = get_llm_json(prompt, system_prompt=system_prompt)
    if not result or "score" not in result:
        return 5.0, "LLM scoring unavailable -- neutral default used."
    return float(result["score"]), result.get("justification", "")


def llm_right_to_win(vertical, use_case, technology):
    """Returns (portfolio_distance, score, matched_assets_str, justification)."""
    prompt = f"Opportunity space: {vertical} x {use_case} x {technology}"
    system_prompt = RIGHT_TO_WIN_SYSTEM_PROMPT.format(
        asset_catalog=_format_asset_catalog(),
        analyst_recognition=_format_analyst_recognition(),
        capability_stats=_format_capability_stats(),
        customer_references=_format_customer_references(vertical),
    )
    result = get_llm_json(prompt, system_prompt=system_prompt)
    if not result or "portfolio_distance" not in result:
        return "L4", 0.0, "", "LLM scoring unavailable -- defaulted to L4/0 (do not trust, re-run scoring)."
    distance = result.get("portfolio_distance", "L4")
    score = float(result.get("right_to_win_score", 0))
    assets = ", ".join(result.get("matched_assets", []))
    return distance, score, assets, result.get("justification", "")


def llm_enrich(vertical, use_case, technology, signals):
    """Returns a dict: role, buyer_persona, geography (comma-joined str),
    horizon, domain, next_action. Falls back to conservative defaults (Later
    horizon, no role/persona/domain claimed) if the LLM is unreachable --
    never crashes."""
    sample_titles = "\n".join(f"- {s['title']}" for s in signals[:10])
    prompt = (
        f"Opportunity space: {vertical} x {use_case} x {technology}\n"
        f"Sample signals:\n{sample_titles}"
    )
    domain_names = [d["name"] for d in DOMAINS_TAXONOMY]
    system_prompt = ENRICHMENT_SYSTEM_PROMPT.format(
        roles=", ".join(ROLES), buyer_personas=", ".join(BUYER_PERSONAS), geos=", ".join(GEOS),
        horizons=", ".join(HORIZONS), domains=", ".join(domain_names),
    )
    result = get_llm_json(prompt, system_prompt=system_prompt)
    if not result or "role" not in result:
        return {
            "role": None, "buyer_persona": None, "geography": None, "horizon": "Later", "domain": None,
            "next_action": "LLM enrichment unavailable -- review manually before showing to Sales.",
        }
    geography = result.get("geography", [])
    domain = result.get("domain")
    if domain not in domain_names:  # guard against the LLM inventing a domain name
        domain = None
    return {
        "role": result.get("role"),
        "buyer_persona": result.get("buyer_persona"),
        "geography": ", ".join(geography) if isinstance(geography, list) else geography,
        "horizon": result.get("horizon", "Later"),
        "domain": domain,
        "next_action": result.get("next_action", ""),
    }


# ---------- Orchestration ----------

def score_opportunity_space(conn, opportunity_space_row):
    """Computes and stores attractiveness (with urgency) for one OS.
    Returns (sub_scores, total, urgency)."""
    vertical = opportunity_space_row["vertical"]
    signals = get_signals_for_vertical(conn, vertical)

    evidence_score, evidence_justification = llm_evidence_quality(signals)
    relevance_score, relevance_justification = llm_strategic_relevance(
        vertical, opportunity_space_row["use_case"], opportunity_space_row["technology"], signals,
    )

    sub_scores = {
        "market_signal_strength": market_signal_strength(signals),
        "source_diversity": source_diversity(signals),
        "evidence_quality": evidence_score,
        "novelty_momentum": novelty_momentum(signals),
        "strategic_relevance": relevance_score,
    }
    urgency = urgency_score(signals)

    total = sum(sub_scores[k] * WEIGHTS[k] for k in WEIGHTS)
    insert_score(
        conn, opportunity_space_row["id"], sub_scores, round(total, 2),
        evidence_quality_justification=evidence_justification,
        strategic_relevance_justification=relevance_justification,
        urgency_score=urgency,
    )
    return sub_scores, round(total, 2), urgency


def score_all_opportunity_spaces(force=False):
    """Scores + enriches opportunity spaces, one pass.

    force=False (default): only opportunity spaces with no score yet
    (get_unscored_opportunity_spaces) -- safe to re-run after every
    `radar_cli.py promote` without burning LLM quota re-scoring OS that
    haven't changed.
    force=True: rescore + re-enrich every opportunity space regardless."""
    conn = get_connection()
    spaces = get_all_opportunity_spaces(conn) if force else get_unscored_opportunity_spaces(conn)

    if not spaces:
        print("Nothing to score -- every opportunity space already has a score. "
              "Use --force to rescore everything anyway.")
        conn.close()
        return

    print(f"Scoring {len(spaces)} opportunity space(s)"
          f"{' (forced rescore of everything)' if force else ' (unscored only)'}\n")

    for space in spaces:
        sub_scores, total, urgency = score_opportunity_space(conn, space)

        distance, rtw_score, assets, rtw_justification = llm_right_to_win(
            space["vertical"], space["use_case"], space["technology"]
        )
        insert_right_to_win_score(conn, space["id"], distance, rtw_score, assets, rtw_justification)

        print(f"{space['label']} ({space['vertical']} x {space['use_case']} x {space['technology']})")
        print(f"  Attractiveness: {total}/10  {sub_scores}")
        print(f"  Urgency:        {urgency}/10")
        print(f"  Right-to-win:   {rtw_score}/10  [{distance}] assets: {assets or 'none'}")
        print(f"  -> {rtw_justification}")

        if space["domain"] and not force:
            print("  Enrichment: skipped (already enriched -- use --force to redo)")
        else:
            vertical = space["vertical"]
            signals = get_signals_for_vertical(conn, vertical)
            enrichment = llm_enrich(vertical, space["use_case"], space["technology"], signals)
            update_opportunity_space_enrichment(
                conn, space["id"],
                role=enrichment["role"], buyer_persona=enrichment["buyer_persona"],
                geography=enrichment["geography"],
                horizon=enrichment["horizon"], domain=enrichment["domain"],
                next_action=enrichment["next_action"],
            )
            print(f"  Enrichment: role={enrichment['role']}  buyer_persona={enrichment['buyer_persona']}  "
                  f"geography={enrichment['geography']}  horizon={enrichment['horizon']}  domain={enrichment['domain']}")
            print(f"  Next action: {enrichment['next_action']}")
        print()

    conn.close()


if __name__ == "__main__":
    score_all_opportunity_spaces(force="--force" in sys.argv)