# 📡 Innovation Radar — Orange Business

Signal-driven Opportunity Space detection pipeline, built for a BeCode AI & Data Science
bootcamp client project with Orange Business. Scans market signals (news, research, regulation,
public procurement, competitor activity) and scores candidate B2B opportunities on two
independent axes — **Attractiveness** and **Right-to-win** — so a Strategist, Sales, or Presales
team can decide where to focus next.

## Quick links

- Live dashboard (Streamlit): run locally, see [Run it](#run-it) below
- Power BI report: `innovation_radar_dashboard_excel.pbix`
- Client-facing summary (auto-generated): `opportunity_spaces_summary.md`
- Orange Business — customer stories: https://www.orange-business.com/en/about-us/customer-stories
- Orange Business — Gartner recognition: https://www.orange-business.com/en/about-us/analysts/gartner-recognition-for-global-wan-services
- TED (EU public procurement) API docs: https://docs.ted.europa.eu/api/latest/index.html
- NewsAPI.ai (Event Registry): https://newsapi.ai
- Groq console (free-tier LLM key): https://console.groq.com
- Ollama (local LLM fallback): https://ollama.com

---

## What it does

1. **Ingest** — pulls signals from 9 sources per vertical (Google News, NewsAPI.ai, GDELT,
   arXiv, Semantic Scholar, vendor blogs, Hacker News, EUR-Lex regulation, TED procurement).
   GDELT has a persistent, disk-backed cooldown (`logs/.source_cooldowns.json`) plus one
   short in-call retry, so a rate-limit doesn't just silently drop the whole vertical.
2. **Analyze** — an LLM reads the collected titles per vertical and proposes candidate
   Opportunity Spaces (Vertical × Use Case × Technology), constrained to a closed taxonomy.
   Anything outside the taxonomy goes to a watchlist instead of being invented.
3. **Extend taxonomy** — `pipeline/extend_taxonomy.py` (a teammate's mechanism) turns watchlist
   terms that hit a frequency threshold into proposals; `radar_cli.py review` lets the team
   approve/reject them; an approved term is written to `taxonomy_extensions.json`, which
   `config.py` loads back into `USE_CASES_TAXONOMY`/`TECHNOLOGIES_TAXONOMY` on the next run.
4. **Score** — every Opportunity Space gets an Attractiveness score (market signal strength,
   source diversity, evidence quality, novelty/momentum, strategic relevance), a separate
   Right-to-win score (L0–L4 portfolio distance, grounded in Orange Business's real API
   catalog, named customers, and capability stats), and a deterministic Urgency score — all
   computed on the signals `link` attached to that specific Opportunity Space, not the whole
   vertical.
5. **Refresh** — existing Opportunity Spaces don't go stale: `python -m pipeline.scoring
   --refresh` recalculates the 4 deterministic sub-scores against each OS's CURRENT linked
   signals, for free (no LLM calls), so new signal volume actually moves the score without
   needing a full `--force` re-score.
6. **Enrich** — each Opportunity Space is tagged with the owning role, buyer persona,
   geography, sales horizon (Now/Next/Later), business domain, and a next action per role
   (Strategist / Sales / Presales) — already generated and stored; only the dashboard filters
   for these are still missing (see "What's left to do").
7. **Link** — `radar_cli.py link` attaches the strongest keyword-matched signals to each
   Opportunity Space (`top_n=45`, calibrated against real data).
8. **Visualize** — a Streamlit dashboard and a Power BI report, both reading from `radar.db`.
9. **Grow** — recurring themes seen across multiple ingest→analyze runs are auto-promoted into
   new Opportunity Spaces (`radar_cli.py promote`).

## Project structure

```
Orange_use_case/
├── pipeline/
│   ├── config.py              # verticals, taxonomy (+ taxonomy_extensions.json loading),
│   │                           # real Orange Business asset catalog, references
│   ├── db.py                  # SQLite schema and data access
│   ├── ingest.py              # 9-source signal collection, TED API, NewsAPI.ai, GDELT retry+cooldown
│   ├── analyze.py             # theme extraction (LLM) + recurring-theme tracking
│   ├── theme_promotion.py     # recurring valid theme tracking (feeds `promote`)
│   ├── extend_taxonomy.py     # teammate's watchlist -> proposal -> taxonomy_extensions.json flow
│   └── scoring.py             # attractiveness + right-to-win scoring, per linked OS
├── llm/
│   └── llm_client.py          # provider-agnostic LLM client (Groq -> Ollama fallback)
├── app/                       # Streamlit dashboard
├── dashboard/
│   └── innovation_radar_dashboard_excel.pbix   # main client-facing deliverable
├── radar_cli.py                # create, promote, review, watchlist, calibrate, dedupe,
│                                # link, themes, scores, summary, all
├── radar_cli_top_15.py         # kept at feature parity with radar_cli.py (same commands)
├── check_urgency_signals_age.py  # standalone: age distribution of regulation/buying_signal signals
├── latest_scores.py            # quick console dump of the latest run's scores
├── taxonomy_extensions.json    # approved taxonomy terms (created automatically if missing)
├── requirements.txt
├── .env.example
└── README.md
```

## Setup

```bash
pip install -r requirements.txt
```

Create a `.env` file at the project root:

```env
LLM_PROVIDER=auto            # auto (Groq -> Ollama fallback) | groq | ollama
GROQ_API_KEY=your-key-here   # free tier: https://console.groq.com
NEWSAPI_AI_KEY=              # optional, free tier: https://newsapi.ai
```

If Groq is unavailable (quota exhausted, no key), install Ollama and pull a local model:

```bash
ollama pull llama3.2:3b
```

## Run it

**Full pipeline, one command:**

```bash
python radar_cli.py all            # ingest -> analyze -> extend_taxonomy -> create -> promote
                                    #   -> link -> score -> summary
python radar_cli.py all --force    # same, but rescores + re-enriches every Opportunity Space
```

**Step by step:**

```bash
python -m pipeline.db              # create/migrate the schema
python -m pipeline.ingest          # collect signals (writes a timestamped log under logs/)
python -m pipeline.analyze         # LLM theme extraction
python -m pipeline.extend_taxonomy # generate taxonomy proposals from watchlist_terms (non-interactive)
python radar_cli.py review         # approve/reject pending taxonomy proposals (interactive)
python radar_cli.py create         # register the hand-picked seed Opportunity Spaces
python radar_cli.py promote        # auto-register recurring themes that matured
python radar_cli.py link           # attach the strongest signals to each Opportunity Space
python -m pipeline.scoring         # score + enrich everything unscored, using each OS's linked signals
python radar_cli.py summary        # write opportunity_spaces_summary.md
python radar_cli.py summary --top 4   # same, keeping only the 4 highest-attractiveness OS
```

**Keeping existing OS fresh (no re-ingest needed, just re-score what's there):**

```bash
python radar_cli.py link                        # re-attach signals -- picks up anything new
python -m pipeline.scoring --refresh             # recompute deterministic sub-scores, free (no LLM)
python -m pipeline.scoring --recalibrate-urgency # urgency only, if that's all that's needed
```

**Other useful commands:** `radar_cli.py -h` for the full list. Highlights: `calibrate` (tune
scoring.py's caps against real linked-signal counts), `dedupe --apply` (remove near-duplicate
signals), `watchlist` (see what's pending/promotable), `scores` (console summary), `delete
OS001 OS024` (targeted removal), `review` (approve/reject taxonomy proposals).

**Dashboard:**

```bash
python -m streamlit run app/streamlit_app.py --server.address=127.0.0.1
```

## Key design decisions

- **One source of truth for verticals** (`config.VERTICAL_SEEDS`) — adding a vertical is a
  one-line change instead of editing several places.
- **Closed taxonomies for Use Case / Technology, extensible through review** — the LLM must
  pick exactly from `USE_CASES_TAXONOMY`/`TECHNOLOGIES_TAXONOMY`; anything else goes to a
  watchlist, then a proposal, then a human decision (`radar_cli.py review`) before it's ever
  added.
- **Score each Opportunity Space on its own linked signals, not the whole vertical.**
- **Existing OS stay fresh without burning LLM quota** — `--refresh` recomputes the
  deterministic half of the score (market signal strength, source diversity, novelty momentum,
  urgency) against current data; the LLM half (evidence quality, strategic relevance) is
  carried forward unless a full `--force` is explicitly requested.
- **Urgency scales dynamically with the current population** — the 95th percentile of
  weighted urgent signals (regulation + buying_signal + a novelty_momentum contribution, see
  below) across every scored OS sets the "10/10" point, recalculated on every scoring run. An
  OS's urgency can shift even if nothing about that OS itself changed — that's the population
  moving, not a bug (see `scoring.py`'s `compute_urgency_scaling_point()` docstring).
- **Novelty feeds both urgency and attractiveness, on purpose** — urgency is meant to be
  "objective" (is there real deadline pressure / momentum), while attractiveness is a weighted
  mix of more subjective judgment calls. Novelty genuinely answers a question relevant to
  both, and this isn't double-counting: urgency and `total_score` (attractiveness) are
  entirely separate outputs — urgency isn't in `WEIGHTS` and never gets summed into
  `total_score`. Only applied once an OS has ≥3 signals (below that, `novelty_momentum()`
  returns a flat neutral fallback that would otherwise fake a momentum boost for every small
  OS) — see `NOVELTY_URGENCY_WEIGHT` in `scoring.py`.
- **Grounded scoring, not free-text LLM guessing** — Right-to-win and Strategic Relevance are
  scored against Orange Business's real API catalog, named customer references, and analyst
  recognition, all sourced and citable.
- **Audit trail, never overwrite** — `scores` and `right_to_win_scores` always INSERT a new
  row; `get_latest_scores()` always reads back the most recent one per Opportunity Space.
- **Resilience over completeness** — every external call is wrapped so one failing source
  never stops the rest of the ingest run.

## Approving taxonomy proposals

`python -m pipeline.extend_taxonomy` scans `watchlist_terms` and turns anything past the
frequency threshold into a row in `proposals`. To actually approve/reject them:

```bash
python radar_cli.py review
```

Walks through each pending proposal one at a time: `1 = Approve, 2 = Reject, 0 = Skip`.
Approving writes straight to `taxonomy_extensions.json` immediately (no need to finish the
whole list first) — `config.py` picks it up on the next run.

**Watch out for bare generic technology terms (e.g. a proposal that's just `"AI"` alone).**
`analyze.py`'s own extraction step has a curation pass that filters these out on purpose (drops
themes whose technology is a bare generic term), but `extend_taxonomy.py` runs on a separate
path that doesn't apply that same filter — so a generic term can still reach `review` and get
approved if nobody catches it. The taxonomy already has specific technologies for this
(`Machine Learning`, `Generative AI`, `Agentic AI`, plus a catch-all `AI, Data, Cloud`) —
approving a bare `"AI"` on top adds a duplicate-in-spirit term that doesn't help distinguish
opportunities. If the LLM keeps proposing bare "AI" repeatedly for a vertical, that's more
likely a sign the source signals themselves aren't specific enough, not that "AI" deserves its
own taxonomy slot — worth rejecting and revisiting the ingest query for that vertical instead.
Approving one occurrence of a term is enough to add it to the JSON (`_add_to_extensions()`
dedupes by term+category) — no need to individually approve the same term proposed under
several different verticals.

## Known limitations / things to watch

- **`--refresh` doesn't re-attach signals itself** — run `radar_cli.py link` first if new
  signals came in since the last link; `--refresh` only reads what's already in
  `opportunity_signals`.
- **LLM fallback to neutral scores** — when Groq's free-tier quota is exhausted and Ollama
  isn't running locally, `evidence_quality`/`strategic_relevance` fall back to a neutral 5.0.
  Check the console for "LLM scoring unavailable" to spot affected OS.
- **`novelty_momentum`** is only meaningful once ingest has run repeatedly over several weeks.
- **Recalibrate `MARKET_SIGNAL_CAP`/`SOURCE_DIVERSITY_CAP`** (`scoring.py`) with
  `radar_cli.py calibrate` after any meaningful change in ingest/link volume.

## What's left to do

Nothing below should be pushed to `dev` until the team has agreed on it together.

**Needs a team decision:**
- **Resolve the OS001/OS013/OS024 duplicate**, plus OS026/OS052 and OS036/OS053 — same
  "registered twice under different labels" pattern. `radar_cli.py delete <labels>` exists;
  which label(s) to keep is the team call.
- **Healthcare coverage** — only one candidate (OS027), weak evidence.
- **Scoring `WEIGHTS`** (30/20/25/10/15%) are manual, undocumented choices — keep, document,
  or derive statistically? Not decided.
- **Backend: persona + vertical ranking** — sorting OS by role/persona combination isn't
  implemented server-side yet; frontend-side sorting is a viable shortcut for a demo.

**Frontend/UI (backend side already done, only the dashboard side is missing):**
- Persona filter, geography filter, signal-type filter, time-horizon (Now/Next/Later) filter —
  all the underlying fields already exist and are populated in `opportunity_spaces`; the
  Streamlit views for them still need building.

**Mechanical, once the above is settled:**
- **Re-score OS with fallback values** — `python -m pipeline.scoring --rescue-fallback`
  targets exactly these, no `--force` needed.
- **Power BI report** — `urgency_score` isn't shown anywhere in the report yet.

## Changelog (most recent first)

- **Sieg 24/8 — novelty folded into urgency too (team decision).** Reasoning: urgency is
  meant to be objective ("is there real momentum/deadline pressure"), attractiveness is more
  subjective (a weighted mix of judgment calls) — novelty genuinely belongs in both, and it's
  not double-counting since urgency and `total_score` are separate outputs, never summed
  together. Added `NOVELTY_URGENCY_WEIGHT` (first estimate, not yet calibrated against real
  data) with a guard: only contributes once an OS has ≥3 signals, so `novelty_momentum()`'s
  own neutral-fallback value (below its 3-signal threshold) can't fake a boost for small OS.
  Tested: a genuinely trending OS (8/10 novelty, no regulation/buying_signal at all) now scores
  meaningfully higher urgency than a flat one with the same signal count spread evenly.
- **Sieg 24/8 — refresh logic (closes the "Refresh Logic for already existing OSs" gap from
  the project status doc).** New `recalibrate_deterministic_scores()` in `scoring.py`
  (`python -m pipeline.scoring --refresh`): recomputes market_signal_strength, source_diversity,
  novelty_momentum, and urgency_score for every scored OS against its CURRENT linked signals,
  free of LLM calls (evidence_quality/strategic_relevance carried forward unchanged). Tested
  against the exact scenario the doc describes (OS scored with N signals, more arrive later,
  score was frozen until now) — confirmed the total moves, the LLM fields don't, and no LLM
  call is made.
- **Sieg 24/8 — dynamic urgency scaling.** Replaced the fixed `URGENCY_CAP` with a 95th-
  percentile-of-the-current-population scaling point (`compute_urgency_scaling_point()`). Found and fixed a real bug during testing: the default percentile method
  extrapolates past the actual maximum for small samples (a 4-point test batch returned a
  "95th percentile" of 15.25 when the highest real value was 10) — fixed with
  `method="inclusive"` plus a hard clamp to the observed maximum.
- **Sieg 24/8 — taxonomy gap closed.** 4 use-case terms and 1 technology term backing already-
  promoted opportunity spaces (OS030–OS034) had never actually been added to
  `USE_CASES_TAXONOMY`/`TECHNOLOGIES_TAXONOMY`, so `analyze.py` couldn't legally re-propose
  them for new signals in the same vertical even though they're real, scored opportunities.
- **Sieg 24/8 — file cleanup.** `theme_promotion.py` kept as the canonical name;
  `signals_discovery.py` removed outright once every import (`analyze.py`, `radar_cli.py`,
  `radar_cli_top_15.py`) was switched over and nothing else referenced it.
- **Sieg 24/8 — GDELT.** Confirmed the retry+cooldown patch (`max_records=8`,
  `GDELT_SLEEP_SECONDS=75`, one 15s in-call retry, 20-min persisted cooldown) is intact in
  `ingest.py` — a local copy running the old unpatched message
  ("don't rerun the pipeline immediately, wait 15-20 min") had gone stale on one machine.
- **Sieg 24/8 — taxonomy extension mechanism, restored end-to-end.** `config.py` didn't have
  the `taxonomy_extensions.json` read side at all on this branch (added, ); `radar_cli.py`'s `review` command and the `extend_taxonomy` step in `all` had gone
  missing (restored); fixed a crash in `review` (`no such table: proposals` if run before
  `extend_taxonomy.py` had ever run once); added the `proposals` table to `db.py`'s central
  `SCHEMA` too, matching diff, so `python -m pipeline.db` alone is enough to have it ready.
- **Sieg 24/8 — merged `radar_cli_top_15.py`'s `--top N`** into `radar_cli.py summary`, kept
  both files at command parity going forward.

## Team

Built as part of the BeCode AI & Data Science bootcamp (cohort BXL-Gebru-1), in collaboration with Orange
Business.