"""
Central configuration for the Innovation Radar signal pipeline.

Every source query list (Google News, GDELT, arXiv, Semantic Scholar,
competitor watch, regulation, buying signals) used to be hand-written 3
times over, once per vertical, in 6 separate lists -- adding a vertical
meant editing 6 places and it was easy to miss one. VERTICAL_SEEDS below
fixes that: one dict, everything else derives from it.

Sieg 25/8 -- reorganized into clearly-delimited sections (was briefly split
into a pipeline/config/ package, reverted: a file-to-folder change is a much messier git merge
than a normal single-file diff for anyone with in-flight changes on the old
config.py). Section order below, same content as before, just labeled:
  1. TAXONOMY EXTENSIONS LOGIC   -- taxonomy_extensions.json load/create
  2. ENVIRONMENT                 -- .env loading, DB_PATH, API keys
  3. ENRICHMENT TAXONOMY         -- roles, geography, horizons
  4. VERTICALS                   -- the single source of truth
  5. USE CASES / TECHNOLOGIES / DOMAINS / SIGNAL TYPES
  6. INGEST SOURCE QUERIES & RATE LIMITS
  7. ORANGE BUSINESS REFERENCE DATA -- assets, customers, stats, partners
  8. VALUE PROPOSITION MATCHER
  9. OPPORTUNITY SPACE SEEDS (CANDIDATES)
Jump to a section by searching for its "# ====" header.
"""

import os
import json
from enum import Enum
from dotenv import load_dotenv


# ============================================================
# 1. TAXONOMY EXTENSIONS LOGIC
# ============================================================
# Sieg 24/8 -- integrated origianl from PR diff (Friday->today), not
# paraphrased, so this reads as her actual contribution when compared
# against that diff.

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


# ============================================================
# 2. ENVIRONMENT
# ============================================================
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

NEWSAPI_AI_KEY = os.environ.get("NEWSAPI_AI_KEY", "")

# Sieg 26/8 -- EPO OPS (patents) uses OAuth2 client_credentials, not a bare
# API key like NEWSAPI_AI_KEY above -- see ingest.py's fetch_epo() for the
# token exchange. Free account: https://developers.epo.org
EPO_CONSUMER_KEY = os.environ.get("EPO_CONSUMER_KEY", "")
EPO_SECRET_KEY = os.environ.get("EPO_SECRET_KEY", "")

# Optional -- Semantic Scholar's unauthenticated pool is shared across everyone
# hitting the API at once and gets rate-limited fast. A free "partner" API key
# (request form at https://www.semanticscholar.org/product/api#api-key-form,
# approval isn't instant) moves you to your own, much higher-limit pool. Until
# then, the cooldown+retry logic in section 6 below is the practical fix.
SEMANTIC_SCHOLAR_API_KEY = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "")


# ============================================================
# 3. ENRICHMENT TAXONOMY -- roles, geography, horizons
# ============================================================
# Split into two lists that used to be one merged `PERSONAS` list -- they answer
# two different questions and were getting confused with each other:
#   ROLES          = which Orange Business team should act on this OS (drives the
#                    dashboard's Role selector / Presales L0-L2 filter)
#   BUYER_PERSONAS = who the actual buyer is on the customer side. Originally
#                    detail-panel-only; Sieg 25/8 added a working sidebar
#                    multiselect for it in streamlit_app.py, so this IS now
#                    filterable too -- comment corrected 26/8, no code change.
ROLES = ["Strategist", "Sales", "Presales"]

BUYER_PERSONAS = [
    "CIOs", "IT and network executives", "Security executives",
    "COOs & production executives", "CMOs & CX executives", "CISOs", "CDOs",
    "Industrial safety managers", "Quality managers",
]

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
# 4. VERTICALS -- the single source of truth for what we cover
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
    # --- Added from the client brief PDF (slide 6, "Business context
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


# ============================================================
# 5. USE CASES / TECHNOLOGIES / DOMAINS / SIGNAL TYPES
# ============================================================

# Signal type vocabulary (must match the brief's taxonomy)
SIGNAL_TYPES = [
    "trend", "regulation", "buying_signal", "market_move", "tech_maturity", "proof_signal",
]

# Sieg 24/8 -- wrapped in list(dict.fromkeys(...)) and appended _EXT_USE_CASES
# so a term approved via `radar_cli.py review` (written to
# taxonomy_extensions.json by extend_taxonomy.py) actually reaches the LLM
# prompt in analyze.py on the next run, without ever duplicating a term
# that's already hand-listed below (dict.fromkeys preserves first-seen
# order and drops repeats).
USE_CASES_TAXONOMY = list(dict.fromkeys([
    "Energy Optimization", "Demand Forecasting", "IT Operations Automation",
    "Imaging Analytics", "Network Modernization & SD-WAN", "Cloud Infrastructure Modernization",
    "Cyber Defense & Zero Trust", "Customer Experience", "Employee Experience",
    "Operational Excellence", "Digital Infrastructure", "Data Sovereignty", "Cybersecurity",
    "Contact Centre Automation", "Clinical Workflow Automation", "Predictive Maintenance",
    "Supply Chain Visibility", "Grid Optimization",
    # --- Restored from emerging_themes.json review (see emerging_themes_review.md) ---
    "Industrial Digital Twin & Automation",  # 8 supporting signals -- strongest candidate in the batch
    "Citizen Participation Platforms",       # 7 supporting signals -- pairs with existing Cloud Data Platform
    # Sieg 24/8 -- the rest of that same emerging_themes.json batch (OS029-034
    # in opportunity_spaces_summary.md) were promoted into real opportunity
    # spaces, but their use_case labels never actually made it into this
    # list -- so analyze.py's LLM prompt still can't legally propose them
    # again for a NEW signal in the same vertical, even though they're
    # already proven, scored, real opportunities in the DB.
    "Manufacturing Process Automation",              # OS034
    "Infrastructure Planning & Management",          # OS032
    "Post-Quantum Cryptography Testing Infrastructure",  # OS030
    "Strategic Communications & Advertising Consultancy",  # OS031
] + _EXT_USE_CASES))

# Sieg 24/8 -- same wrapping as USE_CASES_TAXONOMY above, same reason.
TECHNOLOGIES_TAXONOMY = list(dict.fromkeys([
    "Cloud Data Platform", "IoT Platforms", "Computer Vision", "Machine Learning",
    "Generative AI", "Network & SD-WAN", "Cloud", "Cybersecurity", "5G", "IoT", "AI, Data, Cloud",
    "Agentic AI", "Edge Computing",
    # --- Restored from emerging_themes.json review (see emerging_themes_review.md) ---
    "Digital Twins",  # 8 supporting signals -- pairs with Industrial Digital Twin & Automation above
    "Quantum-safe Cryptography",  # Sieg 24/8 -- same gap as above: backs OS030,
    # promoted and scored, but never added to this list until now.
] + _EXT_TECHNOLOGIES))

# --- Business domain taxonomy (matches the radar's sectors) ---
DOMAINS_TAXONOMY = [
    {"code": "ox", "name": "Smart Industries"},
    {"code": "conn", "name": "Connectivity Solutions"},
    {"code": "cyber", "name": "Cybersecurity"},
    {"code": "cloud", "name": "Cloud"},
    {"code": "cx", "name": "Customer Experience"},
    {"code": "ex", "name": "Employee Experience"},
]

# --- Portfolio distance taxonomy (right-to-win classification) ---
PORTFOLIO_DISTANCE = {
    "L0": {"label": "Direct offer", "blurb": "An existing Orange Business offer addresses this as-is."},
    "L1": {"label": "Bundle", "blurb": "Two or more existing offers exist but are not yet packaged together."},
    "L2": {"label": "Partner-dependent", "blurb": "Needs a capability held by an existing partner, not Orange itself."},
    "L3": {"label": "Adjacent", "blurb": "Needs one capability to be built or acquired -- close, but not there yet."},
    "L4": {"label": "White space", "blurb": "No plausible path from the current portfolio."},
}

RECURRING_THEME_PROMOTION_THRESHOLD = 2


# ============================================================
# 6. INGEST SOURCE QUERIES & RATE LIMITS
# ============================================================

GOOGLE_NEWS_QUERIES = [{"vertical": v, "query": q} for v, q in VERTICAL_SEEDS.items()]

ENABLE_GDELT = True
# Sieg 26/8 -- GDELT (unlike Google News/arXiv/Semantic Scholar) rejects any
# query containing a keyword under ~3 characters ("Your search contained a
# keyword that was too short"), even mid-phrase. Almost every VERTICAL_SEEDS
# entry has "AI" (2 chars) or "EU" (2 chars) in it, which was silently
# killing most GDELT queries and burning through the 2-strikes-then-cooldown
# limit before reaching most verticals. Fixed here, not in VERTICAL_SEEDS
# itself, since Google News/arXiv/Semantic Scholar handle "AI"/"EU" fine and
# don't need the longer substitution.
_GDELT_SAFE_SUBSTITUTIONS = {"AI": "artificial intelligence", "EU": "European Union"}


def _gdelt_safe_query(seed):
    words = seed.split()
    return " ".join(_GDELT_SAFE_SUBSTITUTIONS.get(w, w) for w in words)


GDELT_QUERIES = [{"vertical": v, "query": _gdelt_safe_query(q)} for v, q in VERTICAL_SEEDS.items()]
ARXIV_QUERIES = GOOGLE_NEWS_QUERIES
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

# --- TED Search API v3 -- real EU public procurement data (buying signals) ---
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

# --- NewsAPI.ai (Event Registry) -- broader, higher-quality news than the
# free Google News RSS scrape (proper full-text search, source filtering, no
# "hl=en" locale guessing). https://newsapi.ai -- 2,000 free tokens/month. ---
ENABLE_NEWSAPI_AI = True
NEWSAPI_AI_URL = "https://eventregistry.org/api/v1/article/getArticles"
NEWSAPI_AI_SLEEP_SECONDS = 1
NEWSAPI_AI_QUERIES = [{"vertical": v, "query": q} for v, q in VERTICAL_SEEDS.items()]  # same seeds again, same reasoning as TED_QUERIES above

# --- EPO OPS (patents) -- new 26/8, added the night before the presentation.
# Patent filings are a strong innovation signal (real R&D spend, dated,
# company-attributed) that none of the other 9 sources capture.
# ENABLE_EPO defaults to False on purpose: flip to True in .env-adjacent code
# only once EPO_CONSUMER_KEY/EPO_SECRET_KEY are confirmed working (see
# ingest.py's fetch_epo() docstring for the quick curl test) -- don't let an
# untested 10th source risk the other 9 right before the demo. ---
ENABLE_EPO = False
EPO_AUTH_URL = "https://ops.epo.org/3.2/auth/accesstoken"
EPO_SEARCH_URL = "https://ops.epo.org/3.2/rest-services/published-data/search"
EPO_SLEEP_SECONDS = 2  # be a good citizen -- small gap between per-vertical calls
EPO_QUERIES = [{"vertical": v, "query": seed} for v, seed in VERTICAL_SEEDS.items()]  # same seeds again, same reasoning as TED_QUERIES above

VENDOR_FEEDS = [
    {"name": "AWS News Blog", "url": "https://aws.amazon.com/blogs/aws/feed/"},
    {"name": "Microsoft Azure Blog", "url": "https://azure.microsoft.com/en-us/blog/feed/"},
    {"name": "NVIDIA Blog", "url": "https://blogs.nvidia.com/feed/"},
    {"name": "Cisco Blog", "url": "https://blogs.cisco.com/feed"},
]

HN_QUERIES = ["private 5G", "agentic AI insurance", "sovereign cloud", "AI contact center", "grid AI"]

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

ARXIV_SLEEP_SECONDS = 3              # arXiv asks for >=3s between requests, be a good citizen
GOOGLE_NEWS_SLEEP_SECONDS = 1        # light, but still spaced out across 7 verticals


# ============================================================
# 7. ORANGE BUSINESS REFERENCE DATA -- assets, customers, stats, partners
# ============================================================

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
# fed the scoring at all: product/offering match (ORANGE_BUSINESS_ASSETS,
# matched by the LLM in scoring.llm_right_to_win) and people capability
# (CAPABILITY_STATS below, injected into the same prompt "if relevant").
# CRM customer overlap already has real data one line up (CUSTOMER_REFERENCES
# -- public customer-story pages, used as a CRM-overlap proxy since no
# internal CRM export is available to this team) and is now wired into a
# deterministic bonus in scoring.crm_customer_overlap_bonus(). opportunity_count
# and pipeline_value have NO equivalent anywhere in this repo -- left as
# empty dicts on purpose rather than invented numbers. scoring.py's
# pipeline_calibration_bonus() is a safe +0.0 no-op until a real per-vertical
# CRM export is dropped in here (keyed by the exact VERTICAL_SEEDS names,
# e.g. {"Manufacturing": 12}) -- needs a team decision on where that
# export comes from, see README "Needs a team decision".
OPPORTUNITY_COUNT_BY_VERTICAL = {}   # vertical -> int, from a CRM export (not populated yet)
PIPELINE_VALUE_BY_VERTICAL = {}      # vertical -> EUR value, from a CRM export (not populated yet)

CAPABILITY_STATS = [
    {"stat": "30,000 employees", "source": "Orange Business corporate presentation, 2026"},
    {"stat": "EUR 7.3bn revenue (2025)", "source": "Orange Business corporate presentation, 2026"},
    {"stat": "40,000+ B2B customers, 200+ countries", "source": "Orange Business corporate presentation, 2026"},
    {"stat": "70+ data centers across 5 continents", "source": "Orange Business corporate presentation, 2026"},
    {"stat": "18 SOCs and 15 CyberSOCs worldwide", "source": "Orange Business corporate presentation, 2026"},
    # --- Added from the corporate deck -- especially useful for Defense/
    # Healthcare right-to-win justifications, and for Manufacturing OS that
    # can cite a named partner ecosystem.
    {"stat": "Cyberdefense revenue grew 6.8% in 2025", "source": "Orange Business corporate presentation, 2026"},
    {"stat": "250+ dedicated Defense experts", "source": "Orange Business corporate presentation, 2026"},
    {"stat": "1,000+ dedicated Healthcare experts", "source": "Orange Business corporate presentation, 2026"},
    # --- Added from live orange-business.com pages (Aug 2026 check) ---
    {"stat": "Tier-1 global backbone present in 200+ countries and territories",
     "source": "orange-business.com/en/about-us/analysts/gartner-recognition-for-global-wan-services"},
    {"stat": "Evolution Platform (Network as a Service): SD-WAN, SASE and cloud connectivity "
             "combined through a single API/portal with on-demand, SLA-backed delivery",
     "source": "orange-business.com/en/about-us/analysts/gartner-recognition-for-global-wan-services"},
    # --- Added Aug 2026 from the orange-business.com homepage. NOTE: this page
    # states "65 countries: Team presence" and "30,000+ B2B customers", which
    # reads lower than the corporate-deck figures above (200+ countries,
    # 40,000+ customers) -- kept both rather than silently picking one, since
    # they're plausibly different official metrics (physical team/office
    # presence vs. network backbone reach) rather than a real contradiction.
    # Flag for the client meeting if it comes up: "which count is current?"
    {"stat": "5,500+ AI, Data and Cloud experts", "source": "orange-business.com homepage"},
    {"stat": "#1 global voice and data network; team presence in 65 countries on all continents; "
             "6 major Service Centers", "source": "orange-business.com homepage"},
]

# --- Named partner tiers (corporate deck) -- citable in right-to-win
# justifications when an OS's technology aligns with one of these partners
# (e.g. an AWS-based Cloud OS, a Cisco-based SD-WAN OS).
PARTNER_TIERS = {
    "Cisco": "Global Gold Partner",
    "AWS": "Advanced Partner, MSP",
    "Palo Alto Networks": "Diamond, #1 EMEA Partner",
    "Microsoft": "Gold (MAICPP), Partner of the Year",
    "Google Cloud": "Premier",
}


# ============================================================
# 8. VALUE PROPOSITION MATCHER
# ============================================================
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


# ============================================================
# 9. OPPORTUNITY SPACE SEEDS (CANDIDATES) -- growing beyond a fixed list
# ============================================================

CANDIDATES = [
    ("OS001", "Public Sector", "Sovereign citizen data hosting", "Sovereign cloud + GPU inference"),
    ("OS002", "Manufacturing", "Fire and hazard detection", "Edge computer vision (Raspberry Pi class)"),
    ("OS003", "Finance & Insurance", "Conduct-risk / compliance monitoring", "AI surveillance of communications"),
    ("OS004", "Manufacturing", "Remote-controlled industrial robots", "Vision-guided teleoperation"),
    ("OS005", "Manufacturing", "Energy Optimization", "IoT Platforms"),
    ("OS006", "Manufacturing", "Operational Excellence", "Machine Learning"),
    ("OS007", "Manufacturing", "Cyber Defense & Zero Trust", "Cybersecurity"),
    ("OS008", "Manufacturing", "Imaging Analytics", "Computer Vision"),
    ("OS009", "Finance & Insurance", "Cloud Infrastructure Modernization", "Cloud"),
    ("OS010", "Finance & Insurance", "Cybersecurity", "Machine Learning"),
    ("OS011", "Finance & Insurance", "Customer Experience", "Generative AI"),
    ("OS012", "Finance & Insurance", "IT Operations Automation", "Machine Learning"),
    ("OS013", "Public Sector", "Data Sovereignty", "Cloud"),
    ("OS014", "Public Sector", "Cyber Defense & Zero Trust", "Cybersecurity"),
    ("OS015", "Public Sector", "Digital Infrastructure", "IoT Platforms"),
    # ============================================================
    # OS9xx -- one seed per vertical that had ZERO CANDIDATES coverage
    # (see the Aug 2026 VERTICAL_SEEDS expansion above: 14 of the 17
    # verticals had never had a single hand-picked opportunity space).
    # Labeled OS901+ SPECIFICALLY to avoid colliding with organically
    # promoted OS -- radar_cli.py promote()/next_opportunity_space_label()
    # grow labels upward from OS016, and the live DB already has OS020,
    # OS039, etc. from real signal promotion. If OS001-OS015 above ever
    # grow that high too, bump this block's starting number accordingly.
    #
    # Deliberately NOT exhaustive (one each, not several) -- with 5 days to
    # the client presentation, the goal is to get every vertical a starting
    # point on the radar now, not a fully researched shortlist. Real signal
    # volume over the week (ingest -> analyze -> promote) is what should
    # actually validate or kill these -- treat a low attractiveness/evidence
    # score here as informative, not a bug.
    # ============================================================
    # OS901 removed (Aug 2026): "Retail x Contact Centre Automation x Agentic AI"
    # got independently rediscovered by the real ingest -> analyze -> promote
    # pipeline as OS026 -- keeping this manual seed would just duplicate real,
    # signal-backed data. Good news, not a bug: it means the seed was a solid
    # bet, confirmed by actual market signals rather than just intuition.
    # Grounded in MicroPort CardioFlow (remote monitoring) + the HDS/Enovacom
    # eHealth certification (Orange Business' dedicated Healthcare division).
    ("OS040", "Healthcare", "Clinical Workflow Automation", "Machine Learning"),
    # Grounded in the anonymous energy customer story ("An energy provider
    # adopts generative AI to produce field service reports in a flash").
    ("OS041", "Energy", "Employee Experience", "Generative AI"),
    # OS904 removed (Aug 2026): "Transportation and Logistics x Supply Chain
    # Visibility x IoT Platforms" got independently rediscovered as OS036 --
    # same situation as OS901 above.
    # Grounded in Skytale (secure comms platform, delivered in weeks) -- the
    # closest public proxy we have, even though that story itself is tagged
    # Public Sector (see CUSTOMER_REFERENCES note on why Defense/Aerospace &
    # Defense have no direct public customer story).
    ("OS042", "Defense", "Cyber Defense & Zero Trust", "Cybersecurity"),
    # Grounded in Aberg Connect (Europe-wide tire pressure monitoring) + Toyota
    # (connected cars, traffic hazard detection).
    ("OS043", "Automotive", "Predictive Maintenance", "IoT Platforms"),
    # Grounded in emerging_themes.json's "Industrial Digital Twin & Automation"
    # theme (8 supporting signals, the strongest candidate in that batch --
    # see emerging_themes_review.md) -- Construction fits it as well as
    # Manufacturing does.
    ("OS044", "Construction", "Industrial Digital Twin & Automation", "Digital Twins"),
    # No direct customer story yet -- generic but taxonomy-clean seed; GDPR/AI
    # Act-driven data residency is a real, current pattern for pharma/clinical
    # data (see Data Management page: "compliance with GDPR, NIS2, and the AI
    # Act" from the Data & AI expertise page).
    ("OS045", "Life Sciences", "Data Sovereignty", "Cloud"),
    # No direct customer story yet -- same supply-chain-visibility pattern as
    # Transportation and Logistics (OS904), applied to wholesale distribution.
    ("OS046", "Wholesale", "Supply Chain Visibility", "IoT Platforms"),
    # Grounded in the Managed DDoS Protection product (real, sellable asset --
    # see ORANGE_BUSINESS_ASSETS) -- streaming/media infrastructure is a
    # classic DDoS target.
    ("OS047", "Media & Entertainment", "Cyber Defense & Zero Trust", "Cybersecurity"),
    # Directly lifted from the client brief PDF's own "what a good opportunity
    # topic looks like" example (slide "Some examples"): "Private 5G + edge
    # vision for safety compliance in mining." This is the strongest
    # candidate for a real "pepite" in this batch -- it's literally the
    # brief's model answer, not a guess.
    ("OS048", "Natural Resources", "Operational Excellence", "Computer Vision"),
    # Same trust-critical logic as Defense (OS905) -- see TRUST_CRITICAL_VERTICALS.
    ("OS049", "Aerospace & Defense", "Cyber Defense & Zero Trust", "Cybersecurity"),
    # Matches this vertical's own VERTICAL_SEEDS search seed almost exactly
    # ("AI demand forecasting supply chain FMCG cloud").
    ("OS050", "Fast Moving Consumer Goods", "Demand Forecasting", "Machine Learning"),
    # Grounded in TMF Group (hybrid cloud, risk reduction) -- see CUSTOMER_REFERENCES.
    ("OS051", "IT and Services", "Cloud Infrastructure Modernization", "Cloud"),
]