import sqlite3
import base64
import pandas as pd
import re
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import sys
from pathlib import Path


# Sieg 25/8 -- pipeline.db / pipeline.config replace original raw
# sqlite3 queries. Using the shared pipeline modules means one source of
# truth for the schema, and it picks up columns SELECT (domain, horizon, persona, buyer_persona, geography,
# urgency_score, next_action_*).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline.db import get_connection, get_latest_scores, get_all_opportunity_spaces
from pipeline.config import DOMAINS_TAXONOMY, HORIZONS, CAPABILITY_STATS


# ============================================================
# 0. PATHS DEFINITIONS
# ============================================================

current_file = Path(__file__).resolve()
parent_dir = current_file.parent
grand_parent_dir = current_file.parents[1]
assets_path = grand_parent_dir / "assets"

ICON_ORANGE_PATH = assets_path / "app_icon_orange.png"
LOGO_ORANGE_PATH = assets_path / "orange_business_master_logo_text_white.png"

DB_PATH = "radar.db"


# ============================================================
# 1. CONFIGURATION
# ============================================================

st.set_page_config(
    page_title="Orange Business Innovation Radar",
    page_icon=str(ICON_ORANGE_PATH) if ICON_ORANGE_PATH.exists() else "🟠",
    layout="wide",
)


# ============================================================
# 2. BRANDING CSS
# ============================================================

st.markdown("""
<style>
    /* Font Helvetica Neue */
    html, body, [class*="css"] {
        font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif !important;
    }
    
    /* Global background */
    .stApp {
        background-color: #F6EEDE;
    }
    
    /* Sidebar styling */
    [data-testid="stSidebar"] {
        background-color: #002244;
        color: white;
    }
    
    /* Sidebar text (labels, captions, titles) stays white */
    [data-testid="stSidebar"] .stMarkdown,
    [data-testid="stSidebar"] .stCaption,
    [data-testid="stSidebar"] .stSelectbox label,
    [data-testid="stSidebar"] .stMultiSelect label,
    [data-testid="stSidebar"] .stRadio label,
    [data-testid="stSidebar"] .stCheckbox label {
        color: white !important;
    }

    /* Container for the role group (label + options) – one box */
    [data-testid="stSidebar"] .stRadio {
        background-color: rgba(255,255,255,0.1);
        border-radius: 8px;
        padding: 8px;
        margin-bottom: 5px;
        border: 1px solid rgba(255,255,255,0.2);
    }

    /* Forces radio option TEXT to white (covers multiple inner elements) */
    [data-testid="stSidebar"] .stRadio label p,
    [data-testid="stSidebar"] .stRadio label span,
    [data-testid="stSidebar"] .stRadio label div {
        color: white !important;
    }

    /* Extra fallback for the radio group's labels */
    [data-testid="stSidebar"] .stRadio [role="radiogroup"] label {
        color: white !important;
    }

    /* Dark text inside selectbox / multiselect fields */
    [data-testid="stSidebar"] .stSelectbox div[data-baseweb="select"] > div,
    [data-testid="stSidebar"] .stMultiSelect div[data-baseweb="select"] > div {
        color: #002244 !important;
    }

    /* Arrow and X (clear) icons */
    [data-testid="stSidebar"] .stSelectbox svg,
    [data-testid="stSidebar"] .stMultiSelect svg {
        fill: #002244 !important;
        color: #002244 !important;
    }

    /* Chips (pills) inside the multiselect */
    [data-testid="stSidebar"] .stMultiSelect span[data-baseweb="tag"] {
        background-color: #FF7900 !important;
        color: #002244 !important;
    }

    [data-testid="stSidebar"] .stMultiSelect span[data-baseweb="tag"] span {
        color: #002244 !important;
    }

    /* Dropdown options (menu open) */
    [data-testid="stSidebar"] li[role="option"] {
        background-color: #FFFFFF !important;
        color: #002244 !important;
    }

    [data-testid="stSidebar"] li[role="option"]:hover {
        background-color: #F6EEDE !important;
    }
    
    /* Header */
    .orange-header {
        background-color: #002244;
        padding: 20px;
        border-radius: 10px;
        display: flex;
        align-items: center;
        gap: 20px;
        margin-bottom: 20px;
    }
    .orange-header .logo {
        width: 50px;
        height: 50px;
        background-color: #FF7900;
        border-radius: 8px;
        display: inline-block;
    }
    .orange-header h1 {
        color: white;
        margin: 0;
        font-size: 2rem;
    }
    .orange-header p {
        color: #FF7900;
        margin: 0;
        font-size: 1.2rem;
    }
    
    /* Boxes */
    .orange-box {
        background-color: #FF7900;
        color: white;
        padding: 15px;
        padding-bottom: 45px;
        border-radius: 10px;
        border-left: 5px solid #002244;
        margin-bottom: 10px;
        position: relative;
        height: 300px;
        overflow: hidden;
    }
    .orange-box::after {
        content: "";
        position: absolute;
        bottom: 10px;
        left: 50%;
        transform: translateX(-50%);
        width: 500px;
        height: 20px;
        background: white;
        border-radius: 2px;
    }

    .os-line {
        font-size: 1.3rem;
        margin-bottom: 12px;
    }

    .os-line b {
        font-weight: bold;
    }

    /* New classes for scores and explanation in the boxes */
    .os-scores {
        font-size: 1.1rem;
        margin-bottom: 15px;
        font-weight: 600;
    }

    .os-description {
        font-size: 1.1rem !important;
        line-height: 1.5 !important;
        font-style: italic;
    }
    
    /* KPI cards */
    .kpi-card {
        border-top: 2px solid #E0E0E0;
        padding-top: 10px;
        margin-bottom: 20px;
    }
    .kpi-card h2 {
        margin: 0;
        color: #002244;
        font-size: 2.4rem;
        font-weight: bold;
    }
    .kpi-card p {
        margin: 0;
        color: #666666;
        font-size: 1rem;
    }
    
    /* Personalized boxes */
    .info-box {
        background-color: #FFFFFF;
        border-left: 4px solid #FF7900;
        padding: 10px;
        border-radius: 5px;
        margin-bottom: 10px;
    }
    
    .warning-box {
        background-color: #FFF0CC;
        border-left: 4px solid #FF8C00;
        padding: 10px;
        border-radius: 5px;
        margin-bottom: 10px;
    }
    
    .success-box {
        background-color: #E6F4EA;
        border-left: 4px solid #34A853;
        padding: 10px;
        border-radius: 5px;
        margin-bottom: 10px;
    }
    
    /* Forces the font on each element */
    html, body, [class*="css"], [data-testid="stWidgetLabel"], [data-testid="stSelectbox"], [data-testid="stMultiSelect"] {
        font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif !important;
    }

    .score-pill {
        display: inline-block;
        background-color: rgba(255, 255, 255, 0.2);
        border: 1px solid rgba(255, 255, 255, 0.4);
        border-radius: 6px;
        padding: 4px 10px;
        font-weight: 700;
        font-size: 0.95rem;
        margin-right: 8px;
    }

    [data-testid="stContainer"] [data-testid="stVerticalBlock"] {
        border-top: 2px solid #E0E0E0;
        padding-top: 10px;
        margin-bottom: 20px;
    }
</style>
""", unsafe_allow_html=True
)

# Sieg 25/8 -- constants for the polar radar chart added in section 8:
# each domain gets an equal angular slice, each horizon (Now/Next/Later)
# gets a fixed radius band.
HORIZON_RADIUS = {"Now": 0.28, "Next": 0.60, "Later": 0.92}
DOMAIN_NAMES = [d["name"] for d in DOMAINS_TAXONOMY]
DOMAIN_ANGLE_WIDTH = 360 / max(1, len(DOMAIN_NAMES))


# ============================================================
# 3. HEADER
# ============================================================

if LOGO_ORANGE_PATH.exists():
    with open(LOGO_ORANGE_PATH, "rb") as f:
        logo_b64 = base64.b64encode(f.read()).decode("utf-8")
    st.markdown(
        f"""
        <div class="orange-header">
            <img src="data:image/png;base64,{logo_b64}" 
                 style="height: 60px; width: auto;">
            <div>
                <h1>Orange Business Innovation Radar</h1>
                <p>See what's hot for us</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )
else:
    st.markdown(
        """
        <div class="orange-header">
            <div class="logo"></div>
            <div>
                <h1>Orange Business Innovation Radar</h1>
                <p>See what's hot for us</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )


# ============================================================
# 2. CONNECTION TO THE DATABASE / DATA LOADING
# ============================================================


# Sieg 25/8 -- both functions above are replaced by one cached loader that
# calls the pipeline's own db helpers instead of hand-writing the same JOINs
# again (get_latest_scores already does the scores + right_to_win_scores
# JOIN). This also picks up domain/horizon/persona/buyer_persona/geography
# and the per-role next actions, and pre-loads every OS's signals in one pass (signals_by_os dict) instead of
# re-querying load_signals() on every click.
@st.cache_data(ttl=60)
def load_scores():
    """Pulls latest scores + enrichment + linked signals for every
    opportunity space currently in the database -- not limited to a
    hardcoded count, so this scales as `radar_cli.py promote` adds more."""
    conn = get_connection()
    rows = get_latest_scores(conn)
    df = pd.DataFrame([dict(r) for r in rows])

    total_os_count = len(get_all_opportunity_spaces(conn))

    if df.empty:
        conn.close()
        return df, {}, total_os_count

    # domain/horizon aren't in get_latest_scores() -- pull them from
    # opportunity_spaces directly rather than editing the shared query.
    # next_action_strategist/sales/presales added here too -- one action per
    # role instead of a single generic next_action.
    # added created_at to make Time Slider work
    extra = conn.execute(
        """SELECT id, domain, horizon, persona, buyer_persona, geography,
                  created_at, next_action_strategist, next_action_sales, next_action_presales
           FROM opportunity_spaces"""
    ).fetchall()
    extra_df = pd.DataFrame([dict(r) for r in extra])
    df = df.merge(extra_df, on="id", how="left")

    signals_by_os = {}
    for os_id in df["id"]:
        # collected_at added -- powers the "Evidence over time" momentum chart
        # in the Sources tab (group signal count by month).
        # Sieg 25/8 -- added s.signal_type and s.summary (weren't selected
        # before) so section 16 can restore "filter by evidence
        # type" control and the per-signal summary text, on top of the
        # evidence-over-time chart.
        # Sieg 26/8 -- added s.published_date too. collected_at is just
        # "when our ingest scraped it" (all 9 sources were scraped this
        # same week, so it's nearly a single value across the whole DB) --
        # published_date is the real publication date, spanning 2022-2026,
        # which is what the "Evidence over time" chart is actually supposed
        # to show. See section 16 for the switch.
        sig_rows = conn.execute(
            """SELECT s.source_name, s.title, s.source_url, s.collected_at,
                      s.published_date, s.signal_type, s.summary
               FROM opportunity_signals link
               JOIN signals s ON s.id = link.signal_id
               WHERE link.opportunity_space_id = ?""",
            (os_id,),
        ).fetchall()
        signals_by_os[os_id] = [dict(r) for r in sig_rows]

    conn.close()
    df["domain"] = df["domain"].fillna("Unassigned")
    df["horizon"] = df["horizon"].fillna("Later")
    df["buyer_persona"] = df["buyer_persona"].fillna("Unassigned")
    df["geography"] = df["geography"].fillna("Unassigned")
    return df, signals_by_os, total_os_count

# adding funtion to make Watchlist new terms and Proposals box appear
def load_taxonomy_data():
    """Loads watchlist_terms and proposals from the DB for the dashboard."""
    conn = get_connection()
    
    # Watchlist terms (out-of-taxonomy candidates)
    watchlist_rows = conn.execute(
        """SELECT term, category, vertical, frequency, status, last_seen
           FROM watchlist_terms
           ORDER BY frequency DESC
           LIMIT 10"""
    ).fetchall()
    watchlist_df = pd.DataFrame([dict(r) for r in watchlist_rows])
    
    # Proposals (pending review)
    proposal_rows = conn.execute(
        """SELECT vertical, proposed_use_case, proposed_technology, frequency, status
           FROM proposals
           WHERE status = 'pending'
           ORDER BY frequency DESC
           LIMIT 10"""
    ).fetchall()
    proposal_df = pd.DataFrame([dict(r) for r in proposal_rows])
    
    conn.close()
    return watchlist_df, proposal_df


# Sieg 25/8 -- helper functions for the polar radar chart and
# for syncing a chart click with the OS picker.
def domain_angle(domain, seed):
    """Deterministic-but-jittered angle inside this domain's sector, so
    points in the same domain don't stack exactly on top of each other."""
    try:
        idx = DOMAIN_NAMES.index(domain)
    except ValueError:
        idx = len(DOMAIN_NAMES)  # "Unassigned" -> its own extra sector
    center = idx * DOMAIN_ANGLE_WIDTH
    jitter = ((seed * 2654435761) % 1000 / 1000 - 0.5) * (DOMAIN_ANGLE_WIDTH * 0.7)
    return center + jitter


def radius_for(horizon, seed):
    base = HORIZON_RADIUS.get(horizon, 0.6)
    jitter = ((seed * 40503) % 1000 / 1000 - 0.5) * 0.12
    return max(0.05, min(0.98, base + jitter))


def sync_selection_from_click(event, session_key):
    """Reads a plotly_chart(on_select=...) click event and, if it's a NEW
    click (different from the last one we saw), pushes the clicked OS's
    label into st.query_params -- which is exactly what the "Opportunity
    space" dropdown below already uses to pick its default value, so this
    is the only wiring needed to link chart clicks -> detail panel.

    The session_state guard matters: Plotly keeps a point marked "selected"
    across reruns (e.g. when you change a sidebar filter), not just on the
    click itself. Without the guard, that stale selection would silently
    overwrite a label you'd since picked by hand in the dropdown, on every
    single rerun -- the dropdown would look "stuck" back on the old click.
    """
    if not event:
        return
    points = (event.get("selection") or {}).get("points") or []
    if not points:
        return
    label = points[0].get("customdata")
    if isinstance(label, (list, tuple)):  # plotly nests customdata per-point if set as 2D
        label = label[0] if label else None
    if label and st.session_state.get(session_key) != label:
        st.session_state[session_key] = label
        st.query_params["topic"] = label


# ============================================================
# 6. SIDEBAR — FILTERS
# ============================================================

st.sidebar.header("Filters")
st.sidebar.caption("Filter the radar by business vertical, portfolio distance, persona and geography.")

role = st.sidebar.radio(
    "Role",
    ["Strategist / Innovator", "Sales", "Presales / Proposal"],
    index=0,
)

df, signals_by_os, total_os_count = load_scores()

watchlist_df, proposal_df = load_taxonomy_data()

if df.empty:
    st.title("📡 Innovation Radar")
    if total_os_count == 0:
        st.warning(
            "No opportunity spaces registered yet in radar.db. Run the pipeline first:\n\n"
            "`python -m pipeline.ingest` → `python -m pipeline.analyze` → "
            "`python radar_cli.py create` → `python -m pipeline.scoring`"
        )
    else:
        st.warning(
            f"{total_os_count} opportunity space(s) registered, but none scored yet.\n\n"
            "Run `python -m pipeline.scoring`."
        )
    st.stop()

if role == "Presales / Proposal":
    # Mirrors the reference site: presales only sees things Orange can
    # actually deliver soon (L0-L2), not white-space bets.
    df_role = df[df["portfolio_distance"].isin(["L0", "L1", "L2"])]
else:
    df_role = df


# Sieg 25/8 -- same idea (multiselects, everything selected by default),
# extended from 2 filters (Vertical, Distance) to 6 (Vertical, Domain,
# Horizon, Buyer persona, Geography, Owning persona) since the pipeline now
# enriches every OS with those fields, plus a sort control so the table at
# the bottom isn't locked to Attractiveness only.
verticals = sorted(df_role["vertical"].dropna().unique())
domains = sorted(df_role["domain"].dropna().unique())

# Sieg 25/8 -- closes the "Persona filtering" gap from
# current_project_state_overview.md: this is the OWNING team field
# (opportunity_spaces.persona -- config.ROLES: Strategist/Sales/Presales,
# who should ACT on this OS), a different field from buyer_persona (who the
# customer-side contact is, filterable below) and from the top "Role" radio
# (which is the VIEWER's own role, only used to hide L3/L4 for Presales).
df_role["persona"] = df_role["persona"].fillna("Unassigned")
personas_available = sorted(df_role["persona"].dropna().unique())

# Buyer persona and geography are LLM-filled free fields (buyer_persona is a
# single value per OS; geography can be a comma-joined multi-value string --
# "Europe, Americas" -- so it needs a set-membership match, not .isin()).
buyer_personas_available = sorted(df_role["buyer_persona"].dropna().unique())
geographies_available = sorted({
    g.strip() for cell in df_role["geography"].dropna() for g in cell.split(",") if g.strip()
})


def _matches_any_geo(cell, picked):
    """True if any of the picked geographies appears in this OS's
    (possibly multi-value, comma-joined) geography field."""
    if not isinstance(cell, str) or not cell:
        return False
    cell_geos = {g.strip() for g in cell.split(",")}
    return bool(cell_geos & set(picked))


st.sidebar.markdown("### Filters")
picked_verticals = st.sidebar.multiselect("Vertical", verticals, default=verticals)
picked_domains = st.sidebar.multiselect("Domain", domains, default=domains)
picked_horizons = st.sidebar.multiselect("Horizon", HORIZONS, default=HORIZONS)
picked_personas = st.sidebar.multiselect(
    "Owning team (persona)", personas_available, default=personas_available,
    help="Which Orange Business team should act on this OS -- different from "
         "'Buyer persona' below (the customer-side contact).",
)
picked_buyer_personas = st.sidebar.multiselect(
    "Buyer persona", buyer_personas_available, default=buyer_personas_available
)
picked_geographies = st.sidebar.multiselect(
    "Geography", geographies_available, default=geographies_available
)

sort_by = st.sidebar.selectbox(
    "Order", ["Attractiveness", "Right to win", "Urgency", "Persona + Vertical"], index=0
)
sort_col = {"Attractiveness": "total_score", "Right to win": "right_to_win_score",
            "Urgency": "urgency_score"}.get(sort_by)  # None for "Persona + Vertical" -- handled below


# ============================================================
# 6. APPLICATION OF THE FILTERS
# ============================================================


# Sieg 25/8 -- same filter-then-empty-check pattern, extended to the 6
# filters above (added: owning-team persona) and sorted by whichever
# column/combination the sidebar "Order" control picked. Kept Gaëtan's
# early stop-on-empty here -- it's a good guard my original streamlit_app.py
# didn't have, and without it a 0-result filter combination used to render
# broken empty charts instead of a clear message.
filtered = df_role[
    df_role["vertical"].isin(picked_verticals)
    & df_role["domain"].isin(picked_domains)
    & df_role["horizon"].isin(picked_horizons)
    & df_role["persona"].isin(picked_personas)
    & df_role["buyer_persona"].isin(picked_buyer_personas)
    & df_role["geography"].apply(lambda c: _matches_any_geo(c, picked_geographies))
]

if sort_by == "Persona + Vertical":
    # Sieg 25/8 -- closes the "Persona + vertical ranking" gap from
    # current_project_state_overview.md, frontend side (see
    # db.get_scores_ranked_by_persona_vertical() for the backend/SQL
    # equivalent, usable outside Streamlit too, e.g. from Power BI).
    # Unassigned personas sort last within each group instead of ahead of
    # "Presales"/"Sales"/"Strategist" alphabetically.
    filtered = filtered.assign(_persona_sort=(filtered["persona"] == "Unassigned")).sort_values(
        ["_persona_sort", "persona", "vertical", "total_score"],
        ascending=[True, True, True, False],
    ).drop(columns="_persona_sort")
else:
    filtered = filtered.sort_values(sort_col, ascending=False)

if filtered.empty:
    st.warning("No Opportunity Spaces match your current filters.")
    st.stop()

st.sidebar.markdown(f"**{len(filtered)} of {total_os_count} spaces** match this role and filter")

with st.sidebar.expander("📊 Orange Business at a glance"):
    # CAPABILITY_STATS used to only ever feed the right-to-win LLM prompt --
    # never shown as raw facts anywhere a human could point to them directly
    # in a client meeting. Surfaced here as-is, source included.
    for stat in CAPABILITY_STATS:
        st.caption(f"**{stat['stat']}**  \n_{stat['source']}_")


# ============================================================
# 8. HERO SECTION — WHAT'S HOT NOW (orizzontale)
# ============================================================

st.markdown("### What's Hot Now")

top3 = filtered.nlargest(3, "total_score")

cols = st.columns(3)
for i, (idx, row) in enumerate(top3.iterrows()):
    with cols[i]:
        st.markdown(
            f"""
            <div class="orange-box">
                <div class="os-line">
                    <b>{row['label']}</b> — {row['vertical']} × {row['use_case']} × {row['technology']}
                </div>
                <div class="os-scores">
                    <span class="score-pill">Attractiveness: {row['total_score']:.2f}/10</span>
                    <span class="score-pill">R2W: {row['right_to_win_score']:.2f}/10</span>
                </div>
                <div class="os-description">
                    <i style="font-size: 1.2rem; line-height: 1.5; font-style: italic;">
                        {row['strategic_relevance_justification'] if pd.notna(row['strategic_relevance_justification']) else 'N/A'}
                    </i>
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )


# ============================================================
# 7. KPI OVERVIEW
# ============================================================

# Sieg 25/8 -- dropped the average attractiveness / average right-to-win
# metrics from original: the OS population isn't stable (new OS
# keep landing via `radar_cli.py promote`), so those averages move when
# the denominator changes, not when the market actually does -- misleading
# if read as a trend over time. Replaced with a count of "strong" OS
# (attractiveness >= 7 AND right-to-win >= 7 (to validate) -- same threshold as the ⭐
# quadrant message in the detail panel) and the median
# attractiveness instead of the mean, since a median is less distorted by
# a handful of not-yet-scored or extreme OS than an average is.
st.markdown("### At a Glance")

col1, col2, col3, col4, col5 = st.columns(5)

with col1:
    st.markdown(
        f"""
        <div class="kpi-card">
            <h2>{len(filtered)}</h2>
            <p>Opportunity Spaces</p>
        </div>
        """, unsafe_allow_html=True
    )

with col2:
    strong_count = (
            (filtered["total_score"] >= 7) & (filtered["right_to_win_score"] >= 7)
        ).sum()
    st.markdown(
        f"""
        <div class="kpi-card">
            <h2>{strong_count} / {len(filtered)}</h2>
            <p>⭐ Strong opportunities</p>
        </div>
        """, unsafe_allow_html=True
    )

with col3:
    median_attractiveness = filtered["total_score"].median()
    st.markdown(
        f"""
        <div class="kpi-card">
            <h2>{median_attractiveness:.2f}/10</h2>
            <p>Median Attractiveness</p>
        </div>
        """, unsafe_allow_html=True
    )

with col4:
    best_index = filtered["total_score"].idxmax()
    best_opportunity = filtered.loc[best_index, "label"]
    st.markdown(
        f"""
        <div class="kpi-card">
            <h2>{best_opportunity}</h2>
            <p>Top Opportunity</p>
        </div>
        """, unsafe_allow_html=True
    )

# Sieg 25/8 -- quadrant breakdown. It counts
# every OS in `filtered` into the same 4 buckets as the strategic-position
# quadrant in the detail panel (section 15), so the sidebar and the detail
# panel always agree on what "strong" / "needs capability" etc. mean.
#
with col5:
    strong = ((filtered["total_score"] >= 7) & (filtered["right_to_win_score"] >= 7)).sum()
    needs_capability = ((filtered["total_score"] >= 7) & (filtered["right_to_win_score"] < 7)).sum()
    moderate_market = ((filtered["total_score"] < 7) & (filtered["right_to_win_score"] >= 7)).sum()
    low_both = ((filtered["total_score"] < 7) & (filtered["right_to_win_score"] < 7)).sum()

    st.markdown("**By quadrant**")

    # Row 1
    row1 = st.columns(2)
    with row1[0]:
        st.metric("⭐ Strong", f"{strong}", 
                  help="⭐ Strong: High market potential and high probability of winning.")
    with row1[1]:
        st.metric("⚠️ Needs capability", f"{needs_capability}", 
                  help="⚠️ Needs capability: An interesting market, but it lacks internal capacity.")

    # Row 2
    row2 = st.columns(2)
    with row2[0]:
        st.metric("💡 Moderate market", f"{moderate_market}", 
                  help="💡 Moderate market: We have what it takes to win, but the market is less hot.")
    with row2[1]:
        st.metric("📉 Low both", f"{low_both}", 
                  help="📉 Low both: Low potential and low probability of winning.")



# ============================================================
# 8. RADAR
# ============================================================

st.subheader("Opportunity Radar")

# Time slider (based on Created At)
if "created_at" in filtered.columns:
    min_date = pd.to_datetime(filtered["created_at"]).min()
    max_date = pd.to_datetime(filtered["created_at"]).max()
    if pd.notna(min_date) and pd.notna(max_date) and min_date != max_date:
        date_range = st.slider(
            "Time interval (OS creation)",
            min_value=min_date.to_pydatetime(),
            max_value=max_date.to_pydatetime(),
            value=(min_date.to_pydatetime(), max_date.to_pydatetime()),
            format="YYYY-MM-DD",
            key="date_slider"
        )
        filtered = filtered[
            (pd.to_datetime(filtered["created_at"]) >= date_range[0]) &
            (pd.to_datetime(filtered["created_at"]) <= date_range[1])
        ].copy()

# The Radar
# Sieg 25/8 -- replaced the single scatter with two tabbed views: a polar
# radar (ring = horizon, sector = domain, color = right-to-win) as the
# primary one, plus original scatter-style layout kept alive as a "Bubble
# (classic)" tab, rebuilt with go.Figure for the dark theme and with one
# trace per vertical so the legend doubles as a highlight filter. Both
# charts support click-to-select (see sync_selection_from_click above).
col_radar, col_detail = st.columns([3, 2])

with col_radar:
    tab_radar, tab_bubble = st.tabs(["Radar (polar)", "Bubble (classic)"])

    with tab_radar:
        fig = go.Figure()

        color_vals = filtered["right_to_win_score"].fillna(0)
        size_vals = (filtered["total_score"].fillna(0) * 2.6 + 9)

        thetas = [domain_angle(d, seed) for d, seed in zip(filtered["domain"], filtered["id"])]
        radii = [radius_for(h, seed) for h, seed in zip(filtered["horizon"], filtered["id"])]

        fig.add_trace(go.Scatterpolar(
            r=radii,
            theta=thetas,
            mode="markers",
            marker=dict(
                size=size_vals,
                color=color_vals,
                colorscale=[[0, "#3a2410"], [0.5, "#ff7900"], [1, "#ffd7a8"]],
                cmin=0, cmax=10,
                colorbar=dict(
                    title=dict(text="Right to win", font=dict(color="#002244")),
                    tickfont=dict(color="#002244"),
                ),
                line=dict(width=1, color="#0e1117"),
            ),
            text=[
                f"{row.label} — {row.vertical} × {row.use_case} × {row.technology}<br>"
                # right_to_win_score can be None (LEFT JOIN -- OS scored on
                # attractiveness but not yet on right-to-win) -- ":.1f"
                # crashes on None, so show "not scored yet" instead of
                # crashing the whole dashboard.
                f"Attractiveness {row.total_score:.1f} · Right to win "
                f"{f'{row.right_to_win_score:.1f}' if pd.notna(row.right_to_win_score) else 'not scored yet'} "
                f"[{row.portfolio_distance}]"
                for row in filtered.itertuples()
            ],
            hoverinfo="text",
            customdata=filtered["label"],
        ))

        fig.update_layout(
            polar=dict(
                bgcolor="#F6EEDE",
                radialaxis=dict(
                    range=[0, 1],
                    tickvals=[HORIZON_RADIUS[h] for h in HORIZONS],
                    ticktext=[h.upper() for h in HORIZONS],
                    showline=False,
                    gridcolor="#D2B38E",
                    tickfont=dict(color="#002244"),
                ),
                angularaxis=dict(
                    tickvals=[i * DOMAIN_ANGLE_WIDTH for i in range(len(DOMAIN_NAMES))],
                    ticktext=DOMAIN_NAMES,
                    direction="clockwise",
                    gridcolor="#D2B38E",
                    tickfont=dict(color="#002244", size=15, family="Helvetica Neue, Helvetica, Arial, sans-serif"),
                ),
            ),
            paper_bgcolor="#F6EEDE",
            font=dict(family="Helvetica Neue, Helvetica, Arial, sans-serif", color="#D2B38E"),
            showlegend=False,
            height=480,
            margin=dict(l=40, r=140, t=60, b=60)
        )

        radar_event = st.plotly_chart(
            fig, width="stretch", key="radar_chart",
            on_select="rerun", selection_mode="points",
        )
        sync_selection_from_click(radar_event, "radar_click_label")
        st.caption("Ring = horizon. Sector = domain. Size = attractiveness. "
                   "Color = right to win. Click a bubble to select it.")

    with tab_bubble:
        # Attractiveness x-axis, Right-to-win y-axis, bubble size = market
        # signal strength -- this tab is original scatter concept
        # (same two score axes), rebuilt as a go.Figure so it matches the
        # dark theme, with one trace per vertical (legend doubles as a
        # filter/highlight) instead of the dashed 5/5 guide lines.
        fig_bubble = go.Figure()
        palette = ["#ff7900", "#4fd1c5", "#a78bfa", "#f6ad55", "#fc8181",
                   "#68d391", "#63b3ed", "#f6e05e"]
        for i, v in enumerate(sorted(filtered["vertical"].dropna().unique())):
            sub = filtered[filtered["vertical"] == v]
            fig_bubble.add_trace(go.Scatter(
                x=sub["total_score"], y=sub["right_to_win_score"],
                mode="markers",
                marker=dict(
                    size=(sub["market_signal_strength"].fillna(0) * 2.2 + 8),
                    color=palette[i % len(palette)],
                    line=dict(width=1, color="#0e1117"),
                ),
                name=v,
                customdata=sub["label"],
                text=[
                    f"{row.label} — {row.use_case} × {row.technology}<br>"
                    f"Attractiveness {row.total_score:.1f} · Right to win "
                    f"{row.right_to_win_score if pd.notna(row.right_to_win_score) else 0:.1f} "
                    f"[{row.portfolio_distance}]"
                    for row in sub.itertuples()
                ],
                hoverinfo="text",
            ))

        fig_bubble.update_layout(
            xaxis=dict(title="Attractiveness", range=[0, 10.5], gridcolor="#D2B38E",
                       tickfont=dict(color="#002244"), title_font=dict(color="#002244")),
            yaxis=dict(title="Right to win", range=[0, 10.5], gridcolor="#D2B38E",
                       tickfont=dict(color="#002244"), title_font=dict(color="#002244")),
            paper_bgcolor="#F6EEDE", plot_bgcolor="#F6EEDE",
            font=dict(color="#002244", family="Helvetica Neue, Helvetica, Arial, sans-serif"),
            legend=dict(font=dict(color="#002244"), title=dict(text="Vertical")),
            height=620,
            margin=dict(l=10, r=10, t=10, b=10)
        )

        bubble_event = st.plotly_chart(
            fig_bubble, width="stretch", key="bubble_chart",
            on_select="rerun", selection_mode="points",
        )
        sync_selection_from_click(bubble_event, "bubble_click_label")
        st.caption("X = Attractiveness. Y = Right to win. Bubble size = market signal strength "
                   "(volume proxy for market potential). Color = vertical. Click a bubble to "
                   "select it in the panel on the right.")


# ============================================================
# 9 + 10. RANKING & SELECTION OF AN OS
# ============================================================


# Sieg 25/8 -- original standalone ranking table is superseded by the
# single sortable "All matching opportunity spaces" table at the bottom of
# the page (section 17) -- same information, but sortable by whichever
# metric the sidebar "Order" control picked, so I didn't duplicate it here.
# The OS picker below keeps original core idea (a selectbox over the
# filtered IDs) but adds: labels sorted so the dropdown reads OS001,
# OS002... instead of shuffled by score, and a query-param deep link so a
# chart click (radar or bubble, above) can drive this same selectbox.
query_topic = st.query_params.get("topic")
labels = sorted(filtered["label"].tolist())
default_index = labels.index(query_topic) if query_topic in labels else 0
# Sieg 26/8 -- build a "OS005 — Use Case x Technology" display string per
# label, so the dropdown shows the actual name, not just the OS code. The
# selectbox still stores/returns the plain label under the hood (via the
# dict lookup below) -- filtered["label"]==picked_label elsewhere in the
# file keeps working unchanged.
label_display = {
    lbl: f"{lbl} — {filtered.loc[filtered['label'] == lbl, 'use_case'].iloc[0]} x "
         f"{filtered.loc[filtered['label'] == lbl, 'technology'].iloc[0]}"
    for lbl in labels
}

with col_detail:
    if not labels:
        st.info("No opportunity space matches the current filters.")
        st.stop()

    picked_display = st.selectbox(
        "Opportunity space", [label_display[lbl] for lbl in labels],
        index=default_index,
    )
    picked_label = labels[[label_display[lbl] for lbl in labels].index(picked_display)]
    st.query_params["topic"] = picked_label
    row = filtered[filtered["label"] == picked_label].iloc[0]


    # ========================================================
    # 11. MAIN INFORMATION
    # ========================================================

    # Sieg 25/8 -- same "vertical/use case/technology + score metrics"
    # content, condensed into one header line (title already carries
    # vertical/use case/technology) plus a 3-metric row that adds Urgency
    # next to Attractiveness/Right-to-win (original version only had the
    # first two -- urgency is a separate, deterministic "is there a real
    # deadline" signal the scoring pipeline now produces).
    st.subheader(f"{row.label} — {row.vertical} × {row.use_case} × {row.technology}")
    st.caption(f"Domain: {row.domain} · Horizon: {row.horizon} · Role: {row.persona or '—'} "
                f"· Buyer persona: {row.buyer_persona or '—'} · Geography: {row.geography or '—'}")

    m1, m2, m3 = st.columns(3)
    m1.metric("Attractiveness", f"{row.total_score:.1f}/10")
    m2.metric("Right to win",
                f"{row.right_to_win_score:.1f}/10" if pd.notna(row.right_to_win_score) else "Not scored yet",
                f"[{row.portfolio_distance}]")
    m3.metric("Urgency", f"{row.urgency_score:.1f}/10" if pd.notna(row.urgency_score) else "—",
                help="Deterministic: +2 per regulation/buying_signal signal linked to this OS, capped at 10. "
                    "Answers 'is there a real deadline', separate from attractiveness.")

    # Sieg 25/8 -- next action, ONE per role (original version had no next
    # action at all). The role picked in the sidebar is shown first, the
    # other two roles' actions are one click away in the expander.
    role_to_action = {
        "Strategist / Innovator": row.next_action_strategist,
        "Sales": row.next_action_sales,
        "Presales / Proposal": row.next_action_presales,
    }
    fallback = "No next action generated yet: re-run scoring/enrichment."
    st.markdown(f"**Do this next — {role}**")
    st.info(role_to_action.get(role) or fallback)
    with st.expander("See next action for the other roles"):
        for other_role, action in role_to_action.items():
            if other_role == role:
                continue
            st.markdown(f"**{other_role}**")
            st.caption(action or fallback)


# ============================================================
# 12 + 13. ATTRACTIVENESS BREAKDOWN & JUSTIFICATIONS
# ============================================================


# Sieg 25/8 -- same 5-criterion breakdown, as a native st.bar_chart (no
# plotly needed for a simple bar) inside a "Score breakdown" tab, with both
# justification texts as captions right below the chart instead of two
# separate full-width sections -- same content, more compact, and it now
# sits next to the "Right to win" tab below instead of scrolling the page.
st.divider()
tab_score, tab_evidence, tab_signals = st.tabs(["Score breakdown", "Right to win", "Sources"])

with tab_score:
    categories = ["Market signal strength", "Source diversity", "Evidence quality",
                "Novelty / momentum", "Strategic relevance"]
    values = [row.market_signal_strength, row.source_diversity, row.evidence_quality,
            row.novelty_momentum, row.strategic_relevance]
    # Sieg 26/8 -- switched from st.bar_chart to a filled radar/spider chart
    # per client's requested visual style (filled area, not a plain outline).
    # Scatterpolar closes the loop by repeating the first point at the end
    # -- without that, plotly draws an open pentagon instead of a closed shape.
    fig_breakdown = go.Figure()
    fig_breakdown.add_trace(go.Scatterpolar(
        r=values + values[:1],
        theta=categories + categories[:1],
        fill="toself",
        fillcolor="rgba(255, 121, 0, 0.35)",  # --radar-orange at 35% opacity
        line=dict(color="#ff7900", width=2),
        name="Score breakdown",
    ))
    fig_breakdown.update_layout(
        polar=dict(
            bgcolor="#F6EEDE",  # --radar-panel
            radialaxis=dict(visible=True, range=[0, 10], color="#002244"),
            angularaxis=dict(color="#002244"),
        ),
        paper_bgcolor="#F6EEDE",  # --radar-bg
        showlegend=False,
        margin=dict(l=40, r=40, t=20, b=20),
        font=dict(size=15, family="Helvetica Neue, Helvetica, Arial, sans-serif")
    )
    st.plotly_chart(fig_breakdown, width="stretch", key="breakdown_radar")
    st.caption(f"Evidence quality — {row.evidence_quality_justification or 'no justification recorded.'}")
    st.caption(f"Strategic relevance — {row.strategic_relevance_justification or 'no justification recorded.'}")


# ============================================================
# 14. RIGHT-TO-WIN
# ============================================================


# Sieg 25/8 -- same matched-assets + justification content (the score
# itself is already shown in the m2 metric above, so it isn't repeated
# here), moved into the "Right to win" tab, plus a reference expander
# listing the raw Orange Business capability stats the LLM saw when it
# wrote the justification -- so "why do we have a right to win" has
# something concrete to point to in a client meeting, not just free text.
with tab_evidence:
    st.markdown(f"**Matched assets:** {row.matched_assets or 'none'}")
    st.write(row.justification or "No right-to-win justification recorded.")

    # Comment this if you don't want to see this again (already in the bottom left side bar): 
    with st.expander("Orange Business scale & capability (reference)"):
        for stat in CAPABILITY_STATS:
            st.caption(f"**{stat['stat']}**  \n_{stat['source']}_")


# ============================================================
# 15. STRATEGIC POSITION
# ============================================================

# Sieg 25/8 -- kept this quadrant read-out as-is (my streamlit_app.py
# didn't have it, and the 4-way message is a genuinely useful one-line
# takeaway) -- just renamed the two score fields to match `row` instead of
# original `selected`, and placed it in the "Right to win" tab since it's
# the natural follow-up to the matched-assets/justification above it.
with tab_evidence:
    st.markdown("#### Strategic position")

    attractiveness = row.total_score
    right_to_win = row.right_to_win_score

    if pd.notna(attractiveness) and pd.notna(right_to_win):
        if attractiveness >= 7 and right_to_win >= 7:
            st.success("⭐ Strong opportunity: high attractiveness and strong right-to-win.")
        elif attractiveness >= 7 and right_to_win < 7:
            st.warning("⚠️ Attractive opportunity, but Orange Business may need additional capabilities.")
        elif attractiveness < 7 and right_to_win >= 7:
            st.info("💡 Orange Business has a strong right-to-win, but market attractiveness is more moderate.")
        else:
            st.warning("Opportunity with relatively low attractiveness and right-to-win.")


# ============================================================
# 16. GROUNDING SIGNALS
# ============================================================


# Sieg 25/8 -- signals now come from signals_by_os (preloaded once in
# load_scores(), instead of a per-click load_signals() query.
# Added an "Evidence over time" chart above the list -- same idea as
# scoring.py's novelty_momentum (is coverage increasing or fading) but as
# a chart instead of a single 0-10 number. Restored Gaëtan's "filter by
# evidence type" multiselect and the per-signal summary text below it now
# that section 2's query selects signal_type/summary, and kept his
# per-signal expander drill-down, since my original streamlit_app.py only
# had a flat dataframe there.
with tab_signals:
    sigs = signals_by_os.get(row.id, [])
    st.caption(f"{len(sigs)} grounding signal(s) linked to this opportunity space.")

    if not sigs:
        st.info("No signals linked yet — run `radar_cli.py link` first.")
    else:
        sig_df = pd.DataFrame(sigs)

        st.markdown("**Evidence over time**")
        # Sieg 26/8 -- was grouping on collected_at (when OUR pipeline
        # scraped the signal, all within the same ~1-week ingest run --
        # that's why every OS's chart collapsed to a single monthly bar).
        # Switched to published_date (when the signal itself was actually
        # published, 2022-2026 spread) since that's what "momentum over
        # time" is supposed to mean.
        # published_date also isn't one consistent format across the 9
        # sources -- mix of plain ISO dates, ISO datetimes with "Z", RFC
        # 2822 strings (RSS feeds), and GDELT's compact "YYYYMMDDThhmmssZ".
        # pandas' format="mixed" handles all of those in one pass, EXCEPT
        # TED's malformed "YYYY-MM-DD+HH:MM" (a date with a tz offset glued
        # on, no "T" separator) -- _fix_bare_date_with_offset() below
        # inserts the missing "T00:00:00" so that one parses too, instead
        # of silently becoming NaT and disappearing from the chart.
        def _fix_bare_date_with_offset(v):
            if isinstance(v, str) and re.match(r"^\d{4}-\d{2}-\d{2}[+-]\d{2}:\d{2}$", v):
                return v[:10] + "T00:00:00" + v[10:]
            return v

        dated = sig_df.dropna(subset=["published_date"]).copy()
        if not dated.empty:
            dated["published_date"] = dated["published_date"].map(_fix_bare_date_with_offset)
            dated["parsed_date"] = pd.to_datetime(
                dated["published_date"], format="mixed", utc=True, errors="coerce"
            )
            dated = dated.dropna(subset=["parsed_date"])  # drop anything still unparseable
        if not dated.empty:
            dated["month"] = dated["parsed_date"].dt.to_period("M").astype(str)
            monthly_counts = dated.groupby("month").size().rename("Signals")
            st.line_chart(monthly_counts, color="#ff7900")
        else:
            st.caption("No dated signals to plot yet.")

        # original "filter by evidence type" control, adapted to
        # the sigs list (dicts) instead of a DataFrame column access.
        signal_types = sorted({s["signal_type"] for s in sigs if s.get("signal_type")})
        selected_signal_types = st.multiselect(
            "Filter evidence type", options=signal_types, default=signal_types
        )
        visible_sigs = [s for s in sigs if s.get("signal_type") in selected_signal_types]

        st.markdown("**Sources**")
        if not visible_sigs:
            st.info("No evidence matches the selected signal types.")
        else:
            for sig in visible_sigs:
                label = f"{sig.get('signal_type') or 'Unknown type'} — {sig.get('source_name') or 'Unknown source'}"
                with st.expander(label):
                    st.markdown(f"**{sig.get('title') or 'Untitled'}**")
                    if sig.get("summary"):
                        st.write(sig["summary"])
                    if sig.get("collected_at"):
                        st.caption(f"Collected: {sig['collected_at']}")
                    if sig.get("source_url"):
                        st.markdown(f"[🔗 Open source]({sig['source_url']})")


# ============================================================
# 17. COMPLETE DASHBOARD VIEW
# ============================================================


# Sieg 25/8 -- this table now absorbs original separate "Opportunity
# Ranking" table (it was the same data, sorted the same
# way) -- extended with Domain, Horizon and Urgency columns, and sorted by
# whatever the sidebar "Order" control picked instead of being hardcoded
# to Attractiveness.
st.divider()
st.subheader(f"All matching opportunity spaces ({len(filtered)})")
st.dataframe(
    filtered[["label", "vertical", "use_case", "technology", "domain", "horizon",
              "total_score", "right_to_win_score", "urgency_score", "portfolio_distance"]]
    .rename(columns={
        "label": "Label",
        "vertical": "Vertical",
        "use_case": "Use Case",
        "technology": "Technology",
        "domain": "Domain",
        "horizon": "Horizon",
        "total_score": "Attractiveness",
        "right_to_win_score": "Right to Win",
        "urgency_score": "Urgency",
        "portfolio_distance": "Distance",
    }),
    width="stretch",
    hide_index=True,
)

st.divider()
st.subheader("Taxonomy extension status")

col_watch, col_prop = st.columns(2)

with col_watch:
    st.markdown("### Watchlist (out-of-taxonomy terms)")
    if watchlist_df.empty:
        st.info("No out-of-taxonomy terms tracked yet.")
    else:
        st.caption(f"{len(watchlist_df)} terms currently under observation")
        st.dataframe(watchlist_df, use_container_width=True, hide_index=True)

with col_prop:
    st.markdown("### Pending proposals")
    if proposal_df.empty:
        st.info("No pending taxonomy proposals.")
    else:
        st.caption(f"{len(proposal_df)} proposals awaiting team review")
        st.dataframe(proposal_df, use_container_width=True, hide_index=True)

# ============================================================
# 18. FOOTER
# ============================================================

st.divider() 
st.caption(f"Orange Business Innovation Radar • Data powered by radar.db • Viewing as: {role}")