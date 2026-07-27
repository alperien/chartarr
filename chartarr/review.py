"""review screen: a list of uncertain matches, enter accepts the best guess."""
from __future__ import annotations

import os

from .screen import _fit, _put, _run, accent_pair, available, curses


def run(items, artist_col, title_col, on_decision):
    """show (row, result) pairs in a list; decisions go to on_decision.

    arrow keys move, enter accepts the suggested match, 1-3 pick another
    candidate, s skips, u undoes a decision, a accepts every remaining
    suggestion, q finishes. picking again on a decided row replaces the
    earlier decision.
    """
    if not items:
        return
    if curses is None:
        print("the review screen needs curses (on windows: pip install windows-curses)")
        return
    if not available():
        print(f"this terminal can't draw the review screen "
              f"(TERM={os.environ.get('TERM', '')!r}) — rerun in a working "
              f"terminal, or use --yes to push just the confident matches")
        return
    _run(_loop, items, artist_col, title_col, on_decision)


def _loop(scr, items, artist_col, title_col, on_decision):
    curses.curs_set(0)
    accent = accent_pair()
    dim = curses.A_DIM

    decisions = {}
    pos = 0
    top = 0

    def decide(i, decision):
        key = items[i][1]["key"]
        if decision.get("action") == "clear":
            decisions.pop(key, None)
        else:
            decisions[key] = decision
        on_decision(key, decision)

    def accept_best(i):
        cands = items[i][1].get("candidates") or []
        if not cands:
            return False
        decide(i, {"action": "accept", "mbid": cands[0]["release_group_mbid"],
                   "artist_mbid": cands[0].get("artist_mbid")})
        return True

    while True:
        h, w = scr.getmaxyx()
        list_h = max(3, h - 8)
        if pos < top:
            top = pos
        if pos >= top + list_h:
            top = pos - list_h + 1

        scr.erase()

        undecided = sum(1 for _, res in items if res["key"] not in decisions)
        head = (f"review — {undecided} to decide" if undecided
                else "review — all decided, q to continue")
        tail = f"{len(items) - undecided} decided"
        _put(scr, 0, 1, _fit(head, w - 2), accent)
        if len(head) + len(tail) + 6 < w:
            _put(scr, 0, w - len(tail) - 2, tail, dim)

        for line, i in enumerate(range(top, min(top + list_h, len(items)))):
            row, res = items[i]
            d = decisions.get(res["key"])
            state = "·" if d is None else ("ok" if d["action"] == "accept" else "skip")
            mark = ">" if i == pos else " "
            name = f"{row[artist_col]} — {row[title_col]}"
            _put(scr, 2 + line, 1, _fit(f"{mark} {name}", w - 8),
                 accent if i == pos else 0)
            _put(scr, 2 + line, w - 6, state, dim if d is None else 0)

        # candidates for the selected row
        row, res = items[pos]
        cands = (res.get("candidates") or [])[:3]
        d = decisions.get(res["key"])
        dy = h - 5
        if not cands:
            _put(scr, dy, 3, "nothing found on musicbrainz — s to skip", dim)
        for ci, c in enumerate(cands, 1):
            chosen = (d and d.get("action") == "accept"
                      and d.get("mbid") == c["release_group_mbid"])
            year = (c.get("mb_first_release") or "")[:4]
            ptype = (c.get("mb_primary_type") or "?").lower()
            tag = f"  {ptype} {year}".rstrip()
            line = f"{'*' if chosen else ' '}{ci} {c['mb_artist']} — {c['mb_title']}"
            _put(scr, dy + ci - 1, 3, _fit(line, w - 6 - len(tag)) + tag,
                 accent if chosen else (0 if d else dim if ci > 1 else 0))

        # two spaces between hints, not three: with u undo added, the wider
        # spacing ran to 79 cells and lost "q done" off an 80-column terminal
        _put(scr, h - 1, 1,
             _fit("arrows move  enter accept  1-3 pick  s skip  u undo  "
                  "a accept all  q done", w - 2), dim)
        scr.refresh()

        k = scr.getch()
        if k in (curses.KEY_DOWN, ord("j")):
            pos = min(pos + 1, len(items) - 1)
        elif k in (curses.KEY_UP, ord("k")):
            pos = max(pos - 1, 0)
        elif k in (curses.KEY_ENTER, 10, 13):
            if accept_best(pos):
                pos = min(pos + 1, len(items) - 1)
        elif ord("1") <= k <= ord("3"):
            ci = k - ord("1")
            if ci < len(cands):
                decide(pos, {"action": "accept",
                             "mbid": cands[ci]["release_group_mbid"],
                             "artist_mbid": cands[ci].get("artist_mbid")})
                pos = min(pos + 1, len(items) - 1)
        elif k == ord("s"):
            decide(pos, {"action": "skip"})
            pos = min(pos + 1, len(items) - 1)
        elif k == ord("u"):
            # undecide: the state log already understands a clear record,
            # but nothing could emit one, so a mistyped skip was permanent
            if items[pos][1]["key"] in decisions:
                decide(pos, {"action": "clear"})
        elif k == ord("a"):
            for i, (_, res_i) in enumerate(items):
                if res_i["key"] not in decisions and not accept_best(i):
                    decide(i, {"action": "skip"})
        elif k == ord("q"):
            return
