# Building a Streamlit Dashboard – Step-by-Step Guide

## 🎯 Goal

Build a **working skeleton** of the Streamlit dashboard that:

1. Starts up and shows something useful (even with dummy data).
    
2. Has filters and interactions that simulate real behavior.
    
3. Is ready to accept real data when it arrives.
    

---

## 1. Steps to Follow

### Step 1: Prepare Your Environment

- Create a new Python file called `dashboard.py`.
    
- Install required libraries: `streamlit`, `pandas`, `plotly`.
    
- **Start the Streamlit server even with an empty file** (check **Hot Reload** below, last paragraph): `streamlit run dashboard.py`
    

### Step 2: Set Up the Page Structure

- Use `st.set_page_config()` for title and layout.
    
- Use `st.title()` and `st.caption()` for the header.
    
- Use `st.sidebar` for filters.
    
- Use `st.columns()` for metrics.
    
- Use `st.subheader()` for sections.
    

### Step 3: Create Mock Data

- Define a function that returns a **list of dictionaries**, where each dictionary represents an Opportunity Space.
    
- Each OS must have at least: `id`, `vertical`, `use_case`, `technology`, `score`, `signals` (list of sources).
    
- Scores and signals should be **consistent and varied**.
    
- Use `random` and `datetime` to generate dates and numbers.
    

### Step 4: Build Filters in the Sidebar

- Extract unique values for each category (verticals, use cases, technologies).
    
- Use `st.multiselect()` for each filter.
    
- Add a minimum score filter with `st.slider()`.
    
- Apply filters to the OS list.
    

### Step 5: Display Main Metrics

- Use `st.metric()` to show: total OS count, average score, maximum score.
    
- Calculate these values from the filtered list.
    

### Step 6: Create the Bubble Chart

- Convert the filtered list to a pandas DataFrame.
    
- Use `plotly.express.scatter()` with:
    
    - `x = score`
        
    - `y = a constant value (e.g., 1)` or random values to avoid overlaps
        
    - `size = score`
        
    - `color = vertical`
        
- Add `hover_data` to show details on mouseover.
    

### Step 7: Display the OS Table

- Create a DataFrame with main columns: `ID`, `Vertical`, `Use Case`, `Technology`, `Score`, `Signals`, `Sources`.
    
- Use `st.dataframe()` or `st.table()`.
    

### Step 8: Add OS Detail View

- Use `st.selectbox()` to select an OS.
    
- Show details: name, score, explanation, sources.
    
- Use `st.expander()` to hide/show information.
    

### Step 9: (Optional) Add a Watchlist

- Create a second set of dummy data for signals under observation.
    
- Show them in a separate expander.
    

### Step 10: Add a Footer

- Use `st.divider()` and `st.caption()` for date and credits.
    

---

## 2. Design Decisions You Need to Make

### 1. What Dummy Data to Create?

- How many OS? (10-15 is enough for testing)
    
- Which verticals, use cases, and technologies? (use the taxonomy)
    
- How to distribute scores? (some high, some medium, some low)
    

### 2. How to Structure the Data?

- Each OS is a dictionary.
    
- Each signal is a dictionary with `source` and `date`.
    
- Example:
```python
  {
    "id": "OS001",
    "vertical": "Manufacturing",
    "use_case": "Energy Optimization",
    "technology": "IoT Platforms",
    "score": 85,
    "signals": [
        {"source": "Reuters", "date": "2026-08-15"},
        {"source": "TechCrunch", "date": "2026-08-14"}
    ]
}
```

### 3. Which Filters Are Prioritized?

- Vertical
    
- Use Case
    
- Technology
    
- Minimum Score
    
- (Later you can add Persona, Geography)
    

### 4. Which Metrics to Show?

- Total OS
    
- Average Score
    
- Top Score
    
- Top OS (name)
    

### 5. Which Chart to Use?

- A Bubble Chart is what Orange requested.
    

### 6. How to Show Details?

- In an expander or in a separate column.

---
## 3. Tools to Use

|Tool|Purpose|
|---|---|
|`streamlit`|User interface|
|`pandas`|Data manipulation|
|`plotly.express`|Interactive charts|
|`random`|Generating dummy data|
|`datetime`|Generating dummy dates|

---
## 4. File Structure for `dashboard.py`

```text

1. Import libraries
2. Page configuration
3. Generate dummy data (function)
4. Load data (with caching)
5. Sidebar with filters
6. Apply filters
7. Main metrics
8. Bubble chart
9. OS table
10. OS detail view
11. (Optional) Watchlist
12. Footer
```

---
## ⚠️ Important Details

|Aspect|Advice|
|---|---|
|**Caching**|Use `@st.cache_data` to prevent regenerating data on every interaction.|
|**Scores**|Must be explainable. Even in dummy data, include a text explanation.|
|**Interactivity**|Filters must update chart and table immediately.|
|**Usability**|Test with fresh eyes: are filters clear? Is information easy to find?|

---
## 💡 How to Proceed

### Steps

1. Create `dashboard.py` file.
    
2. Add basic structure (configuration, title, sidebar).
    
3. Generate 10 dummy OS with scores and signals.
    
4. Show main metrics.

5. Add the bubble chart.
    
6. Add the table.
    
7. Add detail view for selected OS.

8. Test with the team (especially Gaetan).
    
9. Gather feedback (especially Gaetan).
    
10. Adjust filters and layout.
    
11. Prepare dashboard to accept real data.
    

---

## 🚀 Getting Started with Streamlit (Hot Reload)

### What is Hot Reload?

When you run `streamlit run dashboard.py`, Streamlit:

1. Starts a web server on your machine (usually at `http://localhost:8501`).
    
2. **Watches** the `dashboard.py` file and **automatically reloads** the page every time you save.
    

### How It Works in Practice

```text
1. Create a dashboard.py file (even empty)
2. Run: streamlit run dashboard.py
3. Streamlit opens the browser (even if empty)
4. Start writing code
5. Every time you save (Ctrl+S), Streamlit:
   - Detects the change
   - Reloads the code
   - Updates the page in the browser (in 1-2 seconds)
1. You see changes in real time!
```

### Why Do This Immediately (Even with an Empty File)?

| Advantage                 | Why It's Useful                                                   |
| ------------------------- | ----------------------------------------------------------------- |
| **Immediate feedback**    | No need to wait until you've written all the code to see results. |
| **Faster debugging**      | If something breaks, you see it immediately and can fix it.       |
| **Iterative development** | Build the dashboard piece by piece, verifying each part works.    |
