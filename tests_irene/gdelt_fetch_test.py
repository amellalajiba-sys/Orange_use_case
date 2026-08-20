# tests_irene/gdelt_fetch_test.py
import requests

url = "https://api.gdeltproject.org/api/v2/doc/doc"
params = {
    "query": "manufacturing",  # ← Simpler query
    "mode": "ArtList",
    "maxrecords": 5,           # ← Request fewer articles
    "format": "json",
    "timespan": "1m",
    "sort": "hybridrel"
}
headers = {"User-Agent": "Mozilla/5.0 (compatible; InnovationRadar/1.0)"}

resp = requests.get(url, params=params, headers=headers, timeout=30)
print(resp.status_code)  # Should be 200, not 429

if resp.status_code == 200:
    data = resp.json()
    print(f"Found {len(data.get('articles', []))} articles")
else:
    print(f"Error: {resp.status_code} — {resp.text[:200]}")