import streamlit as st
import pandas as pd
import plotly.express as px

# -----------------------------------
# 1. CONFIGURATION DE LA PAGE
# -----------------------------------

st.set_page_config(
    page_title="Innovation Radar",
    page_icon="🟠",
    layout="wide"
)

# -----------------------------------
# 2. TITRE
# -----------------------------------

st.title("🟠 Orange Business Innovation Radar")

st.write(
    "Découvrez les Opportunity Spaces les plus intéressants "
    "pour Orange Business."
)

# -----------------------------------
# 3. NOS DONNÉES
# -----------------------------------

data = [
    {
        "ID": "OS004",
        "Vertical": "Manufacturing",
        "Use Case": "Industrial Safety Monitoring",
        "Technology": "Edge AI",
        "Attractiveness": 8.52,
        "Right to Win": 5.0,
        "Distance": "L3"
    },
    {
        "ID": "OS002",
        "Vertical": "Manufacturing",
        "Use Case": "Predictive Maintenance",
        "Technology": "Machine Learning",
        "Attractiveness": 7.02,
        "Right to Win": 6.0,
        "Distance": "L3"
    },
    {
        "ID": "OS001",
        "Vertical": "Public Sector",
        "Use Case": "Sovereign citizen data hosting",
        "Technology": "Sovereign cloud + GPU inference",
        "Attractiveness": 6.60,
        "Right to Win": 5.0,
        "Distance": "L3"
    },
    {
        "ID": "OS003",
        "Vertical": "Finance & Insurance",
        "Use Case": "Conduct-risk / compliance monitoring",
        "Technology": "AI surveillance of communications",
        "Attractiveness": 6.52,
        "Right to Win": 7.0,
        "Distance": "L1"
    },
    {
        "ID": "OS005",
        "Vertical": "Manufacturing",
        "Use Case": "Industrial defect detection",
        "Technology": "Edge computer vision",
        "Attractiveness": 6.50,
        "Right to Win": 6.0,
        "Distance": "L3"
    },
    {
        "ID": "OS006",
        "Vertical": "Public Sector",
        "Use Case": "Sovereign citizen data hosting",
        "Technology": "Sovereign cloud + GPU inference",
        "Attractiveness": 6.30,
        "Right to Win": 5.0,
        "Distance": "L3"
    },
    {
        "ID": "OS007",
        "Vertical": "Finance & Insurance",
        "Use Case": "Conduct-risk / compliance monitoring",
        "Technology": "AI surveillance of communications",
        "Attractiveness": 6.10,
        "Right to Win": 7.0,
        "Distance": "L1"
    },
    {
        "ID": "OS008",
        "Vertical": "Healthcare",
        "Use Case": "Remote patient monitoring",
        "Technology": "IoT sensors + AI analytics",
        "Attractiveness": 5.90,
        "Right to Win": 6.0,
        "Distance": "L2"
    }
]

df = pd.DataFrame(data)


# -----------------------------------
# FILTRES
# -----------------------------------

st.sidebar.header("🎛️ Filters")

verticals = st.sidebar.multiselect(
    "Choose Vertical",
    options=df["Vertical"].unique(),
    default=df["Vertical"].unique()
)

distances = st.sidebar.multiselect(
    "Choose Portfolio Distance",
    options=df["Distance"].unique(),
    default=df["Distance"].unique()
)

filtered_df = df[
    (df["Vertical"].isin(verticals)) &
    (df["Distance"].isin(distances))
]


# -----------------------------------
# 4. AFFICHER LE TABLEAU
# -----------------------------------

st.subheader("📋 All Opportunity Spaces")

st.dataframe(filtered_df, use_container_width=True)


# -----------------------------------
# 5. STATISTIQUES
# -----------------------------------

st.subheader("📊 Overview")

col1, col2, col3 = st.columns(3)

with col1:
    st.metric(
        "Number of Opportunities",
        len(filtered_df)
    )

with col2:
    st.metric(
        "Best Attractiveness",
        f"{filtered_df['Attractiveness'].max():.2f}/10"
    )

with col3:
    st.metric(
        "Best Right to Win",
        f"{filtered_df['Right to Win'].max():.1f}/10"
    )


# -----------------------------------
# 6. INNOVATION RADAR
# -----------------------------------

st.subheader("🎯 Opportunity Radar")

fig = px.scatter(
    filtered_df,
    x="Attractiveness",
    y="Right to Win",
    text="ID",
    hover_data=[
        "Vertical",
        "Use Case",
        "Technology",
        "Distance"
    ],
    size="Attractiveness",
    size_max=50,
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

st.plotly_chart(fig, use_container_width=True)


# -----------------------------------
# 7. DETAILS
# -----------------------------------

st.subheader("🔍 Opportunity Details")

selected_id = st.selectbox(
    "Choose an Opportunity Space",
    filtered_df["ID"]
)

selected = filtered_df[
    filtered_df["ID"] == selected_id
].iloc[0]

st.write("###", selected["ID"])

st.write("**Vertical:**", selected["Vertical"])
st.write("**Use Case:**", selected["Use Case"])
st.write("**Technology:**", selected["Technology"])
st.write("**Attractiveness:**", f"{selected['Attractiveness']}/10")
st.write("**Right to Win:**", f"{selected['Right to Win']}/10")
st.write("**Portfolio Distance:**", selected["Distance"])