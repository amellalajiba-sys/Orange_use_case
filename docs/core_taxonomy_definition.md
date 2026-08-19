# 0 - Core Taxonomy Definition
What Orange has already defined in the documents. It is the **basis for structuring the raw data**.

### Complete List of Verticals (Market Sectors / Industries)
The verticals explicitly mentioned in Orange's documents.

1. Manufacturing (includes heavy industry, process manufacturing, consumer goods, forestry & paper)
2. Retail
3. Finance (includes Banking, Insurance services)
4. Public Sector (includes Government)
5. Healthcare
6. Defense
7. Automotive
8. Fast Moving Consumer Goods
9. Industry (used as a generic term, but overlapping with Manufacturing)
10. IT and Services (mentioned as vertical on page 11 of the `innovation_radar_summary_roadmap_additions` file)

---

### Complete List of Use Cases (Problems to Solve)
The business areas or specific problems that Orange aims to address through innovation.

1. Energy Optimization
2. Demand Forecasting
3. IT Operations Automation
4. Imaging Analytics
5. Network Modernization & SD-WAN
6. Cloud Infrastructure Modernization
7. Cyber ​​Defense & Zero Trust
8. Customer Experience (orchestration, personalization)
9. Employee Experience (positive productivity, hybrid working)
10. Operational Excellence (IoT, industrial optimization, security)
11. Digital Infrastructure (connectivity, cloud, cybersecurity)
12. Data Sovereignty
13. Cybersecurity (as a specific use case)

---

### Complete List of Technologies (Tools / Enabling Platforms)
The technologies that enable the implementation of the use cases.

1. Cloud Data Platform
2. IoT Platforms
3. Computer Vision
4. Machine Learning
5. Generative AI
6. Network & SD-WAN
7. Cloud (generic, but requires specification)
8. Cybersecurity (as an enabling technology)
9. 5G
10. IoT (generic, but requires specification)
11. AI, Data, Cloud (areas of expertise)

---

## How to use them
These are the initial "whitelists." 

As the LLM will analyze a signal, _it will have to select a **Vertical**, a **Use Case** and a **Technology** exclusively from this lists_. 

This will allow us to:
* **Standardize the outputs**
* **Avoid generic topics** like "AI" or "Cloud" on their own.
* Ensure that every Opportunity/Signal (OS) aligns with Orange's business.

> [!WARNING] **Keywords that might be problematic** can still be used, but they require caution (they **must always be combined with other specific terms**).

---

> [!WARNING] **Risk**: We might miss out on opportunities in emerging sectors that Orange has not yet explicitly mentioned.

Below is how we may handle this aspect.
#### 1. Watchlist for "unclassified" signals
When a signal does not match any combination in the current taxonomy, it is not discarded but instead ends up in a watchlist.
The LLM attempts to classify the signal. If it fails, a function sets it aside in the watchlist.
#### 2. Extraction of new candidate terms
Periodically (e.g., daily), we analyze the signals on the watchlist to extract new terms.
#### 3. Relevance threshold and proposal to the team
When a candidate term reaches a relevance threshold (e.g., it appears in at least 5 signals from different sources), it is proposed to the team for validation.
#### 4. Proposal management dashboard
Create a section in the dashboard where the team can:
* View newly proposed terms along with their sources.
* Validate or reject each proposal.
* Automatically add the term to the taxonomy if validated.

> [!NOTE] **Irene**: `discovery_signals.py` in progress.

---

> [!NOTE] We can expand the lists later during the project, but for the MVP this serves as a solid and comprehensive foundation.

As we will go on in the project, it will evolve to an **Extended Taxonomy** that can update itself also considering signals found during exploration phase:

* it will be enriched by signals.
* new entries are added when a theme recurs with sufficient frequency.
* the new entries are submitted to the team for validation.

> [!NOTE] **Irene**: `extend_taxonomy.py` in progress.

---

To summarize:
## Flowchart for Signal Discovery and Taxonomy Evolution Process

```text
                    ┌─────────────────────┐
                    │    Signal Input     │
                    │(News, Reports, etc.)│
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │  LLM Classification │
                    │       Attempt       │
                    └──────────┬──────────┘
                               │
                    ┌──────────┴──────────┐
                    │                     │
                    ▼                     ▼
        ┌───────────────────┐   ┌───────────────────┐
        │   CLASSIFIED      │   │  UNCLASSIFIED     │
        │   Successfully    │   │  (Not in taxonomy)│
        └─────────┬─────────┘   └─────────┬─────────┘
                  │                       │
                  ▼                       ▼
        ┌───────────────────┐   ┌───────────────────┐
        │  ADD TO RADAR     │   │  ADD TO WATCHLIST │
        │  (Main OS)        │   │ (For later review)│
        └───────────────────┘   └─────────┬─────────┘
                                          │
                                          ▼
                               ┌─────────────────────┐
                               │  PERIODIC ANALYSIS  │
                               │  (Daily/Weekly)     │
                               └──────────┬──────────┘
                                          │
                                          ▼
                               ┌─────────────────────┐
                               │  EXTRACT CANDIDATE  │
                               │  TERMS              │
                               │  (New Vertical,     │
                               │   Use Case, Tech)   │
                               └──────────┬──────────┘
                                          │
                                          ▼
                               ┌─────────────────────┐
                               │ RELEVANCE THRESHOLD │
                               │  (Frequency ≥ 5?)   │
                               └──────────┬──────────┘
                                          │
                               ┌──────────┴──────────┐
                               │                     │
                               ▼                     ▼
                  ┌───────────────────┐   ┌───────────────────┐
                  │  YES (≥ 5)        │   │  NO (≤ 4)         │
                  │  Meets threshold  │   │  Below threshold  │
                  └─────────┬─────────┘   └─────────┬─────────┘
                            │                       │
                            ▼                       ▼
                  ┌───────────────────┐   ┌───────────────────┐
                  │  PROPOSE TO TEAM  │   │  KEEP IN          │
                  │  (Pending         │   │  WATCHLIST        │
                  │   Approval)       │   │  (Re-evaluate     │
                  └─────────┬─────────┘   │   later)          │
                            │             └───────────────────┘
                            ▼
                  ┌───────────────────┐
                  │  TEAM VALIDATION  │
                  │  Review & Decide  │
                  └─────────┬─────────┘
                            │
                  ┌─────────┴─────────┐
                  │                   │
                  ▼                   ▼
        ┌───────────────────┐   ┌───────────────────┐
        │  APPROVED         │   │  REJECTED         │
        │  (Validated)      │   │  (Not relevant)   │
        └─────────┬─────────┘   └─────────┬─────────┘
                  │                       │
                  ▼                       ▼
        ┌───────────────────┐   ┌───────────────────┐
        │  ADD TO           │   │  DISCARD          │
        │  TAXONOMY         │   │  (Remove from     │
        │  (New term added) │   │   watchlist)      │
        └───────────────────┘   └───────────────────┘
```


