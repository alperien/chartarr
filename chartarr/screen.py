"""curses screens: a shared progress view and helpers for the review list."""
from __future__ import annotations

import time
from collections import deque

try:
    import curses
except ImportError:  # native windows python without windows-curses
    curses = None


def available() -> bool:
    return curses is not None


def _run(func, *args):
    import locale

    locale.setlocale(locale.LC_ALL, "")
    return curses.wrapper(func, *args)


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


def _accent():
    if curses.has_colors():
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_CYAN, -1)
        return curses.color_pair(1)
    return 0


def _bar(done, total, width):
    if width < 4 or total <= 0:
        return ""
    inner = width - 2
    filled = round(inner * done / total)
    return "[" + "█" * filled + " " * (inner - filled) + "]"


def _eta(start, done, total):
    if done == 0 or done >= total:
        return ""
    left = (time.monotonic() - start) / done * (total - done)
    if left < 90:
        return f"about {max(1, round(left))}s left"
    return f"about {round(left / 60)}m left"


def _progress(scr, title, events, total, counts_line, notable):
    """draw a progress screen while consuming events of (state, label).

    returns True if the user pressed q to stop early.
    """
    curses.curs_set(0)
    accent = _accent()
    dim = curses.A_DIM
    scr.nodelay(True)
    tail = deque(maxlen=64)
    start = time.monotonic()
    done = 0

    def draw():
        h, w = scr.getmaxyx()
        scr.erase()
        _put(scr, 0, 1, _fit(title, w - 20), accent)
        eta = _eta(start, done, total)
        if eta and len(eta) + 4 < w:
            _put(scr, 0, w - len(eta) - 2, eta, dim)
        _put(scr, 2, 1, _fit(_bar(done, total, w - 14) + f" {done}/{total}", w - 2))
        _put(scr, 4, 1, _fit(counts_line(), w - 2))
        rows = max(1, h - 8)
        recent = list(tail)[-rows:]
        for i, (state, label) in enumerate(recent):
            _put(scr, 6 + i, 3, _fit(state, 13), accent if state in notable else dim)
            _put(scr, 6 + i, 17, _fit(label, w - 19))
        _put(scr, h - 1, 1, "q stop (progress is saved)", dim)
        scr.refresh()

    draw()
    for state, label in events:
        done += 1
        tail.append((state, label))
        draw()
        if scr.getch() == ord("q"):
            return True
    draw()
    time.sleep(0.35)
    return False


def match_screen(events, total, base_counts):
    """events yields (label, status). returns (counts, quit_pressed)."""
    counts = dict(base_counts)

    def feed():
        for label, status in events:
            counts[status] = counts.get(status, 0) + 1
            yield {"matched": "ok", "not_found": "no match"}.get(status, status), label

    def line():
        return (f"matched {counts.get('matched', 0)} · "
                f"review {counts.get('review', 0)} · "
                f"not found {counts.get('not_found', 0)}")

    quit_ = _run(_progress, "matching against musicbrainz", feed(), total,
                 line, {"review", "no match"})
    return counts, quit_


def push_screen(events, total):
    """events yields (label, outcome, err). returns (counts, failures, quit_pressed)."""
    counts: dict = {}
    failures: list = []

    def feed():
        for label, outcome, err in events:
            counts[outcome] = counts.get(outcome, 0) + 1
            if err:
                failures.append(f"{label}: {err}")
            yield ("already there" if outcome == "skipped" else outcome), label

    def line():
        s = (f"added {counts.get('added', 0)} · "
             f"monitored {counts.get('monitored', 0)} · "
             f"already there {counts.get('skipped', 0)}")
        if counts.get("failed"):
            s += f" · failed {counts['failed']}"
        return s

    quit_ = _run(_progress, "pushing to lidarr", feed(), total, line,
                 {"monitored", "failed"})
    return counts, failures, quit_
