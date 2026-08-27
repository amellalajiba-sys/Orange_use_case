import sqlite3
import base64
import pandas as pd
import plotly.express as px
import streamlit as st
from pathlib import Path

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
    
    /* Sidebar styling (gruppi widget in box) */
    [data-testid="stSidebar"] {
        background-color: #002244;
        color: white !important;
    }
    [data-testid="stSidebar"] * {
        color: white !important;
    }
    
    [data-testid="stSidebar"] .stMarkdown, 
    [data-testid="stSidebar"] .stCaption, 
    [data-testid="stSidebar"] .stSelectbox, 
    [data-testid="stSidebar"] .stMultiSelect, 
    [data-testid="stSidebar"] .stRadio,
    [data-testid="stSidebar"] .stCheckbox {
        background-color: rgba(255,255,255,0.1);
        border-radius: 8px;
        padding: 8px;
        margin-bottom: 5px;
        border: 1px solid rgba(255,255,255,0.2);
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
        font-size: 1.3rem;       /* firs row size */
        margin-bottom: 12px;     /* space between first row and the next */
    }

    .os-line b {
        font-weight: bold;       /* OS code made bold */
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
    
    /* Box personalizzati */
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
</style>
""", unsafe_allow_html=True)

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
# 4. DATABASE FUNCTIONS
# ============================================================

def load_opportunities():
    """Load Opportunity Spaces con punteggi, urgenza, persona, geografia e data creazione."""
    conn = sqlite3.connect(DB_PATH)
    query = """
        SELECT
            os.id AS opportunity_space_id,
            os.label AS ID,
            os.vertical AS Vertical,
            os.use_case AS "Use Case",
            os.technology AS Technology,
            os.buyer_persona AS "Persona",
            os.geography AS "Geography",
            os.created_at AS "Created At",
            s.market_signal_strength AS "Market Signal Strength",
            s.source_diversity AS "Source Diversity",
            s.evidence_quality AS "Evidence Quality",
            s.evidence_quality_justification AS "Evidence Quality Justification",
            s.novelty_momentum AS "Novelty / Momentum",
            s.strategic_relevance AS "Strategic Relevance",
            s.strategic_relevance_justification AS "Strategic Relevance Justification",
            s.total_score AS Attractiveness,
            s.urgency_score AS Urgency,
            r.right_to_win_score AS "Right to Win",
            r.portfolio_distance AS Distance,
            r.matched_assets AS "Matched Assets",
            r.justification AS "Right to Win Justification"
        FROM opportunity_spaces os
        LEFT JOIN scores s ON os.id = s.opportunity_space_id                                                            
            AND s.computed_at = (SELECT MAX(computed_at) FROM scores WHERE opportunity_space_id = os.id)                
        LEFT JOIN right_to_win_scores r ON os.id = r.opportunity_space_id                                    
            AND r.computed_at = (SELECT MAX(computed_at) FROM right_to_win_scores WHERE opportunity_space_id = os.id)
        ORDER BY s.total_score DESC
    """
    # joins in query changed so that the three boxes in "What's Hot Now" are not about the same OS:
    # the problem with the previous query was due to the fact that there are multiple rows in the database for the same 
    # Opportunity Space (OS015): likely because a new record is inserted into the `scores` table (an audit trail) 
    # each time the scoring is run. When we use `filtered_df.nlargest(3, "Attractiveness")`, if OS015 has the highest scores 
    # across multiple runs, we ended up with three identical boxes. 

    df = pd.read_sql_query(query, conn)
    conn.close()
    return df

def load_signals(opportunity_space_id):
    """Load signals associati a un opportunity space."""
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
        INNER JOIN opportunity_signals os ON s.id = os.signal_id
        WHERE os.opportunity_space_id = ?
        ORDER BY s.published_date DESC
    """
    df = pd.read_sql_query(query, conn, params=(opportunity_space_id,))
    conn.close()
    return df

# ============================================================
# 5. LOAD DATA
# ============================================================

df = load_opportunities()

if df.empty:
    st.error("No Opportunity Spaces were found in radar.db.")
    st.stop()

# ============================================================
# 6. SIDEBAR — FILTERS
# ============================================================

st.sidebar.header("Filters")
st.sidebar.caption("Filter the radar by business vertical, portfolio distance, persona and geography.")

# Role modes
st.sidebar.subheader("User Role")
role_mode = st.sidebar.radio(
    "Select your role",
    ["Strategist", "Sales", "Presales"],
    index=0,
    key="role_mode"
)

# Checkbox per applicare il filtro ruolo
apply_role_filter = st.sidebar.checkbox("Applica filtro ruolo", value=False)

# Default filters based on role
if role_mode == "Strategist":
    default_verticals = sorted(df["Vertical"].dropna().unique())
    default_distances = sorted(df["Distance"].dropna().unique())
elif role_mode == "Sales":
    default_distances = ["L0", "L1"]
    default_verticals = sorted(df["Vertical"].dropna().unique())
else:  # Presales
    default_distances = sorted(df["Distance"].dropna().unique())
    default_verticals = sorted(df["Vertical"].dropna().unique())

# Vertical filter
vertical_options = sorted(df["Vertical"].dropna().unique())
selected_verticals = st.sidebar.multiselect(
    "Business Vertical",
    options=vertical_options,
    default=default_verticals,
    key="vertical_filter"
)

# Distance filter
distance_options = sorted(df["Distance"].dropna().unique())
selected_distances = st.sidebar.multiselect(
    "Portfolio Distance",
    options=distance_options,
    default=default_distances,
    key="distance_filter"
)

# Persona filter
if "Persona" in df.columns:
    persona_options = sorted(df["Persona"].dropna().unique())
    if not persona_options:
        persona_options = ["N/A"]
else:
    persona_options = ["N/A"]

selected_personas = st.sidebar.multiselect(
    "Target Persona",
    options=persona_options,
    default=persona_options,
    key="persona_filter"
)

# Geography filter
if "Geography" in df.columns:
    geo_options = sorted(df["Geography"].dropna().unique())
    if not geo_options:
        geo_options = ["N/A"]
else:
    geo_options = ["N/A"]

selected_geographies = st.sidebar.multiselect(
    "Geography",
    options=geo_options,
    default=geo_options,
    key="geography_filter"
)

# ============================================================
# 7. APPLY FILTERS
# ============================================================

filtered_df = df[
    (df["Vertical"].isin(selected_verticals)) &
    (df["Distance"].isin(selected_distances))
].copy()

# Applica filtro ruolo
if apply_role_filter:
    if role_mode == "Sales":
        filtered_df = filtered_df[filtered_df["Distance"].isin(["L0", "L1"])]
    elif role_mode == "Presales":
        filtered_df = filtered_df[filtered_df["Matched Assets"].notna()]

# Applica filtri persona e geografia
if "Persona" in filtered_df.columns and selected_personas and "N/A" not in selected_personas:
    filtered_df = filtered_df[filtered_df["Persona"].isin(selected_personas)]

if "Geography" in filtered_df.columns and selected_geographies and "N/A" not in selected_geographies:
    filtered_df = filtered_df[filtered_df["Geography"].isin(selected_geographies)]

if filtered_df.empty:
    st.warning("No Opportunity Spaces match your current filters.")
    st.stop()

# ============================================================
# 8. HERO SECTION — WHAT'S HOT NOW (orizzontale)
# ============================================================

st.markdown("### What's Hot Now")

top3 = filtered_df.nlargest(3, "Attractiveness")

cols = st.columns(3)
for i, (idx, row) in enumerate(top3.iterrows()):
    with cols[i]:
        st.markdown(
            f"""
            <div class="orange-box">
                <div class="os-line">
                    <b>{row['ID']}</b> — {row['Vertical']} × {row['Use Case']} × {row['Technology']}
                </div>
                Attractiveness: <b>{row['Attractiveness']:.2f}/10</b> | R2W: <b>{row['Right to Win']:.2f}/10</b><br>
                <i>{row['Strategic Relevance Justification'] if pd.notna(row['Strategic Relevance Justification']) else 'N/A'}</i>
            </div>
            """, unsafe_allow_html=True)

# ============================================================
# 9. KPI — AT A GLANCE
# ============================================================

st.markdown("### At a Glance")

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.markdown(
        f"""
        <div class="kpi-card">
            <h2>{len(filtered_df)}</h2>
            <p>Opportunity Spaces</p>
        </div>
        """, unsafe_allow_html=True
    )

with col2:
    avg_attr = filtered_df["Attractiveness"].mean()
    st.markdown(
        f"""
        <div class="kpi-card">
            <h2>{avg_attr:.2f}/10</h2>
            <p>Average Attractiveness</p>
        </div>
        """, unsafe_allow_html=True
    )

with col3:
    avg_rtw = filtered_df["Right to Win"].mean()
    st.markdown(
        f"""
        <div class="kpi-card">
            <h2>{avg_rtw:.2f}/10</h2>
            <p>Average Right-to-Win</p>
        </div>
        """, unsafe_allow_html=True
    )

with col4:
    best_os = filtered_df.loc[filtered_df["Attractiveness"].idxmax(), "ID"]
    st.markdown(
        f"""
        <div class="kpi-card">
            <h2>{best_os}</h2>
            <p>Top Opportunity</p>
        </div>
        """, unsafe_allow_html=True
    )

# ============================================================
# 10. OPPORTUNITY RADAR + SLIDER TEMPORALE + PANNELLO DETTAGLI
# ============================================================

st.subheader("Opportunity Radar")

# Slider temporale (basato su Created At)
if "Created At" in filtered_df.columns:
    min_date = pd.to_datetime(filtered_df["Created At"]).min()
    max_date = pd.to_datetime(filtered_df["Created At"]).max()
    
    if pd.notna(min_date) and pd.notna(max_date) and min_date != max_date:
        date_range = st.slider(
            "Time interval (OS creation)",
            min_value=min_date.to_pydatetime(),
            max_value=max_date.to_pydatetime(),
            value=(min_date.to_pydatetime(), max_date.to_pydatetime()),
            format="YYYY-MM-DD",
            key="date_slider"
        )
        filtered_df = filtered_df[
            (pd.to_datetime(filtered_df["Created At"]) >= date_range[0]) &
            (pd.to_datetime(filtered_df["Created At"]) <= date_range[1])
        ].copy()

if filtered_df.empty:
    st.warning("No Opportunity Spaces in this time range.")
    st.stop()

display_mode = st.radio("Display mode", ["Whole Radar", "Zoom-in"], horizontal=True, key="display_mode")

# Layout 3:1
col_radar, col_details = st.columns([3, 1])

with col_radar:
    if display_mode == "Whole Radar":
        size_metric = st.radio("Bubble size metric", ["Attractiveness", "Market Signal Strength"], horizontal=True, key="size_metric")
        
        st.markdown("""
        - Size of bubbles: {size_metric}.
        - Distance to the center: urgency.
        - Color: right to win.
        - **Clicca su una bolla** per vedere i dettagli a destra.
        """.format(size_metric=size_metric))

        # Classifica urgenza
        def classify_urgency(u):
            if u >= 7:
                return "Alta"
            elif u >= 4:
                return "Media"
            else:
                return "Bassa"
        
        filtered_df["urgency_level"] = filtered_df["Urgency"].apply(classify_urgency)
        filtered_df["theta"] = filtered_df.apply(lambda row : row.Vertical + " x " + row.Technology, axis = 1)
        filtered_df["rad"] = filtered_df.apply(lambda row : row.Urgency, axis = 1)
        filtered_df["name"] = filtered_df.apply(lambda row : row["Vertical"] + " x " + row["Use Case"] + " x " + row["Technology"], axis = 1)

        fig = px.scatter_polar(
            filtered_df, 
            r='rad', 
            theta='theta', 
            size=size_metric,
            text='ID', 
            size_max=45, 
            range_r=[0,10],
            hover_name='name', 
            hover_data={"Vertical": True,
                        "Use Case": True,
                        "Technology": True,
                        "Urgency": True,
                        "Attractiveness": ":.2f",
                        "Right to Win": ":.2f",
                        "Distance": True,
                        "ID": True,
                        "theta": False},
            color="Right to Win", 
            range_color=[0,10], 
            color_continuous_scale=["#FFF0CC","#FF8C00"], 
            opacity=0.8,
            labels={"rad":"Urgency","Right to Win":"Right to win", "Attractiveness":"Attractiveness", 
                    "theta":"Vertical x Technology", "ID":"Opportunity space label"}
        )

        # Stile tooltip
        fig.update_layout(
            hoverlabel=dict(
                bgcolor="#FF7900",
                bordercolor="#002244",
                align="left",
                font=dict(
                    family="Helvetica Neue, Helvetica, Arial, sans-serif",
                    size=14,
                    color="white"
                )
            ),
            font=dict(family="Helvetica Neue, Helvetica, Arial, sans-serif"),
            height=650,
            margin=dict(l=20, r=20, t=40, b=20)
        )

        # Bordo colorato per urgenza (ridotto a 1.5)
        color_map = {"Bassa": "#0000FF", "Media": "#FFFF00", "Alta": "#FF0000"}
        border_colors = [color_map.get(level, "#000000") for level in filtered_df["urgency_level"]]
        fig.update_traces(marker_line_color=border_colors, marker_line_width=3)

        # Abilita selezione al click
        try:
            selected_event = st.plotly_chart(
                fig,
                use_container_width=True,
                key="radar_chart",
                on_select="rerun",
                selection_mode="points"
            )
            if selected_event and selected_event.selection and selected_event.selection.points:
                point = selected_event.selection.points[0]
                st.session_state.selected_point = point.label
            else:
                st.session_state.selected_point = filtered_df.iloc[0]["ID"]
        except Exception:
            st.plotly_chart(fig, use_container_width=True)
            selected_id = st.selectbox("Seleziona OS", filtered_df["ID"].tolist(), key="fallback_select")
            st.session_state.selected_point = selected_id

    else:  # Zoom-in
        selected_os = st.selectbox("Choose OS", filtered_df["ID"].tolist(), key="zoom_os")
        os_row = filtered_df[filtered_df["ID"] == selected_os].iloc[0]
        st.session_state.selected_point = selected_os

        zoom_df = filtered_df[filtered_df["ID"] == selected_os].copy()
        zoom_df["rad"] = zoom_df["Urgency"]
        zoom_df["theta"] = zoom_df["Vertical"] + " x " + zoom_df["Technology"]

        fig_zoom = px.scatter_polar(
            zoom_df,
            r='rad',
            theta='theta',
            size='Attractiveness',
            text='ID',
            size_max=80,
            range_r=[0,10],
            color='Urgency',
            range_color=[0,10],
            color_continuous_scale=["#0000FF", "#FFFF00", "#FF0000"],
            title=f"Zoom on {selected_os}",
            labels={"rad":"Urgency","theta":"Vertical x Technology","color":"Urgency"}
        )
        fig_zoom.update_traces(marker_line_width=3)
        fig_zoom.update_layout(
            hoverlabel=dict(
                bgcolor="#FF7900",
                bordercolor="#002244",
                font=dict(
                    family="Helvetica Neue, Helvetica, Arial, sans-serif",
                    size=14,
                    color="white"
                )
            ),
            font=dict(family="Helvetica Neue, Helvetica, Arial, sans-serif"),
            height=500,
            margin=dict(l=20, r=20, t=40, b=20)
        )
        st.plotly_chart(fig_zoom, use_container_width=True)

# Colonna destra: dettagli OS selezionato (compatto, in box bianco)
with col_details:
    st.markdown("### OS Details")
    
    if "selected_point" not in st.session_state:
        st.session_state.selected_point = filtered_df.iloc[0]["ID"]
    
    selected_id = st.session_state.selected_point
    
    if selected_id not in filtered_df["ID"].values:
        selected_id = filtered_df.iloc[0]["ID"]
    
    selected = filtered_df[filtered_df["ID"] == selected_id].iloc[0]
    signals_df = load_signals(selected["opportunity_space_id"])
    
    # Box bianco con bordo arancione
    st.markdown(
        f"""
        <div style="background-color: #FFFFFF; border: 1px solid #FF7900; border-radius: 8px; padding: 10px; margin-bottom: 10px;">
            <h4 style="color: #002244; margin-top: 0;">{selected['ID']}</h4>
            <p style="margin: 5px 0; font-size: 0.9rem; color: #002244;"><b>Vertical:</b> {selected['Vertical']}</p>
            <p style="margin: 5px 0; font-size: 0.9rem; color: #002244;"><b>Use Case:</b> {selected['Use Case']}</p>
            <p style="margin: 5px 0; font-size: 0.9rem; color: #002244;"><b>Technology:</b> {selected['Technology']}</p>
            <hr style="margin: 8px 0; border: 0; border-top: 1px solid #E0E0E0;">
            <p style="margin: 5px 0; font-size: 0.9rem; color: #002244;"><b>Attractiveness:</b> {selected['Attractiveness']:.2f}/10</p>
            <p style="margin: 5px 0; font-size: 0.9rem; color: #002244;"><b>Right to Win:</b> {selected['Right to Win']:.2f}/10</p>
            <p style="margin: 5px 0; font-size: 0.9rem; color: #002244;"><b>Urgency:</b> {selected['Urgency']:.2f}/10</p>
            <p style="margin: 5px 0; font-size: 0.9rem; color: #002244;"><b>Distance:</b> {selected['Distance']}</p>
            <p style="margin: 5px 0; font-size: 0.9rem; color: #002244;"><b>Market Signal Strength:</b> {selected['Market Signal Strength']:.2f}/10</p>
            <hr style="margin: 8px 0; border: 0; border-top: 1px solid #E0E0E0;">
            <p style="font-size: 0.8rem; color: #666666; font-style: italic;">{selected['Strategic Relevance Justification'] if pd.notna(selected['Strategic Relevance Justification']) else 'N/A'}</p>
        </div>
        """, unsafe_allow_html=True
    )
    
    if not signals_df.empty:
        st.markdown("#### 📰 Evidence")
        for _, signal in signals_df.head(3).iterrows():
            st.write(f"- [{signal['Type']}] {signal['Title']}")

# ============================================================
# 11. RANKING
# ============================================================

st.subheader("Opportunity Ranking")

ranking_columns = ["ID", "Vertical", "Use Case", "Technology", "Attractiveness", "Right to Win", "Distance"]
ranking = filtered_df[ranking_columns].sort_values("Attractiveness", ascending=False)

st.dataframe(ranking, use_container_width=True, hide_index=True)

# ============================================================
# 12. DETTAGLIO COMPLETO (espandibile)
# ============================================================

st.subheader("Full Opportunity Details")
selected_id_full = st.selectbox("Choose an Opportunity Space", options=filtered_df["ID"].tolist(), key="os_select_full")
selected_full = filtered_df[filtered_df["ID"] == selected_id_full].iloc[0]
signals_df_full = load_signals(selected_full["opportunity_space_id"])

st.markdown(f"### {selected_full['ID']}")

col1, col2 = st.columns(2)
with col1:
    st.markdown("#### Opportunity")
    st.write("**Vertical:**", selected_full["Vertical"])
    st.write("**Use Case:**", selected_full["Use Case"])
    st.write("**Technology:**", selected_full["Technology"])

with col2:
    st.markdown("#### Scores")
    score_col1, score_col2 = st.columns(2)
    with score_col1:
        st.metric("Attractiveness", f"{selected_full['Attractiveness']:.2f}/10")
    with score_col2:
        st.metric("Right-to-Win", f"{selected_full['Right to Win']:.2f}/10")
    st.write("**Portfolio Distance:**", selected_full["Distance"])

# Attractiveness breakdown
st.markdown("### Attractiveness Breakdown")
score_data = pd.DataFrame({
    "Criterion": ["Market Signal Strength", "Source Diversity", "Evidence Quality", "Novelty / Momentum", "Strategic Relevance"],
    "Score": [selected_full["Market Signal Strength"], selected_full["Source Diversity"], selected_full["Evidence Quality"], selected_full["Novelty / Momentum"], selected_full["Strategic Relevance"]]
})
fig_scores = px.bar(score_data, x="Score", y="Criterion", orientation="h", range_x=[0, 10], title="Attractiveness Score Breakdown")
fig_scores.update_layout(height=400)
st.plotly_chart(fig_scores, use_container_width=True)

# Justifications (box custom)
st.markdown("### Strategic Explanation")
if pd.notna(selected_full["Strategic Relevance Justification"]):
    st.markdown(f'<div class="info-box">{selected_full["Strategic Relevance Justification"]}</div>', unsafe_allow_html=True)
else:
    st.markdown('<div class="info-box">No strategic relevance justification available.</div>', unsafe_allow_html=True)

st.markdown("### Evidence Quality")
if pd.notna(selected_full["Evidence Quality Justification"]):
    st.markdown(f'<div class="info-box">{selected_full["Evidence Quality Justification"]}</div>', unsafe_allow_html=True)
else:
    st.markdown('<div class="info-box">No evidence quality justification available.</div>', unsafe_allow_html=True)

# Right-to-Win
st.markdown("### Right-to-Win")
rtw_col1, rtw_col2 = st.columns(2)
with rtw_col1:
    st.metric("Right-to-Win Score", f"{selected_full['Right to Win']:.2f}/10")
    st.write("**Portfolio Distance:**", selected_full["Distance"])
with rtw_col2:
    st.markdown("#### Orange Business Assets")
    if pd.notna(selected_full["Matched Assets"]):
        st.write(selected_full["Matched Assets"])
    else:
        st.markdown('<div class="info-box">No matched assets available.</div>', unsafe_allow_html=True)

st.markdown("#### Why can Orange Business win?")
if pd.notna(selected_full["Right to Win Justification"]):
    st.markdown(f'<div class="info-box">{selected_full["Right to Win Justification"]}</div>', unsafe_allow_html=True)
else:
    st.markdown('<div class="info-box">No right-to-win justification available.</div>', unsafe_allow_html=True)

# Strategic position
st.markdown("### Strategic Position")
attractiveness = selected_full["Attractiveness"]
right_to_win = selected_full["Right to Win"]

if pd.notna(attractiveness) and pd.notna(right_to_win):
    if attractiveness >= 7 and right_to_win >= 7:
        st.markdown('<div class="success-box"><b>Strong opportunity:</b> high attractiveness and strong right-to-win.</div>', unsafe_allow_html=True)
    elif attractiveness >= 7 and right_to_win < 7:
        st.markdown('<div class="warning-box"><b>Attractive opportunity</b>, but Orange Business may need additional capabilities.</div>', unsafe_allow_html=True)
    elif attractiveness < 7 and right_to_win >= 7:
        st.markdown('<div class="info-box">Orange Business has a strong right-to-win, but market attractiveness is more moderate.</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="warning-box">Opportunity with relatively low attractiveness and right-to-win.</div>', unsafe_allow_html=True)

# Grounding signals
st.markdown("### Evidence / Grounding Signals")
if signals_df_full.empty:
    st.markdown('<div class="info-box">No evidence signals are available for this Opportunity Space.</div>', unsafe_allow_html=True)
else:
    signal_types = sorted(signals_df_full["Type"].dropna().unique())
    selected_signal_types = st.multiselect("Filter evidence type", options=signal_types, default=signal_types, key="signal_type_filter")
    visible_signals = signals_df_full[signals_df_full["Type"].isin(selected_signal_types)]

    if visible_signals.empty:
        st.markdown('<div class="info-box">No evidence matches the selected signal types.</div>', unsafe_allow_html=True)
    else:
        for _, signal in visible_signals.iterrows():
            source = signal["Source"]
            signal_type = signal["Type"]
            title = signal["Title"]
            summary = signal["Summary"]
            published_date = signal["Published Date"]
            url = signal["URL"]
            with st.expander(f"{signal_type} — {source}"):
                st.markdown(f"**{title}**")
                if pd.notna(summary) and summary:
                    st.write(summary)
                if pd.notna(published_date) and published_date:
                    st.caption(f"Published: {published_date}")
                if pd.notna(url) and url:
                    st.markdown(f"[Open source]({url})")

# ============================================================
# 13. FOOTER
# ============================================================

st.divider()
st.caption("Orange Business Innovation Radar • Data powered by radar.db")