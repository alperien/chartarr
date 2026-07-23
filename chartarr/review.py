"""fullscreen review of uncertain matches."""
from __future__ import annotations

import webbrowser

try:
    import curses
except ImportError:  # native windows python
    curses = None


def run(items, artist_col, title_col, on_decision):
    """browse (row, result) pairs; report picks via on_decision(key, decision).

    keys: up/down or j/k move, 1-3 pick a candidate, s skip, u undo,
    o open musicbrainz, q save and quit.
    """
    if curses is None:
        print("the review screen needs curses (on windows: pip install windows-curses)")
        return
    import locale

    locale.setlocale(locale.LC_ALL, "")
    curses.wrapper(_loop, items, artist_col, title_col, on_decision)


def _fit(s, width):
    s = str(s).replace("\n", " / ")
    if width < 2:
        return ""
    return s if len(s) <= width else s[: width - 1] + "…"


def _put(scr, y, x, s, attr=0):
    try:
        scr.addstr(y, x, s, attr)
    except curses.error:
        pass


def _loop(scr, items, artist_col, title_col, on_decision):
    curses.curs_set(0)
    accent = 0
    if curses.has_colors():
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_CYAN, -1)
        accent = curses.color_pair(1)
    dim = curses.A_DIM

    decisions = {}
    pos = 0
    while True:
        row, result = items[pos]
        rkey = result["key"]
        cands = result.get("candidates") or []
        d = decisions.get(rkey)
        h, w = scr.getmaxyx()
        scr.erase()

        picked = sum(1 for x in decisions.values() if x["action"] == "accept")
        skipped = sum(1 for x in decisions.values() if x["action"] == "skip")
        head = f"review {pos + 1}/{len(items)}"
        tail = f"{picked} picked, {skipped} skipped"
        _put(scr, 0, 1, _fit(head, w - 2), accent)
        if len(head) + len(tail) + 6 < w:
            _put(scr, 0, w - len(tail) - 2, tail, dim)

        y = 2
        _put(scr, y, 3, _fit(f"{row[artist_col]} — {row[title_col]}", w - 6))
        y += 1
        date = (row.get("release_date") or "").strip()
        if date:
            _put(scr, y, 3, _fit(date, w - 6), dim)
            y += 1
        y += 1

        if not cands:
            _put(scr, y, 3, "nothing found on musicbrainz — s to skip", dim)
            y += 1
        for i, c in enumerate(cands, 1):
            chosen = (d and d.get("action") == "accept"
                      and d.get("mbid") == c["release_group_mbid"])
            mark = "*" if chosen else " "
            types = (c.get("mb_primary_type") or "?").lower()
            if c.get("mb_secondary_types"):
                types += "/" + c["mb_secondary_types"].lower()
            year = (c.get("mb_first_release") or "")[:4]
            _put(scr, y, 3, _fit(f"{mark} {i}  {c['mb_artist']} — {c['mb_title']}", w - 6),
                 accent if chosen else 0)
            y += 1
            if y < h - 2:
                _put(scr, y, 8, _fit(f"{types}  {year}", w - 11), dim)
                y += 1
        if d and d["action"] == "skip":
            _put(scr, y + 1, 3, "skipped", dim)

        _put(scr, h - 1, 1,
             _fit("up/down move   1-3 pick   s skip   u undo   o browser   q done", w - 2),
             dim)
        scr.refresh()

        k = scr.getch()
        if k in (curses.KEY_DOWN, ord("j")):
            pos = min(pos + 1, len(items) - 1)
        elif k in (curses.KEY_UP, ord("k")):
            pos = max(pos - 1, 0)
        elif ord("1") <= k <= ord("3") and k - ord("1") < len(cands):
            c = cands[k - ord("1")]
            d = {"action": "accept", "mbid": c["release_group_mbid"],
                 "artist_mbid": c.get("artist_mbid")}
            decisions[rkey] = d
            on_decision(rkey, d)
            pos = min(pos + 1, len(items) - 1)
        elif k == ord("s"):
            d = {"action": "skip"}
            decisions[rkey] = d
            on_decision(rkey, d)
            pos = min(pos + 1, len(items) - 1)
        elif k == ord("u"):
            if rkey in decisions:
                decisions.pop(rkey)
                on_decision(rkey, {"action": "clear"})
        elif k == ord("o"):
            target = d["mbid"] if d and d.get("action") == "accept" else (
                cands[0]["release_group_mbid"] if cands else None)
            if target:
                webbrowser.open(f"https://musicbrainz.org/release-group/{target}")
        elif k == ord("q"):
            return
