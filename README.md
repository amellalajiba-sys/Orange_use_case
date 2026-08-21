# Innovation Radar — Signal-Driven Opportunity Detection

Prepared for Orange Business by BeCode cohort BXL-Gebru-1 (GenAI Development specialization).

## Executive summary

This project continuously scans market signals — news, vendor announcements, research, regulation,
tenders — to detect emerging **Vertical × Use Case × Technology** opportunities before they become
obvious, and scores each one on two independent axes:

- **Attractiveness** — is the market actually moving (signal volume, source diversity, evidence quality,
  momentum, strategic fit)?
- **Right-to-win** — can Orange Business sell this today, using the existing API/asset catalog, or does it
  require a partner or new capability?

TO DO DO CHECK:
A Power BI dashboard turns the scored opportunities into a decision tool the team can use in client
conversations, and a Streamlit app offers a lighter, role-based view of the same data.

## Recent pipeline changes (read before the next run)

A few fixes are listed here so everyone knows what changed and why before touching the pipeline again.
- **Ran the missing schema migration.** The promoted `radar.db` predated the `buyer_persona` column split
  and was missing it. Fixed by running `python -m pipeline.db`, which applies any pending `ALTER TABLE`
  migrations without touching existing data.
- **Lowered two thresholds given the time left before the presentation:**
  - `analyze.py`: minimum signals required before attempting theme extraction, `5` → `3`.
  - `config.py`: `RECURRING_THEME_PROMOTION_THRESHOLD`, `3` → `2`.
  Tradeoff: faster discovery, slightly less confirmation that a theme is a real recurring pattern. Revert
  toward the original values if this starts surfacing weak/noisy opportunity spaces. Neither change does
  anything on its own — `radar_cli.py all` still needs to run more than once for frequency to accumulate.
- **Merged in a theme-curation step.** `analyze.py` now runs `_curate_themes()` on every batch the LLM
  proposes before they're tracked: drops themes whose technology is a bare generic term (e.g. "AI" alone),
  and fuzzy-matches near-duplicate themes together, keeping the one with more supporting signals. This
  came out of a parallel branch that also explored an open-taxonomy prompt + a separate
  `emerging_themes.json` file for tracking out-of-taxonomy terms — that JSON approach wasn't merged as its
  own mechanism, since the closed-taxonomy contract and the `recurring_themes` table are what `radar_cli.py`
  and `db.py` are built around. The curation logic itself was kept and is now in the shared `analyze.py`.
  The genuinely strong candidates that JSON file had already found (6 full Vertical × Use Case × Technology
  themes with real supporting signal counts) were promoted through the normal `recurring_themes` →
  `radar_cli.py promote` path instead — see OS029–OS034 below.
- **Groq daily token quota ran out mid-presentation-prep.** A `--force` rescore triggered while the quota
  was nearly exhausted overwrote several opportunity spaces' scores with neutral "LLM scoring unavailable"
  defaults (0.0/10 right-to-win, L4). The real scores for all affected OS were restored from the last known
  good run (not re-invented) — see `restore_os001_027_scores.py` and `restore_os029_034_scores.py` at the
  repo root. **OS028 has no known-good prior score** (it was promoted after the original scoring pass) and
  still shows the neutral default — re-run `python -m pipeline.scoring` on it once Groq quota is available
  again, or switch `.env`'s `LLM_PROVIDER` if the team decides on a fallback.
None of this changes the taxonomy, the scoring formulas, or the CLI commands — same `radar_cli.py all`
workflow as before.

## All opportunity spaces identified

34 opportunity spaces: the original 27 from `radar.db`, plus 6 more (OS029–OS034) promoted from a
teammate's `emerging_themes.json` prototype via the standard `recurring_themes` → `radar_cli.py promote`
path. Sorted by attractiveness. Full grounding signals per OS are in `opportunity_spaces_summary.md`.

| OS | Vertical | Use Case | Technology | Attractiveness | Right-to-win | Distance |
|---|---|---|---|---|---|---|
| OS009 | Finance & Insurance | Cloud Infrastructure Modernization | Cloud | 8.53 | 9.0 | L0 |
| OS033 | Manufacturing | Industrial Process Optimization | IoT Platforms | 8.54 | 8.0 | L1 |
| OS015 | Public Sector | Digital Infrastructure | IoT Platforms | 8.52 | 8.0 | L1 |
| OS032 | Public Sector | Infrastructure Planning & Management | Digital Twins | 8.02 | 7.0 | L1 |
| OS005 | Manufacturing | Energy Optimization | IoT Platforms | 8.28 | 6.0 | L3 |
| OS016 | Manufacturing | Network Modernization & SD-WAN | 5G | 8.28 | 8.0 | L1 |
| OS018 | Finance & Insurance | Network Modernization & SD-WAN | Network & SD-WAN | 8.28 | 9.0 | L0 |
| OS034 | Manufacturing | Manufacturing Process Automation | Agentic AI | 8.24 | 0.0 | L4 |
| OS013 | Public Sector | Data Sovereignty | Cloud | 8.17 | 6.0 | L3 |
| OS001 | Public Sector | Sovereign citizen data hosting | Sovereign cloud + GPU inference | 7.92 | 5.0 | L3 |
| OS002 | Manufacturing | Fire and hazard detection | Edge computer vision | 7.83 | 6.0 | L3 |
| OS003 | Finance & Insurance | Conduct-risk / compliance monitoring | AI surveillance of communications | 7.78 | 6.0 | L3 |
| OS010 | Finance & Insurance | Cybersecurity | Machine Learning | 7.78 | 5.0 | L3 |
| OS014 | Public Sector | Cyber Defense & Zero Trust | Cybersecurity | 7.77 | 8.0 | L1 |
| OS031 | Manufacturing | Strategic Communications & Advertising Consultancy | Generative AI | 7.54 | 6.0 | L2 |
| OS006 | Manufacturing | Operational Excellence | Machine Learning | 7.68 | 7.0 | L1 |
| OS004 | Manufacturing | Remote-controlled industrial robots | Vision-guided teleoperation | 7.53 | 8.0 | L1 |
| OS007 | Manufacturing | Cyber Defense & Zero Trust | Cybersecurity | 7.53 | 7.0 | L1 |
| OS008 | Manufacturing | Imaging Analytics | Computer Vision | 7.53 | 6.0 | L3 |
| OS011 | Finance & Insurance | Customer Experience | Generative AI | 7.53 | 5.0 | L2 |
| OS012 | Finance & Insurance | IT Operations Automation | Machine Learning | 7.48 | 5.0 | L3 |
| OS019 | Manufacturing | Operational Excellence | Edge Computing | 7.43 | 8.0 | L1 |
| OS017 | Finance & Insurance | IT Operations Automation | Agentic AI | 7.33 | 5.0 | L3 |
| OS029 | Manufacturing | Industrial Digital Twin & Automation | Digital Twins | 7.99 | 6.0 | L3 |
| OS030 | Manufacturing | Post-Quantum Cryptography Testing Infrastructure | Quantum-safe Cryptography | 7.09 | 5.0 | L3 |
| OS020 | Public Sector | Cloud Infrastructure Modernization | Cloud | 7.02 | 0.0 | L4 |
| OS023 | Public Sector | Digital Infrastructure | Cloud | 7.02 | 0.0 | L4 |
| OS024 | Public Sector | Data Sovereignty | Cloud Data Platform | 7.02 | 0.0 | L4 |
| OS028 | Public Sector | Digital Infrastructure | Cloud Data Platform | 7.02 | 0.0 | L4 |
| OS021 | Energy | Grid Optimization | IoT Platforms | 4.26 | 0.0 | L4 |
| OS022 | Energy | Grid Optimization | Edge Computing | 4.26 | 0.0 | L4 |
| OS025 | Retail | Customer Experience | Agentic AI | 4.08 | 0.0 | L4 |
| OS026 | Retail | Contact Centre Automation | Agentic AI | 4.08 | 0.0 | L4 |
| OS027 | Healthcare | Data Sovereignty | Cloud | 4.04 | 0.0 | L4 |

**Note — the OS001/OS013/OS024 triple-duplicate is confirmed in this data**: all three describe "Public
Sector data sovereignty" under different labels (7.92/L3/5.0, 8.17/L3/6.0, 7.02/L4/0.0). **OS013 has both
the highest attractiveness and the highest right-to-win of the three.** OS024's score should not be read
as "objectively weaker" — its `evidence_quality`, `strategic_relevance`, and right-to-win justification all
read "LLM scoring unavailable, neutral default used," meaning it was never actually scored. Re-run
`python -m pipeline.scoring --force` before citing it in any comparison. Between OS001 and OS013, OS013's
label matches the official taxonomy exactly and its right-to-win justification cites one clean matched
asset (API Cloud Avenue) without overstating what Orange currently offers, while OS001's justification
notes that "GPU inference is not a current specific feature" — the label promises more than the portfolio
currently backs.

**Note — OS028 was never scored** (a "LLM scoring unavailable" default, same situation OS024 was already
in). No known-good prior value exists to restore it from — it was promoted after the original scoring pass.
Re-score before citing it in the pitch.

**Note — OS029–OS034 are new, promoted from a teammate's `emerging_themes.json` exploration** (see changelog
above). OS033 and OS032 in particular are strong enough to be worth a look for the shortlist: OS033
(Manufacturing × Industrial Process Optimization × IoT Platforms, 8.54/L1/8.0) actually outranks every
original OS except OS009 on attractiveness, and OS032 (Public Sector × Infrastructure Planning &
Management × Digital Twins, 8.02/L1/7.0) is a genuinely different Public Sector angle from the
data-sovereignty cluster. OS034's right-to-win is still an unscored default (0.0/L4) — its attractiveness
(8.24) is real, re-score before using its right-to-win figure.

## Final selection for the Orange pitch (4 OS — 10-minute slot)

*10 minutes covers 4 OS well, not 15 or 34. Everything above stays as backup material for Q&A.*

| OS ID | Vertical | Use Case | Technology | Attractiveness | Right-to-win | Why this one |
|---|---|---|---|---|---|---|


Team must sign off on this exact 4 before the presentation — see checklist below.

## Decisions needed from the team

- [ ] **Confirm the 4-OS shortlist.**
- [ ] **Delete OS001 and OS024** (keep OS013 as the canonical Public Sector data-sovereignty entry):
  ```bash
  python radar_cli.py delete OS001 OS024
  ```
- [ ] ** BUT: Re-score OS024 properly** before deleting it!!!!
- [ ] **Re-score OS028 and OS034's right-to-win** — both still carry an unscored "LLM scoring unavailable"
  default (0.0/L4) from the Groq quota exhaustion; their attractiveness scores are real.
- [ ] **Healthcare coverage.** Only one candidate (OS027, attractiveness 4.04, L4/0.0 — no right-to-win at
  all) — leave out of the pitch given the 10-minute limit and the weak score; mention only if Orange asks
  "what about Healthcare."
- [x] **Missing `buyer_persona` migration** — fixed, see changelog above.
- [x] **`PERSONAS` in `config.py` mixed two different concepts** — fixed: split into `ROLES` (3 values,
  drives the dashboard's Role selector) and `BUYER_PERSONAS` (9 values, shown as context in the detail
  panel). `db.py` and `scoring.py` updated to match.


## How to reproduce the results

```bash
pip install -r requirements.txt
```

Create `.env` at the project root:

```env
LLM_PROVIDER=groq            # "ollama" | "groq" | "auto" (Groq first, falls back to Ollama)
GROQ_API_KEY=
GROQ_MODEL=openai/gpt-oss-120b
OLLAMA_URL=http://localhost:11434/api/generate
OLLAMA_MODEL=llama3.2:3b
NEWSAPI_AI_KEY=              # optional, free tier at https://newsapi.ai
```

Run the full pipeline with one command, from the project root:

```bash
python radar_cli.py all            # normal run: skips already-scored opportunity spaces
python radar_cli.py all --force    # forces re-scoring of every OS (use after a config.py change)
```

This chains `pipeline.db` → `pipeline.ingest` → `pipeline.analyze` → `radar_cli.py create` →
`radar_cli.py promote` → `pipeline.scoring` → `radar_cli.py link` → `radar_cli.py summary`, in order,
and stops on the first failing step.

**Groq free tier is capped at 200,000 tokens/day per organization** — a `--force` rescore of 30+ OS can burn
through that in one run. Check remaining quota before running `--force`, and avoid running it more than
once in the same day unless quota allows; a run that hits the cap mid-way overwrites already-good scores
with neutral defaults instead of leaving them alone (see changelog above).

If you've just swapped in a `.db` file from someone else, run `python -m pipeline.db` first — it applies
any pending schema migrations safely, without touching existing data (see changelog above).

### Dashboard

```bash
python -m streamlit run app/streamlit_app.py --server.address=127.0.0.1
```

The Power BI dashboard (`dashboard/powerbi/`) connects to `radar.db` via ODBC and offers five pages:
Decision Matrix, Score Breakdown, Why/Justification, Evidence, and Coverage.

## Scoring methodology

Two scores per opportunity space, kept separate — "is the market hot" and "can we sell this today" are
different questions with different owners at Orange Business.

### Attractiveness (0–10)

```
0.30 x market_signal_strength   deterministic — raw signal volume
0.20 x source_diversity         deterministic — distinct source domains
0.25 x evidence_quality         LLM-assessed — credibility/specificity of sources
0.10 x novelty_momentum         deterministic — recency skew
0.15 x strategic_relevance      LLM-assessed — fit against the real Orange Business API catalog
```

### Right-to-win (0–10) — L0–L4 scale

| Level | Meaning |
|---|---|
| **L0** | Direct offer — an existing Orange Business asset addresses this as-is |
| **L1** | Bundle — two or more existing assets exist but aren't packaged together yet |
| **L2** | Partner-dependent — needs a capability an external partner has |
| **L3** | Adjacent — needs one new capability to be built or acquired |
| **L4** | White space — no plausible path from the current portfolio |

Every classification cites the specific Orange Business asset(s) it's based on — no unsupported claims.

### Real-world evidence behind the scores

- **Analyst recognition** — Gartner Magic Quadrant for Global WAN Services 2026 (Leader, 23rd consecutive
  year); Gartner Peer Insights UCaaS (4.4/5, 16 verified reviews).
- **Customer references** — 5 verified, each backed by a live `orange-business.com` case study:
  - **Saint-Gobain Glass** (Manufacturing) — IoT-based GPS tracking for supply chain / stillage tracking.
  - **De Lijn** (Public Sector) — Tableau-based data visualization for public transport performance and
    customer communication.
  - **SPF Finances / FPS Finance** (Public Sector) — dynamic webshop with integrated auctions, consolidating
    three branches.
  - **BNP Paribas** (Finance & Insurance) — Flexible SD-WAN deployed across 1,800 retail bank branches in
    France.
  - **Groupama** (Finance & Insurance) — 4G mobile platform + collaborative app ("Groupama Campus") for
    employee digital experience.
- **Scale & security** — 30,000 employees, EUR 7.3bn 2025 revenue, 40,000+ B2B customers in 200+ countries,
  70+ data centers, 18 SOCs / 15 CyberSOCs.

## Project structure

```
Orange_use_case/
├── pipeline/                  # ingestion, analysis, scoring engine
│   ├── config.py              # verticals, taxonomy, real Orange Business asset catalog, references
│   ├── db.py                  # SQLite schema and data access
│   ├── ingest.py               # 9-source signal collection
│   ├── analyze.py             # theme extraction (LLM) + curation + recurring-theme tracking
│   ├── signals_discovery.py   # recurring valid theme tracking (feeds `promote`)
│   └── scoring.py             # attractiveness + right-to-win scoring
├── llm/
│   └── llm_client.py          # provider-agnostic LLM client (Groq → OpenRouter → Ollama)
├── app/
│   └── streamlit_app.py
├── dashboard/
│       └── innovation_radar_dashboard.pbix   # main client-facing deliverable
├── radar_cli.py                # create, promote, watchlist, calibrate, dedupe, link, summary, all
├── requirements.txt
├── .env.example
└── README.md
```

## Current scope & roadmap

- **The "Public Sector data sovereignty" opportunity was registered three times** (OS001, OS013, OS024)
  under different labels before the deduplication check was added — resolved above by keeping OS013 as the
  canonical entry (highest attractiveness and right-to-win of the three, once OS024 is properly re-scored);
  `radar_cli.py create`/`promote` now warn on this pattern going forward.
- `novelty_momentum` becomes meaningful once ingest has run over several weeks rather than a short window.
- TED and NewsAPI.ai are wired in but currently contribute limited signal volume — visible in the lower
  attractiveness scores for Energy and Retail opportunity spaces (all four are L4, under 4.3/10).
- The recurring-theme and watchlist promotion thresholds were lowered temporarily ahead of the
  presentation deadline (see changelog above) — worth revisiting once there's more ingest history to judge
  quality against.

## Team

Built as part of the BeCode AI & Data Science bootcamp (cohort BXL-Gebru-1), in collaboration with Orange
Business.