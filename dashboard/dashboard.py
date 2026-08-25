import streamlit as st
import sqlite3
import pandas as pd
import plotly.express as px

#Before running this file you need to make sure the radar.db is not empty !!

# ============================================================
# CONFIGURATION
# ============================================================

from pathlib import Path


# ============================================================
# WAY TO THE DATABASE
# ============================================================

# dashboard.py is located in:
# Orange_use_case/dashboard/dashboard.py
#
# radar.db is located in:
# Orange_use_case/radar.db
#
# So we go up one folder with .parent

BASE_DIR = Path(__file__).resolve().parent.parent

DB_PATH = BASE_DIR / "radar.db"

st.set_page_config(
    page_title="Orange Business Innovation Radar",
    page_icon="🟠",
    layout="wide"
)


# ============================================================
# FONCTIONS DATABASE
# ============================================================

def get_connection():
    """
    Ouvre une connexion à radar.db.
    """

    if not DB_PATH.exists():
        st.error(
            f"❌ Database not found: {DB_PATH}"
        )
        st.stop()

    return sqlite3.connect(DB_PATH)


@st.cache_data
def load_opportunity_spaces():
    """
    Récupère les Opportunity Spaces + leurs scores.
    """

    conn = get_connection()

    query = """
        SELECT
            os.id,
            os.label,
            os.vertical,
            os.use_case,
            os.technology,

            s.market_signal_strength,
            s.source_diversity,
            s.evidence_quality,
            s.novelty_momentum,
            s.strategic_relevance,
            s.total_score AS attractiveness,

            r.portfolio_distance,
            r.right_to_win_score,
            r.matched_assets,
            r.justification AS right_to_win_justification

        FROM opportunity_spaces os

        LEFT JOIN scores s
            ON s.opportunity_space_id = os.id

        LEFT JOIN right_to_win_scores r
            ON r.opportunity_space_id = os.id

        ORDER BY
            s.total_score DESC
    """

    df = pd.read_sql_query(query, conn)

    conn.close()

    return df


@st.cache_data
def load_signals(opportunity_space_id):
    """
    Récupère tous les grounding/evidence signals
    associés à un Opportunity Space.
    """

    conn = get_connection()

    query = """
        SELECT
            s.id,
            s.source_name,
            s.source_url,
            s.signal_type,
            s.title,
            s.summary,
            s.published_date

        FROM opportunity_signals osig

        JOIN signals s
            ON s.id = osig.signal_id

        WHERE osig.opportunity_space_id = ?

        ORDER BY
            s.published_date DESC
    """

    signals = pd.read_sql_query(
        query,
        conn,
        params=(opportunity_space_id,)
    )

    conn.close()

    return signals


# ============================================================
# LOADING DATA
# ============================================================

df = load_opportunity_spaces()


# ============================================================
# VERIFICATION
# ============================================================

if df.empty:

    st.error(
        "❌ No Opportunity Spaces found in radar.db."
    )

    st.stop()


# ============================================================
# TITLE
# ============================================================

st.title("🟠 Orange Business Innovation Radar")

st.write(
    "Discover the most attractive Opportunity Spaces "
    "for Orange Business."
)


# ============================================================
# SIDEBAR — FILTERS
# ============================================================

st.sidebar.header("🎛️ Filters")


# ---------- Vertical ----------

vertical_options = sorted(
    df["vertical"].dropna().unique()
)

selected_verticals = st.sidebar.multiselect(
    "🏭 Vertical",
    options=vertical_options,
    default=vertical_options
)


# ---------- Distance ----------

distance_options = sorted(
    df["portfolio_distance"].dropna().unique()
)

selected_distances = st.sidebar.multiselect(
    "📏 Portfolio Distance",
    options=distance_options,
    default=distance_options
)


# ---------- Minimum attractiveness ----------

min_attractiveness = st.sidebar.slider(
    "⭐ Minimum Attractiveness",
    min_value=0.0,
    max_value=10.0,
    value=0.0,
    step=0.1
)


# ============================================================
# FILTERS APPLICATION
# ============================================================

filtered_df = df[
    (df["vertical"].isin(selected_verticals))
    &
    (df["portfolio_distance"].isin(selected_distances))
    &
    (df["attractiveness"].fillna(0) >= min_attractiveness)
].copy()


# ============================================================
# IF NO RESULTS
# ============================================================

if filtered_df.empty:

    st.warning(
        "No Opportunity Space matches your filters."
    )

    st.stop()


# ============================================================
# OVERVIEW
# ============================================================

st.subheader("📊 Overview")

col1, col2, col3, col4 = st.columns(4)


with col1:

    st.metric(
        "Opportunity Spaces",
        len(filtered_df)
    )


with col2:

    best_attractiveness = filtered_df[
        "attractiveness"
    ].max()

    st.metric(
        "Best Attractiveness",
        f"{best_attractiveness:.2f}/10"
    )


with col3:

    best_rtw = filtered_df[
        "right_to_win_score"
    ].max()

    st.metric(
        "Best Right to Win",
        f"{best_rtw:.1f}/10"
    )


with col4:

    average_attractiveness = filtered_df[
        "attractiveness"
    ].mean()

    st.metric(
        "Average Attractiveness",
        f"{average_attractiveness:.2f}/10"
    )


# ============================================================
# RANKING
# ============================================================

st.subheader("🏆 Opportunity Ranking")

ranking_df = filtered_df[
    [
        "label",
        "vertical",
        "use_case",
        "technology",
        "attractiveness",
        "right_to_win_score",
        "portfolio_distance"
    ]
].copy()


ranking_df = ranking_df.sort_values(
    "attractiveness",
    ascending=False
)


ranking_df.columns = [
    "OS",
    "Vertical",
    "Use Case",
    "Technology",
    "Attractiveness",
    "Right to Win",
    "Distance"
]


st.dataframe(
    ranking_df,
    use_container_width=True,
    hide_index=True
)


# ============================================================
# RADAR
# ============================================================

st.subheader("🎯 Opportunity Radar")

fig = px.scatter(
    filtered_df,

    x="attractiveness",

    y="right_to_win_score",

    text="label",

    size="attractiveness",

    size_max=45,

    hover_data=[
        "vertical",
        "use_case",
        "technology",
        "portfolio_distance"
    ],

    labels={
        "attractiveness": "Attractiveness",
        "right_to_win_score": "Right to Win"
    },

    title="Attractiveness vs Right to Win"
)


fig.update_traces(
    textposition="top center"
)


fig.update_xaxes(
    range=[0, 10]
)


fig.update_yaxes(
    range=[0, 10]
)


st.plotly_chart(
    fig,
    use_container_width=True
)


# ============================================================
# OPPORTUNITY DETAILS
# ============================================================

st.subheader("🔍 Opportunity Details")


# IMPORTANT :
# On sélectionne le LABEL pour l'utilisateur,
# mais ensuite on récupère l'ID numérique de SQLite.

selected_label = st.selectbox(
    "Choose an Opportunity Space",
    filtered_df["label"].tolist()
)


selected = filtered_df[
    filtered_df["label"] == selected_label
].iloc[0]


# ID NUMÉRIQUE DE LA DATABASE

selected_id = int(
    selected["id"]
)


# ============================================================
# DEBUG — À ENLEVER PLUS TARD
# ============================================================

with st.expander("🔧 Database Debug"):

    st.write(
        "Selected OS:",
        selected_label
    )

    st.write(
        "Database ID:",
        selected_id
    )


# ============================================================
# INFORMATIONS PRINCIPALES
# ============================================================

st.markdown(
    f"### {selected['label']}"
)


col1, col2 = st.columns(2)


with col1:

    st.write(
        "**🏭 Vertical:**",
        selected["vertical"]
    )

    st.write(
        "**🎯 Use Case:**",
        selected["use_case"]
    )

    st.write(
        "**💻 Technology:**",
        selected["technology"]
    )


with col2:

    st.write(
        "**⭐ Attractiveness:**",
        f"{selected['attractiveness']:.2f}/10"
        if pd.notna(selected["attractiveness"])
        else "N/A"
    )

    st.write(
        "**🏆 Right to Win:**",
        f"{selected['right_to_win_score']:.1f}/10"
        if pd.notna(selected["right_to_win_score"])
        else "N/A"
    )

    st.write(
        "**📏 Portfolio Distance:**",
        selected["portfolio_distance"]
        if pd.notna(selected["portfolio_distance"])
        else "N/A"
    )


# ============================================================
# RIGHT TO WIN DETAILS
# ============================================================

st.subheader("💪 Right to Win")


if pd.notna(selected["matched_assets"]):

    st.write("**Matched Orange Business Assets:**")

    st.info(
        selected["matched_assets"]
    )


if pd.notna(
    selected["right_to_win_justification"]
):

    st.write(
        "**Why Orange Business can win:**"
    )

    st.write(
        selected["right_to_win_justification"]
    )


# ============================================================
# ATTRACTIVENESS SCORE DETAILS
# ============================================================

st.subheader("📈 Attractiveness Score Breakdown")


score_data = pd.DataFrame({
    "Dimension": [
        "Market Signal Strength",
        "Source Diversity",
        "Evidence Quality",
        "Novelty / Momentum",
        "Strategic Relevance"
    ],

    "Score": [
        selected["market_signal_strength"],
        selected["source_diversity"],
        selected["evidence_quality"],
        selected["novelty_momentum"],
        selected["strategic_relevance"]
    ]
})


score_data = score_data.dropna()


fig_scores = px.bar(
    score_data,

    x="Dimension",

    y="Score",

    range_y=[0, 10],

    title="Attractiveness Components"
)


st.plotly_chart(
    fig_scores,
    use_container_width=True
)


# ============================================================
# GROUNDING / EVIDENCE SIGNALS
# ============================================================

st.subheader("📰 Market Evidence & Signals")


# WE USE NURERIC ID !
signals_df = load_signals(
    selected_id
)


# TEMPORARY DEBUG

with st.expander("🔧 Signal Debug"):

    st.write(
        "Opportunity Space ID:",
        selected_id
    )

    st.write(
        "Number of signals:",
        len(signals_df)
    )


# ============================================================
# DISPLAYING SIGNALS
# ============================================================

if signals_df.empty:

    st.warning(
        "No evidence signals are available "
        "for this Opportunity Space."
    )

else:

    st.success(
        f"{len(signals_df)} evidence signals found."
    )


    # ---------- Filter signal type ----------

    signal_types = sorted(
        signals_df["signal_type"]
        .dropna()
        .unique()
    )


    selected_signal_types = st.multiselect(
        "Filter signal type",
        options=signal_types,
        default=signal_types
    )


    displayed_signals = signals_df[
        signals_df["signal_type"].isin(
            selected_signal_types
        )
    ]


    # ---------- Display ----------

    for _, signal in displayed_signals.iterrows():

        with st.expander(
            f"📰 {signal['title']}"
        ):

            st.write(
                "**Source:**",
                signal["source_name"]
            )


            st.write(
                "**Type:**",
                signal["signal_type"]
            )


            if pd.notna(
                signal["published_date"]
            ):

                st.write(
                    "**Published:**",
                    signal["published_date"]
                )


            if pd.notna(
                signal["summary"]
            ):

                st.write(
                    signal["summary"]
                )


            if pd.notna(
                signal["source_url"]
            ):

                st.markdown(
                    f"[🔗 Read original source]({signal['source_url']})"
                )


# ============================================================
# FOOTER
# ============================================================

st.divider()

st.caption(
    "Orange Business Innovation Radar — "
    "Data loaded from radar.db"
)