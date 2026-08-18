"""
Central configuration for the Innovation Radar signal pipeline.
Edit SOURCES to add/remove feeds without touching ingest.py.
"""

DB_PATH = "radar.db"

# --- Google News RSS: one entry per (vertical, query) pair you want to track ---
# 3-4 queries per vertical, not 1 -- a single narrow query biases every
# downstream theme toward that one niche (e.g. Manufacturing was only ever
# returning 5G/edge-vision signals, so that's the only kind of theme the LLM
# could ever find). More queries = more signal volume, more source diversity,
# and candidate OS that actually reflect the vertical instead of one query.
GOOGLE_NEWS_QUERIES = [
    {"vertical": "Manufacturing", "query": "private 5G edge AI manufacturing safety"},
    {"vertical": "Manufacturing", "query": "predictive maintenance manufacturing AI"},
    {"vertical": "Manufacturing", "query": "supply chain automation digital twin manufacturing"},
    {"vertical": "Manufacturing", "query": "industrial IoT OT cybersecurity"},

    {"vertical": "Finance & Insurance", "query": "agentic AI insurance claims automation"},
    {"vertical": "Finance & Insurance", "query": "AI fraud detection banking"},
    {"vertical": "Finance & Insurance", "query": "regtech compliance automation financial services"},
    {"vertical": "Finance & Insurance", "query": "cloud modernization digital banking"},

    {"vertical": "Public Sector", "query": "sovereign cloud EU government data"},
    {"vertical": "Public Sector", "query": "AI public sector citizen services"},
    {"vertical": "Public Sector", "query": "government zero trust cybersecurity"},
    {"vertical": "Public Sector", "query": "smart city IoT infrastructure government"},
]

ENABLE_GDELT = True
GDELT_QUERIES = GOOGLE_NEWS_QUERIES  # reuse the same queries for consistency

# --- EUR-Lex RSS feeds (regulation signals) ---
# EUR-Lex lets you build a search RSS feed; start with these general ones
# and refine with more specific search terms once you see relevant results.
EURLEX_FEEDS = [
    {
        "name": "EUR-Lex - Digital / AI Act updates",
        "url": "https://eur-lex.europa.eu/EN/display-feed.rss?myRssId=DVJk...",  # placeholder: build your own via eur-lex.europa.eu "RSS" export
    },
]

# --- Vendor / tech blogs (RSS, no key needed) ---
VENDOR_FEEDS = [
    {"name": "AWS News Blog", "url": "https://aws.amazon.com/blogs/aws/feed/"},
    {"name": "Microsoft Azure Blog", "url": "https://azure.microsoft.com/en-us/blog/feed/"},
    {"name": "NVIDIA Blog", "url": "https://blogs.nvidia.com/feed/"},
    {"name": "Cisco Blog", "url": "https://blogs.cisco.com/feed"},
]

# --- Hacker News (Algolia API, no key) ---
HN_QUERIES = [
    "private 5G", "predictive maintenance manufacturing",
    "agentic AI insurance", "fraud detection banking",
    "sovereign cloud", "zero trust government",
]

# --- Competitor tracking (market_move / buying_signal) ---
# Same Google News + GDELT fetchers, just naming the direct competitors of
# Orange Business Europe explicitly so their moves show up as their own signals.
# Widened alongside GOOGLE_NEWS_QUERIES -- OR'ing in a second topic per
# vertical so competitor watch isn't stuck on the same single niche either.
COMPETITORS = ["NTT", "AT&T Business", "Vodafone Business", "BT Business",
               "Deutsche Telekom", "Colt Technology", "Verizon Business"]

COMPETITOR_QUERIES = [
    {"vertical": "Manufacturing", "query": f"({' OR '.join(COMPETITORS)}) (private 5G manufacturing OR predictive maintenance)"},
    {"vertical": "Finance & Insurance", "query": f"({' OR '.join(COMPETITORS)}) (AI insurance OR fraud detection banking)"},
    {"vertical": "Public Sector", "query": f"({' OR '.join(COMPETITORS)}) (sovereign cloud government OR zero trust)"},
]

# --- Scientific articles: arXiv (free, no key) ---
# arXiv covers CS/AI/networking preprints -- good proof of technical maturity.
# Widened to match GOOGLE_NEWS_QUERIES' topic spread per vertical.
ARXIV_QUERIES = [
    {"vertical": "Manufacturing", "query": "edge computer vision industrial safety"},
    {"vertical": "Manufacturing", "query": "predictive maintenance machine learning"},
    {"vertical": "Manufacturing", "query": "industrial IoT cybersecurity"},

    {"vertical": "Finance & Insurance", "query": "agentic AI claims automation"},
    {"vertical": "Finance & Insurance", "query": "fraud detection machine learning finance"},

    {"vertical": "Public Sector", "query": "sovereign cloud data governance"},
    {"vertical": "Public Sector", "query": "zero trust government cybersecurity"},
]

# --- Scientific articles: Semantic Scholar (free, no key for light use) ---
# Broader than arXiv -- covers non-CS fields too (health, energy, etc.).
SEMANTIC_SCHOLAR_QUERIES = ARXIV_QUERIES  # reuse the same queries as a starting point

# --- TED (Tenders Electronic Daily): EU public procurement notices ---
# Search API v3 is free and keyless for search/retrieval (auth is only
# needed to submit notices, not to read them). A published tender naming a
# technology is a stronger buying_signal than a news article about it.
TED_QUERIES = GOOGLE_NEWS_QUERIES  # reuse the same queries as a starting point

# --- NewsAPI.ai (Event Registry): broader multilingual news + NLP metadata ---
# Needs a free API key (2,000 tokens/month) -- register at https://newsapi.ai
# and set NEWSAPI_AI_KEY in .env. Set ENABLE_NEWSAPI_AI = False to skip
# entirely without touching ingest.py; the fetcher also self-skips if the
# key is missing, so leaving this True with no key is harmless.
ENABLE_NEWSAPI_AI = True
NEWSAPI_AI_QUERIES = GOOGLE_NEWS_QUERIES  # reuse the same queries as a starting point

# --- Orange Business real product APIs (from apiforbusiness catalog) ---
# Used to ground strategic_relevance scoring: an opportunity space scores
# higher when it maps to a REAL, currently sellable Orange Business asset,
# not just a generic "fits the Cloud domain" guess. This is the concrete
# "right to win" evidence the brief asks for.
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

# --- External analyst recognition (real, sourced) ---
# Used to strengthen right-to-win judgments with third-party validation, not
# just internal asset-matching. Add to this list as you find more (Gartner,
# IDC, Forrester, etc.) -- keep only ones you've actually verified the source of.
# NOTE: two different Orange Business pages give a different consecutive-year
# count for what appears to be the same Gartner network-services recognition
# (23 years on the dedicated WAN Services MQ page vs. 22 years on the general
# infrastructure landing page) -- kept both, sourced separately, unresolved.
# Cite the WAN Services one (dated, specific report) if only one is needed.
ANALYST_RECOGNITION = [
    {
        "source": "Gartner Magic Quadrant for Global WAN Services (2026)",
        "finding": "Leader for the 23rd consecutive year",
        "relevant_assets": ["API Flexible SDWAN Cisco", "API Evolution Platform"],
        "url": "https://www.orange-business.com/en/about-us/analysts/gartner-recognition-for-global-wan-services",
    },
    {
        "source": "Gartner Peer Insights -- Unified Communications as a Service",
        "finding": "4.4/5 stars across 16 verified reviews (Business Together as a Service, Cisco/Microsoft)",
        "relevant_assets": ["API Business Talk Digital", "API Contact Everyone"],
        "url": "https://www.gartner.com/reviews/market/unified-communications-as-a-service/vendor/orange-business",
    },
    {
        "source": "Gartner (via Orange Business digital infrastructure page)",
        "finding": "Ranked a global network services Leader for 22 consecutive years (see note above on the discrepancy)",
        "relevant_assets": ["API Flexible SDWAN Cisco", "API Evolution Platform", "API Cloud Avenue"],
        "url": "https://www.orange-business.com/en/business-needs/scalable-responsive-secure-digital-infrastructure",
    },
]

# --- Customer references (real, sourced from orange-business.com) ---
# Verified named customers, one per vertical they clearly match -- stronger
# right-to-win evidence than an asset existing alone, since it proves actual
# delivery, not just capability. Only listed where the vertical match is
# defensible; skip loose/adjacent fits rather than overclaiming.
CUSTOMER_REFERENCES = [
    {
        "customer": "BNP Paribas Group",
        "vertical": "Finance & Insurance",
        "detail": "Deployed SD-WAN across 1,800+ branches in France",
        "source": "https://www.orange-business.com/en/case-study/bnp-paribas-deploys-sd-wan-technology-more-1800-branches-france",
    },
    {
        "customer": "Groupama",
        "vertical": "Finance & Insurance",
        "detail": "End-to-end digital workplace support (device choice, Wi-Fi coverage, service catalog, user support strategy)",
        "source": "https://www.orange-business.com/en/business-needs/digital-work-experience",
    },
    {
        "customer": "AkzoNobel Packaging and Coatings",
        "vertical": "Manufacturing",
        "detail": "Network and internet security transformation protecting manufacturing IP",
        "source": "https://www.orange-business.com/en/business-needs/secure-enterprise",
    },
    {
        "customer": "Veolia Water Technologies",
        "vertical": "Manufacturing",
        "detail": "Multi-service IT/OT partnership supporting an industrial digitalization roadmap",
        "source": "https://www.orange-business.com/en/business-needs/operational-experience-optimize-industry-digitizing-processes",
    },
]

# --- Capability stats (real, sourced from orange-business.com) ---
# Scale/credibility facts, not tied to one vertical -- can strengthen ANY
# right-to-win judgment that leans on delivery capacity or security posture.
CAPABILITY_STATS = [
    "10,000+ digital infrastructure experts across cloud, connectivity and cybersecurity",
    "70+ global data centers, 220+ countries/territories of network coverage",
    "3,000 Orange Cyberdefense experts, 18 SOCs, 14 CyberSOCs, 90% of threats identified before business impact",
    "World's 5th largest Microsoft Teams integrator, 25-year Microsoft partner, 1,700 Microsoft certifications",
    "287 million customers served",
]

# --- Portfolio distance taxonomy (right-to-win classification) ---
# Answers a DIFFERENT question than attractiveness: not "is the market hot"
# but "can Orange actually sell this today, given what it already has".
# L0 = closest to sellable, L4 = furthest (no plausible path today).
PORTFOLIO_DISTANCE = {
    "L0": {"label": "Direct offer", "blurb": "An existing Orange Business offer addresses this as-is."},
    "L1": {"label": "Bundle", "blurb": "Two or more existing offers exist but are not yet packaged together."},
    "L2": {"label": "Partner-dependent", "blurb": "Needs a capability held by an existing partner, not Orange itself."},
    "L3": {"label": "Adjacent", "blurb": "Needs one capability to be built or acquired -- close, but not there yet."},
    "L4": {"label": "White space", "blurb": "No plausible path from the current portfolio."},
}

# Signal type vocabulary (must match the brief's taxonomy)
SIGNAL_TYPES = [
    "trend",
    "regulation",
    "buying_signal",
    "market_move",
    "tech_maturity",
    "proof_signal",
]

# --- Vertical / Use Case / Technology taxonomy (brief Phase 0) ---
# Draft starting point taken directly from the brief's example lists -- this is
# Gaetan's territory (Documentation Specialist, phases 0 & 3) to own and refine,
# not a solo decision. Wired into analyze.py's theme extraction so candidate OS
# use these exact labels instead of the LLM inventing its own each run.
TAXONOMY_VERTICALS = [
    "Manufacturing", "Retail", "Finance", "Public Sector", "Healthcare",
    "Defense", "Automotive", "Fast Moving Consumer Goods", "Industry",
    "IT and Services",
]

TAXONOMY_USE_CASES = [
    "Energy Optimization", "Demand Forecasting", "IT Operations Automation",
    "Imaging Analytics", "Network Modernization & SD-WAN",
    "Cloud Infrastructure Modernization", "Cyber Defence & Zero Trust",
    "Customer Experience", "Employee Experience", "Operational Excellence",
    "Digital Infrastructure", "Data Sovereignty", "Cybersecurity",
]

TAXONOMY_TECHNOLOGIES = [
    "Cloud Data Platform", "IoT Platforms", "Computer Vision",
    "Machine Learning", "Generative AI", "Network & SD-WAN", "Cloud",
    "Cybersecurity", "5G", "IoT", "AI",
]

# Phase 3 curation: technology values too generic to be a real Opportunity
# Space on their own (brief explicitly calls out "AI", "Cloud", "Cybersecurity"
# as reject-on-sight). Checked case-insensitively against the LLM's raw
# technology string.
GENERIC_TECHNOLOGY_TERMS = {"ai", "cloud", "cybersecurity"}