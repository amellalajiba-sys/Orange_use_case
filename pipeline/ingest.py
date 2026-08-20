"""
Signal ingestion: pulls from each configured source and writes into the
`signals` table via db.py. Run directly to do a full refresh:

    python -m pipeline.ingest

Requires: feedparser, requests  (pip install feedparser requests)
"""

import os
import time
import urllib.parse
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
    TED_QUERIES,
    ENABLE_NEWSAPI_AI,
    NEWSAPI_AI_QUERIES,
)
from pipeline.db import get_connection, init_db, insert_signal

GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
HN_ALGOLIA_URL = "https://hn.algolia.com/api/v1/search"
ARXIV_API_URL = "https://export.arxiv.org/api/query"
SEMANTIC_SCHOLAR_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
TED_SEARCH_URL = "https://api.ted.europa.eu/v3/notices/search"
NEWSAPI_AI_URL = "https://eventregistry.org/api/v1/article/getArticles"


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
    resp = requests.get(GDELT_DOC_URL, params=params, headers=GDELT_HEADERS, timeout=30)
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
    # returns 0 results. Join significant words with AND instead.
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


# ---------- TED (Tenders Electronic Daily) -- EU public procurement notices ----------
# Search API v3, free and keyless for search/retrieval. A published tender naming
# a technology is a stronger buying_signal than a news article speculating about it.

def fetch_ted(conn, vertical, query, signal_type="buying_signal", max_results=15):
    # Anonymous, keyless read access -- no EU Login / API key needed for search.
    # An exact-phrase match on the whole query almost never appears verbatim in
    # a tender title, so narrow to the 2 longest (most specific) words instead,
    # ANDed together -- narrow enough to stay relevant, loose enough to match.
    terms = sorted(query.split(), key=len, reverse=True)[:2]
    search_expr = " AND ".join(f'FT~"{t}"' for t in terms)
    body = {
        "query": search_expr,
        "fields": ["publication-number", "notice-title", "buyer-name", "buyer-country", "publication-date"],
        "limit": max_results,
        "scope": "ACTIVE",
        "paginationMode": "ITERATION",
    }
    resp = requests.post(TED_SEARCH_URL, json=body, headers={"Content-Type": "application/json"}, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    count = 0
    if not data.get("notices"):
        print(f"[TED] 0 notices matched query: {search_expr}")
    for notice in data.get("notices", []):
        pub_number = notice.get("publication-number")
        title = notice.get("notice-title")
        # notice-title can come back as a dict keyed by language code
        if isinstance(title, dict):
            title = title.get("eng") or next(iter(title.values()), None)
        if not title or not pub_number:
            continue
        buyer = notice.get("buyer-name")
        if isinstance(buyer, list):
            buyer = buyer[0] if buyer else None
        buyer_country = notice.get("buyer-country")
        added = insert_signal(
            conn,
            source_name=f"TED - {buyer}" if buyer else "TED",
            source_url=f"https://ted.europa.eu/en/notice/-/detail/{pub_number}",
            signal_type=signal_type,
            title=title,
            summary=f"Buyer country: {buyer_country}" if buyer_country else None,
            published_date=notice.get("publication-date"),
            vertical_hint=vertical,
        )
        count += added
    return count


# ---------- NewsAPI.ai / Event Registry (market_move, broader multilingual coverage) ----------
# Needs NEWSAPI_AI_KEY in .env (free tier: 2,000 tokens/month, https://newsapi.ai).
# Self-skips (returns 0, no crash) if the key isn't set.

def fetch_newsapi_ai(conn, vertical, query, signal_type="market_move", max_items=15):
    api_key = os.environ.get("NEWSAPI_AI_KEY")
    if not api_key:
        print("[NewsAPI.ai] NEWSAPI_AI_KEY not set in .env -- skipping")
        return 0
    params = {
        "action": "getArticles",
        "keyword": query,
        "lang": "eng",
        "articlesSortBy": "date",
        "articlesCount": max_items,
        "resultType": "articles",
        "apiKey": api_key,
    }
    resp = requests.get(NEWSAPI_AI_URL, params=params, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    articles = data.get("articles", {}).get("results", [])
    count = 0
    for a in articles:
        added = insert_signal(
            conn,
            source_name=(a.get("source") or {}).get("title", "NewsAPI.ai"),
            source_url=a.get("url"),
            signal_type=signal_type,
            title=a.get("title"),
            summary=(a.get("body") or "")[:500] or None,
            published_date=a.get("date"),
            vertical_hint=vertical,
        )
        count += added
    return count


def run_full_refresh():
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
            time.sleep(15)  # GDELT rate-limits aggressively -- space out consecutive calls
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

    for q in SEMANTIC_SCHOLAR_QUERIES:
        safe_run(f"Semantic Scholar / {q['vertical']}", fetch_semantic_scholar, conn, q["vertical"], q["query"])
        time.sleep(8)  

    for q in TED_QUERIES:
        safe_run(f"TED / {q['vertical']}", fetch_ted, conn, q["vertical"], q["query"])

    if ENABLE_NEWSAPI_AI:
        for q in NEWSAPI_AI_QUERIES:
            safe_run(f"NewsAPI.ai / {q['vertical']}", fetch_newsapi_ai, conn, q["vertical"], q["query"])
    else:
        print("[NewsAPI.ai] disabled in config.py (ENABLE_NEWSAPI_AI = False) -- skipping")

    conn.close()
    print(f"\nTotal new signals collected: {total}")


if __name__ == "__main__":
    run_full_refresh()