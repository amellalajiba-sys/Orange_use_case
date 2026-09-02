# Innovation Radar — Orange Business

Signal-driven Opportunity Space detection pipeline, built for a BeCode AI & Data Science
bootcamp client project with Orange Business. Scans market signals (news, research, regulation,
public procurement, competitor activity) and scores candidate B2B opportunities on two
independent axes, **Attractiveness** and **Right-to-win**, so a Strategist, Sales, or Presales
team can decide where to focus next.

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat&logo=python&logoColor=white)](https://www.python.org/)
[![Streamlit](https://img.shields.io/badge/Streamlit-App-FF4B4B?style=flat&logo=streamlit&logoColor=white)](https://orange-radar.streamlit.app)
[![LLM](https://img.shields.io/badge/LLM-Groq%2FCerebras%2FSambaNova-f34e3a?style=flat&logo=groq&logoColor=white)](https://groq.com/)
[![Database](https://img.shields.io/badge/Database-SQLite-003B57?style=flat&logo=sqlite&logoColor=white)](https://www.sqlite.org/)
![Status](https://img.shields.io/badge/Status-Completed-brightgreen?style=flat)
[![Training](https://img.shields.io/badge/Training-BeCode-black?style=flat)](https://becode.org/)

<p align="center">
  <img src="assets/orange_business_master_logo_text_white.png" alt="Orange Business Logo" width="380"/>
</p>

<p align="center">
  <a href="https://orange-radar.streamlit.app/" target="_blank">
    <img src="https://static.streamlit.io/badges/streamlit_badge_black_white.svg" alt="Streamlit App"/>
  </a>
</p>

The Innovation Radar transforms scattered external signals into clear, actionable Opportunity Spaces. It ingests data from nine sources (news, research, regulation, tenders, competitor activity), uses an LLM to extract recurring themes constrained to a closed taxonomy, and scores each candidate on Attractiveness (market visibility) and Right-to-win (portfolio fit). The dashboard gives Orange Business strategists, sales, and presales teams a fast, evidence-based decision tool.

* **Domain:** Innovation Discovery, Market Intelligence, Generative AI, Data Engineering
* **Execution Timeframe:** Multi‑week project (Orange Business client case)
* **Development Type:** Team project (BeCode AI & Data Science bootcamp)

---

## Architecture & System Data Flow

```text
        +-----------------------+      HTTP POST      +-----------------------------------------+
        |  Streamlit UI         |    (User Prompt)    |  pipeline/ingest.py                     |
        |  (dashboard/)         | ------------------> |  - 9 external signal sources            |
        |  - Filters & Visuals  |                     |  - Rate‑limit & cooldown handling       |
        +-----------------------+                     +-----------------------------------------+
                |                                                       |
                |                                                       v
                | Execute / refresh                                     | pipeline/analyze.py
                |                                                       |  - LLM theme extraction
                |                                                       |  - Taxonomy classification
                |                                                       +--------------------------------+
                |                                                                                        |
                v                                                                                        v
        +-----------------------------------------+                                    +----------------------------------------+
        |  pipeline/db.py                         |                                    |  pipeline/scoring                      |
        |  - SQLite schema (radar.db)             |                                    |  - Attractiveness (5 weighted factors) |
        |  - Dedupe & unique constraint           |                                    |  - Right‑to‑win (L0–L4)                |
        |  - Linked signals per OS                |                                    |  - Urgency (dynamic scaling)           |
        +-----------------------------------------+                                    +----------------------------------------+
                                                                                                            |
                                                                                                            v
        +-----------------------------------------+                                    +-----------------------------------------+
        |  pipeline/extend_taxonomy.py            |                                    |  dashboard/ (Streamlit + Power BI)      |
        |  - Watchlist → proposals                |                                    |  - Radar chart, filters, KPI            |
        |  - Manual approval flow                 |                                    +-----------------------------------------+
        +-----------------------------------------+
```

---

## System Workflow
* **Ingest**: collect signals from 9 sources (Google News, NewsAPI.ai, GDELT, arXiv, Semantic Scholar, vendor blogs, Hacker News, EUR‑Lex, TED).
* **Analyze**: LLM extracts recurring Use Case × Technology themes, constrained to the closed taxonomy.
* **Taxonomy Extension**: out‑of‑taxonomy terms go to a watchlist; when they cross a frequency threshold they become proposals, reviewed and approved by the team via radar_cli.py review.
* **Create / Promote**: seed Opportunity Spaces from config.CANDIDATES; recurring themes are auto‑promoted (radar_cli.py promote). A DB‑level unique index prevents duplicate triples.
* **Link**: attach the strongest keyword‑matched signals to each Opportunity Space.
* **Score**: compute Attractiveness, Right‑to‑win, and Urgency on each OS's linked signals (not the whole vertical).
* **Refresh**: deterministic sub‑scores are re‑computed against current linked signals (free, no LLM).
* **Enrich**: add role, buyer persona, geography, horizon, domain, and next actions per role.
* **Visualize**: Streamlit dashboard and Power BI report, both reading radar.db.

---

## Quick Start
```bash
git clone <repo-url> && cd Orange_use_case
pip install -r requirements.txt
python radar_cli.py all           # full pipeline (uses LLM quota)
python -m streamlit run dashboard/streamlit_app.py --server.address=127.0.0.1
```

No Groq key? Install Ollama locally and set LLM_PROVIDER=auto – the client falls back to it automatically.

---

## 📁 Project Structure
```text
Orange_use_case/
├── dashboard/                    # Streamlit dashboard + Power BI report
│   ├── streamlit_app.py
│   ├── innovation_radar_dashboard.pbix
│   └── ...
├── pipeline/
│   ├── config.py                 # Vertical seeds, taxonomy, Orange Business assets
│   ├── db.py                     # SQLite schema, data access, dedupe
│   ├── ingest.py                 # 9‑source signal collector
│   ├── analyze.py                # LLM theme extraction
│   ├── theme_promotion.py        # Recurring valid themes
│   ├── extend_taxonomy.py        # Watchlist → proposals flow
│   ├── taxonomy_validation.py    # Guard against generic terms
│   └── scoring.py                # Attractiveness + Right‑to‑win + Urgency
├── llm/
│   └── llm_client.py             # Provider‑agnostic LLM client
├── logs/                         # Timestamped ingest logs + cooldown state
├── radar_cli.py                  # CLI entry point
├── taxonomy_extensions.json      # Approved taxonomy terms
├── opportunity_spaces_summary.md # Auto‑generated client‑facing summary
└── requirements.txt
```

---

## Setup
Create a `.env` file at the project root:
```env
LLM_PROVIDER=auto              # auto | groq | cerebras | sambanova | ollama
GROQ_API_KEY=your-key-here
CEREBRAS_API_KEY=               # optional
SAMBANOVA_API_KEY=              # optional
NEWSAPI_AI_KEY=                 # optional
```

Any cloud LLM key can be left blank – `auto` mode skips that provider and falls through to the next one. Only `GROQ_API_KEY` is effectively required for a useful run.

---

## Run It

### Full pipeline (one command):
```bash
python radar_cli.py all            # ingest → analyze → extend_taxonomy → create → promote
                                   #   → link → score → summary
python radar_cli.py all --force    # same, but rescore + re‑enrich everything
```

### Step by step:
```bash
python -m pipeline.db
python -m pipeline.ingest
python -m pipeline.analyze
python -m pipeline.extend_taxonomy
python radar_cli.py review         # approve/reject taxonomy proposals
python radar_cli.py create
python radar_cli.py promote
python radar_cli.py link
python -m pipeline.scoring
python radar_cli.py summary
```

### Dashboard:
```bash
python -m streamlit run dashboard/streamlit_app.py --server.address=127.0.0.1
```
**Other useful commands**: `radar_cli.py -h` for the full list. Highlights: `calibrate`, `dedupe --apply`, `watchlist`, `scores`, `delete`, `review`.

---

## Key Design Decisions
* **One source of truth for verticals** (`config.VERTICAL_SEEDS`)
* **Closed taxonomies** for Use Case / Technology, extensible via approved proposals
* **Score each OS on its own linked signals** – not the whole vertical
* **Duplicate triples are impossible** – check + DB unique index
* **Existing OS stay fresh without burning LLM quota** – `--refresh` recomputes deterministic fields
* **Urgency scales dynamically** – 95th percentile of weighted urgent signals, recalculated each run
* **Novelty feeds both urgency and attractiveness** – intentional, not double‑counting
* **Grounded scoring** – Right‑to‑win and Strategic Relevance are based on Orange Business's real API catalog, named customers, and analyst recognition
* **Audit trail, never overwrite** – `scores` and `right_to_win_scores` always INSERT
* **Resilience over completeness** – every external call is wrapped so one source failure doesn't crash the run

---

## Key features that make this tool unique

* **Multi‑provider LLM fallback** – the pipeline automatically rotates across Groq → Cerebras → SambaNova → Ollama, ensuring it never halts due to a single provider's rate limit. This is rare in a bootcamp project and gives real production‑grade resilience.
* **Self‑extending taxonomy** – new terms are discovered from signals, enter a watchlist, and only become official after human approval. The system grows with the data, not via manual config editing.
* **Explainable scoring** – every score is computed on signals linked to the specific Opportunity Space, and each OS carries a textual justification. The output is transparent, not a black box.
* **Living urgency** – the urgency score is recalibrated against the current population (95th percentile of weighted urgent signals) on every run, so the radar reflects the current market context rather than a static snapshot.
* **Duplicate‑proof by design** – a database‑level `UNIQUE(vertical, use_case, technology)` index makes it impossible to register the same opportunity twice under different labels, even if the application‑level check fails.

---

## Known Limitations

* `--refresh` doesn't re‑attach signals – run `radar_cli.py link` first if new signals arrived
* LLM fallback to neutral scores when quota exhausted – check console for "LLM scoring unavailable"
* `novelty_momentum` is only meaningful after several weeks of ingest history
* Recalibrate `MARKET_SIGNAL_CAP` / `SOURCE_DIVERSITY_CAP` with `calibrate` after meaningful changes
* **Pipeline runs locally** – currently operates on a local machine with a local `radar.db`; it is not 24/7 cloud‑hosted, and updates require manual execution.
* **LLM quota is the bottleneck** – when the free tier is exhausted, evidence_quality and strategic_relevance fall back to neutral values that need re‑scoring later.
* **Some verticals have sparse coverage** – e.g. Healthcare, Natural Resources – leading to less reliable scores for those segments.
* **Scoring weights are manual** – the 30/20/25/10/15% split is a judgment call; with more data, they should be statistically derived.

---

## Next Steps

1. **Deploy to cloud** – containerise the pipeline (Docker) and host the database (e.g. Azure SQL/PostgreSQL) so the dashboard becomes always available and automatically updated via scheduled runs (GitHub Actions or cron).
2. **Integrate internal data** – use Orange's CRM (customer overlap, pipeline value) to refine the Right‑to‑win calibration, as requested in the brief.
3. **Automate refresh cycles** – trigger `link` + `--refresh` automatically after each ingest so scores update without manual intervention.
4. **Add review UI** – embed the taxonomy proposal approval directly into the Streamlit dashboard instead of requiring CLI usage.
5. **Improve source coverage** – add more data sources for verticals with weak signal volume, or refine queries to reduce noise.
6. **Recalibrate weights** – after collecting several runs, derive the attractiveness weights statistically rather than keeping them manually tuned.  

<br>

<br>

---

<br>

## Authors 
**Irene Ghioni** (Team Lead)
[AI & Data Science](https://becode.org/en/job-seekers/trainings/ai-data-science) Trainee at [BeCode Belgium](https://becode.org/) *(Specializing in Data Science)*  
[![LinkedIn Profile](https://img.shields.io/badge/LinkedIn-0A66C2?style=flat&logo=linkedin&logoColor=white)](https://www.linkedin.com/in/ireneghioni/) [![GitHub](https://img.shields.io/badge/GitHub-181717?style=flat&logo=github&logoColor=white)](https://github.com/ireneghioni-glitch)

**Gaetan Bricteux** (Documentations Specialist)
[AI & Data Science](https://becode.org/en/job-seekers/trainings/ai-data-science) Trainee at [BeCode Belgium](https://becode.org/) *(Specializing in Data Science)*  
[![LinkedIn Profile](https://img.shields.io/badge/LinkedIn-0A66C2?style=flat&logo=linkedin&logoColor=white)](https://www.linkedin.com/in/ga%C3%ABtan-bricteux/) [![GitHub](https://img.shields.io/badge/GitHub-181717?style=flat&logo=github&logoColor=white)](https://github.com/gbricteux) 

**Siegried Camus** (Data Architect)
[AI & Data Science](https://becode.org/en/job-seekers/trainings/ai-data-science) Trainee at [BeCode Belgium](https://becode.org/) *(Specializing in Generative AI)*  
[![LinkedIn Profile](https://img.shields.io/badge/LinkedIn-0A66C2?style=flat&logo=linkedin&logoColor=white)](http://www.linkedin.com/in/siegried-camus) [![GitHub](https://img.shields.io/badge/GitHub-181717?style=flat&logo=github&logoColor=white)](https://github.com/Siegried81) 

**Hiba Amellal** (Data Architect)
[AI & Data Science](https://becode.org/en/job-seekers/trainings/ai-data-science) Trainee at [BeCode Belgium](https://becode.org/) *(Specializing in Data Engineering)*  
[![LinkedIn Profile](https://img.shields.io/badge/LinkedIn-0A66C2?style=flat&logo=linkedin&logoColor=white)](https://www.linkedin.com/in/amellal-hiba-7a636940a/) [![GitHub](https://img.shields.io/badge/GitHub-181717?style=flat&logo=github&logoColor=white)](https://github.com/amellalajiba-sys)