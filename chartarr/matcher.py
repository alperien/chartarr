"""match artist/title pairs to musicbrainz release groups."""
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


def norm(s: str) -> str:
    """comparison form: casefolded, no diacritics, no punctuation."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.casefold().replace("&", " and ")
    s = "".join(c if c.isalnum() else " " for c in s)
    return re.sub(r"\s+", " ", s).strip()


def sim(a: str, b: str) -> float:
    """similarity in [0, 1]."""
    na, nb = norm(a), norm(b)
    if na and nb:
        return SequenceMatcher(None, na, nb).ratio()
    # symbol-only strings ("★") normalize to nothing; compare them raw
    ra = re.sub(r"\s+", "", a.casefold())
    rb = re.sub(r"\s+", "", b.casefold())
    if not ra or not rb:
        return 0.0
    return SequenceMatcher(None, ra, rb).ratio()


def variants(s: str) -> list[str]:
    """alternate forms: the whole string, each line, bracket contents."""
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


def _lucene_quote(s: str) -> str:
    return '"' + s.replace("\\", r"\\").replace('"', r"\"") + '"'


def mb_search(query: str, limit: int = 25, dismax: bool = False) -> dict | None:
    """release-group search, paced and with retry.

    limit=25: one request costs the same at any limit, and 8 cut the right
    release group off noisy queries. dismax=true switches mb to its lenient
    edismax parser, which escapes lucene metacharacters itself.
    """
    params = {"query": query, "fmt": "json", "limit": limit}
    if dismax:
        params["dismax"] = "true"
    url = "https://musicbrainz.org/ws/2/release-group/?" + urllib.parse.urlencode(params)
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
                # honor the server's backoff beyond the old 30s clamp; the
                # cap only guards against a pathological Retry-After header
                time.sleep(min(pause, 600))
            else:
                time.sleep(2 ** attempt)
        except Exception:
            time.sleep(2 ** attempt)
    return None


def _rg_aliases(mbid: str) -> list[dict]:
    """aliases for one release group, paced like mb_search.

    search results never include aliases (verified live: even a doc found by
    an alias: query comes back without them), so confirming that a candidate
    is really "also titled X" costs one lookup. failure degrades gracefully:
    the candidate just keeps its title-only score.
    """
    url = (f"https://musicbrainz.org/ws/2/release-group/{mbid}?"
           + urllib.parse.urlencode({"fmt": "json", "inc": "aliases"}))
    for attempt in range(3):
        wait = _last_request[0] + MIN_SPACING - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_request[0] = time.monotonic()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8")).get("aliases") or []
        except Exception:
            time.sleep(2 ** attempt)
    return []


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


# live albums, compilations, demos etc. are primary-type Album too, so the
# Album bump used to hand them wins over the studio album sharing the same
# title ("Ziggy Stardust" the 1993 comp+live rg vs the 1972 album; the four
# same-titled "Fleetwood Mac" rgs). each secondary type costs clearly more
# than the Album bump (0.03) so a clean studio album always outranks a
# same-titled flavoured one; ties otherwise favour the fewest secondary
# types. the penalty lives in the sort key ONLY — confidence/title_sim are
# untouched, so a legitimately live/soundtrack chart entry that wins its row
# anyway ("The Last Waltz", "Purple Rain") still clears the auto-match gate.
_SECONDARY_PENALTY = 0.05
# when the csv title itself names the flavour ("Live at the Apollo",
# "Greatest Hits"), the row is asking for that secondary type, so demoting
# it would fight the user; the penalty then drops to a residual that only
# breaks exact ties toward a clean release group.
_SECONDARY_WAIVED = 0.002
_SECONDARY_HINTS = {  # normalized phrases that mark a title as wanting the type
    "Live": ("live", "unplugged", "concert"),
    "Compilation": ("greatest hits", "best of", "anthology", "collection",
                    "compilation", "singles", "hits"),
    "Soundtrack": ("soundtrack", "ost", "original motion picture", "music from"),
    "Demo": ("demo", "demos"),
    "Remix": ("remix", "remixes", "remixed"),
    "Mixtape/Street": ("mixtape",),
    "DJ-mix": ("dj mix", "mixed by"),
    "Interview": ("interview",),
    "Spokenword": ("spoken word",),
    "Audiobook": ("audiobook",),
}


def _hinted_types(t_vars: list[str]) -> set[str]:
    """secondary types the csv title itself asks for (word-bounded match)."""
    text = " " + " ".join(norm(tv) for tv in t_vars) + " "
    return {stype for stype, words in _SECONDARY_HINTS.items()
            if any(f" {w} " in text for w in words)}


def score_rgs(rgs: list[dict], t_vars: list[str], a_vars: list[str]) -> list[dict]:
    """score release groups against the variants, best first."""
    out = []
    hinted = _hinted_types(t_vars)
    for rg in rgs:
        rg_title = rg.get("title", "")
        rg_artist = _credit_name(rg)
        # aliases count as titles: mb files bowie's Blackstar under "★" with
        # "Blackstar" only an alias. search docs omit aliases, but docs
        # enriched via _rg_aliases (and test fixtures) carry them.
        titles = [rg_title] + [a.get("name", "") for a in rg.get("aliases") or []]
        t_sim = max((sim(tv, t) for tv in t_vars for t in titles if t), default=0.0)
        a_sim = max((sim(av, rg_artist) for av in a_vars), default=0.0)
        conf = 0.55 * t_sim + 0.45 * a_sim
        ptype = rg.get("primary-type") or ""
        # albums beat singles on ties (bowie has both, titled ★)
        sort_key = conf + {"Album": 0.03, "EP": 0.015}.get(ptype, 0.0)
        sort_key += 0.0003 * float(rg.get("score", 0))
        for stype in rg.get("secondary-types") or []:
            sort_key -= _SECONDARY_WAIVED if stype in hinted else _SECONDARY_PENALTY
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
    """look up one row; returns status, best fields, review candidates."""
    t_vars = variants(title)
    a_vars = variants(artist)

    q_artist = _lucene_quote(a_vars[0])
    # status:official on the fielded rungs sheds bootleg-only release groups
    # (radiohead queries surface "Computer K.O."-style bootlegs). the
    # unfielded fallback stays unfiltered, so a chart entry whose only mb
    # release is unofficial can still resolve as a last resort.
    queries = [(f"releasegroup:{_lucene_quote(t_vars[0])} AND artist:{q_artist}"
                " AND status:official", False)]
    for tv in t_vars[1:3]:
        queries.append((f"releasegroup:{_lucene_quote(tv)} AND artist:{q_artist}"
                        " AND status:official", False))
    # some titles exist only as aliases: mb titles bowie's Blackstar "★", so
    # releasegroup:"Blackstar" alone can never find it
    alias_q = f"alias:{_lucene_quote(t_vars[0])} AND artist:{q_artist} AND status:official"
    queries.append((alias_q, False))
    # unquoted fallback: dismax=true makes mb escape lucene metacharacters
    # itself ("Godspeed You! Black Emperor" would otherwise inject a NOT),
    # chosen over hand-escaping because an escaped-but-unfielded query would
    # still search only the releasegroup title field, where the artist terms
    # constrain nothing; dismax searches mb's preset fields instead.
    queries.append((f"{t_vars[0]} {a_vars[0]}", True))

    pool: dict[str, dict] = {}
    raw: dict[str, dict] = {}   # raw docs, kept so candidates can be rescored
    alias_hits: list[str] = []  # ids mb matched via alias:, in response order
    ran_alias_q = False

    def absorb(data: dict, from_alias: bool = False) -> None:
        rgs = data.get("release-groups", [])
        for doc in rgs:
            if doc.get("id"):
                raw.setdefault(doc["id"], doc)
                if from_alias and doc["id"] not in alias_hits:
                    alias_hits.append(doc["id"])
        for cand in score_rgs(rgs, t_vars, a_vars):
            cur = pool.get(cand["release_group_mbid"])
            if cur is None or cand["_sort"] > cur["_sort"]:
                pool[cand["release_group_mbid"]] = cand

    for q, dismax in queries:
        data = mb_search(q, dismax=dismax)
        if q == alias_q:
            ran_alias_q = True
        if data:
            absorb(data, from_alias=q == alias_q)
        best = max(pool.values(), key=lambda c: c["_sort"], default=None)
        if best and best["title_sim"] >= 0.87 and best["artist_sim"] >= 0.75:
            break

    # alias pass: when the winner is either unproven (fails the auto-match
    # gates) or a flavoured release group the row did not ask for, spend a
    # few lookups confirming aliases for candidates an alias could still
    # save — right artist, unproven title. this is what lets "Blackstar"
    # auto-match ★ instead of stalling on "Blackstar Radio Edits".
    hinted = _hinted_types(t_vars)

    def _unwaived(c: dict) -> bool:
        types = [t for t in c["mb_secondary_types"].split(",") if t]
        return any(t not in hinted for t in types)

    best = max(pool.values(), key=lambda c: c["_sort"], default=None)
    if best is not None and (
            _unwaived(best) or best["title_sim"] < 0.85
            or best["artist_sim"] < 0.7 or best["confidence"] < 0.8):
        if not ran_alias_q:  # the early break can skip the alias rung
            data = mb_search(alias_q)
            if data:
                absorb(data, from_alias=True)
        eligible = [c for c in sorted(pool.values(), key=lambda c: c["_sort"], reverse=True)
                    if c["artist_sim"] >= 0.7 and c["title_sim"] < 0.87]
        # alias-rung hits first: mb already asserted their alias matches
        eligible.sort(key=lambda c: c["release_group_mbid"] not in alias_hits)
        for cand in eligible[:4]:
            doc = raw.get(cand["release_group_mbid"])
            if doc is None or doc.get("aliases"):
                continue
            doc["aliases"] = _rg_aliases(cand["release_group_mbid"])
            if not doc["aliases"]:
                continue
            rescored = score_rgs([doc], t_vars, a_vars)[0]
            if rescored["_sort"] > cand["_sort"]:
                pool[cand["release_group_mbid"]] = rescored

    ranked = sorted(pool.values(), key=lambda c: c["_sort"], reverse=True)
    if not ranked:
        return {"status": "not_found", "candidates": []}

    best = dict(ranked[0])
    best.pop("_sort", None)
    # a flavoured release group the row never asked for is a question, not an
    # answer, however well it scores: "David Bowie — Ziggy Stardust" matches a
    # live single titled exactly that, and no sort key can lift the studio
    # album above it when mb files that album under a different title. ask.
    if best["title_sim"] >= 0.85 and best["artist_sim"] >= 0.7 \
            and best["confidence"] >= 0.8 and not _unwaived(best):
        best["status"] = "matched"
        best["candidates"] = []
    else:
        best["status"] = "review" if best["confidence"] >= 0.55 else "not_found"
        best["candidates"] = [
            {k: v for k, v in c.items() if k != "_sort"} for c in ranked[:3]
        ]
    return best


def iter_match(rows, artist_col: str, title_col: str):
    """yield (row, result) per row."""
    for row in rows:
        result = match_row(row[title_col], row[artist_col])
        yield row, result
