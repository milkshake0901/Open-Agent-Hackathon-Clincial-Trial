"""Cached, rate-limited GET for ClinicalTrials.gov API v2. Stdlib only.

Every response is saved under ../cache/ keyed by path + query; re-runs read the cache and never call the API.
Pacing: >= 1.3 s between live calls (about 46/min). On HTTP 429: wait 60 s, retry once.
"""
from __future__ import annotations

import hashlib
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://clinicaltrials.gov/api/v2"
ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "cache"
OUT = ROOT / "out"
MIN_GAP_S = 1.3
# macOS keychain roots (exported to ../system-ca.pem); python.org Python does not see them by default.
_SSL = ssl.create_default_context(cafile=str(ROOT / "system-ca.pem")) if (ROOT / "system-ca.pem").exists() else None

_last_call = 0.0
live_calls = 0


def _cache_path(path: str, params: dict | None) -> Path:
    query = urllib.parse.urlencode(sorted((params or {}).items()))
    slug = path.strip("/").replace("/", "_") or "root"
    digest = hashlib.sha1(f"{path}?{query}".encode()).hexdigest()[:12]
    return CACHE / f"{slug}__{digest}.json"


def get(path: str, params: dict | None = None):
    global _last_call, live_calls
    p = _cache_path(path, params)
    if p.exists():
        return json.loads(p.read_text())["body"]
    url = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
    for attempt in (1, 2):
        wait = MIN_GAP_S - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()
        live_calls += 1
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "trialmatch-discovery/0.1"})
            with urllib.request.urlopen(req, timeout=120, context=_SSL) as r:
                body = json.loads(r.read())
            break
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt == 1:
                time.sleep(60)
                continue
            raise RuntimeError(f"HTTP {e.code} for {url}: {e.read()[:300]!r}") from e
    CACHE.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"url": url, "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "body": body}))
    return body


def get_all(path: str, params: dict, cap: int) -> list[dict]:
    """Follow nextPageToken until exhausted or cap studies reached."""
    studies: list[dict] = []
    token = None
    while True:
        q = dict(params)
        if token:
            q["pageToken"] = token
        body = get(path, q)
        studies.extend(body.get("studies", []))
        token = body.get("nextPageToken")
        if not token or len(studies) >= cap:
            return studies[:cap]
