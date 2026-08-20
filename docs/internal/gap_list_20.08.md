# Gap List - 20/08/2026

## 📊 Complete Gaps Table

| **Feature / Requirement**                 | **Current Status** | **Where It's Missing** | **Required By**    |
| ----------------------------------------- | ------------------ | ---------------------- | ------------------ |
| **Persona filtering**                     | ❌ Not implemented  | Dashboard              | Brief, Page 5 & 6  |
| **Geography filtering**                   | ❌ Not implemented  | Dashboard              | Brief, Page 5 & 13 |
| **Persona + vertical ranking**            | ❌ Not implemented  | Scoring logic          | Brief, Page 5      |
| **Persona in OS definition**              | ❌ Not tracked      | OS table               | Brief, Page 5 & 6  |
| **Persona-specific acceptance criteria**  | ❌ Not implemented  | Dashboard/UX           | Brief, Page 13     |
| **Time horizon logic (Now, Next, Later)** | ❌ Not implemented  | OS table / Scoring     | Brief, Page 19     |
| **Urgency scoring component**             | ❌ Not implemented  | Scoring logic          | Brief, Page 16     |
| **Recommended next action per OS**        | ❌ Not implemented  | OS table / Dashboard   | Brief, Page 16     |
| **Geography in OS definition**            | ❌ Not tracked      | OS table               | Brief, Page 5 & 13 |
| **Signal type taxonomy fully used**       | ⚠️ Partially       | Dashboard filtering    | Brief, Page 16     |
| **Watchlist logic**                       | ⚠️ Planned         | Not yet implemented    | Brief, Page 19     |
| **Right-to-win internal data**            | ⚠️ Partial         | Scoring logic          | Brief, Page 18     |

---

## 📋 Detailed Gap Breakdown

### 1. Persona — Explicitly Required

| Requirement                              | Document Reference | What's Missing                           |
| ---------------------------------------- | ------------------ | ---------------------------------------- |
| Filter by Persona (CIO, CISO, COO, etc.) | Brief, Page 5 & 6  | No persona filter in dashboard           |
| Persona + vertical returns ranked topics | Brief, Page 5      | Not used in scoring or filtering         |
| Persona-specific user stories            | Brief, Page 13     | Not implemented in UX                    |
| Persona in OS definition                 | Brief, Page 6      | Not stored in `opportunity_spaces` table |

> [!NOTE] **Target Personas from Orange** (Brief, Page 6):
> - CIOs
> - IT and network executives
> - Security executives
> - COOs & production executives
> - CMOs & CX executives
> - CISOs
> - CDOs
> - Industrial safety managers Quality managers

---

### 2. Geography — Explicitly Required

|Requirement|Document Reference|What's Missing|
|---|---|---|
|Filter by Geography|Brief, Page 5 & 13|No geography filter in dashboard|
|Geography in OS definition|Brief, Page 5|Not stored in `opportunity_spaces` table|

> [!WARNING] **Missing**: Your `signals` table stores `source_name` (e.g., "TED - European Commission") but there is **no dedicated `geography` or `region` field**. This data is not being captured or used.

---

### 3. Time Horizon / Urgency — Explicitly Required

|Requirement|Document Reference|What's Missing|
|---|---|---|
|Time horizon logic (Now, Next, Later)|Brief, Page 19|Not implemented|
|Urgency scoring component|Brief, Page 16|Not in scoring formula|
|"Why hot now" explanation|Brief, Page 16|Not in OS summary|

**Current scoring**:

```text
30% market_signal_strength
20% source_diversity
20% evidence_quality
15% strategic_relevance
15% novelty_momentum
```

> [!WARNING] **Missing**:
> - **Urgency** as a separate component;
> - **Time horizon classification** (Now, Next, Later)

---

### 4. Recommended Next Action — Explicitly Required

|Requirement|Document Reference|What's Missing|
|---|---|---|
|"Recommended next action" per topic|Brief, Page 16|Not in OS table or dashboard|
|Actionable next step (idea, deep-dive, talking point)|Brief, Page 13|Not implemented|

> [!NOTE] **Example from Orange** (Brief, Page 7):
> _"Private 5G + edge vision for safety compliance in mining"_
> - Hot: Regulators mandate real-time monitoring
> - Next step: **Deep dive with customer in mining vertical**

---

### 5. Signal Type Taxonomy — Partially Implemented

|Requirement|Document Reference|What's Missing|
|---|---|---|
|Explicit signal types|Brief, Page 16|Types exist in DB but not used in UI|
|Filter by signal type|Brief, Page 5|Not in dashboard|
|Explain "why hot" with signal types|Brief, Page 16|Not in OS summary|

**What you have**: The `signals` table has `signal_type` (trend, regulation, buying_signal, market_move, tech_maturity, proof_signal).

> [!WARNING] **What's missing**: The signal types are **not exposed** in the dashboard for filtering or used to explain "why hot."

---

### 6. Right-to-Win Internal Data — Only Partially Implemented

|Requirement|Document Reference|What's Missing|
|---|---|---|
|Internal data for right-to-win|Brief, Page 18|Only API catalog is used|
|CRM customer overlap|Brief, Page 18|Not used|
|Opportunity count / pipeline value|Brief, Page 18|Not used|
|Product/offering match|Brief, Page 18|✅ Partially (API catalog)|
|People capability|Brief, Page 18|Not used|

> [!NOTE] **What Orange says** (Brief, Page 18):
> _"Internal data will be added in the next phase, after the external discovery and scoring model is finalized."_
> **So this is acceptable for MVP**, but you should note it as a **known limitation**.

---

### 7. Watchlist Logic — Planned but Not Implemented

|Requirement|Document Reference|What's Missing|
|---|---|---|
|Watchlist for early signals|Brief, Page 19|`signals_discovery.py` not yet implemented|
|Internal topic ranking for OS generation|Brief, Page 19|Not yet implemented|

> [!WARNING] **Your status**: You have `emerging_themes.json` and `detect_emerging_from_themes()` working, but **`signals_discovery.py` and `extend_taxonomy.py` are not yet implemented**.

---

## 🎯 Priorities

| Priority | Feature                                      | Effort | Why It Matters                     |
| -------- | -------------------------------------------- | ------ | ---------------------------------- |
| **1** 🟥 | **Persona filtering** in dashboard           | Medium | Explicitly required, visible in UI |
| **2** 🟥 | **Geography filtering** in dashboard         | Low    | Explicitly required, visible in UI |
| **3** 🟥 | **Recommended next action** per OS           | Low    | Explicitly required, easy to add   |
| **4** 🟨 | **Time horizon / Urgency** in scoring        | Medium | Adds "why hot now" explanation     |
| **5** 🟩 | **Signal type filtering** in dashboard       | Low    | Adds depth to filtering            |
| **6** 🟨 | **Watchlist logic** (`signals_discovery.py`) | Medium | Required for "living radar"        |
| **7** 🟨 | **Extend taxonomy** (`extend_taxonomy.py`)   | Medium | Required for "living radar"        |
