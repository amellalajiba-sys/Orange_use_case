"""
Signal ingestion: pulls from each configured source and writes into the
`signals` table via db.py. Run directly to do a full refresh:

    python -m pipeline.ingest

Requires: feedparser, requests  (pip install feedparser requests)

LOGGING
-------
Every run mirrors everything printed to the console into a timestamped file
under logs/ (created automatically, e.g. logs/ingest_2026-08-20_1735.log).
This matters because safe_run() below deliberately swallows exceptions and
only prints a one-line summary per source -- without a persisted log, that
information is gone the moment the terminal closes. It's what lets you
answer "why did today's run collect fewer signals than yesterday's" days
later instead of only at the moment it happened.
logs/ is already covered by .gitignore's `*.log` rule -- these are meant to
stay local, not get committed.
"""

import json
import os
import sys
import time
import urllib.parse
from datetime import datetime, timedelta

import feedparser
import requests

from pipeline.config import (
    GOOGLE_NEWS_QUERIES,
    GDELT_QUERIES,
    ENABLE_GDELT,
    GDELT_SLEEP_SECONDS, GDELT_RETRY_WAIT_SECONDS, GDELT_COOLDOWN_MINUTES,
    VENDOR_FEEDS,
    HN_QUERIES,
    COMPETITOR_QUERIES,
    ARXIV_QUERIES,
    SEMANTIC_SCHOLAR_QUERIES,
    SEMANTIC_SCHOLAR_SLEEP_SECONDS,
    SEMANTIC_SCHOLAR_API_KEY, SEMANTIC_SCHOLAR_RETRY_WAIT_SECONDS, SEMANTIC_SCHOLAR_COOLDOWN_MINUTES,
    REGULATION_QUERIES,
    BUYING_SIGNAL_QUERIES,
    # --- real TED + NewsAPI.ai sources (replace/augment the Google-News proxies above) ---
    ENABLE_TED, TED_API_URL, TED_QUERIES, TED_FIELDS, TED_LOOKBACK_DAYS, TED_SLEEP_SECONDS,
    ENABLE_NEWSAPI_AI, NEWSAPI_AI_URL, NEWSAPI_AI_QUERIES, NEWSAPI_AI_KEY, NEWSAPI_AI_SLEEP_SECONDS,
)
from pipeline.db import get_connection, init_db, insert_signal

GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
HN_ALGOLIA_URL = "https://hn.algolia.com/api/v1/search"
ARXIV_API_URL = "https://export.arxiv.org/api/query"
SEMANTIC_SCHOLAR_URL = "https://api.semanticscholar.org/graph/v1/paper/search"

LOGS_DIR = "logs"


COOLDOWN_FILE = os.path.join(LOGS_DIR, ".source_cooldowns.json")


def _load_cooldowns():
    try:
        with open(COOLDOWN_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _mark_blocked(source_key):
    """Record 'this source just got rate-limited' with a timestamp -- persisted
    to disk so the cooldown survives across separate ingest runs, not just
    within one. Called from inside fetch_gdelt()/fetch_semantic_scholar()."""
    os.makedirs(LOGS_DIR, exist_ok=True)
    cooldowns = _load_cooldowns()
    cooldowns[source_key] = datetime.now().isoformat()
    with open(COOLDOWN_FILE, "w", encoding="utf-8") as f:
        json.dump(cooldowns, f)


def _cooldown_remaining_minutes(source_key, cooldown_minutes):
    """Returns minutes left on this source's cooldown, or 0 if it's clear."""
    last = _load_cooldowns().get(source_key)
    if not last:
        return 0.0
    elapsed_min = (datetime.now() - datetime.fromisoformat(last)).total_seconds() / 60
    return max(0.0, cooldown_minutes - elapsed_min)


class _Tee:
    """Writes to two streams at once (console + log file). Used to mirror
    every print() in this module into a persisted file without having to
    rewrite every print() call as a logger call."""

    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for s in self.streams:
            s.write(data)
            s.flush()  # flush immediately -- a run that gets killed mid-way
                       # (e.g. Ctrl+C during a GDELT rate-limit wait) still
                       # leaves a readable partial log instead of an empty file

    def flush(self):
        for s in self.streams:
            s.flush()


def _start_logging():
    """Creates logs/ if needed and starts mirroring stdout to a timestamped
    file. Returns (log_path, original_stdout) so the caller can restore
    stdout when done -- see run_full_refresh()'s try/finally."""
    os.makedirs(LOGS_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    log_path = os.path.join(LOGS_DIR, f"ingest_{timestamp}.log")
    log_file = open(log_path, "a", encoding="utf-8")
    original_stdout = sys.stdout
    sys.stdout = _Tee(original_stdout, log_file)
    print(f"=== Ingest run started {datetime.now().isoformat()} -- log: {log_path} ===\n")
    return log_path, log_file, original_stdout





# ---------- Google News RSS (market_move / trend / buying_signal) ----------

def fetch_google_news(conn, vertical, query, signal_type="market_move", max_items=15):
    url = "https://news.google.com/rss/search?q=" + urllib.parse.quote(query) + "&hl=en"
    feed = feedparser.parse(url)
    count = 0
    for entry in feed.entries[:max_items]:
        added = insert_signal(
            conn,
            source_name=entry.get("source", {}).get("title", "Google News"),
            source_url=entry.get("link"),
            signal_type=signal_type,
            title=entry.get("title"),
            summary=entry.get("summary"),
            published_date=entry.get("published"),
            vertical_hint=vertical,
        )
        count += added
    return count


# ---------- GDELT DOC 2.0 API (novelty_momentum / market_signal_strength) ----------

GDELT_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; InnovationRadar/1.0)"}


# 23/08 Sieg, GDELT kept 429-ing on the 17-vertical loop even with the
# retry+cooldown mechanism -- lowered max_records (25 -> 8) to cut payload
# per call, same fix a teammate's isolated test used (she used 5; 8 keeps a
# bit more signal per vertical while still being much lighter than 25).
def fetch_gdelt(conn, vertical, query, signal_type="trend", max_records=8, timespan="1m", _is_retry=False):
    params = {
        "query": query,
        "mode": "ArtList",
        "maxrecords": max_records,
        "format": "json",
        "timespan": timespan,
        "sort": "hybridrel",
    }
    resp = requests.get(GDELT_DOC_URL, params=params, headers=GDELT_HEADERS, timeout=20)

    if resp.status_code == 429:
        if not _is_retry:
            # One short in-call retry -- GDELT's throttling is often a brief
            # burst limit, not a hard multi-minute ban, so a short wait
            # sometimes clears it without needing the full cooldown.
            print(f"[GDELT] rate-limited -- waiting {GDELT_RETRY_WAIT_SECONDS}s and retrying once...")
            time.sleep(GDELT_RETRY_WAIT_SECONDS)
            return fetch_gdelt(conn, vertical, query, signal_type, max_records, timespan, _is_retry=True)
        print("[GDELT] still rate-limited after one retry -- skipping this query and starting a cooldown")
        _mark_blocked("gdelt")
        return 0

    resp.raise_for_status()

    # Robust parsing: GDELT occasionally sends JSON with a text/html
    # content-type, a stray BOM, or a genuinely empty/truncated body under
    # load. Try the normal path first, then a manual json.loads() on the
    # stripped text (catches the mislabeled-content-type case the first
    # attempt misses), and only then give up -- with real diagnostics
    # (content-type + a text snippet) instead of a generic "likely overloaded".
    data = None
    try:
        data = resp.json()
    except ValueError:
        try:
            data = json.loads(resp.text.strip())
        except (ValueError, AttributeError):
            pass

    if data is None:
        content_type = resp.headers.get("content-type", "unknown")
        snippet = resp.text[:120].replace("\n", " ") if resp.text else "(empty body)"
        print(f"[GDELT] non-JSON response (content-type: {content_type!r}, body starts: {snippet!r}) "
              f"-- skipping this query and starting a cooldown")
        _mark_blocked("gdelt")
        return 0

    count = 0
    for article in data.get("articles", []):
        added = insert_signal(
            conn,
            source_name=article.get("domain", "GDELT"),
            source_url=article.get("url"),
            signal_type=signal_type,
            title=article.get("title"),
            summary=None,
            published_date=article.get("seendate"),
            vertical_hint=vertical,
        )
        count += added
    return count


# ---------- Vendor blogs RSS (tech_maturity / proof_signal) ----------

def fetch_vendor_feed(conn, name, url, vertical_hint=None, signal_type="tech_maturity", max_items=10):
    feed = feedparser.parse(url)
    count = 0
    for entry in feed.entries[:max_items]:
        added = insert_signal(
            conn,
            source_name=name,
            source_url=entry.get("link"),
            signal_type=signal_type,
            title=entry.get("title"),
            summary=entry.get("summary"),
            published_date=entry.get("published"),
            vertical_hint=vertical_hint,
        )
        count += added
    return count


# ---------- Hacker News via Algolia (trend, bonus source) ----------

def fetch_hacker_news(conn, query, signal_type="trend", max_items=10, vertical_hint=None):
    resp = requests.get(HN_ALGOLIA_URL, params={"query": query, "tags": "story"}, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    count = 0
    for hit in data.get("hits", [])[:max_items]:
        added = insert_signal(
            conn,
            source_name="Hacker News",
            source_url=hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}",
            signal_type=signal_type,
            title=hit.get("title"),
            summary=None,
            published_date=hit.get("created_at"),
            vertical_hint=vertical_hint,
        )
        count += added
    return count


# ---------- arXiv (scientific papers, proof_signal / tech_maturity) ----------

def fetch_arxiv(conn, vertical, query, signal_type="proof_signal", max_results=10):
    # arXiv's search syntax needs boolean operators between terms -- a bare
    # space-separated phrase like "all:edge computer vision safety" often
    # returns 0 results. Join significant words with OR instead.
    terms = query.split()
    search_query = " OR ".join(f"all:{t}" for t in terms)
    params = {
        "search_query": search_query,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "max_results": max_results,
    }
    url = ARXIV_API_URL + "?" + urllib.parse.urlencode(params)
    feed = feedparser.parse(url)  # arXiv returns an Atom feed -- feedparser handles it directly
    count = 0
    for entry in feed.entries:
        added = insert_signal(
            conn,
            source_name="arXiv",
            source_url=entry.get("link"),
            signal_type=signal_type,
            title=entry.get("title", "").replace("\n", " ").strip(),
            summary=entry.get("summary"),
            published_date=entry.get("published"),
            vertical_hint=vertical,
        )
        count += added
    return count


# ---------- Semantic Scholar (broader scientific coverage, proof_signal) ----------

def fetch_semantic_scholar(conn, vertical, query, signal_type="proof_signal", limit=10, _is_retry=False):
    params = {"query": query, "limit": limit, "fields": "title,abstract,url,publicationDate,venue"}
    # Optional -- moves you off the shared unauthenticated pool onto your own,
    # much higher-limit one. Free key: https://www.semanticscholar.org/product/api
    headers = {"x-api-key": SEMANTIC_SCHOLAR_API_KEY} if SEMANTIC_SCHOLAR_API_KEY else {}

    resp = requests.get(SEMANTIC_SCHOLAR_URL, params=params, headers=headers, timeout=20)

    if resp.status_code == 429:
        if not SEMANTIC_SCHOLAR_API_KEY and not _is_retry:
            print(f"[Semantic Scholar] rate-limited (no API key -- get one free at "
                  f"semanticscholar.org/product/api) -- waiting {SEMANTIC_SCHOLAR_RETRY_WAIT_SECONDS}s "
                  f"and retrying once...")
            time.sleep(SEMANTIC_SCHOLAR_RETRY_WAIT_SECONDS)
            return fetch_semantic_scholar(conn, vertical, query, signal_type, limit, _is_retry=True)
        print("[Semantic Scholar] still rate-limited after retry -- skipping this query and starting a cooldown")
        _mark_blocked("semantic_scholar")
        return 0

    resp.raise_for_status()

    # Same defensive parsing as fetch_gdelt() -- an overloaded API can send a
    # malformed/empty body without a clean error status.
    try:
        data = resp.json()
    except ValueError:
        content_type = resp.headers.get("content-type", "unknown")
        print(f"[Semantic Scholar] non-JSON response (content-type: {content_type!r}) "
              f"-- skipping this query and starting a cooldown")
        _mark_blocked("semantic_scholar")
        return 0

    count = 0
    for paper in data.get("data", []):
        added = insert_signal(
            conn,
            source_name=paper.get("venue") or "Semantic Scholar",
            source_url=paper.get("url"),
            signal_type=signal_type,
            title=paper.get("title"),
            summary=paper.get("abstract"),
            published_date=paper.get("publicationDate"),
            vertical_hint=vertical,
        )
        count += added
    return count


# ---------- TED Search API v3 (real EU procurement data -- buying_signal) ----------

def _ted_pick_multilingual(value):
    """TED's eForms fields come back as {'eng': [...], 'fra': [...], ...} --
    a plain string is never returned. Picks the English value if present,
    else falls back to the first language that has one, else None. Always
    returns a plain string (or None) so insert_signal() never chokes on a
    dict where it expects title text."""
    if not value:
        return None
    if isinstance(value, str):
        return value  # defensive -- shouldn't happen per the API, but cheap to handle
    if isinstance(value, dict):
        for lang in ("eng", "fra"):
            v = value.get(lang)
            if v:
                return v[0] if isinstance(v, list) else v
        for v in value.values():
            if v:
                return v[0] if isinstance(v, list) else v
    return None


def fetch_ted(conn, vertical, query, signal_type="buying_signal", max_items=25):
    """Real TED Search API v3 call (POST, no API key needed for search --
    only submitting NOT-YET-published notices needs auth). Replaces the old
    'site:ted.europa.eu' Google News scrape with actual structured notices:
    buyer name, country, CPV classification, submission deadline.

    query is one of TED_QUERIES' expert-search strings (e.g. FT~"sovereign
    cloud EU government data"); a publication-date floor is appended here so
    every call only looks at recent notices, not TED's full 15k-notice-per-
    query ceiling.
    """
    since = (datetime.now() - timedelta(days=TED_LOOKBACK_DAYS)).strftime("%Y%m%d")
    body = {
        "query": f"({query}) AND publication-date>={since}",
        "fields": TED_FIELDS,
        "limit": max_items,
        "scope": "ACTIVE",              # only currently-open/recent notices, not the full archive
        "checkQuerySyntax": False,
        "paginationMode": "ITERATION",  # we only ever take page 1 -- fine for a radar, not a bulk export
    }
    resp = requests.post(TED_API_URL, json=body, headers={"Content-Type": "application/json"}, timeout=25)
    if resp.status_code != 200:
        print(f"[TED] request failed (HTTP {resp.status_code}) -- skipping this query. "
              f"Body: {resp.text[:200]}")
        return 0
    data = resp.json()
    # The API has used both "notices" and "results" as the top-level results key
    # across versions/environments -- check both rather than trusting one blindly.
    notices = data.get("notices") or data.get("results") or []

    count = 0
    for n in notices[:max_items]:
        title = _ted_pick_multilingual(n.get("notice-title"))
        buyer = _ted_pick_multilingual(n.get("buyer-name"))
        pub_number = n.get("publication-number")
        combined_title = f"{title} — {buyer}" if title and buyer else (title or f"TED notice {pub_number}")
        url = f"https://ted.europa.eu/en/notice/-/detail/{pub_number}" if pub_number else None
        added = insert_signal(
            conn,
            source_name="TED - EU Public Procurement",
            source_url=url,
            signal_type=signal_type,
            title=combined_title,
            summary=None,
            published_date=n.get("publication-date"),
            vertical_hint=vertical,
        )
        count += added
    return count


# ---------- NewsAPI.ai / Event Registry (market_move, broader than Google News RSS) ----------

def fetch_newsapi_ai(conn, vertical, query, signal_type="market_move", max_items=15):
    """NewsAPI.ai's getArticles endpoint -- proper full-text search with
    source/date filtering, unlike Google News RSS's locale-guessing "hl=en"
    trick. Needs NEWSAPI_AI_KEY in .env (free tier: 2,000 tokens/month, see
    https://newsapi.ai). Skips cleanly (0 signals, one print) if the key is
    missing -- never crashes the rest of the ingest run."""
    if not NEWSAPI_AI_KEY:
        print("[NewsAPI.ai] NEWSAPI_AI_KEY not set in .env -- skipping (get a free key at newsapi.ai)")
        return 0
    params = {
        "apiKey": NEWSAPI_AI_KEY,
        "action": "getArticles",
        "keyword": query,
        "keywordSearchMode": "simple",  # match any significant word in the phrase, not exact phrase-only
        "lang": "eng",
        "articlesSortBy": "date",
        "articlesSortByAsc": False,
        "articlesCount": max_items,
        "resultType": "articles",
    }
    resp = requests.get(NEWSAPI_AI_URL, params=params, timeout=20)
    if resp.status_code != 200:
        print(f"[NewsAPI.ai] request failed (HTTP {resp.status_code}) -- skipping this query")
        return 0
    data = resp.json()
    articles = data.get("articles", {}).get("results", [])

    count = 0
    for a in articles[:max_items]:
        added = insert_signal(
            conn,
            source_name=(a.get("source") or {}).get("title", "NewsAPI.ai"),
            source_url=a.get("url"),
            signal_type=signal_type,
            title=a.get("title"),
            summary=(a.get("body") or "")[:500] or None,  # trimmed -- full body isn't needed for scoring prompts
            published_date=a.get("date"),
            vertical_hint=vertical,
        )
        count += added
    return count


def run_full_refresh():
    log_path, log_file, original_stdout = _start_logging()
    try:
        init_db()
        conn = get_connection()
        total = 0

        def safe_run(label, fn, *args, **kwargs):
            """Run one source; log and continue if it fails, never crash the whole refresh."""
            nonlocal total
            try:
                n = fn(*args, **kwargs)
                print(f"[{label}] +{n} new signals")
                total += n
            except Exception as e:
                print(f"[{label}] FAILED ({e}) -- skipping, continuing with other sources")

        for q in GOOGLE_NEWS_QUERIES:
            safe_run(f"Google News / {q['vertical']}", fetch_google_news, conn, q["vertical"], q["query"])

        if ENABLE_NEWSAPI_AI:
            for q in NEWSAPI_AI_QUERIES:
                safe_run(f"NewsAPI.ai / {q['vertical']}", fetch_newsapi_ai, conn, q["vertical"], q["query"])
                time.sleep(NEWSAPI_AI_SLEEP_SECONDS)
        else:
            print("[NewsAPI.ai] disabled in config.py (ENABLE_NEWSAPI_AI = False) -- skipping")

        if ENABLE_GDELT:
            remaining = _cooldown_remaining_minutes("gdelt", GDELT_COOLDOWN_MINUTES)
            if remaining > 0:
                print(f"[GDELT] cooling down from a recent rate-limit ({remaining:.0f} min left) -- "
                      f"skipping the whole GDELT pass this run instead of hammering it again. "
                      f"It'll retry automatically once the cooldown clears.")
            else:
                consecutive_blocks = 0
                for q in GDELT_QUERIES:
                    safe_run(f"GDELT / {q['vertical']}", fetch_gdelt, conn, q["vertical"], q["query"])
                    if _cooldown_remaining_minutes("gdelt", GDELT_COOLDOWN_MINUTES) > 0:
                        consecutive_blocks += 1
                    else:
                        consecutive_blocks = 0
                    if consecutive_blocks >= 2:
                        print(f"[GDELT] blocked 2x in a row -- stopping the GDELT pass early "
                              f"(only tried {GDELT_QUERIES.index(q) + 1}/{len(GDELT_QUERIES)} verticals) "
                              f"instead of burning through the rest. Will retry automatically after "
                              f"the {GDELT_COOLDOWN_MINUTES}-min cooldown.")
                        break
                    time.sleep(GDELT_SLEEP_SECONDS)
        else:
            print("[GDELT] disabled in config.py (ENABLE_GDELT = False) -- skipping")

        # Sieg 26/8 -- both these sources are genuinely not tied to one
        # vertical (vendor blogs, general HN search terms), which used to
        # leave vertical_hint as NULL -> showed as a silent "(Blank)" slice
        # in the Power BI treemap (128 signals, no explanation). Giving it a
        # real, documented label instead -- same "Cross-vertical" value
        # already used elsewhere in the data -- so it's an honest category,
        # not a data gap. See README's "Cross-vertical signals" note.
        for feed in VENDOR_FEEDS:
            safe_run(f"Vendor / {feed['name']}", fetch_vendor_feed, conn, feed["name"], feed["url"],
                     vertical_hint="Cross-vertical")

        for q in HN_QUERIES:
            safe_run(f"Hacker News / '{q}'", fetch_hacker_news, conn, q, vertical_hint="Cross-vertical")

        for q in COMPETITOR_QUERIES:
            safe_run(f"Competitor watch / {q['vertical']}", fetch_google_news,
                      conn, q["vertical"], q["query"], signal_type="market_move")

        for q in ARXIV_QUERIES:
            safe_run(f"arXiv / {q['vertical']}", fetch_arxiv, conn, q["vertical"], q["query"])

        for q in REGULATION_QUERIES:
            safe_run(f"Regulation (EUR-Lex) / {q['vertical']}", fetch_google_news,
                      conn, q["vertical"], q["query"], signal_type="regulation")

        if ENABLE_TED:
            for q in TED_QUERIES:
                safe_run(f"TED API / {q['vertical']}", fetch_ted, conn, q["vertical"], q["query"])
                time.sleep(TED_SLEEP_SECONDS)
        else:
            # Fallback: the old Google-News "site:ted.europa.eu" scrape --
            # much noisier (whatever Google happened to index) but needs no key.
            print("[TED] ENABLE_TED = False -- falling back to Google News site: scrape")
            for q in BUYING_SIGNAL_QUERIES:
                safe_run(f"Buying signal (TED via Google News) / {q['vertical']}", fetch_google_news,
                          conn, q["vertical"], q["query"], signal_type="buying_signal")

        remaining = _cooldown_remaining_minutes("semantic_scholar", SEMANTIC_SCHOLAR_COOLDOWN_MINUTES)
        if remaining > 0:
            print(f"[Semantic Scholar] cooling down from a recent rate-limit ({remaining:.0f} min left) "
                  f"-- skipping the whole pass this run. It'll retry automatically once the cooldown clears.")
        else:
            consecutive_blocks = 0
            for q in SEMANTIC_SCHOLAR_QUERIES:
                safe_run(f"Semantic Scholar / {q['vertical']}", fetch_semantic_scholar, conn, q["vertical"], q["query"])
                if _cooldown_remaining_minutes("semantic_scholar", SEMANTIC_SCHOLAR_COOLDOWN_MINUTES) > 0:
                    consecutive_blocks += 1
                else:
                    consecutive_blocks = 0
                if consecutive_blocks >= 2:
                    print(f"[Semantic Scholar] blocked 2x in a row -- stopping this pass early "
                          f"instead of burning through the rest. Will retry automatically after "
                          f"the {SEMANTIC_SCHOLAR_COOLDOWN_MINUTES}-min cooldown.")
                    break
                time.sleep(SEMANTIC_SCHOLAR_SLEEP_SECONDS)

        conn.close()
        print(f"\nTotal new signals collected: {total}")
        print(f"\n=== Ingest run finished {datetime.now().isoformat()} ===")
    finally:
        sys.stdout = original_stdout
        log_file.close()
        print(f"Log written: {log_path}")


if __name__ == "__main__":
    run_full_refresh()
