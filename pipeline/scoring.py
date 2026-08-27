"""
Scores every un-scored opportunity space on TWO separate axes
(attractiveness, right-to-win), plus enriches it with the metadata a
sales/presales team needs to act on it (persona, geography, horizon, domain,
next action) -- all in one pass, one file, no separate enrich.py.

Weights: 30% market_signal_strength, 20% source_diversity, 25% evidence_quality,
10% novelty_momentum, 15% strategic_relevance.

CHANGE IN THIS REVISION -- score on LINKED signals, not the whole vertical
------------------------------------------------------------------------------
Previously every sub-score was computed on get_signals_for_vertical() -- ALL
signals of the OS's whole vertical, an identical pool for every OS sharing
that vertical. Two different OS in the same vertical (e.g. "Manufacturing x
IoT" vs "Manufacturing x Computer Vision") ended up with the exact same
market_signal_strength/source_diversity/novelty_momentum/evidence_quality,
even though they're about different things -- these scores weren't actually
OS-specific, just vertical-specific, which isn't defensible when the whole
point is to rank individual opportunity spaces against each other.

`radar_cli.py link` already computes, independently of scoring, which
signals are actually about a given OS (keyword overlap between
use_case/technology and each signal's title) and stores that in the
opportunity_signals table -- this is also what the client-facing summary
already shows as "grounding evidence" for each OS. Reusing that link instead
of re-deriving relevance here means the score and the evidence shown next to
it are now computed from the SAME signal set, instead of contradicting each
other.

PIPELINE ORDER CHANGE THIS REQUIRES -- `link` must now run BEFORE `scoring`,
not after (README/radar_cli.py's `all` command need updating to match: was
ingest -> analyze -> create -> promote -> score -> link -> summary, now
ingest -> analyze -> create -> promote -> link -> score -> summary). This
reordering is safe because cmd_link() (radar_cli.py) never reads scores or
right_to_win_scores itself -- it only reads opportunity_spaces and signals,
so there's no circular dependency.

MARKET_SIGNAL_CAP / SOURCE_DIVERSITY_CAP -- recalibrated (see below) since
they used to be tuned against vertical-wide signal counts (100s of signals)
and now apply to a single OS's linked signals, capped at `link`'s top_n
(default 15). Re-run `radar_cli.py calibrate` against real linked-signal
counts once `link` has run on the full dataset -- these are a rough
starting point, NOT re-derived from real numbers yet (team should confirm
before trusting the resulting ranking).

An OS that hasn't been linked yet (link was never run, or found zero
keyword overlap) scores 0.0/neutral on every sub-score, same as a vertical
with nothing ingested used to -- see get_linked_signals_for_opportunity_space()
in db.py, no new fallback logic needed for this.

CHANGE IN A PREVIOUS REVISION -- skip already-scored opportunity spaces by default
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
built via an f-string, but the same pattern elsewhere with LLM-derived strings would be a
real SQL-injection risk, so it's re-implemented as one parameterized query,
db.get_unscored_opportunity_spaces()):

    python -m pipeline.scoring            # score only what has no score yet
    python -m pipeline.scoring --force    # rescore + re-enrich EVERYTHING

The audit-trail behavior (always INSERT, never UPDATE) is unchanged for
whatever actually does get scored -- --force just widens which OS that is.
"""

import sys
# Sieg 23/08 -- needed for the novelty_momentum() time-window fix below
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pipeline.db import (
    get_connection, get_linked_signals_for_opportunity_space,
    get_all_opportunity_spaces, get_unscored_opportunity_spaces,
    get_opportunity_spaces_missing_right_to_win,
    get_opportunity_spaces_with_fallback_scores,
    get_opportunity_spaces_with_old_scores,
    get_latest_scores,
    insert_score, insert_right_to_win_score, update_opportunity_space_enrichment,
)
from pipeline.config import (
    ORANGE_BUSINESS_ASSETS, ANALYST_RECOGNITION, CAPABILITY_STATS, CUSTOMER_REFERENCES,
    ROLES, BUYER_PERSONAS, GEOS_PROMPT, HORIZONS, DOMAINS_TAXONOMY,
    TRUST_CRITICAL_VERTICALS, map_to_value_proposition,
    # Sieg 24/8 -- the 2 brief calibration factors with no data source yet
    # (see config.py comment above their definition for the full context).
    OPPORTUNITY_COUNT_BY_VERTICAL, PIPELINE_VALUE_BY_VERTICAL,
    # Sieg 24/8 -- reused as the buying_signal decay window in urgency_score()
    # below, instead of inventing a separate constant (see comment there).
    TED_LOOKBACK_DAYS,
)
from llm.llm_client import get_llm_json

WEIGHTS = {
    "market_signal_strength": 0.30,
    "source_diversity": 0.20,
    "evidence_quality": 0.25,
    "novelty_momentum": 0.10,
    "strategic_relevance": 0.15,
}

# Sieg 23/08 -- recalibrated against real `radar_cli.py calibrate` output
# (link ran with top_n=45): 93 OS, linked signal count min=2 max=45 avg=21.8,
# distinct sources min=1 max=41 avg=14.6.
#
# MARKET_SIGNAL_CAP=45 is NOT a guess -- it's tied directly to link's top_n.
# Since `link` hard-caps every OS at top_n linked signals, no OS can EVER
# have more than top_n (45) -- so an OS that reaches that ceiling has, by
# construction, the maximum obtainable evidence volume and deserves 10/10.
# This is a structural fact, not a judgment call, UNLIKE the cap before the
# link-before-score change (which had no such relationship to anything).
# IMPORTANT: if `link`'s top_n (radar_cli.py's cmd_link) is ever changed
# again, this must be updated to match, or the two silently drift apart --
# same category of risk as EVIDENCE_QUALITY_MAX_SIGNALS/ENRICHMENT_SAMPLE_SIZE
# above needing a check whenever top_n moves.
#
# Sieg 26/08 (2h du matin, veille de la présentation) -- 45 -> 56, pour
# suivre EXACTEMENT `radar_cli.py cmd_link`'s nouveau top_n=56 (voir le
# commentaire complet à cet endroit dans radar_cli.py pour le detail du
# calcul -- même 90e percentile, mesuré sur 125 OS réels après le fix GDELT
# et le filtre NON_TECH_SOURCES). Recalculé ici uniquement pour rester
# structurellement vrai avec le nouveau plafond de `link` -- pas une
# deuxième mesure indépendante. Pour vérifier que les deux valeurs sont
# toujours synchronisées après un futur changement de top_n :
#   grep "top_n=" radar_cli.py     # doit matcher MARKET_SIGNAL_CAP ci-dessous
#
# SOURCE_DIVERSITY_CAP=40 has no equivalent structural tie (source diversity
# isn't hard-capped by top_n the way raw count is) -- this IS a judgment
# call from real data: set near the observed max (41) rather than the
# average (14.6 would saturate roughly half the OS at 10/10). Re-run
# `calibrate` and revisit if ingest volume/source variety changes meaningfully.
# Sieg 26/08 -- left at 40 for now: the "Across N OS" distinct-sources max
# seen tonight (after the NON_TECH_SOURCES filter) was still <=40, so this
# one hasn't gone stale yet -- re-check with `calibrate`'s first block
# ("distinct sources min=X max=Y avg=Z") after the next full relink+rescore,
# since removing junk sources could plausibly lower the real max slightly.
MARKET_SIGNAL_CAP = 56       # = link's top_n -- structural ceiling, not a guess (see comment above)
SOURCE_DIVERSITY_CAP = 40    # distinct named sources that maps to a 10/10 source_diversity


# Sieg 23/08 -- found while investigating whether link's top_n=15 (radar_cli.py)
# is arbitrary: llm_evidence_quality() and llm_enrich() below were ALSO
# separately hardcoding `signals[:15]` / `signals[:10]` inline, with no
# comment and no link to top_n at all -- a second, independent, undocumented
# cap nobody had connected to the first one. Named here instead so it's at
# least visible and grep-able in one place, and documented WHY it's kept as
# a separate concept from link's top_n rather than just reusing all of
# `signals`: these two functions build an LLM prompt, and prompt length is
# a cost/latency concern (more signal titles = more tokens per call, and
# Groq's free tier is already token-rate-limited -- see the 429 errors we've
# been hitting), which top_n's job (picking which signals are RELEVANT to
# the OS) has nothing to do with. If `link`'s top_n ever moves below 15 this
# becomes a no-op (nothing left to cut); if it moves above 15, this constant
# is the thing that then matters -- worth re-checking together whenever
# top_n changes, not assuming they'll silently stay in sync.
EVIDENCE_QUALITY_MAX_SIGNALS = 15  # titles sent to the evidence_quality LLM prompt
ENRICHMENT_SAMPLE_SIZE = 10        # titles sent to the enrichment LLM prompt


# ---------- Deterministic sub-scores (no LLM, no black box) ----------

def market_signal_strength(signals) -> float:
    """0-10: how visible the topic is, based on raw signal volume."""
    return min(10.0, (len(signals) / MARKET_SIGNAL_CAP) * 10)


def source_diversity(signals) -> float:
    """0-10: how many distinct named sources cover the topic.
    Sieg 23/08 -- comment fix: this counts distinct `source_name` values
    (e.g. "Reuters", "EUR-Lex", "arXiv" -- 788 distinct values in the current
    DB), not literal domain names as the docstring used to say. It's a
    reasonable diversity proxy either way, just renamed to match what the
    code actually does."""
    distinct_sources = {s["source_name"] for s in signals}
    return min(10.0, (len(distinct_sources) / SOURCE_DIVERSITY_CAP) * 10)


def _parse_signal_date(signal):
    """Sieg 23/08 -- helper for novelty_momentum(): best-effort real-world
    date for a signal. Prefers `published_date` (when the thing actually
    happened) over `collected_at` (when ingest.py happened to run) --
    novelty should reflect how fresh the news itself is, not our scrape
    schedule. Falls back to `collected_at` since `published_date`'s format
    varies across the 9 sources (RFC 822 RSS, ISO from arXiv/Semantic
    Scholar/TED, GDELT's compact seendate) and is sometimes missing
    entirely. Returns a tz-aware datetime, or None (never raises) if
    nothing parseable was found -- so one bad row in `signals` can't crash
    a whole scoring run."""
    for key in ("published_date", "collected_at"):
        try:
            raw = signal[key]
        except (KeyError, IndexError):
            continue
        if not raw:
            continue
        raw = raw.strip()
        dt = None
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            pass
        if dt is None:
            try:
                dt = parsedate_to_datetime(raw)  # RFC 822, e.g. Google News / vendor RSS
            except (ValueError, TypeError):
                pass
        if dt is None:
            try:
                dt = datetime.strptime(raw, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)  # GDELT seendate
            except ValueError:
                pass
        if dt is not None:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
    return None


def novelty_momentum(signals) -> float:
    """0-10: share of signals whose real-world date (published_date, or
    collected_at when published_date is missing/unparseable) falls in the
    most recent third of the time elapsed between the OLDEST signal and
    NOW. Only meaningful once ingest has been running over weeks, not a
    single short window."""
    if not signals:
        return 0.0
    # Sieg 23/08 -- 2nd bug fix on this function (see also the earlier
    # count-based version). The previous rewrite measured recency against
    # the END OF ITS OWN SAMPLE (window_end = last signal's date), not
    # against today -- so a burst of signals from 3 months ago and the same
    # signals spread evenly over 3 months both scored identically (both are
    # "the most recent third of themselves"). It couldn't tell "old but
    # bursty" from "old and stale". Now the recent third is measured against
    # datetime.now(), so a burst near TODAY scores higher than the same
    # count of signals spread across the whole history -- which is what
    # "momentum" is supposed to mean.
    #
    # Sieg 23/08 -- also switched the date source from collected_at back to
    # _parse_signal_date() (published_date first, collected_at fallback),
    # with defensive multi-format parsing so one malformed timestamp in the
    # DB can't crash the entire scoring run. collected_at only reflects our
    # scrape schedule, not when the underlying news actually happened -- two
    # signals ingested the same day can be a fresh announcement and a
    # 6-month-old article, and collected_at alone can't tell them apart.
    parsed_dates = [d for d in (_parse_signal_date(s) for s in signals) if d is not None]
    if len(parsed_dates) < 3:
        return 5.0
    parsed_dates.sort()
    oldest = parsed_dates[0]
    now = datetime.now(timezone.utc)
    span_seconds = (now - oldest).total_seconds()
    if span_seconds <= 0:
        return 5.0  # oldest signal is somehow "in the future" (clock skew) -- can't measure momentum, stay neutral
    recent_third_start = now - (now - oldest) / 3
    recent_count = sum(1 for d in parsed_dates if d >= recent_third_start)
    recent_share = recent_count / len(parsed_dates)
    return round(recent_share * 10, 2)


# Sieg 24/8 -- this set is an UNDOCUMENTED design choice, not derived from
# the client brief -- there's no comment anywhere in the codebase (checked
# scoring.py/config.py/README.md) explaining why exactly `regulation` and
# `buying_signal` are the 2 "urgent" types out of the 6 in
# config.SIGNAL_TYPES, and not e.g. `tech_maturity`. Flagging this
# explicitly instead of silently treating it as settled -- worth raising
# with the team if urgency needs to be defensible in front of the client.
URGENT_SIGNAL_TYPES = {"regulation", "buying_signal"}

# Sieg 24/8 -- replaced the fixed URGENCY_CAP with a dynamic, per-run
# scaling point, per her design (Discord/verbally, 24/8): instead of a
# hardcoded ceiling, take the 95th percentile of the weighted-urgent-signal
# distribution across every scored OS THIS run, and use that as the value
# that maps to 10/10. Rationale, in her words: "if a large number of urgent
# signals arrive during a given period, the maximum rises and the urgency
# score becomes more selective; if the volume is low, the maximum drops and
# the urgency assessment becomes more sensitive." Deliberately recalculated
# on every run -- existing OS's urgency_score WILL shift as the population
# changes, which is intentional (the radar should stay "alive" and reflect
# current context), not a bug.
#
# 95th percentile, not the raw max: a single outlier OS (e.g. one with 10
# regulation signals when everyone else has 0-2) would otherwise single-
# handedly compress everyone else's score toward 0. The percentile is a
# floor-protected minimum of 1.0 -- an all-quiet run (every OS at 0-1
# weighted urgent signals) must not divide by ~0 and blow every score up to
# a meaningless 10/10.
URGENCY_PERCENTILE = 95
URGENCY_MIN_SCALING_POINT = 1.0

# Sieg 24/8 -- kept as the fallback scaling point for the rare case where
# urgency_score() is called on a single OS with no population context at
# all (e.g. some future one-off diagnostic script) -- score_opportunity_space()
# and recalibrate_urgency() below always pass a real, freshly-computed
# scaling point instead of relying on this default.
URGENCY_CAP = 6.0

# Sieg 24/8 -- weight of the novelty_momentum() contribution folded into
# urgency (see _urgency_weighted() below for the full reasoning).
NOVELTY_URGENCY_WEIGHT = 2.0


def _urgency_weighted(signals) -> float:
    """The raw, un-normalized weighted urgent-signal value for one OS --
    split out of urgency_score() so the dynamic scaling point (95th
    percentile across the whole population, see URGENCY_PERCENTILE above)
    can be computed from real numbers in one pass, then applied in a
    second pass. See urgency_score()'s docstring for what the weights mean."""
    weighted = 0.0
    for s in signals:
        if s["signal_type"] == "regulation":
            weighted += 1.0
        elif s["signal_type"] == "buying_signal":
            dt = _parse_signal_date(s)
            if dt is None:
                weighted += 0.5  # unknown date -- neutral partial weight, not 0 and not full
            else:
                age_days = (datetime.now(timezone.utc) - dt).total_seconds() / 86400
                weighted += max(0.0, 1 - age_days / TED_LOOKBACK_DAYS)

    # Sieg 24/8 -- team decision (24/8): fold novelty into urgency too, not
    # just attractiveness. Her reasoning: "urgency score has a real meaning
    # (is the signal urgent) while attractiveness is more subjective (it
    # depends on what we choose to take into account) -- novelty could be
    # integrated in both." This is NOT double-counting in the harmful sense:
    # urgency and total_score (attractiveness) are entirely separate
    # outputs -- urgency isn't in WEIGHTS and never gets summed into
    # total_score -- so the same underlying signal-timing data can
    # legitimately answer two different questions ("is this trending up"
    # matters for both "is this urgent" and "is this attractive").
    #
    # Guard: only added once there are >=3 signals -- novelty_momentum()
    # returns a flat neutral 5.0 fallback below its OWN 3-signal threshold
    # (see that function's docstring), and without this guard that neutral
    # default would inject a fake, identical momentum boost into urgency
    # for every small/sparse OS regardless of its actual timing.
    #
    # NOVELTY_URGENCY_WEIGHT=2.0 is a first estimate, not derived from real
    # data (unlike URGENCY_PERCENTILE/MARKET_SIGNAL_CAP, which were
    # calibrated against actual radar.db output) -- roughly "as urgent as
    # 2 regulation signals" at full momentum (10/10). Revisit with
    # `radar_cli.py calibrate` once there's real before/after data to look at.
    if len(signals) >= 3:
        weighted += NOVELTY_URGENCY_WEIGHT * (novelty_momentum(signals) / 10.0)

    return weighted


def compute_urgency_scaling_point(conn, opportunity_space_ids=None) -> float:
    """Sieg 24/8 -- the 95th percentile of _urgency_weighted() across a set
    of opportunity spaces, floored at URGENCY_MIN_SCALING_POINT. Pass
    opportunity_space_ids to score just that set (used by
    score_all_opportunity_spaces() for a fresh run); omit it to use every
    currently-scored OS (used by recalibrate_urgency()). Uses
    statistics.quantiles (n=100) rather than a hand-rolled percentile --
    stdlib, no new dependency, and it's the same linear-interpolation
    method most people mean by "95th percentile"."""
    import statistics

    if opportunity_space_ids is None:
        rows = get_latest_scores(conn)
        ids = [r["id"] for r in rows]
    else:
        ids = list(opportunity_space_ids)

    weighted_values = [_urgency_weighted(get_linked_signals_for_opportunity_space(conn, os_id)) for os_id in ids]
    weighted_values = [w for w in weighted_values if w > 0]  # OS with zero urgent signals don't inform the ceiling

    if len(weighted_values) < 2:
        # Too few data points for a meaningful percentile (0 or 1 OS with
        # any urgent signals at all this run) -- fall back to the static
        # cap rather than let one single value become the scaling point.
        return URGENCY_CAP

    percentile_95 = statistics.quantiles(weighted_values, n=100, method="inclusive")[URGENCY_PERCENTILE - 1]
    # Sieg 24/8 -- safety clamp: statistics.quantiles' default ('exclusive')
    # interpolation can extrapolate PAST the actual maximum for small
    # samples (checked: 4 data points [1,2,3,10] gave a 95th percentile of
    # 15.25 -- higher than the highest value in the data, nonsensical for a
    # percentile). method="inclusive" fixes most of it, but with very few
    # OS in a run this clamp is the real guarantee: the scaling point can
    # never exceed the single most urgent OS actually observed this run.
    percentile_95 = min(percentile_95, max(weighted_values))
    return max(percentile_95, URGENCY_MIN_SCALING_POINT)


def urgency_score(signals, scaling_point=URGENCY_CAP) -> float:
    """0-10, deterministic. Weights the 2 URGENT_SIGNAL_TYPES differently
    instead of counting every urgent signal equally -- checked their real
    age distribution first (see Discord thread, 24/8): regulation signals
    have a median age of ~3 years (EUR-Lex full-text search surfaces
    regulations still in force, not just new ones -- an old regulation you
    still have to comply with isn't "less urgent" just because it's old),
    while buying_signal (TED) notices have a real submission deadline that
    genuinely passes over time.
      - regulation: full weight (1.0) per linked signal, no date decay --
        staying in force doesn't depend on publication date.
      - buying_signal: linear decay from 1.0 (published today) to 0.0
        (published TED_LOOKBACK_DAYS ago or more) -- reuses the existing
        ingest window (config.py) instead of inventing a second, unrelated
        constant. This is a proxy for "is the tender still open", NOT the
        real submission deadline -- fetch_ted() (ingest.py) actually
        requests TED's deadline-receipt-tender-date-lot field from the API
        but never stores it (see Discord thread) -- storing and using the
        real deadline instead of this age-based proxy is a bigger,
        separate schema change, not done here.
    Answers 'is there a real deadline here', separate from novelty_momentum
    which just measures 'is coverage increasing'.

    Sieg 24/8 -- scaling_point replaces the old fixed URGENCY_CAP division:
    pass the current run's dynamic value from compute_urgency_scaling_point()
    (see that function). Defaults to the static URGENCY_CAP only for
    standalone/no-population-context calls -- normal scoring always passes
    a real one."""
    if not signals:
        return 0.0
    weighted = _urgency_weighted(signals)
    return round(min(10.0, (weighted / scaling_point) * 10), 2)


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
{capability_stats}

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
{{"portfolio_distance": "L0"|"L1"|"L2"|"L3"|"L4", "right_to_win_score": <0-10, ONE DECIMAL PLACE (e.g. 6.7, not 6 or 7), where L0~9-10, L4~0-2>,
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

Also write ONE concrete next action PER ROLE below -- Strategist, Sales, and Presales each need
to do something DIFFERENT with the same opportunity (e.g. Strategist commissions a deep-dive,
Sales opens a conversation, Presales prepares a bid brief). Do not repeat the same sentence
for all three.

Respond with ONLY a JSON object, no preamble, no markdown fences:
{{"role": "<one from the roles list>", "buyer_persona": "<one from the buyer personas list>",
  "geography": ["<1-3 from the list>"], "horizon": "Now"|"Next"|"Later",
  "domain": "<exact domain name from the list>",
  "next_action_strategist": "<one concrete sentence for the Strategist/Innovator role>",
  "next_action_sales": "<one concrete sentence for the Sales role>",
  "next_action_presales": "<one concrete sentence for the Presales/Proposal role>"}}"""


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
    titles = "\n".join(f"- [{s['source_name']}] {s['title']}" for s in signals[:EVIDENCE_QUALITY_MAX_SIGNALS])
    prompt = f"Signals to evaluate:\n{titles}"
    result = get_llm_json(prompt, system_prompt=EVIDENCE_QUALITY_SYSTEM_PROMPT)
    if not result or "score" not in result:
        return 5.0, "LLM scoring unavailable -- neutral default used."
    return float(result["score"]), result.get("justification", "")


def llm_strategic_relevance(vertical, use_case, technology, signals) -> tuple:
    """Returns (score, justification), grounded in the real API catalog + analyst facts.
    On top of the LLM's judgment call, two deterministic adjustments are layered in
    -- both traceable to the corporate deck rather than free-text LLM guessing:
      1. Value proposition match (slide 17) -- named in the justification if found.
      2. Trust-critical vertical bonus (slide 12-14) -- +0.5 for Defense/Healthcare,
         since Orange runs dedicated divisions there (250+/1,000+ experts)."""
    prompt = (
        f"Opportunity space: {vertical} x {use_case} x {technology}\n"
        f"Number of supporting signals: {len(signals)}"
    )
    system_prompt = STRATEGIC_RELEVANCE_SYSTEM_PROMPT.format(
        asset_catalog=_format_asset_catalog(), analyst_recognition=_format_analyst_recognition(),
        capability_stats=_format_capability_stats(),
    )
    result = get_llm_json(prompt, system_prompt=system_prompt)
    if not result or "score" not in result:
        return 5.0, "LLM scoring unavailable -- neutral default used."

    score = float(result["score"])
    justification = result.get("justification", "")

    value_prop = map_to_value_proposition(f"{vertical} {use_case} {technology}")
    if value_prop:
        justification += f" Maps to Orange's '{value_prop.value}' value proposition."

    if vertical in TRUST_CRITICAL_VERTICALS:
        score = min(10.0, score + 0.5)
        justification += (f" +0.5 trust-critical bonus: Orange runs a dedicated "
                           f"{vertical} division (corporate deck, slide 12-14).")

    return score, justification


# Sieg 24/8 -- the client brief lists 5 factors for internal right-to-win
# calibration: CRM customer overlap, opportunity count, pipeline value,
# product/offering match, people capability. Before this, only 2 of the 5
# actually fed the score: product/offering match (ORANGE_BUSINESS_ASSETS
# matching inside the LLM prompt below) and people capability (CAPABILITY_STATS,
# injected into the same prompt "if relevant" -- generic text, not a scored
# factor). The 2 functions below add the missing/partial ones as small,
# deterministic, additive bonuses -- same pattern as the trust-critical-
# vertical bonus in llm_strategic_relevance() -- rather than trying to shoehorn
# them into the LLM's free-text judgment where they'd be unverifiable.
def crm_customer_overlap_bonus(vertical) -> float:
    """Sieg 24/8 -- CRM customer overlap factor. No internal CRM export is
    available to this team, so this uses CUSTOMER_REFERENCES (public,
    sourced customer-story pages, already grounding the right-to-win prompt)
    as the closest available proxy: a named customer in this vertical is real
    evidence Orange already has a foothold there, even without a live CRM
    feed of live pipeline/account data. +0.5 per named customer in this
    vertical, capped at +1.0 (2+ customers) so one vertical with many public
    case studies can't dominate the score the way the LLM's free-text
    judgment already can."""
    count = sum(1 for c in CUSTOMER_REFERENCES if c.get("vertical") == vertical)
    return min(1.0, count * 0.5)


def pipeline_calibration_bonus(vertical) -> float:
    """Sieg 24/8 -- opportunity count + pipeline value factors from the brief.
    Deliberately a SAFE NO-OP (+0.0) for every vertical right now: neither
    OPPORTUNITY_COUNT_BY_VERTICAL nor PIPELINE_VALUE_BY_VERTICAL (config.py)
    has any real data in it -- there's no CRM export to pull from yet, and
    inventing numbers here would make the score look more grounded than it
    is. Once the team drops a real per-vertical export into those 2 dicts,
    this starts contributing +0.3 for a tracked opportunity count and +0.3
    more if pipeline_value is at/above the per-vertical median -- structured
    now so wiring in real numbers later is a config.py edit only, not a
    scoring.py change."""
    bonus = 0.0
    if OPPORTUNITY_COUNT_BY_VERTICAL.get(vertical):
        bonus += 0.3
    values = [v for v in PIPELINE_VALUE_BY_VERTICAL.values() if v]
    median_value = sorted(values)[len(values) // 2] if values else None
    if median_value is not None and PIPELINE_VALUE_BY_VERTICAL.get(vertical, 0) >= median_value:
        bonus += 0.3
    return bonus


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
    justification = result.get("justification", "")

    # Sieg 24/8 -- apply the 2 deterministic calibration bonuses (see the
    # functions above). crm_bonus is real data (CUSTOMER_REFERENCES);
    # pipeline_bonus is a no-op until real CRM data exists -- see their
    # docstrings. Only append to the justification when a bonus actually
    # applied, so untouched scores don't get a misleading "+0.0" note.
    crm_bonus = crm_customer_overlap_bonus(vertical)
    pipeline_bonus = pipeline_calibration_bonus(vertical)
    total_bonus = crm_bonus + pipeline_bonus
    if total_bonus:
        score = min(10.0, score + total_bonus)
        justification += (f" +{total_bonus:.1f} calibration bonus (CRM customer overlap"
                           f"{', opportunity count/pipeline value' if pipeline_bonus else ''}).")

    return distance, score, assets, justification


def llm_enrich(vertical, use_case, technology, signals):
    """Returns a dict: role, buyer_persona, geography (comma-joined str),
    horizon, domain, next_action_strategist, next_action_sales,
    next_action_presales. Falls back to conservative defaults (Later
    horizon, no role/persona/domain claimed, same generic "review manually"
    message on all 3 next actions) if the LLM is unreachable -- never crashes."""
    sample_titles = "\n".join(f"- {s['title']}" for s in signals[:ENRICHMENT_SAMPLE_SIZE])
    prompt = (
        f"Opportunity space: {vertical} x {use_case} x {technology}\n"
        f"Sample signals:\n{sample_titles}"
    )
    domain_names = [d["name"] for d in DOMAINS_TAXONOMY]
    system_prompt = ENRICHMENT_SYSTEM_PROMPT.format(
        roles=", ".join(ROLES), buyer_personas=", ".join(BUYER_PERSONAS), geos=GEOS_PROMPT,
        horizons=", ".join(HORIZONS), domains=", ".join(domain_names),
    )
    result = get_llm_json(prompt, system_prompt=system_prompt)
    fallback_action = "LLM enrichment unavailable -- review manually before showing to Sales."
    if not result or "role" not in result:
        return {
            "role": None, "buyer_persona": None, "geography": None, "horizon": "Later", "domain": None,
            "next_action_strategist": fallback_action,
            "next_action_sales": fallback_action,
            "next_action_presales": fallback_action,
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
        "next_action_strategist": result.get("next_action_strategist", fallback_action),
        "next_action_sales": result.get("next_action_sales", fallback_action),
        "next_action_presales": result.get("next_action_presales", fallback_action),
        "next_action": result.get("next_action", ""),
    }


# ---------- Orchestration ----------

def score_opportunity_space(conn, opportunity_space_row, urgency_scaling_point=URGENCY_CAP):
    """Computes and stores attractiveness (with urgency) for one OS.
    Returns (sub_scores, total, urgency).

    Sieg 23/08 -- was get_signals_for_vertical(conn, vertical): every OS in
    the same vertical scored on the exact same signal pool, so their
    deterministic sub-scores (and evidence_quality/strategic_relevance,
    which get shown that same signal list) were never actually OS-specific.
    Now uses get_linked_signals_for_opportunity_space(), the OS-specific set
    `radar_cli.py link` already builds -- REQUIRES link to have run first
    (see module docstring for the new pipeline order). An OS not yet linked
    simply gets an empty list here, which every sub-score below already
    treats as a defined 0.0/neutral case.

    Sieg 24/8 -- urgency_scaling_point: the dynamic 95th-percentile value
    from compute_urgency_scaling_point(), computed once per batch by the
    caller (score_all_opportunity_spaces()) and passed in here rather than
    recomputed per-OS -- recomputing the whole population's percentile for
    every single OS in a loop would be O(n^2) in signal-fetching calls for
    no benefit, since the scaling point is the same for every OS scored in
    the same run."""
    signals = get_linked_signals_for_opportunity_space(conn, opportunity_space_row["id"])

    evidence_score, evidence_justification = llm_evidence_quality(signals)
    relevance_score, relevance_justification = llm_strategic_relevance(
        opportunity_space_row["vertical"], opportunity_space_row["use_case"],
        opportunity_space_row["technology"], signals,
    )

    sub_scores = {
        "market_signal_strength": market_signal_strength(signals),
        "source_diversity": source_diversity(signals),
        "evidence_quality": evidence_score,
        "novelty_momentum": novelty_momentum(signals),
        "strategic_relevance": relevance_score,
    }
    urgency = urgency_score(signals, scaling_point=urgency_scaling_point)

    total = sum(sub_scores[k] * WEIGHTS[k] for k in WEIGHTS)
    insert_score(
        conn, opportunity_space_row["id"], sub_scores, round(total, 2),
        evidence_quality_justification=evidence_justification,
        strategic_relevance_justification=relevance_justification,
        urgency_score=urgency,
    )
    return sub_scores, round(total, 2), urgency


def score_all_opportunity_spaces(force=False, from_label=None, to_label=None):
    """Scores + enriches opportunity spaces, one pass.

    force=False (default): only opportunity spaces with no score yet
    (get_unscored_opportunity_spaces) -- safe to re-run after every
    `radar_cli.py promote` without burning LLM quota re-scoring OS that
    haven't changed. ALSO repairs any OS stuck with a scores row but no
    right_to_win_scores row (interrupted run) -- see the loop below.
    force=True: rescore + re-enrich every opportunity space regardless.
    from_label: resume a --force run that got interrupted (e.g. Groq quota
    ran out mid-run) -- skips every OS whose label sorts BEFORE this one
    alphabetically, so already-redone OS aren't burned through again. Only
    meaningful together with force=True; ignored otherwise (unscored-only
    mode already naturally skips whatever got scored on the interrupted run).
    to_label: Sieg 26/08 -- symmetric to from_label, for the opposite case:
    rescoring a bounded range (e.g. "--from=OS006 --to=OS060" after a
    top_n/cap recalibration, to check the new caps' effect on a sample
    before spending quota on all 125 OS). Skips every OS whose label sorts
    AFTER this one. Combinable with from_label for a two-sided range, or
    usable alone for "everything up to and including this label". Only
    meaningful together with force=True, same as from_label.

    Sieg 25/8 -- deliberately NOT merging in db.get_opportunity_spaces_with_
    old_scores() (OS scored >3 days ago) as a teammate's version did: that
    silently ran the full paid LLM pass (evidence_quality, strategic_
    relevance, right_to_win -- 3 calls per OS) on every stale OS on every
    plain, non --force run, which is exactly the kind of quota burn every
    other --recalibrate-*/--refresh alternative in this file exists to
    avoid. Keeping existing OS fresh on a schedule is a real, good goal --
    just do it via the FREE path already built for it: `python -m
    pipeline.scoring --refresh` (recalibrate_deterministic_scores()) after
    `radar_cli.py link`. get_opportunity_spaces_with_old_scores() is kept in
    db.py, unused for now, for whoever wants to wire an automatic
    "--refresh only what's stale" mode later."""
    conn = get_connection()
    spaces = get_all_opportunity_spaces(conn) if force else get_unscored_opportunity_spaces(conn)

    # Sieg 23/08 -- bug fix: get_unscored_opportunity_spaces() only checks the
    # `scores` table, so an OS interrupted between insert_score() and
    # insert_right_to_win_score() (Groq quota exhausted mid-run, crash, etc.)
    # had a `scores` row already, so it was never picked up by a normal
    # (non --force) run again -- permanently stuck until someone noticed and
    # manually ran `--force --from=OSxxx`. Folded in here as a SEPARATE list
    # (not merged into `spaces`) so the loop below can skip the expensive
    # evidence_quality/strategic_relevance LLM calls for these -- they
    # already have a perfectly good attractiveness score, only right-to-win
    # is missing.
    repair_spaces = [] if force else get_opportunity_spaces_missing_right_to_win(conn)
    if repair_spaces:
        print(f"Repairing {len(repair_spaces)} opportunity space(s) left incomplete by an "
              f"earlier interrupted run (has attractiveness score, missing right-to-win):")
        for s in repair_spaces:
            print(f"  {s['label']} ({s['vertical']} x {s['use_case']} x {s['technology']})")
        print()

    if force and from_label:
        before = len(spaces)
        spaces = [s for s in spaces if s["label"] >= from_label]
        print(f"--from {from_label}: skipping {before - len(spaces)} opportunity space(s) "
              f"already done before the interruption.\n")

    if force and to_label:
        before = len(spaces)
        spaces = [s for s in spaces if s["label"] <= to_label]
        print(f"--to {to_label}: keeping only {len(spaces)} of {before} opportunity space(s) "
              f"up to and including this label.\n")

    if not spaces and not repair_spaces:
        print("Nothing to score -- every opportunity space already has a score. "
              "Use --force to rescore everything anyway.")
        conn.close()
        return

    print(f"Scoring {len(spaces)} opportunity space(s)"
          f"{' (forced rescore of everything)' if force else ' (unscored only)'}\n")

    # Sieg 24/8 -- dynamic urgency scaling point (her design, 24/8): computed
    # ONCE per run, over every OS this run touches (both freshly scored and
    # repaired), not per-OS -- see compute_urgency_scaling_point()'s
    # docstring. score_opportunity_space() below just uses the value.
    urgency_scaling_point = compute_urgency_scaling_point(
        conn, opportunity_space_ids=[s["id"] for s in spaces] + [s["id"] for s in repair_spaces]
    )
    print(f"Urgency scaling point this run (95th percentile of weighted urgent signals): "
          f"{urgency_scaling_point:.2f} -- an OS at or above this weighted value scores 10/10 on urgency.\n")

    for space in spaces:
        sub_scores, total, urgency = score_opportunity_space(conn, space, urgency_scaling_point=urgency_scaling_point)

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
            # Sieg 23/08 -- was get_signals_for_vertical(conn, vertical): the
            # sample titles fed to the enrichment LLM (used to write persona/
            # role/next actions) came from the whole vertical, not this OS --
            # same fix as score_opportunity_space() above, same reasoning.
            signals = get_linked_signals_for_opportunity_space(conn, space["id"])
            enrichment = llm_enrich(vertical, space["use_case"], space["technology"], signals)
            update_opportunity_space_enrichment(
                conn, space["id"],
                role=enrichment["role"], buyer_persona=enrichment["buyer_persona"],
                geography=enrichment["geography"],
                horizon=enrichment["horizon"], domain=enrichment["domain"],
                next_action_strategist=enrichment["next_action_strategist"],
                next_action_sales=enrichment["next_action_sales"],
                next_action_presales=enrichment["next_action_presales"],
            )
            print(f"  Enrichment: role={enrichment['role']}  buyer_persona={enrichment['buyer_persona']}  "
                  f"geography={enrichment['geography']}  horizon={enrichment['horizon']}  domain={enrichment['domain']}")
            print(f"  Next action (Strategist): {enrichment['next_action_strategist']}")
            print(f"  Next action (Sales):      {enrichment['next_action_sales']}")
            print(f"  Next action (Presales):   {enrichment['next_action_presales']}")
        print()

    # Sieg 23/08 -- repair pass: only the missing right-to-win step (+ enrichment
    # if it was never done either), no re-run of score_opportunity_space() --
    # that would waste LLM quota re-scoring evidence_quality/strategic_relevance
    # that's already fine.
    for space in repair_spaces:
        distance, rtw_score, assets, rtw_justification = llm_right_to_win(
            space["vertical"], space["use_case"], space["technology"]
        )
        insert_right_to_win_score(conn, space["id"], distance, rtw_score, assets, rtw_justification)
        print(f"REPAIRED {space['label']}: Right-to-win {rtw_score}/10 [{distance}] "
              f"assets: {assets or 'none'}")

        if not space["domain"]:
            vertical = space["vertical"]
            # Sieg 23/08 -- was get_signals_for_vertical(conn, vertical): the
            # sample titles fed to the enrichment LLM (used to write persona/
            # role/next actions) came from the whole vertical, not this OS --
            # same fix as score_opportunity_space() above, same reasoning.
            signals = get_linked_signals_for_opportunity_space(conn, space["id"])
            enrichment = llm_enrich(vertical, space["use_case"], space["technology"], signals)
            update_opportunity_space_enrichment(
                conn, space["id"],
                role=enrichment["role"], buyer_persona=enrichment["buyer_persona"],
                geography=enrichment["geography"],
                horizon=enrichment["horizon"], domain=enrichment["domain"],
                next_action_strategist=enrichment["next_action_strategist"],
                next_action_sales=enrichment["next_action_sales"],
                next_action_presales=enrichment["next_action_presales"],
            )
        print()

    # Sieg 24/8 -- her design: the dynamic urgency scaling point should
    # reflect the WHOLE current population on every run, not just the OS
    # scored/repaired in this particular batch (a mostly-empty incremental
    # run would otherwise compute its percentile from 1-2 OS and barely move
    # anyone). Rescaling everyone here, at the end, is free (no LLM calls,
    # see recalibrate_urgency()'s docstring) -- this is what actually makes
    # existing OS's urgency "alive" and shift with new signal volume, per
    # her stated intent.
    recalibrate_urgency(conn)

    # Sieg 25/8 -- closes the "does it refresh automatically after 3 days"
    # question: it didn't, on purpose (a teammate's version wired this to a
    # full LLM rescore on every plain run, which would silently burn quota
    # -- see recalibrate_deterministic_scores()'s docstring). This does the
    # SAME staleness check, but only ever triggers the FREE deterministic
    # refresh (no LLM calls, same one --refresh runs by hand) -- so a normal
    # `python -m pipeline.scoring` / `radar_cli.py all` run now keeps any
    # 3+ day old OS's market_signal_strength/source_diversity/novelty_
    # momentum/urgency current automatically, at zero extra Groq cost,
    # without ever touching evidence_quality/strategic_relevance.
    stale_ids = {s["id"] for s in get_opportunity_spaces_with_old_scores(conn)}
    if stale_ids:
        stale_rows = [r for r in get_latest_scores(conn) if r["id"] in stale_ids]
        if stale_rows:
            print(f"\nAuto-refreshing {len(stale_rows)} opportunity space(s) scored "
                  f"more than 3 days ago (free, deterministic only -- run "
                  f"`radar_cli.py link` first if new signals should count):\n")
            recalibrate_deterministic_scores(conn, rows=stale_rows)

    conn.close()


def recalibrate_deterministic_scores(conn=None, rows=None):
    """Implements the 'Refresh Logic for already existing OSs' gap from
    current_project_state_overview.md: 'We have a process that
    adds new data and promotes new OSes, but it doesn't update the scores
    of existing OSes [...] the radar does not reflect the current market
    state for already known OSs.' Without this, an OS scored Monday with
    100 signals still shows Monday's score Tuesday even after 50 more
    signals arrive for it -- `radar_cli.py all` only ever scores NEW
    (unscored) OS, see score_all_opportunity_spaces()'s docstring.

    Recalculates market_signal_strength, source_diversity, novelty_momentum,
    and urgency_score for the given OS (or EVERY currently-scored OS if
    `rows` is omitted), using each OS's CURRENT linked signals -- so run
    `radar_cli.py link` again first if new signals have come in since the
    last link; this function only reads opportunity_signals, it doesn't
    re-attach anything itself (link's own top_n logic is a bigger, separate
    operation not worth duplicating here).

    evidence_quality/strategic_relevance (LLM-based, the expensive half) are
    carried forward UNCHANGED from each OS's latest score -- same principle
    as recalibrate_urgency()/recalibrate_right_to_win(): this whole refresh
    is free in Groq quota terms. total_score is recomputed from the mix of
    fresh deterministic values + the unchanged LLM values.

    urgency_score reuses the SAME dynamic 95th-percentile scaling point as
    the rest of the pipeline (compute_urgency_scaling_point(), see that
    function and recalibrate_urgency()) -- not a second, separate urgency
    calculation, so this and a plain `python -m pipeline.scoring` run never
    disagree about what "urgent" means this run.

    Sieg 25/8 -- `rows` param added so score_all_opportunity_spaces() can
    call this automatically on just the STALE subset (OS scored >3 days
    ago, see get_opportunity_spaces_with_old_scores()) at the end of every
    normal run, instead of needing someone to remember `--refresh` by hand.
    Manual `--refresh` from the command line is UNCHANGED -- it still omits
    `rows` and refreshes every scored OS, not just the stale ones.

    Run: python -m pipeline.scoring --refresh
    """
    close_after = conn is None
    if conn is None:
        conn = get_connection()

    if rows is None:
        rows = get_latest_scores(conn)
    if not rows:
        print("No scored opportunity spaces found -- nothing to refresh. "
              "Run `python -m pipeline.scoring` first.")
        if close_after:
            conn.close()
        return

    urgency_scaling_point = compute_urgency_scaling_point(conn)
    print(f"Refreshing deterministic scores (market signal strength, source diversity, "
          f"novelty momentum, urgency) for {len(rows)} opportunity space(s) -- "
          f"no LLM calls, free in quota terms. Urgency scaling point: "
          f"{urgency_scaling_point:.2f}\n")

    for r in rows:
        signals = get_linked_signals_for_opportunity_space(conn, r["id"])
        new_deterministic = {
            "market_signal_strength": market_signal_strength(signals),
            "source_diversity": source_diversity(signals),
            "novelty_momentum": novelty_momentum(signals),
        }
        new_urgency = urgency_score(signals, scaling_point=urgency_scaling_point)

        sub_scores = {
            **new_deterministic,
            "evidence_quality": r["evidence_quality"],
            "strategic_relevance": r["strategic_relevance"],
        }
        new_total = round(sum(sub_scores[k] * WEIGHTS[k] for k in WEIGHTS), 2)

        insert_score(
            conn, r["id"], sub_scores, new_total,
            evidence_quality_justification=r["evidence_quality_justification"],
            strategic_relevance_justification=r["strategic_relevance_justification"],
            urgency_score=new_urgency,
        )
        moved = " (unchanged)" if new_total == r["total_score"] else ""
        print(f"{r['label']} ({r['vertical']} x {r['use_case']} x {r['technology']}): "
              f"total {r['total_score']}/10 -> {new_total}/10{moved}, "
              f"urgency {r['urgency_score']}/10 -> {new_urgency}/10")

    if close_after:
        conn.close()


def recalibrate_urgency(conn=None):
    """Sieg 24/8 -- redoes urgency_score for every already-scored OS using a
    freshly-computed dynamic scaling point (95th percentile of weighted
    urgent signals across the WHOLE current population -- see
    compute_urgency_scaling_point()), not a fixed cap. WITHOUT ANY LLM CALL
    AT ALL -- urgency_score is 100% deterministic, so this is free in Groq
    quota terms, unlike recalibrate_right_to_win() below which still needs
    one LLM call per OS.

    Her design intent, verbatim: "if we recalibrate the scaling point during
    each run [...] the urgency scores for existing OSs will change with
    every update. This is intentional -- the radar needs to be alive and
    reflect the current context." So yes, re-running this can genuinely
    move an OS's urgency_score up or down even though nothing about that
    specific OS changed -- that's the population shifting, not a bug.

    Called automatically at the end of score_all_opportunity_spaces() (see
    below) so a normal `python -m pipeline.scoring` run already keeps every
    OS's urgency current -- also runnable standalone:
    `python -m pipeline.scoring --recalibrate-urgency`, e.g. right after a
    fresh ingest without wanting a full rescore.

    Keeps every other field of the latest `scores` row as-is (market_signal_
    strength, source_diversity, evidence_quality, novelty_momentum,
    strategic_relevance, total_score -- urgency isn't part of the weighted
    total, see WEIGHTS) and only recomputes urgency_score, then re-inserts
    via insert_score() -- still respects the "always INSERT, never UPDATE"
    audit-trail rule (see README "Key design decisions"), just carries the
    unchanged fields forward instead of recomputing them.

    Run: python -m pipeline.scoring --recalibrate-urgency
    """
    close_after = conn is None
    if conn is None:
        conn = get_connection()

    rows = get_latest_scores(conn)
    if not rows:
        print("No scored opportunity spaces found -- nothing to recalibrate. "
              "Run `python -m pipeline.scoring` first.")
        if close_after:
            conn.close()
        return

    urgency_scaling_point = compute_urgency_scaling_point(conn)
    print(f"Recalibrating urgency_score for {len(rows)} opportunity space(s) -- "
          f"no LLM calls, free in quota terms. Scaling point (95th percentile): "
          f"{urgency_scaling_point:.2f}\n")
    for r in rows:
        signals = get_linked_signals_for_opportunity_space(conn, r["id"])
        new_urgency = urgency_score(signals, scaling_point=urgency_scaling_point)
        sub_scores = {
            "market_signal_strength": r["market_signal_strength"],
            "source_diversity": r["source_diversity"],
            "evidence_quality": r["evidence_quality"],
            "novelty_momentum": r["novelty_momentum"],
            "strategic_relevance": r["strategic_relevance"],
        }
        insert_score(
            conn, r["id"], sub_scores, r["total_score"],
            evidence_quality_justification=r["evidence_quality_justification"],
            strategic_relevance_justification=r["strategic_relevance_justification"],
            urgency_score=new_urgency,
        )
        print(f"{r['label']} ({r['vertical']} x {r['use_case']} x {r['technology']}): "
              f"urgency {r['urgency_score']}/10 -> {new_urgency}/10")

    if close_after:
        conn.close()


def recalibrate_right_to_win(conn=None):
    """Sieg 24/8 -- redoes ONLY the right-to-win step (llm_right_to_win) for
    every opportunity space that already has an attractiveness score, so
    today's crm_customer_overlap_bonus()/pipeline_calibration_bonus() change
    gets applied to already-scored OS WITHOUT re-burning LLM quota on
    evidence_quality/strategic_relevance/enrichment, which didn't change and
    already have good values -- `--force` would redo all of those too for no
    reason, and Groq's free tier is already quota-tight (see llm_client.py).
    Use this after a calibration-only change like today's; use `--force`
    only when the scoring LOGIC itself (not just right-to-win) changes.
    right_to_win_scores is audit-trail (always INSERT, never UPDATE), so this
    naturally produces a fresh row per OS and get_latest_scores() picks the
    newest one up automatically -- no explicit overwrite step needed.

    Run: python -m pipeline.scoring --recalibrate-right-to-win
    """
    close_after = conn is None
    if conn is None:
        conn = get_connection()

    # Opportunity spaces with NO attractiveness score yet still need the
    # full score_opportunity_space() pass (they need evidence_quality etc.
    # computed for the first time) -- not this shortcut. Run the normal
    # `python -m pipeline.scoring` (unscored-only mode) for those first.
    unscored_ids = {s["id"] for s in get_unscored_opportunity_spaces(conn)}
    spaces = [s for s in get_all_opportunity_spaces(conn) if s["id"] not in unscored_ids]

    if not spaces:
        print("No already-scored opportunity spaces found -- nothing to recalibrate. "
              "Run `python -m pipeline.scoring` first.")
        if close_after:
            conn.close()
        return

    print(f"Recalibrating right-to-win only for {len(spaces)} already-scored opportunity "
          f"space(s) -- evidence_quality/strategic_relevance/enrichment untouched.\n")
    for space in spaces:
        distance, rtw_score, assets, rtw_justification = llm_right_to_win(
            space["vertical"], space["use_case"], space["technology"]
        )
        insert_right_to_win_score(conn, space["id"], distance, rtw_score, assets, rtw_justification)
        print(f"{space['label']} ({space['vertical']} x {space['use_case']} x {space['technology']})")
        print(f"  Right-to-win: {rtw_score}/10  [{distance}] assets: {assets or 'none'}")
        print(f"  -> {rtw_justification}\n")

    if close_after:
        conn.close()


def recalibrate_geography(conn=None):
    """Sieg 25/8 -- the client brief (25/8) changed the geography taxonomy
    from 5 broad continents to the Innovation Radar's actual regional
    grouping (Benelux, Germany, Southern Europe, DACH, UK & Ireland,
    Nordics, Eastern Europe, + continent-level for the rest of the world --
    see config.GEOS/GEOS_PROMPT). Every OS already enriched has a
    `geography` value in the OLD taxonomy, and score_all_opportunity_spaces()
    skips re-enrichment for any OS that already has a `domain` set (see its
    "already enriched" check) -- so without this, old and new geography
    labels would sit side by side indefinitely. `--force` would also fix
    it, but it re-burns LLM quota re-doing evidence_quality/
    strategic_relevance/right_to_win too, none of which changed.

    Redoes ONLY llm_enrich() -- 1 LLM call per OS, same cost class as
    recalibrate_right_to_win() -- for every already-scored OS. This
    overwrites the whole enrichment (role/buyer_persona/horizon/domain/
    next_actions too, not just geography) since llm_enrich() returns all of
    it in one call -- harmless, since the same inputs produce essentially
    the same outputs for those; only geography is actually expected to move.

    Run: python -m pipeline.scoring --recalibrate-geography
    """
    close_after = conn is None
    if conn is None:
        conn = get_connection()

    unscored_ids = {s["id"] for s in get_unscored_opportunity_spaces(conn)}
    spaces = [s for s in get_all_opportunity_spaces(conn) if s["id"] not in unscored_ids]

    if not spaces:
        print("No already-scored opportunity spaces found -- nothing to re-enrich. "
              "Run `python -m pipeline.scoring` first.")
        if close_after:
            conn.close()
        return

    print(f"Re-enriching geography (new taxonomy, see config.GEOS_PROMPT) for "
          f"{len(spaces)} already-scored opportunity space(s) -- attractiveness/"
          f"right-to-win untouched.\n")

    for space in spaces:
        signals = get_linked_signals_for_opportunity_space(conn, space["id"])
        enrichment = llm_enrich(space["vertical"], space["use_case"], space["technology"], signals)
        update_opportunity_space_enrichment(
            conn, space["id"],
            role=enrichment["role"], buyer_persona=enrichment["buyer_persona"],
            geography=enrichment["geography"],
            horizon=enrichment["horizon"], domain=enrichment["domain"],
            next_action_strategist=enrichment["next_action_strategist"],
            next_action_sales=enrichment["next_action_sales"],
            next_action_presales=enrichment["next_action_presales"],
        )
        print(f"{space['label']} ({space['vertical']} x {space['use_case']} x {space['technology']}) "
              f"-> geography={enrichment['geography']}")

    if close_after:
        conn.close()


def clean_scores(conn=None):
    """Sieg 25/8 -- teammate's contribution, adopted with a change: kept as
    a standalone, EXPLICITLY-invoked maintenance command instead of being
    called automatically at the top of every score_all_opportunity_spaces()
    run. Removes every `scores`/`right_to_win_scores` row for an OS except
    the most recent one (by computed_at) -- real bloat this addresses: some
    OS had 30+ historical rows after repeated --refresh/--recalibrate-*/
    --force runs over the week.

    Why not automatic: `scores`/`right_to_win_scores` being append-only is a
    documented design decision (README "Key design decisions" / interview
    prep Q5 -- "Audit trail, never overwrite"), and get_latest_scores()
    already only ever reads the newest row per OS, so the extra history is
    inert, not wrong. Pruning it is a reasonable occasional cleanup (DB size
    ahead of the client demo, say) but running it unconditionally on every
    single scoring pass would quietly throw away that history on every run,
    for a benefit (DB size) this project doesn't currently need on every run.

    Run: python -m pipeline.scoring --prune-scores
    """
    close_after = conn is None
    if conn is None:
        conn = get_connection()

    before_scores = conn.execute("SELECT COUNT(*) AS c FROM scores").fetchone()["c"]
    before_rtw = conn.execute("SELECT COUNT(*) AS c FROM right_to_win_scores").fetchone()["c"]

    conn.execute(
        """
        DELETE FROM scores
        WHERE id IN (
            SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY opportunity_space_id ORDER BY computed_at DESC
                ) AS row_number
                FROM scores
            )
            WHERE row_number > 1
        )
        """
    )
    conn.execute(
        """
        DELETE FROM right_to_win_scores
        WHERE id IN (
            SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY opportunity_space_id ORDER BY computed_at DESC
                ) AS row_number
                FROM right_to_win_scores
            )
            WHERE row_number > 1
        )
        """
    )
    conn.commit()

    after_scores = conn.execute("SELECT COUNT(*) AS c FROM scores").fetchone()["c"]
    after_rtw = conn.execute("SELECT COUNT(*) AS c FROM right_to_win_scores").fetchone()["c"]
    print(f"Pruned scores: {before_scores} -> {after_scores} rows "
          f"({before_scores - after_scores} removed).")
    print(f"Pruned right_to_win_scores: {before_rtw} -> {after_rtw} rows "
          f"({before_rtw - after_rtw} removed).")

    if close_after:
        conn.close()


def rescue_fallback_scores(conn=None):
    """Sieg 24/8 -- quota-safe alternative to `--force --from=OSxxx` for the
    specific case of OS that got a neutral FALLBACK value (evidence_quality/
    strategic_relevance=5.0, right_to_win=0.0/L4) because Groq's quota was
    exhausted at the moment they were scored -- see
    db.get_opportunity_spaces_with_fallback_scores() for how these are found
    (grepping the "LLM scoring unavailable" justification text).

    `--force --from=OS003` would re-spend quota on EVERY OS from OS003
    onward alphabetically (most of which already have a real, good score) --
    with the quota already exhausted, that's not affordable. This instead
    re-runs the full scoring pass (evidence_quality, strategic_relevance,
    right_to_win, enrichment) ONLY for the OS that actually need it -- 31 on
    the last check, not 90+.

    Run once quota is available again (fresh key, tomorrow's reset, or
    Ollama): python -m pipeline.scoring --rescue-fallback
    """
    close_after = conn is None
    if conn is None:
        conn = get_connection()

    spaces = get_opportunity_spaces_with_fallback_scores(conn)
    if not spaces:
        print("No opportunity space currently has a fallback score -- nothing to rescue.")
        if close_after:
            conn.close()
        return

    print(f"Rescuing {len(spaces)} opportunity space(s) that got a neutral fallback "
          f"score (Groq quota was exhausted when they were first scored):\n")
    for space in spaces:
        sub_scores, total, urgency = score_opportunity_space(conn, space)
        distance, rtw_score, assets, rtw_justification = llm_right_to_win(
            space["vertical"], space["use_case"], space["technology"]
        )
        insert_right_to_win_score(conn, space["id"], distance, rtw_score, assets, rtw_justification)

        print(f"{space['label']} ({space['vertical']} x {space['use_case']} x {space['technology']})")
        print(f"  Attractiveness: {total}/10  {sub_scores}")
        print(f"  Right-to-win:   {rtw_score}/10  [{distance}]")
        print(f"  -> {rtw_justification}\n")

        vertical = space["vertical"]
        signals = get_linked_signals_for_opportunity_space(conn, space["id"])
        enrichment = llm_enrich(vertical, space["use_case"], space["technology"], signals)
        update_opportunity_space_enrichment(
            conn, space["id"],
            role=enrichment["role"], buyer_persona=enrichment["buyer_persona"],
            geography=enrichment["geography"],
            horizon=enrichment["horizon"], domain=enrichment["domain"],
            next_action_strategist=enrichment["next_action_strategist"],
            next_action_sales=enrichment["next_action_sales"],
            next_action_presales=enrichment["next_action_presales"],
        )

    if close_after:
        conn.close()


if __name__ == "__main__":
    # --from=OS018 : resume an interrupted --force run starting at this label
    # (e.g. after switching GROQ_API_KEY mid-run). Ignored without --force.
    # Sieg 24/8 -- --recalibrate-right-to-win : cheap alternative to --force
    # after a right-to-win-only calibration change (see function docstring).
    # Sieg 24/8 -- --rescue-fallback : quota-safe alternative to --force for
    # redoing ONLY the OS that got a neutral fallback score, not everything
    # from a --from= label onward (see function docstring).
    # Sieg 24/8 -- --recalibrate-urgency : free (no LLM) alternative to
    # --force after a deterministic-only formula change (see function
    # docstring). Check this one before --recalibrate-right-to-win since
    # both can be needed after the same session -- run urgency first, it
    # costs nothing.
    from_label = None
    to_label = None  # Sieg 26/08 -- see score_all_opportunity_spaces()'s docstring
    for arg in sys.argv:
        if arg.startswith("--from="):
            from_label = arg.split("=", 1)[1]
        elif arg.startswith("--to="):
            to_label = arg.split("=", 1)[1]
    # Sieg 24/8 -- --refresh : implements the "Refresh Logic for already
    # existing OSs" gap (current_project_state_overview.md) -- redoes all 4
    # deterministic sub-scores (not just urgency) for every scored OS using
    # their CURRENT linked signals, free of LLM calls. Run `radar_cli.py
    # link` first if new signals came in since the last link. Checked before
    # --recalibrate-urgency below since --refresh already includes urgency.
    if "--refresh" in sys.argv:
        recalibrate_deterministic_scores()
    elif "--recalibrate-urgency" in sys.argv:
        recalibrate_urgency()
    elif "--recalibrate-right-to-win" in sys.argv:
        recalibrate_right_to_win()
    elif "--recalibrate-geography" in sys.argv:
        recalibrate_geography()
    elif "--rescue-fallback" in sys.argv:
        rescue_fallback_scores()
    elif "--prune-scores" in sys.argv:
        clean_scores()
    else:
        score_all_opportunity_spaces(force="--force" in sys.argv, from_label=from_label, to_label=to_label)