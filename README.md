<!-- https://www.orange-business.com/en/business-needs/scalable-responsive-secure-digital-infrastructure
https://www.orange-business.com/en/about-us/analysts/gartner-recognition-for-global-wan-services
https://www.gartner.com/reviews/market/unified-communications-as-a-service/vendor/orange-business
https://www.orange-business.com/en/business-needs/digital-work-experience
https://www.orange-business.com/en/business-needs/scalable-responsive-secure-digital-infrastructure
https://www.orange-business.com/en/business-needs/operational-experience-optimize-industry-digitizing-processes
https://www.orange-business.com/en/business-needs/customer-experience
https://www.orange-business.com/en/business-needs/operational-experience-optimize-industry-digitizing-processes
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

## ⚠️ Opportunity spaces are not decided yet — this needs a team call

Four opportunity spaces (OS001-004) are already registered and scored, but they were picked by me as a way to test the pipeline end-to-end. The LLM actually found 14 candidate Use Case × Technology patterns across our 3 verticals — the full unfiltered list is in
`candidate_opportunity_spaces.md`, regenerate anytime with `python list_all_themes.py`.

**Before treating any score as final, we should:** look at all 14 candidates together, decide
which to keep (any mix of the 4 already-scored ones, new ones from the list, or a swap), then re-run
steps 4-7 below on the final list.

## Run order

All commands run from the project root (the code imports as `pipeline.*` / `llm.*` packages):

```bash
python -m pipeline.db              # 1. create/migrate radar.db (safe to re-run, never deletes data)
python -m pipeline.ingest          # 2. pull signals from 9 sources into `signals`
python -m pipeline.analyze         # 3. (optional) quick stats + LLM theme extraction per vertical
python list_all_themes.py          # 3b. (optional) regenerate candidate_opportunity_spaces.md, unfiltered
python dedupe_signals.py           # 3c. (optional) report near-duplicate signals across sources
python dedupe_signals.py --apply   #     actually remove them, once you've reviewed the report
python create_opportunity_spaces.py  # 4. register the team's chosen Vertical x Use Case x Technology candidates
python -m pipeline.scoring         # 5. score each one: attractiveness + right-to-win
python link_signals.py             # 6. link the strongest real signals to each opportunity space
python export_summary.py           # 7. write opportunity_spaces_summary.md (the one file to bring to a meeting)
```

Steps 1-3c only need re-running when you want fresh/cleaner signals. Steps 4-7 are the scoring loop —
re-run 5-7 any time you change `scoring.py`, change which OS are registered, or switch LLM provider;
`scoring.py` always `INSERT`s a new row rather than overwriting, so `latest_scores.py` /
`export_summary.py` always read the most recent run per opportunity space.

`create_opportunity_spaces.py` currently registers the 4 OS mentioned above — edit its `CANDIDATES`
list once the team has decided, then re-run steps 4-7.

Useful one-offs:

```bash
python latest_scores.py    # print latest scores to console, no file written
python calibrate_caps.py   # print real signal count + source diversity per vertical, to recalibrate scoring.py's caps
```

## Files, one by one

**`pipeline/config.py`** — all configuration: query sets per source, the real Orange Business API
catalog (`ORANGE_BUSINESS_ASSETS`, 17 products), real external validation (`ANALYST_RECOGNITION`,
`CUSTOMER_REFERENCES`, `CAPABILITY_STATS` — see below), the `PORTFOLIO_DISTANCE` taxonomy, and the
`SIGNAL_TYPES` vocabulary.

**`pipeline/db.py`** — SQLite schema and data-access functions. Five tables: `signals`,
`opportunity_spaces`, `opportunity_signals` (link table), `scores`, `right_to_win_scores`.

**`pipeline/ingest.py`** — raw collection from 9 sources (Google News, GDELT, vendor blogs, Hacker
News, arXiv, Semantic Scholar, TED, NewsAPI.ai, competitor watch), each wrapped in `safe_run()` so one
broken source never kills the whole run.

**`pipeline/analyze.py`** — the "Theme Extraction" step. `summary()` / `dump_titles()` for a no-LLM
skim first; `extract_themes()` — an LLM proposes 3-6 specific Use Case × Technology combinations per
vertical.

**`llm/llm_client.py`** — provider-agnostic LLM client, controlled entirely by `.env`.

**`pipeline/scoring.py`** — the scoring engine. See [Scoring methodology](#scoring-methodology) below.

**`create_opportunity_spaces.py`** — registers whichever opportunity spaces the team has chosen.

**`list_all_themes.py`** — regenerates `candidate_opportunity_spaces.md`: every candidate the LLM
finds per vertical, unfiltered.

**`dedupe_signals.py`** — finds near-duplicate signals (same story picked up by multiple sources with
slightly different titles) via fuzzy title matching. Dry-run by default; `--apply` actually deletes,
keeping the oldest signal in each duplicate group.

**`link_signals.py`** — links the strongest real signals to each opportunity space by keyword overlap.

**`calibrate_caps.py`** — diagnostic: real signal count and source diversity per vertical, to re-tune
scoring caps.

**`latest_scores.py`** / **`export_summary.py`** — read the most recent score per opportunity space;
`export_summary.py` writes `opportunity_spaces_summary.md`, the file to bring to a meeting.

**`.gitignore`** — excludes `.env`, `radar.db`, Python caches, and logs from Git.

## Scoring methodology

Two scores per opportunity space, computed and stored separately — never blended into one number,
because "is the market hot" and "can we sell this today" are different questions with different owners.

### Attractiveness (0-10)

```
0.30 x market_signal_strength   (deterministic: raw signal volume)
0.20 x source_diversity         (deterministic: distinct source domains)
0.25 x evidence_quality         (LLM: credibility/specificity of sources)
0.10 x novelty_momentum         (deterministic: recency skew — currently unreliable, see below)
0.15 x strategic_relevance      (LLM: fit against the real Orange Business API catalog)
```

The brief's starting weights were 30/20/20/15/15. I moved 5 points from `novelty_momentum` (15% →
10%) to `evidence_quality` (20% → 25%), decided *before* looking at how it would move the ranking:
`novelty_momentum`'s proxy only means something once signals are spread over weeks or months, and every
opportunity space has landed at ~3.3 on it regardless of topic so far since all data was ingested in
one short window. **This reweighting was a solo decision — we confirm together before treating it as final.**

`MARKET_SIGNAL_CAP` (150) and `SOURCE_DIVERSITY_CAP` (50) were recalibrated from placeholder values
(20 / 8) once real volume existed to measure against — re-run `calibrate_caps.py` whenever ingest
volume changes meaningfully (e.g. after `dedupe_signals.py --apply`).

### Right-to-win (0-10), separate — the L0-L4 scale explained

Answers a different question than attractiveness: not "is the market hot" but "can Orange actually
sell this today, given what it already has." An LLM classifies each opportunity space against the real
Orange Business API catalog, always citing the specific asset(s) that apply.

| Level | Meaning | What it looks like in practice |
|---|---|---|
| **L0** | **Direct offer** — an existing asset addresses this as-is | Orange already sells exactly this. Fastest to market, lowest risk. |
| **L1** | **Bundle** — two or more existing assets exist but aren't packaged together yet | Everything needed already exists in the catalog; it just needs to be assembled and marketed as one offer. Still low technical risk. |
| **L2** | **Partner-dependent** — needs a capability an external partner has, not Orange itself | Orange would need to lean on a partner (e.g. Cisco, AWS, Fortinet) for a missing piece. Doable, but depends on that relationship. |
| **L3** | **Adjacent** — needs one new capability to be built or acquired | Close, but there's a real gap — Orange would need R&D, a new product, or an acquisition to fully deliver. |
| **L4** | **White space** — no plausible path from the current portfolio | No credible route to sell this today with what Orange has, owns, or partners with. |

**In our current scores, no opportunity space has hit L0 or L2** — everything so far is L1 (bundle of
existing assets) or L3 (missing one real capability). That's a useful pattern to point out in the
meeting: **L1 opportunities are the safer, faster bets** (repackage what already exists); **L3
opportunities are the bigger swings** (real product investment needed, but potentially more
differentiated precisely because competitors can't just repackage either).

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
invented.

### Reliability notes

- Every LLM call falls back to a neutral default if it fails — a run full of defaults is a sign to
  re-run, not a real judgment to present.
- **Groq free tier is rate-limited to 8,000 tokens/minute** — watch the console for
  `rate_limit_exceeded`; any OS scored during/after that error needs a solo re-run of `pipeline.scoring`.

## Current opportunity spaces

Latest scores, after deduplicating 9 near-duplicate signals (was 106-128 signals/28-47 sources per
vertical, now 105-120/28-41):

| OS | Vertical × Use Case × Technology | Attractiveness | Right-to-win | Distance |
|---|---|---|---|---|
| OS004 | Manufacturing × Remote-controlled industrial robots × Vision-guided teleoperation | 7.32/10 | 8.0/10 | L1 |
| OS002 | Manufacturing × Fire and hazard detection × Edge computer vision (Raspberry Pi class) | 7.02/10 | 6.0/10 | L3 |
| OS001 | Public Sector × Sovereign citizen data hosting × Sovereign cloud + GPU inference | 6.60/10 | 5.0/10 | L3 |
| OS003 | Finance & Insurance × Conduct-risk / compliance monitoring × AI surveillance of communications | 6.52/10 | 7.0/10 | L1 |

Full breakdown with sub-scores, justifications, and grounding signals: `opportunity_spaces_summary.md`
(regenerate with `python export_summary.py`). Remember: this is scored against only 4 of the 14
candidates found — see the warning at the top of this README.

## Known limitations / what's still open

- `novelty_momentum` isn't meaningful yet — needs ingest running over several weeks.
- `link_signals.py` is keyword-overlap, not LLM-judged — a few 1-keyword matches are noise; prefer
  citing the 2+ keyword matches in discussion.
- TED and NewsAPI.ai are wired in but contribute little so far.
- No verified Public Sector customer reference yet in `CUSTOMER_REFERENCES`.
- Weight/cap changes and the evidence wiring were made solo, to confirm.
- `dedupe_signals.py`'s similarity threshold (0.85) is a judgment call — review its report before
  applying, don't trust it blindly.

## Next steps for the team

1. **Look at all 14 candidates in `candidate_opportunity_spaces.md` together and decide which to score**
   — OS001-004 is a working example, not a decision.
2. Update `CANDIDATES` in `create_opportunity_spaces.py` to match, then re-run steps 4-7.
3. Confirm whether the reweighted formula (30/20/25/10/15) and the evidence additions are acceptable.
4. Hand the `scores` + `right_to_win_scores` + `opportunity_spaces` tables to whoever builds the dashboard.