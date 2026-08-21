"""
Central configuration for the Innovation Radar signal pipeline.

Every source query list (Google News, GDELT,
arXiv, Semantic Scholar, competitor watch, regulation, buying signals) used
to be hand-written 3 times over, once per vertical, in 6 separate lists, aAdding a vertical
meant editing 6 places and it was easy to miss one.

"""

import os

DB_PATH = "radar.db"

ROLES = ["Strategist", "Sales", "Presales"]

BUYER_PERSONAS = [
    "CIOs", "IT and network executives", "Security executives",
    "COOs & production executives", "CMOs & CX executives", "CISOs", "CDOs",
    "Industrial safety managers", "Quality managers",
]

# --- Orange Business geography, for the "geography" enrichment field ---

GEOS = ["Europe", "Africa", "Middle East", "Asia Pacific", "Americas"]

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
}

VERTICALS = sorted(VERTICAL_SEEDS)

# Academic-style phrasing, used ONLY for arXiv / Semantic Scholar.
# Press-release wording (VERTICAL_SEEDS) doesn't match how papers are
# titled, so a few verticals get a reworded query here. Any vertical NOT
# listed just falls back to its normal VERTICAL_SEEDS query below --
# this is additive, not a second full list to maintain.
ACADEMIC_SEEDS_OVERRIDE = {
    "Manufacturing": "edge computer vision industrial safety",
    "Finance & Insurance": "agentic AI claims automation",
    "Public Sector": "sovereign cloud data governance",
}

GOOGLE_NEWS_QUERIES = [{"vertical": v, "query": q} for v, q in VERTICAL_SEEDS.items()]

ENABLE_GDELT = True
GDELT_QUERIES = GOOGLE_NEWS_QUERIES

# arXiv / Semantic Scholar: use the academic override when we have one for
# this vertical, otherwise fall back to the standard VERTICAL_SEEDS query.
ARXIV_QUERIES = [
    {"vertical": v, "query": ACADEMIC_SEEDS_OVERRIDE.get(v, VERTICAL_SEEDS[v])}
    for v in VERTICALS
]
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
BUYING_SIGNAL_QUERIES = [
    {"vertical": v, "query": f"site:ted.europa.eu {v} tender"}
    for v in VERTICALS
]
VENDOR_FEEDS = [
    {"name": "AWS News Blog", "url": "https://aws.amazon.com/blogs/aws/feed/"},
    {"name": "Microsoft Azure Blog", "url": "https://azure.microsoft.com/en-us/blog/feed/"},
    {"name": "NVIDIA Blog", "url": "https://blogs.nvidia.com/feed/"},
    {"name": "Cisco Blog", "url": "https://blogs.cisco.com/feed"},
]

HN_QUERIES = ["private 5G", "agentic AI insurance", "sovereign cloud", "AI contact center", "grid AI"]

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
        "customer": "BNP Paribas",
        "vertical": "Finance & Insurance",
        "source": "https://www.orange-business.com/en/press/bnp-paribas-joins-forces-orange-business-services-deploy-sd-wan-1800-retail-sites-france",
    },
    {
        "customer": "Groupama",
        "vertical": "Finance & Insurance",
        "source": "https://www.orange-business.com/en/case-study/groupama-designs-digital-and-mobile-journey",
    },
]

CAPABILITY_STATS = [
    {"stat": "30,000 employees", "source": "Orange Business corporate presentation, 2026"},
    {"stat": "EUR 7.3bn revenue (2025)", "source": "Orange Business corporate presentation, 2026"},
    {"stat": "40,000+ B2B customers, 200+ countries", "source": "Orange Business corporate presentation, 2026"},
    {"stat": "70+ data centers across 5 continents", "source": "Orange Business corporate presentation, 2026"},
    {"stat": "18 SOCs and 15 CyberSOCs worldwide", "source": "Orange Business corporate presentation, 2026"},
]

# --- Portfolio distance taxonomy (right-to-win classification) ---
PORTFOLIO_DISTANCE = {
    "L0": {"label": "Direct offer", "blurb": "An existing Orange Business offer addresses this as-is."},
    "L1": {"label": "Bundle", "blurb": "Two or more existing offers exist but are not yet packaged together."},
    "L2": {"label": "Partner-dependent", "blurb": "Needs a capability held by an existing partner, not Orange itself."},
    "L3": {"label": "Adjacent", "blurb": "Needs one capability to be built or acquired -- close, but not there yet."},
    "L4": {"label": "White space", "blurb": "No plausible path from the current portfolio."},
}

# --- Business domain taxonomy (matches the radar's sectors) ---
DOMAINS_TAXONOMY = [
    {"code": "ox", "name": "Smart Industries"},
    {"code": "conn", "name": "Connectivity Solutions"},
    {"code": "cyber", "name": "Cybersecurity"},
    {"code": "cloud", "name": "Cloud"},
    {"code": "cx", "name": "Customer Experience"},
    {"code": "ex", "name": "Employee Experience"},
]

USE_CASES_TAXONOMY = [
    "Energy Optimization", "Demand Forecasting", "IT Operations Automation",
    "Imaging Analytics", "Network Modernization & SD-WAN", "Cloud Infrastructure Modernization",
    "Cyber Defense & Zero Trust", "Customer Experience", "Employee Experience",
    "Operational Excellence", "Digital Infrastructure", "Data Sovereignty", "Cybersecurity",
    "Contact Centre Automation", "Clinical Workflow Automation", "Predictive Maintenance",
    "Supply Chain Visibility", "Grid Optimization",
]

TECHNOLOGIES_TAXONOMY = [
    "Cloud Data Platform", "IoT Platforms", "Computer Vision", "Machine Learning",
    "Generative AI", "Network & SD-WAN", "Cloud", "Cybersecurity", "5G", "IoT", "AI, Data, Cloud",
    "Agentic AI", "Edge Computing",
]

# Signal type vocabulary (must match the brief's taxonomy)
SIGNAL_TYPES = [
    "trend", "regulation", "buying_signal", "market_move", "tech_maturity", "proof_signal",
]

# Seed opportunity spaces -- NOT a cap. `radar_cli.py create` registers
# these 15 as a starting point. Beyond them, the pipeline discovers new
# ones automatically and with no limit: every `python -m pipeline.analyze`
# run extracts Vertical x Use Case x Technology themes from fresh signals
# and bumps their frequency in the `recurring_themes` table; once a theme's
# frequency hits RECURRING_THEME_PROMOTION_THRESHOLD (below), `radar_cli.py
# promote` turns it into a brand-new OS (OS016, OS017, ... with no upper
# bound). This is exactly the mechanism that grew the set from 15 to 27 --
# see OS016-OS027 already in radar.db.

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
]

RECURRING_THEME_PROMOTION_THRESHOLD = 2
