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

import os
import sys
import time
import urllib.parse
from datetime import datetime

import feedparser
import requests

from pipeline.config import (
    GOOGLE_NEWS_QUERIES,
    GDELT_QUERIES,
    ENABLE_GDELT,
    VENDOR_FEEDS,
    HN_QUERIES,
    COMPETITOR_QUERIES,
    ARXIV_QUERIES,
    SEMANTIC_SCHOLAR_QUERIES,
    REGULATION_QUERIES,
    BUYING_SIGNAL_QUERIES,
)
from pipeline.db import get_connection, init_db, insert_signal

GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
HN_ALGOLIA_URL = "https://hn.algolia.com/api/v1/search"
ARXIV_API_URL = "https://export.arxiv.org/api/query"
SEMANTIC_SCHOLAR_URL = "https://api.semanticscholar.org/graph/v1/paper/search"

LOGS_DIR = "logs"


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


def fetch_gdelt(conn, vertical, query, signal_type="trend", max_records=25, timespan="1m"):
    params = {
        "query": query,
        "mode": "ArtList",
        "maxrecords": max_records,
        "format": "json",
        "timespan": timespan,
        "sort": "hybridrel",
    }
    resp = requests.get(GDELT_DOC_URL, params=params, headers=GDELT_HEADERS, timeout=20
    )
    if resp.status_code == 429:
        print("[GDELT] rate-limited -- skipping this query (don't rerun the pipeline immediately, wait 15-20 min)")
        return 0
    resp.raise_for_status()
    try:
        data = resp.json()
    except ValueError:
        # GDELT occasionally returns an empty/non-JSON body under load instead of a
        # clean error code -- treat it the same as "no results" rather than crashing.
        print("[GDELT] got a non-JSON response (likely overloaded) -- skipping this query")
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

def fetch_semantic_scholar(conn, vertical, query, signal_type="proof_signal", limit=10):
    params = {"query": query, "limit": limit, "fields": "title,abstract,url,publicationDate,venue"}
    resp = requests.get(SEMANTIC_SCHOLAR_URL, params=params, timeout=20)
    if resp.status_code == 429:
        print("[Semantic Scholar] rate-limited (no API key) -- try again later or slow down requests")
        return 0
    resp.raise_for_status()
    data = resp.json()
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

        if ENABLE_GDELT:
            for q in GDELT_QUERIES:
                safe_run(f"GDELT / {q['vertical']}", fetch_gdelt, conn, q["vertical"], q["query"])
                time.sleep(45)  # GDELT rate-limits aggressively -- space out consecutive calls
        else:
            print("[GDELT] disabled in config.py (ENABLE_GDELT = False) -- skipping")

        for feed in VENDOR_FEEDS:
            safe_run(f"Vendor / {feed['name']}", fetch_vendor_feed, conn, feed["name"], feed["url"])

        for q in HN_QUERIES:
            safe_run(f"Hacker News / '{q}'", fetch_hacker_news, conn, q)

        for q in COMPETITOR_QUERIES:
            safe_run(f"Competitor watch / {q['vertical']}", fetch_google_news,
                      conn, q["vertical"], q["query"], signal_type="market_move")

        for q in ARXIV_QUERIES:
            safe_run(f"arXiv / {q['vertical']}", fetch_arxiv, conn, q["vertical"], q["query"])

        for q in REGULATION_QUERIES:
            safe_run(f"Regulation (EUR-Lex) / {q['vertical']}", fetch_google_news,
                      conn, q["vertical"], q["query"], signal_type="regulation")

        for q in BUYING_SIGNAL_QUERIES:
            safe_run(f"Buying signal (TED) / {q['vertical']}", fetch_google_news,
                      conn, q["vertical"], q["query"], signal_type="buying_signal")

        for q in SEMANTIC_SCHOLAR_QUERIES:
            safe_run(f"Semantic Scholar / {q['vertical']}", fetch_semantic_scholar, conn, q["vertical"], q["query"])
            time.sleep(20)  # unauthenticated Semantic Scholar limit is strict (~1 req / few seconds)

        conn.close()
        print(f"\nTotal new signals collected: {total}")
        print(f"\n=== Ingest run finished {datetime.now().isoformat()} ===")
    finally:
        sys.stdout = original_stdout
        log_file.close()
        print(f"Log written: {log_path}")


if __name__ == "__main__":
    run_full_refresh()