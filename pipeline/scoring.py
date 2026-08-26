"""
Central configuration for the Innovation Radar signal pipeline.

Every source query list (Google News, GDELT,
arXiv, Semantic Scholar, competitor watch, regulation, buying signals) used
to be hand-written 3 times over, once per vertical, in 6 separate lists, aAdding a vertical
meant editing 6 places and it was easy to miss one.

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
    ROLES, BUYER_PERSONAS, GEOS, HORIZONS, DOMAINS_TAXONOMY,
    TRUST_CRITICAL_VERTICALS, map_to_value_proposition,
    # Sieg 24/8 -- the 2 brief calibration factors with no data source yet
    # (see config.py comment above their definition for the full context).
    OPPORTUNITY_COUNT_BY_VERTICAL, PIPELINE_VALUE_BY_VERTICAL,
    # Sieg 24/8 -- reused as the buying_signal decay window in urgency_score()
    # below, instead of inventing a separate constant (see comment there).
    TED_LOOKBACK_DAYS,
)
from llm.llm_client import get_llm_json

# Sieg 24/8 -- integrated verbatim from her PR diff (Friday->today), not
# paraphrased, so this reads as her actual contribution when compared
# against that diff. Only change: placed here (top of this file, after the
# imports) since this config.py grew a 17-vertical/TED/NewsAPI.ai structure
# on a separate branch and her diff's original anchor point (right before
# `DB_PATH = "radar.db"`) doesn't exist in the same spot here.

# =============================================
# TAXONOMY EXTENSIONS LOGIC
# =============================================

# Path for taxonomy extensions (in root folder)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TAXONOMY_EXTENSIONS_PATH = os.path.join(BASE_DIR, "taxonomy_extensions.json")

def _init_taxonomy_extensions():
    """If the file does not exist, it creates it with an empty list."""
    if not os.path.exists(TAXONOMY_EXTENSIONS_PATH):
        with open(TAXONOMY_EXTENSIONS_PATH, "w") as f:
            json.dump([], f)

# Call function at the start so that file exists
_init_taxonomy_extensions()

def _load_taxonomy_extensions():
    """Loads the approved terms from the JSON file and returns them as two lists: use_cases and technologies."""
    if os.path.exists(TAXONOMY_EXTENSIONS_PATH):
        with open(TAXONOMY_EXTENSIONS_PATH, "r") as f:
            data = json.load(f)
        use_cases = [item["term"] for item in data if item["category"] == "use_case"]
        technologies = [item["term"] for item in data if item["category"] == "technology"]
        return use_cases, technologies
    return [], []

# Extensions loading
_EXT_USE_CASES, _EXT_TECHNOLOGIES = _load_taxonomy_extensions()

# =============================================
# Rest of config.py as before
# =============================================

# Load .env HERE, not just in llm_client.py -- config.py is imported by
# ingest.py, which never imports llm_client.py (ingest doesn't touch the
# LLM at all). Without this line, running `python -m pipeline.ingest` on
# its own never reads .env, so NEWSAPI_AI_KEY stays "" even when it's set
# correctly in the file -- llm_client.py's own load_dotenv() call only
# helped when analyze.py/scoring.py (which DO import llm_client) ran first
# in the same process. Calling load_dotenv() twice (once here, once in
# llm_client.py) is harmless -- python-dotenv is idempotent.
load_dotenv()

DB_PATH = "radar.db"

# --- Reference taxonomy for OS enrichment (persona, geography, time horizon) ---
# Split into two lists that used to be one merged `PERSONAS` list -- they answer
# two different questions and were getting confused with each other:
#   ROLES          = which Orange Business team should act on this OS (drives the
#                    dashboard's Role selector / Presales L0-L2 filter)
#   BUYER_PERSONAS = who the actual buyer is on the customer side (shown in the
#                    detail panel as context, not used for filtering)
ROLES = ["Strategist", "Sales", "Presales"]

BUYER_PERSONAS = [
    "CIOs", "IT and network executives", "Security executives",
    "COOs & production executives", "CMOs & CX executives", "CISOs", "CDOs",
    "Industrial safety managers", "Quality managers",
]

# --- Orange Business geography, for the "geography" enrichment field ---

# --- Orange Business geography, for the "geography" enrichment field ---
# Sieg 25/8 -- replaced the old 5-continent-level list with the Innovation
# Radar's actual regional grouping (client brief, 25/8).
#
# GEOS: plain region names -- used wherever only the label matters (e.g. a
# future dashboard filter dropdown).
#
# GEOS_PROMPT: the SAME regions, but spelling out which countries each one
# covers -- used only in scoring.py's enrichment prompt. Several of these
# are NON-standard and a bare label would invite the LLM to guess wrong:
#   - "DACH" here is Switzerland + Austria ONLY -- Germany is broken out as
#     its own region, unlike the usual DACH convention that includes it.
#   - Israel sits under "Southern Europe", not "Middle East".
# Rest-of-world regions (Africa, Middle East, Asia Pacific, Americas) have
# no per-country breakdown -- continent-level is enough, per the brief.
#
# Keep these two in sync by hand if the grouping ever changes again.
GEOS = [
    "Benelux", "Germany", "Southern Europe", "DACH", "UK & Ireland",
    "Nordics", "Eastern Europe", "Africa", "Middle East", "Asia Pacific", "Americas",
]

GEOS_PROMPT = (
    "Benelux (Netherlands, Belgium, Luxembourg), "
    "Germany (Germany), "
    "Southern Europe (Italy, Spain, Portugal, Israel), "
    "DACH (Switzerland, Austria), "
    "UK & Ireland (United Kingdom, Ireland), "
    "Nordics (Norway, Sweden, Denmark, Finland, Iceland), "
    "Eastern Europe, Africa, Middle East, Asia Pacific, Americas"
)
HORIZONS = ["Now", "Next", "Later"]  # Now = sellable this quarter, Next = 6-12mo, Later = exploratory

# ============================================================
# VERTICALS -- the single source of truth for what we cover.
# ============================================================

VERTICAL_SEEDS = {
    "Manufacturing": "private 5G edge AI manufacturing safety",
    "Finance & Insurance": "agentic AI insurance claims automation",
    "Public Sector": "sovereign cloud EU government data",
    "Retail": "retail contact centre automation agentic AI",
    "Healthcare": "AI clinical workflow hospital data platform",
    "Energy": "AI grid optimization renewable energy IoT",
    "Transportation and Logistics": "AI fleet tracking supply chain IoT",
    # --- Added from the Orange Business corporate deck review (slides 12-14):
    # Orange has had "a particular focus on sectors where trust matters most:
    # Defense and Healthcare" since 2025, backed by dedicated divisions.
    # Healthcare was already covered above; Defense was completely missing.
    "Defense": "defense zero trust secure communications sovereign networks",
    # --- Added Aug 2026 from the client brief PDF (slide 6, "Business context
    # the radar must speak" -- CUSTOMER VERTICALS) and slide 11's opportunity-
    # space examples. This is the FULL list the client actually gave us; the
    # 8 verticals above were only ever a partial subset. Deliberately NOT
    # adding "Industry" as its own vertical -- the brief's own slide 11 lists
    # it right next to Manufacturing as a generic/overlapping term, and
    # core_taxonomy_definition.md flags the same overlap -- a separate
    # "Industry" vertical would just double-collect signals about the same
    # companies under two labels.
    "Automotive": "connected vehicle V2X 5G manufacturing cloud platform",
    "Construction": "IoT connected jobsite digital twin construction safety",
    "Life Sciences": "cloud data platform pharma clinical trial AI compliance",
    "Wholesale": "supply chain visibility IoT wholesale distribution cloud",
    "Media & Entertainment": "cloud content delivery streaming security AI",
    "Natural Resources": "IoT remote monitoring mining oil gas edge AI",
    # Kept distinct from "Defense" above -- Defense (slide 6) reads as the
    # government/military OPERATOR side (secure comms, sovereign networks,
    # procurement), while Aerospace & Defense (also slide 6, its own bullet)
    # reads as the aerospace/defense MANUFACTURING & supply-chain side. If
    # signals end up looking identical between the two after a few ingest
    # runs, that's a signal to merge them -- flag it in Decisions needed.
    "Aerospace & Defense": "aerospace defense manufacturing secure cloud cybersecurity",
    "Fast Moving Consumer Goods": "AI demand forecasting supply chain FMCG cloud",
    "IT and Services": "managed IT services cloud modernization cybersecurity",
}

VERTICALS = sorted(VERTICAL_SEEDS)

# --- Trust-critical verticals (corporate deck, slide 12) -- gets a small
# additive bonus in the strategic_relevance scoring component, since Orange
# is explicitly investing in these two sectors with dedicated divisions
# (250+ Defense experts, 1,000+ Healthcare experts -- see CAPABILITY_STATS).
# Aerospace & Defense added alongside Defense -- same trust/security-critical
# logic applies (dedicated Defense division, 250+ experts) even though it's
# tracked as a separate vertical from plain "Defense" -- see the vertical's
# own comment above for why they're kept separate rather than merged.
TRUST_CRITICAL_VERTICALS = {"Defense", "Healthcare", "Aerospace & Defense"}

GOOGLE_NEWS_QUERIES = [{"vertical": v, "query": q} for v, q in VERTICAL_SEEDS.items()]

ENABLE_GDELT = True
GDELT_QUERIES = GOOGLE_NEWS_QUERIES  
ARXIV_QUERIES = GOOGLE_NEWS_QUERIES  #
SEMANTIC_SCHOLAR_QUERIES = ARXIV_QUERIES

COMPETITORS = [
    "NTT", "AT&T Business", "Vodafone Business", "BT Business",
    "Deutsche Telekom", "Colt Technology", "Verizon Business",
]
COMPETITOR_QUERIES = [
    {"vertical": v, "query": f"({' OR '.join(COMPETITORS)}) {q}"}
    for v, q in VERTICAL_SEEDS.items()
]

REGULATION_QUERIES = [
    {"vertical": v, "query": f"site:eur-lex.europa.eu {v} regulation"}
    for v in VERTICALS
]

# TED = EU public procurement -- buying signals (tenders).
# NOTE: this Google-News "site:ted.europa.eu" scrape is kept as a fallback only.
# The real source is TED_QUERIES below (pipeline.ingest.fetch_ted), which calls
# the actual TED Search API v3 and gets structured notices (buyer, CPV, deadline)
# instead of whatever Google indexed. ingest.py tries the real API first and
# only falls back to this Google-News version if ENABLE_TED is False.
BUYING_SIGNAL_QUERIES = [
    {"vertical": v, "query": f"site:ted.europa.eu {v} tender"}
    for v in VERTICALS
]

# ============================================================
# TED Search API v3 -- real EU public procurement data (buying signals)
# ============================================================
# https://api.ted.europa.eu/v3/notices/search -- public, keyless for search
# (only submitting/managing NOT-YET-published notices needs an API key).
# Docs: https://docs.ted.europa.eu/api/latest/index.html
# Fair-usage policy: https://ted.europa.eu/en/simap/developers-corner-for-reusers-fair-usage-policy-TED
ENABLE_TED = True
TED_API_URL = "https://api.ted.europa.eu/v3/notices/search"
TED_LOOKBACK_DAYS = 730  # Sieg 24/8 -- widened from 180: was refetching the same window every run
                          # with nothing new to find. Also now the decay window for buying_signal
                          # in scoring.urgency_score() -- see that function's docstring.
TED_SLEEP_SECONDS = 2    # be a good citizen -- small gap between per-vertical calls

# Field names are eForms names (kebab-case), not the legacy 2-letter TED codes.
TED_FIELDS = [
    "publication-number", "notice-title", "buyer-name", "buyer-country",
    "publication-date", "deadline-receipt-tender-date-lot", "classification-cpv",
]

# One expert-search query per vertical, built from the same VERTICAL_SEEDS used
# for Google News/GDELT/arXiv -- reusing one seed phrase per vertical (rather
# than hand-writing a second, TED-specific list) keeps all sources searching for
# "the same thing" per vertical, which is what makes market_signal_strength and
# source_diversity meaningfully comparable across sources.
TED_QUERIES = [{"vertical": v, "query": f'FT~"{seed}"'} for v, seed in VERTICAL_SEEDS.items()]

# ============================================================
# NewsAPI.ai (Event Registry) -- broader, higher-quality news than the free
# Google News RSS scrape (proper full-text search, source filtering, no
# "hl=en" locale guessing). https://newsapi.ai -- 2,000 free tokens/month.
# ============================================================
ENABLE_NEWSAPI_AI = True
NEWSAPI_AI_URL = "https://eventregistry.org/api/v1/article/getArticles"
NEWSAPI_AI_SLEEP_SECONDS = 1
NEWSAPI_AI_QUERIES = [{"vertical": v, "query": q} for v, q in VERTICAL_SEEDS.items()]  # same seeds again, same reasoning as TED_QUERIES above

VENDOR_FEEDS = [
    {"name": "AWS News Blog", "url": "https://aws.amazon.com/blogs/aws/feed/"},
    {"name": "Microsoft Azure Blog", "url": "https://azure.microsoft.com/en-us/blog/feed/"},
    {"name": "NVIDIA Blog", "url": "https://blogs.nvidia.com/feed/"},
    {"name": "Cisco Blog", "url": "https://blogs.cisco.com/feed"},
]

HN_QUERIES = ["private 5G", "agentic AI insurance", "sovereign cloud", "AI contact center", "grid AI"]

# --- Strategic Value Propositions (corporate deck, slide 17/20) -- mapping
# target for "strategic relevance" scoring. Without this, the 15% weight
# given to strategic_relevance was a pure LLM guess with nothing concrete to
# check it against. Each OS gets matched (best-effort, keyword-based) to the
# closest of Orange's 5 named value propositions.
class ValueProposition(str, Enum):
    SECURE_CONNECTIVITY = "NextGen Secured Connectivity"
    SECURE_CLOUD = "Secure Cloud Orchestration"
    GENAI_WORKFORCE = "GenAI Empowered Workforce"
    CUSTOMER_EXPERIENCE = "Orchestrate Customer Interactions"
    OPERATIONAL_EXPERIENCE = "Smart Manufacturing & Operations"


# Keyword hints for the lightweight classifier below. Not exhaustive --
# a starting seed list, extend as more opportunity spaces get scored.
VALUE_PROP_KEYWORDS = {
    ValueProposition.SECURE_CONNECTIVITY: ["sd-wan", "network", "5g", "connectivity", "sase"],
    ValueProposition.SECURE_CLOUD: ["cloud migration", "multi-cloud", "sovereign cloud", "cloud security", "cloud"],
    ValueProposition.GENAI_WORKFORCE: ["copilot", "generative ai", "agentic ai", "productivity", "collaboration"],
    ValueProposition.CUSTOMER_EXPERIENCE: ["contact center", "contact centre", "customer journey", "cx", "personalization"],
    ValueProposition.OPERATIONAL_EXPERIENCE: ["iot", "predictive maintenance", "computer vision", "ot", "manufacturing"],
}


def map_to_value_proposition(os_text):
    """Naive keyword matcher over 'vertical use_case technology', lowercased.
    Returns the first matching ValueProposition, or None if nothing matches
    -- None means 'no strategic relevance boost applied', not an error."""
    text = os_text.lower()
    for vp, keywords in VALUE_PROP_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return vp
    return None


# --- Rate-limit delays between requests, per source -- CRITICAL, do not remove.
# Without these, GDELT and Semantic Scholar throttle or temporarily ban the IP
# mid-ingest, which silently truncates signal collection for whichever
# verticals were still queued. Values are conservative on purpose; lowering
# them risks bans again, not just slower runs.
GDELT_SLEEP_SECONDS = 75          # GDELT DOC 2.0 API -- strict per-request throttling
GDELT_RETRY_WAIT_SECONDS = 15       # short in-call retry once on a single rate-limit hit
GDELT_COOLDOWN_MINUTES = 20         # after 2 consecutive blocks, skip the whole GDELT pass
                                     # for this long -- across runs too (tracked in logs/.source_cooldowns.json)
                                     # -- instead of burning through all verticals uselessly.

SEMANTIC_SCHOLAR_SLEEP_SECONDS = 20  # Semantic Scholar API -- unauthenticated rate limit
SEMANTIC_SCHOLAR_RETRY_WAIT_SECONDS = 15
SEMANTIC_SCHOLAR_COOLDOWN_MINUTES = 20
# Optional -- Semantic Scholar's unauthenticated pool is shared across everyone
# hitting the API at once and gets rate-limited fast. A free "partner" API key
# (request form at https://www.semanticscholar.org/product/api#api-key-form,
# approval isn't instant) moves you to your own, much higher-limit pool. Until
# then, the cooldown+retry logic below is the practical fix.
SEMANTIC_SCHOLAR_API_KEY = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "")
ARXIV_SLEEP_SECONDS = 3              # arXiv asks for >=3s between requests, be a good citizen
GOOGLE_NEWS_SLEEP_SECONDS = 1        # light, but still spaced out across 7 verticals

NEWSAPI_AI_KEY = os.environ.get("NEWSAPI_AI_KEY", "")

# --- Orange Business real product APIs (from apiforbusiness catalog) ---
# Used to ground strategic_relevance/right-to-win scoring: an opportunity
# space scores higher when it maps to a real, currently sellable Orange
# Business asset, not just a generic "fits the Cloud domain" guess.
ORANGE_BUSINESS_ASSETS = [
    {"name": "API Satellite", "category": "Relation client"},
    {"name": "API Mobile Suite", "category": "Mobilite"},
    {"name": "API M2M for IoT Connect Express", "category": "Data, IA & IoT"},
    {"name": "API Contact Everyone", "category": "Collaboration & Teletravail"},
    {"name": "API Cloud Avenue", "category": "Cloud"},
    {"name": "API Live Identity Captcha", "category": "Securite"},
    {"name": "API Live Identity Verify", "category": "Securite"},
    {"name": "API Flexible SDWAN Cisco", "category": "Internet & Reseaux"},
    {"name": "API Business Talk Digital", "category": "Telephonie fixe & Voix"},
    {"name": "API Evolution Platform", "category": "Relation client"},
    {"name": "API Incident", "category": "Securite"},
    {"name": "API View Bill", "category": "Relation client"},
    {"name": "API Maintenance", "category": "Relation client"},
    {"name": "API Mobile", "category": "Relation client"},
    {"name": "API Ordering et Order Tracking", "category": "Relation client"},
    {"name": "API Eligibility", "category": "Internet & Reseaux"},
    {"name": "API Core Information", "category": "Relation client"},
]

# --- External validation, wired into strategic_relevance / right-to-win prompts
# NOTE: this used to be defined TWICE in this file (an earlier, shorter version
# followed immediately by this fuller one -- the first was dead code, since the
# second simply overwrote it at import time). Removed the duplicate; nothing
# else needed to change since every caller already only ever saw this version.
ANALYST_RECOGNITION = [
    {
        "fact": "Orange Business recognized as a Leader for the 23rd consecutive year "
                "in the Gartner Magic Quadrant 2026 for Global WAN Services",
        "source": "orange-business.com/en/about-us/analysts/gartner-recognition-for-global-wan-services",
    },
    {
        "fact": "Orange Business holds a 4.4/5 overall rating on Gartner Peer Insights "
                "(16 verified reviews, Unified Communications as a Service market)",
        "source": "gartner.com/reviews/market/unified-communications-as-a-service/vendor/orange-business",
    },
    # --- Added from the corporate deck (OB_Corporate_Presentation_ENG_2026) ---
    {
        "fact": "Orange Business named a Leader in the Gartner Magic Quadrant 2026 "
                "for 4G and 5G Private Mobile Network Services",
        "source": "Orange Business corporate presentation, 2026",
    },
    {
        "fact": "Orange Business rated a Leader in GlobalData's 2025 Company Assessment "
                "for Global Enterprise",
        "source": "Orange Business corporate presentation, 2026",
    },
    {
        "fact": "158 analyst mentions and 56 Leader-tier reports in 2025",
        "source": "Orange Business corporate presentation, 2026",
    },
]

CUSTOMER_REFERENCES = [
    {
        "customer": "Saint-Gobain Glass",
        "vertical": "Manufacturing",
        "source": "https://www.orange-business.com/en/about-us/customer-stories/saint-gobain-glass",
    },
    {
        "customer": "De Lijn",
        "vertical": "Public Sector",
        "source": "https://www.orange-business.com/be-en/about-us/customer-stories/lijn-data-visualization-enhances-public-transport-service",
    },
    {
        "customer": "SPF Finances (Belgian Federal Public Service Finance)",
        "vertical": "Public Sector",
        "source": "https://www.orange-business.com/be-en/about-us/customer-stories/dynamic-webshop-belgian-federal-public-service-finance",
    },
    {
        "customer": "DINUM (French Inter-ministerial Directorate for Digital Affairs)",
        "vertical": "Public Sector",
        "source": "https://www.orange-business.com/en/case-study/simplifying-data-network-management-using-apis",
    },
    {
        "customer": "BNP Paribas",
        "vertical": "Finance & Insurance",
        "source": "https://www.orange-business.com/en/press/bnp-paribas-joins-forces-orange-business-services-deploy-sd-wan-1800-retail-sites-france",
    },
    {
        "customer": "Groupama",
        "vertical": "Finance & Insurance",
        "source": "https://www.orange-business.com/en/case-study/groupama-designs-digital-and-mobile-journey",
    },
    # --- Added Aug 2026, checked live on orange-business.com/en/about-us/customer-stories ---
    {
        "customer": "Tricots Saint James",
        "vertical": "Manufacturing",
        "source": "https://www.orange-business.com/en/about-us/customer-stories/tricots-saint-james-entrusting-all-its-it-management-orange-business",
    },
    {
        "customer": "MicroPort CardioFlow",
        "vertical": "Healthcare",
        "source": "https://www.orange-business.com/en/about-us/customer-stories/microport-cardioflow-enabling-reliable-remote-heart-monitoring-through",
    },
    {
        "customer": "Boulanger",
        "vertical": "Retail",
        "source": "https://www.orange-business.com/en/about-us/customer-stories/ai-conversational-agent-customer-service-expertime-helped-boulanger-move",
    },
    {
        "customer": "Banqsoft",
        "vertical": "Finance & Insurance",
        "source": "https://www.orange-business.com/en/about-us/customer-stories/foundation-innovation-how-banqsoft-builds-european-cloud-platform",
    },
    {
        "customer": "St\u00f8",
        "vertical": "Finance & Insurance",
        "source": "https://www.orange-business.com/en/about-us/customer-stories/sto-sovereign-services-banking-finance",
    },
    # No named Defense customer story is public -- Skytale (secure comms platform,
    # Kubernetes, delivered "in record time") is the closest public proxy and is
    # tagged Public Sector rather than Defense to avoid overclaiming a sector match
    # the source page itself doesn't make.
    {
        "customer": "Skytale",
        "vertical": "Public Sector",
        "source": "https://www.orange-business.com/en/about-us/customer-stories/skytale-secure-communication-platform-delivered-record-time",
    },
    {
        "customer": "Grand Paris Sud (arenas)",
        "vertical": "Public Sector",
        "source": "https://www.orange-business.com/en/about-us/customer-stories/grand-paris-sud-arenas-secure-indoor-europe-esports-hub",
    },
    # --- Added Aug 2026, found via the client's two shared links (DINUM case
    # study page + its "Recommended for you" trail, and the customer-stories
    # homepage carousel) -- covers 4 more verticals that had zero real evidence.
    {
        "customer": "Aberg Connect",
        "vertical": "Automotive",
        "source": "https://www.orange-business.com/en/about-us/customer-stories/aberg-connect-launches-europe-wide-tire-pressure-monitoring-system",
    },
    {
        "customer": "Toyota",
        "vertical": "Automotive",
        "source": "https://www.orange-business.com/en/about-us/customer-stories/toyota-gets-connected-cars-right-lane-identify-traffic-hazard-spots",
    },
    {
        "customer": "Cainiao (Alibaba logistics arm)",
        "vertical": "Transportation and Logistics",
        "source": "https://www.orange-business.com/en/about-us/customer-stories/cainiao-partners-prioritize-customer-privacy-improve-trust",
    },
    {
        "customer": "Intis (unattended/autonomous retail)",
        "vertical": "Retail",
        "source": "https://www.orange-business.com/en/about-us/customer-stories/intis-connects-unattended-retail-around-world-televend",
    },
    {
        "customer": "TMF Group",
        "vertical": "IT and Services",
        "source": "https://www.orange-business.com/en/about-us/customer-stories/tmf-group-reduces-risk-enhances-services-hybrid-cloud",
    },
]

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
        roles=", ".join(ROLES), buyer_personas=", ".join(BUYER_PERSONAS), geos=", ".join(GEOS),
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


def score_all_opportunity_spaces(force=False, from_label=None):
    """Scores + enriches opportunity spaces, one pass.

    force=False (default): only opportunity spaces with no score yet or old scores see the loop below
    -- safe to re-run after every `radar_cli.py promote` without burning LLM quota re-scoring OS that
    haven't changed. ALSO repairs any OS stuck with a scores row but no
    right_to_win_scores row (interrupted run) --.
    force=True: rescore + re-enrich every opportunity space regardless.
    from_label: resume a --force run that got interrupted (e.g. Groq quota
    ran out mid-run) -- skips every OS whose label sorts BEFORE this one
    alphabetically, so already-redone OS aren't burned through again. Only
    meaningful together with force=True; ignored otherwise (unscored-only
    mode already naturally skips whatever got scored on the interrupted run)."""
    conn = get_connection()
    clean_scores(conn)

    if force:
        spaces = get_all_opportunity_spaces(conn)
    else:
        unscored_spaces = get_unscored_opportunity_spaces(conn)
        old_score_spaces = get_opportunity_spaces_with_old_scores(conn)
        # Merge the two lists and remove duplicates using the opportunity space ID
        spaces_by_id = {
            space["id"]: space
            for space in unscored_spaces + old_score_spaces
        }
        spaces = list(spaces_by_id.values())

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

    conn.close()


def recalibrate_deterministic_scores(conn=None):
    """Implements the 'Refresh Logic for already existing OSs' gap from
    current_project_state_overview.md: 'We have a process that
    adds new data and promotes new OSes, but it doesn't update the scores
    of existing OSes [...] the radar does not reflect the current market
    state for already known OSs.' Without this, an OS scored Monday with
    100 signals still shows Monday's score Tuesday even after 50 more
    signals arrive for it -- `radar_cli.py all` only ever scores NEW
    (unscored) OS, see score_all_opportunity_spaces()'s docstring.

    Recalculates market_signal_strength, source_diversity, novelty_momentum,
    and urgency_score for EVERY currently-scored OS, using each OS's
    CURRENT linked signals -- so run `radar_cli.py link` again first if new
    signals have come in since the last link; this function only reads
    opportunity_signals, it doesn't re-attach anything itself (link's own
    top_n logic is a bigger, separate operation not worth duplicating here).

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

    Run: python -m pipeline.scoring --refresh
    """
    close_after = conn is None
    if conn is None:
        conn = get_connection()

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

def clean_scores(connection) -> None:
    """
    Remove duplicate scores for the same opportunity_space_id,
    keeping only the most recent row based on computed_at.
    """

    connection.execute(
        """
        DELETE FROM scores
        WHERE id IN (
            SELECT id
            FROM (
                SELECT
                    id,
                    ROW_NUMBER() OVER (
                        PARTITION BY opportunity_space_id
                        ORDER BY computed_at DESC
                    ) AS row_number
                FROM scores
            )
            WHERE row_number > 1
        )
        """
    )



    connection.execute(
        """
        DELETE FROM right_to_win_scores
        WHERE id IN (
            SELECT id
            FROM (
                SELECT
                    id,
                    ROW_NUMBER() OVER (
                        PARTITION BY opportunity_space_id
                        ORDER BY computed_at DESC
                    ) AS row_number
                FROM right_to_win_scores
            )
            WHERE row_number > 1
        )
        """
    )

    connection.commit()


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
    for arg in sys.argv:
        if arg.startswith("--from="):
            from_label = arg.split("=", 1)[1]
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
    elif "--rescue-fallback" in sys.argv:
        rescue_fallback_scores()
    else:
        score_all_opportunity_spaces(force="--force" in sys.argv, from_label=from_label)
