"""curses screens: a shared progress view and helpers for the review list."""
from __future__ import annotations

import sys
import time
import unicodedata
from collections import deque

try:
    import curses
except ImportError:  # native windows python without windows-curses
    curses = None


def available() -> bool:
    """curses is importable and can actually drive this terminal type.

    importability alone isn't enough: with TERM unset, or set to something
    terminfo has never heard of (ssh from an exotic emulator, TERM=unknown),
    curses.wrapper dies at setupterm. checking here lets every caller fall
    back to the plain-line output instead of crashing.

    note: cpython caches setupterm's first success process-wide, so this
    answers for the TERM the process started with — which is the one that
    matters. tests that flip TERM must probe in a subprocess.
    """
    if curses is None:
        return False
    try:
        fd = sys.stdout.fileno()
    except (OSError, ValueError, AttributeError):
        fd = 2  # stdout is captured or synthetic; any fd does for terminfo
    try:
        curses.setupterm(fd=fd)
    except curses.error:
        return False
    return True


def _run(func, *args):
    import locale

    # a utf-8 locale makes ncurses draw wide characters correctly, but an
    # LC_ALL this box doesn't know (classic ssh-forwarded locale) must not
    # kill the screen — degrade toward the C locale instead
    try:
        locale.setlocale(locale.LC_ALL, "")
    except locale.Error:
        try:
            locale.setlocale(locale.LC_ALL, "C.UTF-8")
        except locale.Error:
            pass
    return curses.wrapper(func, *args)


def _cell(ch: str) -> int:
    if unicodedata.category(ch) in ("Mn", "Me", "Cf"):
        return 0  # combining marks and format controls draw nothing
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def cells(s: str) -> int:
    """display cells s occupies — the terminal lays out by cell, not code
    point, and cjk take two, so len() undercounts exactly on the
    dual-script charts this tool is for."""
    return sum(_cell(ch) for ch in s)


def _fit(s, width):
    """truncate s to at most width display cells, ellipsis included."""
    s = str(s).replace("\n", " / ")
    if width < 2:
        return ""
    if cells(s) <= width:
        return s
    out: list = []
    used = 0
    for ch in s:
        w = _cell(ch)
        if used + w > width - 1:  # keep one cell for the ellipsis
            break
        out.append(ch)
        used += w
    return "".join(out) + "…"


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
