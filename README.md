<!-- https://www.orange-business.com/en/business-needs/scalable-responsive-secure-digital-infrastructure
https://www.orange-business.com/en/about-us/analysts/gartner-recognition-for-global-wan-services
https://www.gartner.com/reviews/market/unified-communications-as-a-service/vendor/orange-business
https://www.orange-business.com/en/business-needs/digital-work-experience
https://www.orange-business.com/en/business-needs/scalable-responsive-secure-digital-infrastructure
https://www.orange-business.com/en/business-needs/operational-experience-optimize-industry-digitizing-processes
https://www.orange-business.com/en/business-needs/customer-experience
https://www.orange-business.com/en/business-needs/secure-enterprise
https://newsapi.ai/dashboard?tab=home
https://docs.ted.europa.eu/api/latest/index.html -->

# Innovation Radar — Signal Pipeline

Signal collection → theme extraction → curation → opportunity space scoring, for Orange Business.
Detects Vertical × Use Case × Technology patterns from real market signals, then scores each one on
two separate axes: **attractiveness** (is the market hot) and **right-to-win** (can Orange actually sell it).

## Setup (once per machine)

```bash
pip install -r requirements.txt
```

Create `.env` at the project root (same level as `pipeline/` and `llm/`):

```env
LLM_PROVIDER=groq            # "ollama" | "groq" | "auto" (Groq first, falls back to Ollama)

GROQ_API_KEY=
GROQ_MODEL=openai/gpt-oss-120b

OLLAMA_URL=http://localhost:11434/api/generate
OLLAMA_MODEL=llama3.2:3b

NEWSAPI_AI_KEY=              # optional, free tier at https://newsapi.ai
```

Only `.env` changes between machines or between Groq/Ollama — the code never does. Groq
(`openai/gpt-oss-120b`) gave noticeably more reliable judgments than local `llama3.2:3b` in testing.
Use Groq for any scores you intend to present. Groq's free tier is rate-limited to 8,000 tokens/minute
— if `pipeline.scoring` logs `rate_limit_exceeded` partway through, the affected opportunity space(s)
get a fallback L4/0 right-to-win that is **not a real judgment** — just re-run `pipeline.scoring` alone
once the limit resets.

`.env` is loaded from `pipeline/config.py` itself, not as a side effect of importing
`llm/llm_client.py` — this was previously a bug: running `python -m pipeline.ingest` on its own (which
never imports `llm_client.py`) silently never loaded `.env` at all, so `NEWSAPI_AI_KEY` looked unset
even when correctly filled in, purely depending on which script ran first. Fixed by loading `.env`
directly in `config.py`, which every entry point imports.

## Taxonomy — read `docs/core_taxonomy_definition.md` first

The Vertical / Use Case / Technology taxonomy that `pipeline/config.py`'s `TAXONOMY_*` lists are built
from is defined in `docs/core_taxonomy_definition.md`.

**Open question, not yet resolved:** that doc currently states the LLM should pick Vertical/Use
Case/Technology *exclusively* from the taxonomy lists (strict whitelist). The extraction prompt in
`pipeline/analyze.py` currently treats the lists as *examples, not an exhaustive whitelist* — this was
a deliberate change made after earlier team feedback ("too strict"), so the LLM could still surface a
real pattern (e.g. "Edge AI") that isn't in the base lists yet. Flagged to the team to confirm which
version is current — **do not change `THEME_EXTRACTION_SYSTEM_PROMPT` until this is resolved**, to
avoid reverting a change that was specifically requested.

The doc also describes a formal mechanism (in progress: `discovery_signals.py`, `extend_taxonomy.py`)
for promoting new terms into the taxonomy: unclassified signals go to a watchlist, terms that recur in
5+ signals get proposed to the team, and approved terms get added to the taxonomy.
`config.py`'s `TAXONOMY_TECHNOLOGIES_EMERGING` list (Agentic AI, Digital Twins, Edge AI, Quantum-safe
Cryptography, Synthetic Data) was added ahead of that mechanism, as a stopgap — once the watchlist/
validation flow is ready, this should be folded into that process instead of living as a manually
maintained list.

## ⚠️ Opportunity spaces are now auto-registered from every ingest — read this before presenting numbers

`create_opportunity_spaces.py` no longer registers a fixed, hand-picked list of candidates. It now
calls `extract_themes()` for every vertical present in `signals` and registers *everything* the LLM
returns (after Phase 3 curation in `analyze.py`: generic terms like bare "AI" dropped, near-duplicate
themes merged). This means:

- **The number and identity of opportunity spaces changes every time you run it**, depending on how
  much has been ingested and what the LLM extracts that day. There is no fixed OS numbering anymore —
  don't treat old OS labels as stable identifiers across sessions.
- **The script wipes `opportunity_spaces`, `scores`, `right_to_win_scores`, and `opportunity_signals`
  before repopulating**, every run. This was a deliberate fix — previously, a run that found *fewer*
  themes than a prior run left stale, orphaned opportunity spaces behind under old labels, which could
  silently duplicate against a freshly-extracted theme that happened to reuse the same label. If the
  team later freezes a final list of opportunity spaces after reviewing candidates together, **stop
  re-running this script** — re-running it will erase that frozen selection and replace it with a
  fresh automatic extraction.
- Since this auto-registers rather than curating, **do not treat the resulting summary as a team
  decision** — it's still a working extraction to review together, same caution as before, just
  automated instead of manually picked.

## Run order

All commands run from the project root (the code imports as `pipeline.*` / `llm.*` packages):

```bash
python -m pipeline.db              # 1. create/migrate radar.db (safe to re-run, never deletes data)
python -m pipeline.ingest          # 2. pull signals from 9 sources into `signals`
python -m pipeline.analyze         # 3. (optional) quick stats + LLM theme extraction per vertical
python list_all_themes.py          # 3b. (optional) regenerate candidate_opportunity_spaces.md, unfiltered
python dedupe_signals.py           # 3c. (optional) report near-duplicate signals across sources
python dedupe_signals.py --apply   #     actually remove them, once you've reviewed the report
python create_opportunity_spaces.py  # 4. wipe + re-register ALL extracted opportunity spaces
python -m pipeline.scoring         # 5. score each one: attractiveness + right-to-win
python link_signals.py             # 6. link the strongest real signals to each opportunity space
python export_summary.py           # 7. write opportunity_spaces_summary.md (the one file to bring to a meeting)
```

Steps 1-3c only need re-running when you want fresh/cleaner signals. Steps 4-7 are the scoring loop —
re-run 4-7 any time you change `scoring.py`, want a fresh extraction, or switch LLM provider;
`scoring.py` always `INSERT`s a new row rather than overwriting, so `latest_scores.py` /
`export_summary.py` always read the most recent run per opportunity space. Step 4 now wipes and
rebuilds `opportunity_spaces` itself, so 4-7 together give a fully fresh, internally consistent set
every time.

With more opportunity spaces auto-registered per run than before, `scoring.py` makes proportionally
more LLM calls — watch the console for `rate_limit_exceeded` on Groq's 8,000 tokens/minute free tier
more closely; if it hits, re-run `pipeline.scoring` alone after the limit resets rather than the whole
4-7 sequence.

Useful one-offs:

```bash
python latest_scores.py    # print latest scores to console, no file written
python calibrate_caps.py   # print real signal count + source diversity per vertical, to recalibrate scoring.py's caps
python check_signals.py    # print total signal count by vertical, quick sanity check after an ingest run
```

## Automating ingest

`run_ingest.bat` (project root) runs `python -m pipeline.ingest` and logs console output to a
timestamped file under `logs/`. Meant to be triggered by Windows Task Scheduler for a daily automatic
refresh, not run by hand.

Deliberately ingest-only — it does *not* chain into `create_opportunity_spaces.py` /
`pipeline.scoring` / etc. Since step 4 now wipes and rebuilds opportunity spaces on every run,
auto-chaining the full pipeline nightly would silently regenerate/invalidate whatever opportunity
spaces were last reviewed or presented, with no one watching it happen. Signals accumulate safely in
the background; regenerating opportunity spaces stays a deliberate, manual step.

Setup: Task Scheduler → Create Basic Task → daily trigger (off-hours, avoid overlapping with a manual
pipeline run since two ingests close together tend to hit GDELT's rate limit) → action "Start a
program" → full path to `run_ingest.bat`. Check `logs/` after the first automatic run to confirm it
completed cleanly.

## Files, one by one

**`pipeline/config.py`** — all configuration: query sets per source, the real Orange Business API
catalog (`ORANGE_BUSINESS_ASSETS`, 17 products), real external validation (`ANALYST_RECOGNITION`,
`CUSTOMER_REFERENCES`, `CAPABILITY_STATS` — see below), the `PORTFOLIO_DISTANCE` taxonomy, the
`SIGNAL_TYPES` vocabulary, and the `TAXONOMY_*` lists (see Taxonomy section above). Loads `.env`
directly.

**`pipeline/db.py`** — SQLite schema and data-access functions. Five tables: `signals`,
`opportunity_spaces`, `opportunity_signals` (link table), `scores`, `right_to_win_scores`.
`upsert_opportunity_space()` previously only refreshed the `last_refreshed` timestamp when a label
already existed, silently leaving stale `vertical`/`use_case`/`technology` values in place — fixed to
update all four fields, so a label always reflects the theme it was most recently assigned to.

**`pipeline/ingest.py`** — raw collection from 9 sources (Google News, GDELT, vendor blogs, Hacker
News, arXiv, Semantic Scholar, TED, NewsAPI.ai, competitor watch), each wrapped in `safe_run()` so one
broken source never kills the whole run.

**`pipeline/analyze.py`** — the "Theme Extraction" step. `summary()` / `dump_titles()` for a no-LLM
skim first; `extract_themes()` — an LLM proposes 3-6 specific Use Case × Technology combinations per
vertical, using the `TAXONOMY_*` lists as guidance (see open whitelist question above). `_curate_themes()`
does Phase 3 curation: drops themes whose technology is a bare generic term (`GENERIC_TECHNOLOGY_TERMS`),
merges near-duplicate themes via fuzzy matching.

**`llm/llm_client.py`** — provider-agnostic LLM client, controlled entirely by `.env`.

**`pipeline/scoring.py`** — the scoring engine. See [Scoring methodology](#scoring-methodology) below.

**`create_opportunity_spaces.py`** — wipes and auto-registers every opportunity space
`extract_themes()` returns, across every vertical present in `signals`. See the warning section above
before relying on its output as final.

**`list_all_themes.py`** — regenerates `candidate_opportunity_spaces.md`: every candidate the LLM
finds per vertical, unfiltered.

**`dedupe_signals.py`** — finds near-duplicate signals (same story picked up by multiple sources with
slightly different titles) via fuzzy title matching. Dry-run by default; `--apply` actually deletes,
keeping the oldest signal in each duplicate group.

**`link_signals.py`** — links the strongest real signals to each opportunity space by keyword overlap.

**`calibrate_caps.py`** — diagnostic: real signal count and source diversity per vertical, to re-tune
scoring caps.

**`check_signals.py`** — small diagnostic: prints total signal count by vertical. Quick sanity check
after an `ingest.py` run, especially useful to confirm GDELT rate-limiting or a partial run didn't
quietly starve the pipeline of data.

**`run_ingest.bat`** — see [Automating ingest](#automating-ingest) above.

**`latest_scores.py`** / **`export_summary.py`** — read the most recent score per opportunity space;
`export_summary.py` writes `opportunity_spaces_summary.md`, the file to bring to a meeting.

**`docs/core_taxonomy_definition.md`** — taxonomy definition, see Taxonomy section above.

**`.gitignore`** — excludes `.env`, `radar.db`, Python caches, and logs from Git.

## Scoring methodology

Two scores per opportunity space, computed and stored separately — never blended into one number,
because "is the market hot" and "can we sell this today" are different questions with different owners.

### Attractiveness (0-10)

```
0.30 x market_signal_strength   (deterministic: raw signal volume)
0.20 x source_diversity         (deterministic: distinct source domains)
0.25 x evidence_quality         (LLM: credibility/specificity of sources)
0.10 x novelty_momentum         (deterministic: recency skew — now measurable, see below)
0.15 x strategic_relevance      (LLM: fit against the real Orange Business API catalog)
```

The brief's starting weights were 30/20/20/15/15. Moved 5 points from `novelty_momentum` (15% → 10%)
to `evidence_quality` (20% → 25%). **This reweighting was a solo decision — confirm together before
treating it as final.**

`novelty_momentum()` computes a real average signal age plus a two-window momentum comparison, with a
`NOVELTY_WINDOW_DAYS = 90` window (not the brief's suggested 1 year — GDELT's rolling window caps
around ~3 months and most RSS sources have no historical backfill at all, so a 1-year window would
flatten novelty across the board; see `date_range_check.py` for the empirical check behind this
choice). Momentum stays neutral (5.0) until at least `MOMENTUM_MIN_SPAN_DAYS = 7` of real date spread
exists in the signal set, rather than being computed on noise.

`MARKET_SIGNAL_CAP` (150) and `SOURCE_DIVERSITY_CAP` (50) were recalibrated from placeholder values
(20 / 8) once real volume existed to measure against — re-run `calibrate_caps.py` whenever ingest
volume changes meaningfully (e.g. after `dedupe_signals.py --apply`, or after accumulating several
days of automated ingest).

### Right-to-win (0-10), separate — the L0-L4 scale explained

Answers a different question than attractiveness: not "is the market hot" but "can Orange actually
sell this today, given what it already has." An LLM classifies each opportunity space against the real
Orange Business API catalog, always citing the specific asset(s) that apply.

| Level | Meaning | What it looks like in practice |
|---|---|---|
| **L0** | **Direct offer** — an existing asset addresses this as-is | Orange already sells exactly this. Fastest to market, lowest risk. |
| **L1** | **Bundle** — two or more existing assets exist but aren't packaged together yet | Everything needed already exists in the catalog; it just needs to be assembled and marketed as one offer. Still low technical risk. |
| **L2** | **Partner-dependent** — needs a capability an external partner has, not Orange itself | Orange would need to lean on a partner (e.g. Cisco, Microsoft, Fortinet, HPE, Palo Alto) for a missing piece. Doable, but depends on that relationship. |
| **L3** | **Adjacent** — needs one new capability to be built or acquired | Close, but there's a real gap — Orange would need R&D, a new product, or an acquisition to fully deliver. |
| **L4** | **White space** — no plausible path from the current portfolio | No credible route to sell this today with what Orange has, owns, or partners with. |

The L1 vs L2 boundary is a judgment call for the LLM, not a deterministic rule — it has been observed
to classify the *same* opportunity space as L1 on one run and L2 on another, when the technology
involved isn't clearly "just network/cloud/security" (e.g. robotics, computer vision). Worth
double-checking any L1/L2 result the team plans to lean on, rather than treating one run as final.

### Real-world evidence wired into scoring

Beyond the API catalog, three sourced (not fabricated) pieces of external evidence feed the
right-to-win prompt:

- **`ANALYST_RECOGNITION`** — Gartner Magic Quadrant for Global WAN Services 2026 (Leader, 23rd
  consecutive year); Gartner Peer Insights UCaaS (4.4/5, 16 verified reviews).
- **`CUSTOMER_REFERENCES`** — real named customers, filtered by vertical: BNP Paribas and Groupama for
  Finance & Insurance; AkzoNobel Packaging and Coatings and Veolia Water Technologies for Manufacturing.
  No verified Public Sector reference yet.
- **`CAPABILITY_STATS`** — scale/security facts (10,000+ infrastructure experts, 70+ data centers,
  3,000 Orange Cyberdefense experts, 25-year Microsoft partnership, 287M customers served).

All three are sourced from orange-business.com and gartner.com pages actually fetched and read, not
invented. The 17-API catalog itself comes from the official API catalog at
`orange-business.com/en/solutions/apiforbusiness` — 3 of the 17 (Mobile Suite, M2M for IoT Connect
Express, Ordering et Order Tracking) are only listed on the French-language version of that catalog
page, not the English one; all verified real, just FR-only pages.

### Reliability notes

- Every LLM call falls back to a neutral default if it fails — a run full of defaults is a sign to
  re-run, not a real judgment to present. A right-to-win result of exactly `L4/0` with justification
  "LLM scoring unavailable" is always this fallback, never a real classification — don't present it.
- **Groq free tier is rate-limited to 8,000 tokens/minute** — watch the console for
  `rate_limit_exceeded`; any OS scored during/after that error needs a solo re-run of `pipeline.scoring`.
  More opportunity spaces per run (now auto-registered, not fixed) means this happens more often than
  before.

## Current opportunity spaces

Not yet listed

## Known limitations / what's still open

- **Taxonomy whitelist question unresolved** — strict whitelist vs. examples-only, pending
  confirmation (see Taxonomy section above). Do not change the extraction prompt until this lands.
- **`TAXONOMY_TECHNOLOGIES_EMERGING`** was added ahead of the formal watchlist/validation mechanism
  (`discovery_signals.py`, `extend_taxonomy.py`, in progress) — should be folded into that process once
  it's ready, rather than living as a separately maintained list.
- `link_signals.py` is keyword-overlap, not LLM-judged — a few 1-keyword matches are noise; prefer
  citing the 2+ keyword matches in discussion.
- NewsAPI.ai's `.env` key-loading bug meant it had never actually been called before this fix — its
  real contribution (not a quota issue, simply never exercised) is still unverified; re-check signal
  counts from that source after a clean run.
- No verified Public Sector customer reference yet in `CUSTOMER_REFERENCES`.
- Weight/cap changes and the evidence wiring were made solo, to confirm.
- `dedupe_signals.py`'s similarity threshold (0.85) is a judgment call — review its report before
  applying, don't trust it blindly.
- L1 vs L2 right-to-win classification has been observed to flip between runs on the same opportunity
  space — see Scoring methodology above.
- GDELT has been intermittently rate-limited/timing out across several sessions — consider setting
  `ENABLE_GDELT = False` in `config.py` temporarily if it's consistently blocking a run; the other 8
  sources cover the taxonomy well on their own.

## Next steps for the team

1. Resolve the taxonomy whitelist question (strict vs. examples) before the next extraction run that
   matters for a presentation.
2. Once resolved, run the full pipeline (steps 4-7) fresh and review the resulting
   `opportunity_spaces_summary.md` together as a team — this is still a working extraction, not a
   decision, regardless of automation.
3. If/when the team freezes a final opportunity space list, **stop re-running
   `create_opportunity_spaces.py`** (see warning above) — it will erase a frozen selection on its next
   run.
4. Confirm whether the reweighted attractiveness formula (30/20/25/10/15) and the evidence wiring are
   acceptable as final.
5. Hand the `scores` + `right_to_win_scores` + `opportunity_spaces` tables to whoever builds the
   dashboard.
6. Fold `TAXONOMY_TECHNOLOGIES_EMERGING` into the watchlist/validation flow once `discovery_signals.py`
   / `extend_taxonomy.py` are ready.