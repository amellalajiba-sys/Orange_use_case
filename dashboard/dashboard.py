import sqlite3

import pandas as pd
import plotly.express as px
import streamlit as st


# ============================================================
# 1. CONFIGURATION
# ============================================================

st.set_page_config(
    page_title="Orange Business Innovation Radar",
    page_icon="🟠",
    layout="wide",
)


# ============================================================
# 2. CONNECTION TO THE DATABASE
# ============================================================

DB_PATH = "radar.db"


def load_opportunities():
    """
    Load Opportunity Spaces together with their attractiveness
    and right-to-win scores.
    """

    conn = sqlite3.connect(DB_PATH)

    query = """
        SELECT
            os.id AS opportunity_space_id,
            os.label AS ID,
            os.vertical AS Vertical,
            os.use_case AS "Use Case",
            os.technology AS Technology,

            s.market_signal_strength AS "Market Signal Strength",
            s.source_diversity AS "Source Diversity",
            s.evidence_quality AS "Evidence Quality",
            s.evidence_quality_justification AS "Evidence Quality Justification",
            s.novelty_momentum AS "Novelty / Momentum",
            s.strategic_relevance AS "Strategic Relevance",
            s.strategic_relevance_justification AS "Strategic Relevance Justification",
            s.total_score AS Attractiveness,

            r.right_to_win_score AS "Right to Win",
            r.portfolio_distance AS Distance,
            r.matched_assets AS "Matched Assets",
            r.justification AS "Right to Win Justification"

        FROM opportunity_spaces os

        LEFT JOIN scores s
            ON os.id = s.opportunity_space_id

        LEFT JOIN right_to_win_scores r
            ON os.id = r.opportunity_space_id

        ORDER BY s.total_score DESC
    """

    df = pd.read_sql_query(query, conn)

    conn.close()

    return df


def load_signals(opportunity_space_id):
    """
    Load all grounding signals associated with one Opportunity Space.
    """

    conn = sqlite3.connect(DB_PATH)

    query = """
        SELECT
            s.source_name AS "Source",
            s.source_url AS "URL",
            s.signal_type AS "Type",
            s.title AS "Title",
            s.summary AS "Summary",
            s.published_date AS "Published Date"

        FROM signals s

        INNER JOIN opportunity_signals os
            ON s.id = os.signal_id

        WHERE os.opportunity_space_id = ?

        ORDER BY s.published_date DESC
    """

    df = pd.read_sql_query(
        query,
        conn,
        params=(opportunity_space_id,),
    )

    conn.close()

    return df


# ============================================================
# 3. LOADING THE DATA
# ============================================================

df = load_opportunities()


# If the database is empty, display an error message and stop the app
if df.empty:
    st.error(
        "No Opportunity Spaces were found in radar.db."
    )
    st.stop()


# ============================================================
# 4. HEADER
# ============================================================

st.title("🟠 Orange Business Innovation Radar")

st.write(
    "Explore and compare Opportunity Spaces based on "
    "market attractiveness and Orange Business right-to-win."
)


# ============================================================
# 5. SIDEBAR — FILTERS
# ============================================================

st.sidebar.header("🎛️ Filters")

st.sidebar.caption(
    "Filter the radar by business vertical and portfolio distance."
)


# -------- Vertical --------

vertical_options = sorted(
    df["Vertical"].dropna().unique()
)

selected_verticals = st.sidebar.multiselect(
    "Business Vertical",
    options=vertical_options,
    default=vertical_options,
)


# -------- Distance --------

distance_options = sorted(
    df["Distance"].dropna().unique()
)

selected_distances = st.sidebar.multiselect(
    "Portfolio Distance",
    options=distance_options,
    default=distance_options,
)


# ============================================================
# 6. APPLICATION OF THE FILTERS
# ============================================================

filtered_df = df[
    (df["Vertical"].isin(selected_verticals))
    &
    (df["Distance"].isin(selected_distances))
].copy()


# Aucun résultat
if filtered_df.empty:

    st.warning(
        "No Opportunity Spaces match your current filters."
    )

    st.stop()


# ============================================================
# 7. KPI 
# ============================================================

st.subheader("📊 Overview")

col1, col2, col3, col4 = st.columns(4)


with col1:

    st.metric(
        "Opportunity Spaces",
        len(filtered_df),
    )


with col2:

    average_attractiveness = (
        filtered_df["Attractiveness"].mean()
    )

    st.metric(
        "Average Attractiveness",
        f"{average_attractiveness:.2f}/10",
    )


with col3:

    average_right_to_win = (
        filtered_df["Right to Win"].mean()
    )

    st.metric(
        "Average Right-to-Win",
        f"{average_right_to_win:.2f}/10",
    )


with col4:

    best_index = filtered_df[
        "Attractiveness"
    ].idxmax()

    best_opportunity = filtered_df.loc[
        best_index,
        "ID",
    ]

    st.metric(
        "Top Opportunity",
        best_opportunity,
    )


# ============================================================
# 8. RADAR
# ============================================================

st.subheader("🎯 Opportunity Radar")

st.caption(
    "The radar compares market attractiveness with "
    "Orange Business right-to-win."
)


fig = px.scatter(
    filtered_df,
    x="Attractiveness",
    y="Right to Win",
    text="ID",
    size="Attractiveness",
    size_max=45,

    hover_data={
        "Vertical": True,
        "Use Case": True,
        "Technology": True,
        "Attractiveness": ":.2f",
        "Right to Win": ":.2f",
        "Distance": True,
        "ID": False,
    },

    title="Attractiveness vs Right-to-Win",
)


fig.update_traces(
    textposition="top center"
)


fig.update_xaxes(
    title="Market Attractiveness",
    range=[0, 10],
)


fig.update_yaxes(
    title="Orange Business Right-to-Win",
    range=[0, 10],
)


# Repères visuels
fig.add_vline(
    x=5,
    line_dash="dash",
)

fig.add_hline(
    y=5,
    line_dash="dash",
)


fig.update_layout(
    height=600,
)


st.plotly_chart(
    fig,
    use_container_width=True,
)


# ============================================================
# 9. RANKING
# ============================================================

st.subheader("🏆 Opportunity Ranking")

ranking_columns = [
    "ID",
    "Vertical",
    "Use Case",
    "Technology",
    "Attractiveness",
    "Right to Win",
    "Distance",
]


ranking = (
    filtered_df[ranking_columns]
    .sort_values(
        "Attractiveness",
        ascending=False,
    )
)


st.dataframe(
    ranking,
    use_container_width=True,
    hide_index=True,
)


# ============================================================
# 10. SELECTION OF AN OS
# ============================================================

st.subheader("🔎 Opportunity Details")

selected_id = st.selectbox(
    "Choose an Opportunity Space",
    options=filtered_df["ID"].tolist(),
)


selected = filtered_df[
    filtered_df["ID"] == selected_id
].iloc[0]


# Loading sources corresponding to one OS
signals_df = load_signals(
    selected["opportunity_space_id"]
)


# ============================================================
# 11. MAIN INFORMATION
# ============================================================

st.markdown(
    f"### {selected['ID']}"
)


col1, col2 = st.columns(2)


with col1:

    st.markdown("#### Opportunity")

    st.write(
        "**Vertical:**",
        selected["Vertical"],
    )

    st.write(
        "**Use Case:**",
        selected["Use Case"],
    )

    st.write(
        "**Technology:**",
        selected["Technology"],
    )


with col2:

    st.markdown("#### Scores")

    score_col1, score_col2 = st.columns(2)

    with score_col1:

        st.metric(
            "Attractiveness",
            f"{selected['Attractiveness']:.2f}/10",
        )

    with score_col2:

        st.metric(
            "Right-to-Win",
            f"{selected['Right to Win']:.2f}/10",
        )

    st.write(
        "**Portfolio Distance:**",
        selected["Distance"],
    )


# ============================================================
# 12. ATTRACTIVENESS BREAKDOWN
# ============================================================

st.markdown("### 📊 Attractiveness Breakdown")

score_data = pd.DataFrame(
    {
        "Criterion": [
            "Market Signal Strength",
            "Source Diversity",
            "Evidence Quality",
            "Novelty / Momentum",
            "Strategic Relevance",
        ],

        "Score": [
            selected["Market Signal Strength"],
            selected["Source Diversity"],
            selected["Evidence Quality"],
            selected["Novelty / Momentum"],
            selected["Strategic Relevance"],
        ],
    }
)


fig_scores = px.bar(
    score_data,
    x="Score",
    y="Criterion",
    orientation="h",
    range_x=[0, 10],
    title="Attractiveness Score Breakdown",
)


fig_scores.update_layout(
    height=400,
)


st.plotly_chart(
    fig_scores,
    use_container_width=True,
)


# ============================================================
# 13. JUSTIFICATIONS
# ============================================================

st.markdown("### 💡 Strategic Explanation")

if pd.notna(
    selected["Strategic Relevance Justification"]
):

    st.write(
        selected[
            "Strategic Relevance Justification"
        ]
    )

else:

    st.info(
        "No strategic relevance justification available."
    )


st.markdown("### 🔬 Evidence Quality")

if pd.notna(
    selected["Evidence Quality Justification"]
):

    st.write(
        selected[
            "Evidence Quality Justification"
        ]
    )

else:

    st.info(
        "No evidence quality justification available."
    )


# ============================================================
# 14. RIGHT-TO-WIN
# ============================================================

st.markdown("### 🏆 Right-to-Win")


rtw_col1, rtw_col2 = st.columns(2)


with rtw_col1:

    st.metric(
        "Right-to-Win Score",
        f"{selected['Right to Win']:.2f}/10",
    )

    st.write(
        "**Portfolio Distance:**",
        selected["Distance"],
    )


with rtw_col2:

    st.markdown("#### Orange Business Assets")

    if pd.notna(selected["Matched Assets"]):

        st.write(
            selected["Matched Assets"]
        )

    else:

        st.info(
            "No matched assets available."
        )


st.markdown("#### Why can Orange Business win?")


if pd.notna(
    selected["Right to Win Justification"]
):

    st.write(
        selected[
            "Right to Win Justification"
        ]
    )

else:

    st.info(
        "No right-to-win justification available."
    )


# ============================================================
# 15. STRATEGIC POSITION
# ============================================================

st.markdown("### 🧭 Strategic Position")


attractiveness = selected["Attractiveness"]
right_to_win = selected["Right to Win"]


if (
    pd.notna(attractiveness)
    and pd.notna(right_to_win)
):

    if (
        attractiveness >= 7
        and right_to_win >= 7
    ):

        st.success(
            "⭐ Strong opportunity: "
            "high attractiveness and strong right-to-win."
        )

    elif (
        attractiveness >= 7
        and right_to_win < 7
    ):

        st.warning(
            "⚠️ Attractive opportunity, "
            "but Orange Business may need additional capabilities."
        )

    elif (
        attractiveness < 7
        and right_to_win >= 7
    ):

        st.info(
            "💡 Orange Business has a strong right-to-win, "
            "but market attractiveness is more moderate."
        )

    else:

        st.warning(
            "Opportunity with relatively low "
            "attractiveness and right-to-win."
        )


# ============================================================
# 16. GROUNDING SIGNALS
# ============================================================

st.markdown("### 📰 Evidence / Grounding Signals")


if signals_df.empty:

    st.info(
        "No evidence signals are available for this Opportunity Space."
    )

else:

   

    signal_types = sorted(
        signals_df["Type"]
        .dropna()
        .unique()
    )


    selected_signal_types = st.multiselect(
        "Filter evidence type",
        options=signal_types,
        default=signal_types,
    )


    visible_signals = signals_df[
        signals_df["Type"].isin(
            selected_signal_types
        )
    ]


   

    if visible_signals.empty:

        st.info(
            "No evidence matches the selected signal types."
        )

    else:

        for _, signal in visible_signals.iterrows():

            source = signal["Source"]
            signal_type = signal["Type"]
            title = signal["Title"]
            summary = signal["Summary"]
            published_date = signal["Published Date"]
            url = signal["URL"]


            with st.expander(
                f"{signal_type} — {source}"
            ):

                st.markdown(
                    f"**{title}**"
                )


                if (
                    pd.notna(summary)
                    and summary
                ):

                    st.write(
                        summary
                    )


                if (
                    pd.notna(published_date)
                    and published_date
                ):

                    st.caption(
                        f"Published: {published_date}"
                    )


                if (
                    pd.notna(url)
                    and url
                ):

                    st.markdown(
                        f"[🔗 Open source]({url})"
                    )


# ============================================================
# 17. COMPLETE BOARD
# ============================================================

st.subheader("📋 All Opportunity Spaces")

st.caption(
    "Filtered view of all Opportunity Spaces currently available."
)


display_columns = [
    "ID",
    "Vertical",
    "Use Case",
    "Technology",
    "Attractiveness",
    "Right to Win",
    "Distance",
]


st.dataframe(
    filtered_df[display_columns]
    .sort_values(
        "Attractiveness",
        ascending=False,
    ),
    use_container_width=True,
    hide_index=True,
)


# ============================================================
# 18. FOOTER
# ============================================================

st.divider()

st.caption(
    "Orange Business Innovation Radar • "
    "Data powered by radar.db"
)