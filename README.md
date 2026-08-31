# 📡 Innovation Radar — Orange Business

Signal-driven Opportunity Space detection pipeline, built for a BeCode AI & Data Science
bootcamp client project with Orange Business. Scans market signals (news, research, regulation,
public procurement, competitor activity) and scores candidate B2B opportunities on two
independent axes — **Attractiveness** and **Right-to-win** — so a Strategist, Sales, or Presales
team can decide where to focus next.

## Quick start

```bash
git clone <repo-url> && cd Orange_use_case
pip install -r requirements.txt
python radar_cli.py all           # full pipeline: ingest -> ... -> summary (~10-20 min, uses LLM quota)
python -m streamlit run dashboard/streamlit_app.py --server.address=127.0.0.1
```

No Groq key yet, or quota exhausted? `ollama pull llama3.2:3b` first — `LLM_PROVIDER=auto` in
`.env` falls back to it automatically. Full options: [Setup](#setup) and [Run it](#run-it) below.

## Quick links

- Live dashboard (Streamlit): run locally, see [Run it](#run-it) below
- Power BI report: `innovation_radar_dashboard.pbix`
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
4. **Create / promote — duplicate-proof** — seed Opportunity Spaces come from `config.CANDIDATES`
   (`create`); recurring themes that matured get auto-registered (`promote`). Both now go through
   a check-then-block *and* a DB-level `UNIQUE(vertical, use_case, technology)` index — the same
   triple can no longer be registered twice under two different labels, however it's triggered.
5. **Score** — every Opportunity Space gets an Attractiveness score (market signal strength,
   source diversity, evidence quality, novelty/momentum, strategic relevance), a separate
   Right-to-win score (L0–L4 portfolio distance, grounded in Orange Business's real API
   catalog, named customers, and capability stats), and a deterministic Urgency score — all
   computed on the signals `link` attached to that specific Opportunity Space, not the whole
   vertical.
6. **Refresh** — existing Opportunity Spaces don't go stale: `python -m pipeline.scoring
   --refresh` recalculates the 4 deterministic sub-scores against each OS's CURRENT linked
   signals, for free (no LLM calls), so new signal volume actually moves the score without
   needing a full `--force` re-score.
7. **Enrich** — each Opportunity Space is tagged with the owning role, buyer persona,
   geography, sales horizon (Now/Next/Later), business domain, and a next action per role
   (Strategist / Sales / Presales). Geography uses Orange Business's own regional grouping
   (Benelux, Germany, Southern Europe, DACH, UK & Ireland, Nordics, Eastern Europe, + continent
   level for the rest of the world — `config.GEOS`/`GEOS_PROMPT`), not generic continents.
8. **Link** — `radar_cli.py link` attaches the strongest keyword-matched signals to each
   Opportunity Space (`top_n=45`, calibrated against real data).
9. **Visualize** — a Streamlit dashboard and a Power BI report, both reading from `radar.db`.
10. **Grow** — recurring themes seen across multiple ingest→analyze runs are auto-promoted into
    new Opportunity Spaces (`radar_cli.py promote`).

## Sample output

One Opportunity Space from a real `opportunity_spaces_summary.md` run (grounding signals
trimmed to 4 of 32 for length — the real file lists every one):

```
## OS002 — Manufacturing × Fire and hazard detection × Edge computer vision (Raspberry Pi class)

**Attractiveness: 7.07/10**
- Market signal strength: 7.11
- Source diversity: 5.25
- Evidence quality: 7.0 — multi-source signals from analyst reports, industry news, and
  peer-reviewed papers on private 5G/edge computing, diluted by some vendor-centric posts.
- Novelty / momentum: 9.38
- Strategic relevance: 8.0 — Directly extends API M2M for IoT Connect Express by adding
  edge computer-vision fire detection for manufacturing sites. Maps to Orange's
  'Smart Manufacturing & Operations' value proposition.

**Urgency: 4.77/10** — deterministic, +2 per regulation/buying_signal signal linked to this OS.

**Right-to-win: 6.5/10 [L3]**
- Matched assets: API M2M for IoT Connect Express, API Cloud Avenue, API Incident, Evolution Platform
- Orange Business can provide IoT connectivity, cloud processing and incident handling, but
  lacks a native edge-AI/computer-vision runtime for Raspberry-Pi-class devices. +1.0
  calibration bonus (CRM customer overlap).

**Grounding signals (32):**
- [Tech Monitor] Bringing intelligence to the factory floor: Private 5G and edge computing
- [ARC Advisory Group] Beyond Connectivity: Embedded Security, AI/Edge Computing...
- [arXiv] Vision-Language Models for Analog Gauge Reading: An Empirical Study...
- [EE Times] Edge AI Is Forcing a Rethink of Predictive Maintenance Architecture
  ... (28 more)
```

## Project structure

```
Orange_use_case/
├── .githooks/                    # post-merge hook running check_no_streamlit_leak.py
├── dashboard/                    # client-facing deliverables
│   ├── dashboard.py
│   ├── streamlit_dash_final.py           # interactive Streamlit dashboard
│   ├── streamlit_app_sieg.py
│   ├── innovation_radar_dashboard.pbix   # Power BI report
│   ├── radar_powerbi_model.xlsx
│   └── radar_powerbi_tables.xlsx
├── docs/
├── images/
├── llm/
│   ├── __init__.py
│   └── llm_client.py             # provider-agnostic LLM client (Groq -> Cerebras -> SambaNova -> Ollama)
├── logs/                         # timestamped ingest logs + GDELT cooldown state
├── pipeline/
│   ├── __init__.py
│   ├── config.py                 # verticals, taxonomy, Orange Business asset catalog, geography
│   ├── db.py                     # SQLite schema + data access, dedupe, uniqueness constraint
│   ├── ingest.py                 # 9-source signal collection (TED, NewsAPI.ai, GDELT, etc.)
│   ├── analyze.py                # LLM theme extraction + classification
│   ├── theme_promotion.py        # recurring valid theme tracking (feeds `promote`)
│   ├── extend_taxonomy.py        # watchlist -> proposal -> taxonomy_extensions.json flow
│   ├── taxonomy_validation.py    # shared guardrail against bare generic terms (e.g. "AI")
│   └── scoring.py                # attractiveness + right-to-win scoring, per linked OS
├── tests/
│   ├── analyze_healthcare.py     # deep-dive report for one vertical
│   ├── check_healthcare.py       # quick DB spot-check
│   ├── test_LLM.py               # malformed/missing LLM output handling
│   ├── test_scoring_and_db.py
│   └── tests_irene/
├── .env                          # not committed — see Setup
├── .gitignore
├── check_no_streamlit_leak.py    # guards pipeline/ and llm/ against a dashboard-code leak
├── extend_taxonomy.md            # design notes for the taxonomy-extension mechanism
├── opportunity_spaces_summary.md # auto-generated, client-facing
├── radar_cli.py                  # create, promote, review, link, score, summary, all
├── radar.db / radar_g.db
├── requirements.txt
├── score_breakdown.png
├── taxonomy_extensions.json      # approved taxonomy terms (auto-created if missing)
└── README.md
```

## Setup

```bash
pip install -r requirements.txt
```

Create a `.env` file at the project root:

```env
LLM_PROVIDER=auto            # auto (Groq -> Cerebras -> SambaNova -> Ollama) | groq | cerebras | sambanova | ollama
GROQ_API_KEY=your-key-here       # free tier: https://console.groq.com
CEREBRAS_API_KEY=                # optional, free tier: https://cloud.cerebras.ai (14,400 req/day)
SAMBANOVA_API_KEY=               # optional, free tier: https://cloud.sambanova.ai (unlimited, slower)
NEWSAPI_AI_KEY=                  # optional, free tier: https://newsapi.ai
```

Any of the 3 cloud LLM keys can be left blank -- `auto` mode just skips that step of the chain
and moves to the next one (see `llm/llm_client.py`'s docstring). Only `GROQ_API_KEY` is
effectively required for a useful `auto` run; the rest raise the pipeline's actual daily quota
ceiling as you add them.

If none of the cloud providers are reachable (all quotas exhausted, no keys at all), install
Ollama and pull a local model -- the true last-resort fallback, free and offline:

```bash
ollama pull llama3.2:3b
```

## External dependencies & costs

Everything below is free-tier / no-cost for a project this size — flagging the actual limits
so nobody's surprised mid-run.

| Service | Used for | Cost / limit |
|---|---|---|
| **Groq API** | LLM calls, provider 1 of 4 (theme extraction, scoring, enrichment) | Free tier: ~200k tokens/day (shared across all calls) — this is the pipeline's real bottleneck, see `llm_client.py` and the multi-key rotation in `.env` |
| **Cerebras API** | LLM fallback, provider 2 of 4 | Free tier: 14,400 requests/day — optional, `auto` mode skips it cleanly if `CEREBRAS_API_KEY` is blank |
| **SambaNova API** | LLM fallback, provider 3 of 4 | Free tier: unlimited but slower — optional, same skip-if-blank behavior |
| **Ollama (local)** | LLM fallback, provider 4 of 4 — the true last resort | Free, runs on your machine, no API key or network needed — slower, and noticeably less reliable on strict-JSON output than the 3 cloud providers above |
| **NewsAPI.ai (Event Registry)** | News signal ingestion | Free tier, optional (`NEWSAPI_AI_KEY` in `.env`) — ingest still runs without it, just fewer sources |
| **GDELT, arXiv, Semantic Scholar, EUR-Lex, TED, Hacker News, Google News (RSS), vendor blogs** | The other 6 signal sources | Free, no key required — GDELT has its own rate limit, handled by `ingest.py`'s cooldown+retry (see README "What it does") |
| **SQLite (`radar.db`)** | All storage | Free, no server, single file |
| **Streamlit / Power BI** | Dashboard | Free (Streamlit); Power BI Desktop is free, a paid license is only needed to publish/share the report online |

No paid API is required to run this project end to end.

## Run it

**Full pipeline, one command:**

```bash
python radar_cli.py all            # ingest -> analyze -> extend_taxonomy -> create -> promote
                                    #   -> link -> score -> summary
python radar_cli.py all --force    # same, but rescores + re-enriches every Opportunity Space
```

**Step by step:**

```bash
python -m pipeline.db              # create/migrate the schema (also dedupes + locks OS triples)
python -m pipeline.ingest          # collect signals (writes a timestamped log under logs/)
python -m pipeline.analyze         # LLM theme extraction
python -m pipeline.extend_taxonomy # generate taxonomy proposals from watchlist_terms (non-interactive)
python radar_cli.py review         # approve/reject pending taxonomy proposals (interactive)
python radar_cli.py create         # register the hand-picked seed Opportunity Spaces
python radar_cli.py promote        # auto-register recurring themes that matured
python radar_cli.py link           # attach the strongest signals to each Opportunity Space
python -m pipeline.scoring         # score + enrich everything unscored, using each OS's linked signals
python radar_cli.py summary        # write opportunity_spaces_summary.md
python radar_cli.py summary --top 10   # same, keeping only the 10 highest-attractiveness OS
```

**Keeping existing OS fresh (no re-ingest needed, just re-score what's there):**

```bash
python radar_cli.py link                          # re-attach signals -- picks up anything new
python -m pipeline.scoring --refresh               # recompute deterministic sub-scores, free (no LLM)
python -m pipeline.scoring --recalibrate-urgency    # urgency only, if that's all that's needed
python -m pipeline.scoring --recalibrate-right-to-win  # right-to-win only, after a calibration change
python -m pipeline.scoring --recalibrate-geography  # re-apply the geography taxonomy only (1 LLM call/OS)
```

**Other useful commands:** `radar_cli.py -h` for the full list. Highlights: `calibrate` (tune
scoring.py's caps against real linked-signal counts), `dedupe --apply` (remove near-duplicate
signals), `watchlist` (see what's pending/promotable), `scores` (console summary), `delete
OS001 OS024` (targeted removal), `review` (approve/reject taxonomy proposals).

**Dashboard:**

```bash
python -m streamlit run dashboard/streamlit_app.py --server.address=127.0.0.1
```

## Key design decisions

- **One source of truth for verticals** (`config.VERTICAL_SEEDS`) — adding a vertical is a
  one-line change instead of editing several places.
- **Closed taxonomies for Use Case / Technology, extensible through review** — the LLM must
  pick exactly from `USE_CASES_TAXONOMY`/`TECHNOLOGIES_TAXONOMY`; anything else goes to a
  watchlist, then a proposal, then a human decision (`radar_cli.py review`) before it's ever
  added.
- **Score each Opportunity Space on its own linked signals, not the whole vertical.**
- **A duplicate triple can't happen, not just "shouldn't."** `create`/`promote` check before
  inserting, and a DB-level `UNIQUE(vertical, use_case, technology)` index backs that check up —
  so even a code path nobody's traced yet can't silently register the same Opportunity Space
  twice under two labels (this is what created OS026/OS052 and OS036/OS053 before the fix).
- **Existing OS stay fresh without burning LLM quota** — `--refresh` recomputes the
  deterministic half of the score (market signal strength, source diversity, novelty momentum,
  urgency) against current data; the LLM half (evidence quality, strategic relevance) is
  carried forward unless a full `--force` is explicitly requested. Same principle for
  `--recalibrate-right-to-win` and `--recalibrate-geography`: redo only the one thing that
  actually changed, not the whole scoring pass.
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

### Right-to-win (0–10) — L0–L4 scale
| Level | Meaning |
|---|---|
| **L0** | Direct offer — an existing Orange Business asset addresses this as-is |
| **L1** | Bundle — two or more existing assets exist but aren't packaged together yet |
| **L2** | Partner-dependent — needs a capability an external partner has |
| **L3** | Adjacent — needs one new capability to be built or acquired |
| **L4** | White space — no plausible path from the current portfolio |

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
- **OS001/OS013/OS024** — same vertical, closely related but NOT identical use_case/technology
  wording (conceptual near-duplicates, not exact triples, so the automatic dedupe below doesn't
  touch them on purpose). `radar_cli.py delete <labels>` exists; which label(s) to keep is the
  team call.
- **Healthcare coverage** — only one candidate (OS027), weak evidence.
- **Scoring `WEIGHTS`** (30/20/25/10/15%) are manual, undocumented choices — keep, document,
  or derive statistically? Not decided.

**Frontend/UI — corrected 25/8: most of this was already done, the README was stale.**
Persona (buyer), geography, horizon, and signal-type filters all already existed in
`dashboard/streamlit_app.py` before this note was written — confirmed by reading the actual
file, not assumed. Only 2 things were genuinely missing, both closed 25/8:
- ~~**Backend: persona + vertical ranking**~~ — done: `db.get_scores_ranked_by_persona_vertical()`
  (optional `persona`/`vertical` filter params, ranks by owning-team persona then vertical then
  score) — usable from Power BI too, same DB file. Frontend: new "Persona + Vertical" option in
  the dashboard's "Order" sort control.
- ~~**Owning-team persona filter**~~ — done: new "Owning team (persona)" sidebar multiselect,
  same pattern as the existing filters. Distinct from "Buyer persona" (customer-side contact,
  already filterable) and the top "Role" radio (the dashboard viewer's own role, only used to
  hide L3/L4 opportunities from Presales) — three different things sharing similar names, worth
  double-checking you're editing the right one if this needs to change again.

**Blocked — needs a file, not a decision:**
- ~~**Multi-provider LLM fallback (Groq → Cerebras → SambaNova)**~~ — done (25/8): `llm/
  llm_client.py` extended, chain is now Groq → Cerebras → SambaNova → Ollama in `auto` mode,
  each step skipping cleanly if its key is blank. `get_llm_json()`/`get_llm_response()`'s
  signatures are unchanged, so `analyze.py`/`scoring.py` needed zero edits. Tested with mocks
  (no real Cerebras/SambaNova keys available yet) — add `CEREBRAS_API_KEY`/`SAMBANOVA_API_KEY`
  to `.env` to actually exercise those 2 steps for real; until then `auto` mode behaves exactly
  like the old Groq→Ollama chain (both new steps fail fast on "key not set" and fall through).

**Mechanical, once the above is settled:**
- **Re-score OS with fallback values** — `python -m pipeline.scoring --rescue-fallback`
  targets exactly these, no `--force` needed.
- **Power BI report** — `urgency_score` isn't shown anywhere in the report yet.

**Structural cleanup — deliberately AFTER the Friday client demo, not before:**
A code-quality pass (25/8) flagged real, verified issues, prioritized by risk — the point is
none of these change behavior, so they're safe once nobody's presenting on top of the code the
same week, but not worth the regression risk of touching working files 3 days out from a demo.
1. ~~`pipeline/analyze.py`: separate the LLM extraction call from the `recurring_themes`/
   `watchlist_terms` persistence logic~~ — done (25/8): `extract_themes()` split into
   `_call_theme_extraction_llm()` (LLM boundary) + `_classify_themes()` (pure, no DB/LLM) +
   a thin orchestrator. Verified behaviorally identical to the original on 5 edge cases
   (missing key, null value, bare generic term, etc.) before/after the split.
2. ~~`pipeline/config.py`: split into a `pipeline/config/` package (env/taxonomy/sources/
   business_data)~~ — done (25/8), then **reverted the same day**: the team is multiple
   people actively on this repo, and turning one file into 6 is a much worse git-merge
   conflict for anyone with in-flight changes than a normal single-file diff. Kept as ONE
   file, reorganized into 9 clearly `# ====`-delimited sections instead (see the header
   comment in `config.py`) — same readability win from the audit, none of the merge risk.
   If this is ever revisited, the tested/working package version is in this changelog's
   git history (25/8, "Sieg 25/8 — code-quality pass: analyze.py split, config.py package").

## Changelog (most recent first)

- **Sieg 25/8 — multi-provider LLM fallback closed.** `llm/llm_client.py`'s `auto` mode is now
  a 4-step chain (Groq → Cerebras → SambaNova → Ollama, per
  `current_project_state_overview.md`'s rate-limit section) instead of 2 (Groq → Ollama).
  Cerebras/SambaNova called via their OpenAI-compatible `/v1/chat/completions` endpoints using
  `requests` (no new SDK dependency, same approach as the existing Ollama call) — each step
  fails fast and falls through cleanly if its API key is blank, so a partially-configured `.env`
  degrades gracefully instead of erroring. `get_llm_json()`/`get_llm_response()` signatures
  unchanged — zero edits needed in `analyze.py`/`scoring.py`. Tested with mocked provider
  responses (chain order, JSON parsing through the new steps, direct `LLM_PROVIDER=cerebras`/
  `sambanova` modes, all-providers-fail error propagation) since no real Cerebras/SambaNova keys
  were available in this session.
- **Sieg 25/8 — persona + vertical ranking (backend + frontend), owning-team persona filter,
  and a stale-README correction.** New `db.get_scores_ranked_by_persona_vertical()` (optional
  `persona`/`vertical` params, ranks by owning-team persona then vertical then score — usable
  from Power BI too) closes the "Persona + vertical ranking" backend gap from
  `current_project_state_overview.md`; wired into the dashboard as a new "Persona + Vertical"
  sort option, plus a new "Owning team (persona)" sidebar filter (distinct from "Buyer persona"
  and the viewer's own "Role" — see "What's left to do" for the disambiguation). While doing
  this, found that 3 other "still missing" items in that same doc (persona/buyer filtering,
  geography filtering, horizon filtering, signal-type filtering) were actually ALREADY built in
  `dashboard/streamlit_app.py` — the README had been describing a stale state; corrected.
  Multi-provider LLM fallback (Groq → Cerebras → SambaNova, same doc) stays open: it needs
  `llm/llm_client.py`, never shared in this session, and that file wasn't touched blind.
- **Sieg 25/8 — `app/` merged into `dashboard/`.** Both client-facing deliverables (the
  Streamlit app and the Power BI report) now live in one `dashboard/` folder instead of two
  separate `app/`/`dashboard/` folders. No code change needed: `streamlit_app.py`'s
  `sys.path.insert(0, str(Path(__file__).resolve().parent.parent))` resolves to the project
  root the same way from any single-level subfolder, so moving it didn't touch that line.
- **Sieg 25/8 — code-quality pass: `analyze.py` split, `config.py` reorganized, tests added.**
  `pipeline/analyze.py`'s `extract_themes()` split into a pure LLM-call function, a pure
  classification function (no DB/LLM — directly unit-testable), and a thin orchestrator;
  behaviorally verified identical to the pre-split version on 5 edge cases. `pipeline/config.py`
  was briefly split into a `pipeline/config/` package (env/taxonomy/sources/business_data +
  re-exporting `__init__.py`, verified zero value/behavior mismatch against the original on
  every one of its 58 public names) — then reverted the same day to a single file with 9
  `# ====`-delimited sections instead, since the team is multiple people actively on this repo
  and a file-to-folder change is a much worse merge conflict than a single-file diff for anyone
  with in-flight changes. New `tests/test_malformed_llm_output.py` (26 tests, additive only, no
  overlap with `tests_irene/`) covers malformed/missing/null LLM output across `analyze.py`,
  `scoring.py`, and `extend_taxonomy.py`. Also this session: removed 230 lines of commented-out
  legacy code and a duplicate import block from `dashboard/streamlit_app.py` (1009 → 769 lines, zero
  behavior change); README got a copy-paste Quick Start, a real trimmed sample of
  `opportunity_spaces_summary.md`'s output, and an External dependencies & costs table.
- **Sieg 25/8 — geography taxonomy replaced.** `config.GEOS` went from 5 broad continents to
  Orange Business's actual regional grouping (Benelux, Germany, Southern Europe, DACH — Switzerland
  + Austria only, Germany is separate —, UK & Ireland, Nordics, Eastern Europe, + continent-level
  for the rest of the world). `GEOS_PROMPT` spells out the countries per region for the enrichment
  LLM prompt, since several of these are non-standard and a bare label would invite a wrong guess
  (e.g. the usual DACH definition includes Germany; ours doesn't). New
  `scoring.py --recalibrate-geography` re-applies it to every already-enriched OS for 1 LLM
  call each, without re-burning quota on evidence_quality/strategic_relevance/right-to-win.
- **Sieg 25/8 — OS026/OS052 and OS036/OS053 duplicate, root-caused and closed.** `create()`'s
  duplicate check only ever warned, never blocked the insert — that's how the same
  (vertical, use_case, technology) triple ended up registered twice under two labels, and made
  it verbatim into the client-facing summary (same 43 grounding signals, counted twice).
  `pipeline/db.py`'s `init_db()` now runs `dedupe_opportunity_spaces()` (keeps the oldest
  registration, deletes the newer duplicate + its scores/links) followed by a DB-level
  `UNIQUE(vertical, use_case, technology)` index, so a duplicate triple can no longer be
  inserted by any code path, not just the one we found. `create`/`promote` also block on the
  application-level check as a first line of defense, with the DB constraint as the backstop.
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
  the now-retired `radar_cli_top_15.py`) was switched over and nothing else referenced it.
- **Sieg 24/8 — GDELT.** Confirmed the retry+cooldown patch (`max_records=8`,
  `GDELT_SLEEP_SECONDS=75`, one 15s in-call retry, 20-min persisted cooldown) is intact in
  `ingest.py` — a local copy running the old unpatched message
  ("don't rerun the pipeline immediately, wait 15-20 min") had gone stale on one machine.
- **Sieg 24/8 — taxonomy extension mechanism, restored end-to-end.** `config.py` didn't have
  the `taxonomy_extensions.json` read side at all on this branch (added, ); `radar_cli.py`'s `review` command and the `extend_taxonomy` step in `all` had gone
  missing (restored); fixed a crash in `review` (`no such table: proposals` if run before
  `extend_taxonomy.py` had ever run once); added the `proposals` table to `db.py`'s central
  `SCHEMA` too, matching diff, so `python -m pipeline.db` alone is enough to have it ready.
- **Sieg 26/8 — `radar_cli_top_15.py` retired.** Its only unique feature (`--top N`) was
  merged into `radar_cli.py summary` back on 24/8; keeping a second file at "command parity"
  with zero unique behavior left was just a second place to forget to update. Deleted.

## Team

Built as part of the BeCode AI & Data Science bootcamp, in collaboration with Orange Business.

---

