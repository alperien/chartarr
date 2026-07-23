"""Match (artist, album title) pairs to MusicBrainz release groups.

The scoring survived a 1,395-album RateYourMusic chart with an 88.6%
auto-match rate, including titles like "★ [Blackstar]", "F♯A♯∞" and
dual-script Japanese releases.
"""
from __future__ import annotations

import json
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from difflib import SequenceMatcher

from . import __version__

USER_AGENT = f"chartarr/{__version__} (+https://github.com/alperien/chartarr)"
MIN_SPACING = 1.1  # seconds between requests; MusicBrainz allows 1 req/sec

_last_request = [0.0]


# ---------------------------------------------------------------- normalizing

def norm(s: str) -> str:
    """Casefolded, diacritic-free, punctuation-free form for comparison."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.casefold().replace("&", " and ")
    s = "".join(c if c.isalnum() else " " for c in s)
    return re.sub(r"\s+", " ", s).strip()


def sim(a: str, b: str) -> float:
    """Similarity in [0, 1]; falls back to raw comparison for symbol-only
    strings like Bowie's "★" that normalize to nothing."""
    na, nb = norm(a), norm(b)
    if na and nb:
        return SequenceMatcher(None, na, nb).ratio()
    ra = re.sub(r"\s+", "", a.casefold())
    rb = re.sub(r"\s+", "", b.casefold())
    if not ra or not rb:
        return 0.0
    return SequenceMatcher(None, ra, rb).ratio()


def variants(s: str) -> list[str]:
    """Alternate forms worth trying: the flattened string, each line of a
    multi-line value (RYM exports dual-script titles on two lines), and
    bracket-stripped forms ("★ [Blackstar]" -> "★" and "Blackstar")."""
    out: list[str] = []

    def add(x: str) -> None:
        x = re.sub(r"\s+", " ", x).strip()
        if x and x not in out:
            out.append(x)

    add(s.replace("\n", " "))
    for line in s.split("\n"):
        add(line)
    flat = re.sub(r"\s+", " ", s).strip()
    m = re.match(r"^(.*?)\s*\[([^\]]+)\]$", flat)
    if m:
        add(m.group(1))
        add(m.group(2))
    m = re.match(r"^(.*?)\s*\(([^)]+)\)$", flat)
    if m:
        add(m.group(1))
    return out


# ------------------------------------------------------------- MusicBrainz IO

def _lucene_quote(s: str) -> str:
    return '"' + s.replace("\\", r"\\").replace('"', r"\"") + '"'


def mb_search(query: str, limit: int = 8) -> dict | None:
    """Rate-limited release-group search with retry/backoff."""
    url = "https://musicbrainz.org/ws/2/release-group/?" + urllib.parse.urlencode(
        {"query": query, "fmt": "json", "limit": limit})
    for attempt in range(6):
        wait = _last_request[0] + MIN_SPACING - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_request[0] = time.monotonic()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (429, 503):
                retry_after = e.headers.get("Retry-After")
                try:
                    pause = float(retry_after) if retry_after else 2.0 * (attempt + 1)
                except ValueError:
                    pause = 2.0 * (attempt + 1)
                time.sleep(min(pause, 30))
            else:
                time.sleep(2 ** attempt)
        except Exception:
            time.sleep(2 ** attempt)
    return None


def _credit_name(rg: dict) -> str:
    parts = []
    for c in rg.get("artist-credit", []) or []:
        parts.append(c.get("name") or (c.get("artist") or {}).get("name", ""))
        parts.append(c.get("joinphrase") or "")
    return "".join(parts).strip()


def _first_artist(rg: dict) -> tuple[str | None, str]:
    for c in rg.get("artist-credit", []) or []:
        a = c.get("artist") or {}
        if a.get("id"):
            return a["id"], a.get("name", "")
    return None, ""


# ------------------------------------------------------------------- scoring

def score_rgs(rgs: list[dict], t_vars: list[str], a_vars: list[str]) -> list[dict]:
    """Score release groups against all title/artist variants.

    Returns candidates sorted best-first. The sort key is the confidence
    plus small uncapped bonuses (Album > EP > other, then MusicBrainz's own
    relevance) so that e.g. Bowie's "★" Album beats the "★" Single even when
    both hit similarity 1.0.
    """
    out = []
    for rg in rgs:
        rg_title = rg.get("title", "")
        rg_artist = _credit_name(rg)
        t_sim = max((sim(tv, rg_title) for tv in t_vars), default=0.0)
        a_sim = max((sim(av, rg_artist) for av in a_vars), default=0.0)
        conf = 0.55 * t_sim + 0.45 * a_sim
        ptype = rg.get("primary-type") or ""
        sort_key = conf + {"Album": 0.03, "EP": 0.015}.get(ptype, 0.0)
        sort_key += 0.0003 * float(rg.get("score", 0))
        aid, aname = _first_artist(rg)
        out.append({
            "_sort": sort_key,
            "release_group_mbid": rg.get("id"),
            "mb_title": rg_title,
            "mb_artist": rg_artist,
            "mb_artist_primary": aname,
            "artist_mbid": aid,
            "mb_primary_type": ptype,
            "mb_secondary_types": ",".join(rg.get("secondary-types") or []),
            "mb_first_release": rg.get("first-release-date", ""),
            "title_sim": round(t_sim, 3),
            "artist_sim": round(a_sim, 3),
            "confidence": round(conf, 3),
        })
    out.sort(key=lambda c: c["_sort"], reverse=True)
    return out


def match_row(title: str, artist: str) -> dict:
    """Match one row. Returns a result dict with status matched / review /
    not_found, the best candidate's fields inline, and up to three ranked
    candidates for human review when the match wasn't confident."""
    t_vars = variants(title)
    a_vars = variants(artist)

    queries = [f"releasegroup:{_lucene_quote(t_vars[0])} AND artist:{_lucene_quote(a_vars[0])}"]
    for tv in t_vars[1:3]:
        queries.append(f"releasegroup:{_lucene_quote(tv)} AND artist:{_lucene_quote(a_vars[0])}")
    queries.append(f"{t_vars[0]} {a_vars[0]}")

    pool: dict[str, dict] = {}
    for q in queries:
        data = mb_search(q)
        if data:
            for cand in score_rgs(data.get("release-groups", []), t_vars, a_vars):
                cur = pool.get(cand["release_group_mbid"])
                if cur is None or cand["_sort"] > cur["_sort"]:
                    pool[cand["release_group_mbid"]] = cand
        best = max(pool.values(), key=lambda c: c["_sort"], default=None)
        if best and best["title_sim"] >= 0.87 and best["artist_sim"] >= 0.75:
            break

    ranked = sorted(pool.values(), key=lambda c: c["_sort"], reverse=True)
    if not ranked:
        return {"status": "not_found", "candidates": []}

    best = dict(ranked[0])
    best.pop("_sort", None)
    if best["title_sim"] >= 0.85 and best["artist_sim"] >= 0.7 and best["confidence"] >= 0.8:
        best["status"] = "matched"
        best["candidates"] = []
    else:
        best["status"] = "review" if best["confidence"] >= 0.55 else "not_found"
        best["candidates"] = [
            {k: v for k, v in c.items() if k != "_sort"} for c in ranked[:3]
        ]
    return best


def iter_match(rows, artist_col: str, title_col: str):
    """Yield (row, result) for each row; caller drives progress and state."""
    for row in rows:
        result = match_row(row[title_col], row[artist_col])
        yield row, result
