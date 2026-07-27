"""terminal degradation and display-width fitting."""
import io
import os
import subprocess
import sys
import unicodedata
from pathlib import Path

import pytest

from chartarr import cli, review, screen
from chartarr.screen import _fit, cells

REPO = Path(__file__).resolve().parents[1]

FISHMANS = "98.12.28 男達の別れ"          # the demo's dual-script title


def _old_fit(s, width):
    """the code-point version _fit replaced, kept for parity checks."""
    s = str(s).replace("\n", " / ")
    if width < 2:
        return ""
    return s if len(s) <= width else s[: width - 1] + "…"


def _run_probe(code, term):
    proc = subprocess.run(
        [sys.executable, "-c", code], env={**os.environ, "TERM": term},
        cwd=str(REPO), timeout=30,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return proc.returncode == 0


def _terminfo_has(term):
    # a SUCCESSFUL curses.setupterm is cached process-wide by cpython
    # (initialised_setupterm), after which every later call succeeds no
    # matter what TERM says, so positive probes must run in a fresh
    # process, or they poison the TERM=unknown tests below. failures are
    # not cached, so the negative tests are safe in-process.
    return _run_probe(
        "import curses, sys\n"
        "try:\n curses.setupterm(fd=2)\n"
        "except curses.error:\n sys.exit(3)", term)


# display width

def test_cells_ascii_matches_len():
    for s in ("", "a", "Fleetwood Mac — Rumours", "q stop (progress is saved)"):
        assert cells(s) == len(s)


def test_cells_counts_cjk_as_two():
    # the audit's confirmed numbers: len 14 / 19 cells, len 25 / 30 cells
    assert (len(FISHMANS), cells(FISHMANS)) == (14, 19)
    both = f"Fishmans — {FISHMANS}"
    assert (len(both), cells(both)) == (25, 30)
    assert cells("男達の別れ") == 10


def test_cells_symbols_from_the_sample_chart_are_single():
    # ambiguous-width symbols the example csv actually contains
    assert cells("★") == 1
    assert cells("F♯A♯∞") == 5
    assert cells("…") == 1
    assert cells("█") == 1  # the progress bar glyph


def test_cells_combining_marks_are_free():
    composed = "Ágætis byrjun"
    decomposed = unicodedata.normalize("NFD", composed)
    assert len(decomposed) == len(composed) + 1
    assert cells(composed) == 13
    assert cells(decomposed) == 13


# fitting

def test_fit_matches_old_behavior_for_ascii():
    for s in ("Fleetwood Mac — Rumours", "abc", ""):
        for w in range(0, 30):
            assert _fit(s, w) == _old_fit(s, w)


def test_fit_truncates_by_cells_not_code_points():
    # review.py fits the name to w-8 and writes the status at w-6; the old
    # fit left this title 29 cells long in a 26-cell slot, over the status
    fitted = _fit(f"> Fishmans — {FISHMANS}", 26)
    assert cells(fitted) <= 26
    assert fitted.endswith("…")
    old = _old_fit(f"> Fishmans — {FISHMANS}", 26)
    assert cells(old) > 26  # the bug this replaces


def test_fit_never_overflows_at_any_width():
    probes = [
        f"Fishmans — {FISHMANS}",
        "男達の別れ" * 4,
        unicodedata.normalize("NFD", "Ágætis byrjun — Sigur Rós"),
        "★ [Blackstar] — F♯A♯∞",
    ]
    for s in probes:
        for w in range(2, 41):
            assert cells(_fit(s, w)) <= w, (s, w)


def test_fit_exact_fit_is_untouched():
    assert _fit(FISHMANS, 19) == FISHMANS
    assert _fit(FISHMANS, 18) != FISHMANS


def test_fit_keeps_a_combining_mark_on_the_cut_edge():
    s = "Ábcdef"  # decomposed Á
    fitted = _fit(s, 4)
    assert fitted == "Ábc…"
    assert cells(fitted) == 4


def test_fit_narrow_and_newlines():
    assert _fit("anything", 1) == ""
    assert _fit("a\nb", 10) == "a / b"


# degradation seams

@pytest.mark.skipif(os.name != "posix",
                    reason="windows-curses doesn't consult TERM/terminfo")
def test_available_is_false_when_term_is_broken(monkeypatch):
    if screen.curses is None:
        pytest.skip("no curses at all")
    monkeypatch.setenv("TERM", "unknown")
    assert screen.available() is False


def test_available_is_true_on_a_normal_term():
    if not _terminfo_has("xterm"):
        pytest.skip("no xterm terminfo on this box")
    # fresh process for the same setupterm-caching reason as _terminfo_has
    assert _run_probe(
        "from chartarr import screen; import sys\n"
        "sys.exit(0 if screen.available() else 3)", "xterm")


def test_available_is_false_without_curses(monkeypatch):
    monkeypatch.setattr(screen, "curses", None)
    assert screen.available() is False


def test_run_survives_a_broken_locale(monkeypatch):
    # LC_ALL=xx_YY.utf8 (classic ssh-forwarded locale) used to kill _run
    import locale

    def boom(category, loc=None):
        raise locale.Error("unsupported locale setting")

    monkeypatch.setattr(locale, "setlocale", boom)
    monkeypatch.setattr(screen.curses, "wrapper", lambda func, *a: func("scr", *a))
    assert screen._run(lambda scr, x: (scr, x), 7) == ("scr", 7)


def test_review_run_with_no_items_is_a_noop():
    # used to hit items[pos] -> IndexError before the first draw
    assert review.run([], "artist", "title", lambda k, d: None) is None


@pytest.mark.skipif(os.name != "posix",
                    reason="windows-curses ignores TERM, so it would open a real console")
def test_review_run_degrades_when_the_terminal_is_unusable(monkeypatch, capsys):
    if screen.curses is None:
        pytest.skip("no curses at all")
    monkeypatch.setenv("TERM", "unknown")
    items = [({"artist": "Fishmans", "title": FISHMANS},
              {"key": "1", "status": "review", "candidates": []})]
    decisions = []
    review.run(items, "artist", "title", lambda k, d: decisions.append(k))
    out = capsys.readouterr().out
    assert "TERM" in out and "--yes" in out
    assert decisions == []  # nothing decided, nothing crashed


def test_status_line_never_overflows_the_terminal(monkeypatch):
    class FakeTty(io.StringIO):
        def isatty(self):
            return True

    out = FakeTty()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setenv("COLUMNS", "24")
    monkeypatch.setenv("LINES", "24")
    cli.status(f"  3/10  ok 100%  Fishmans — {FISHMANS}")
    written = out.getvalue().lstrip("\r")
    # fitted and padded to exactly one row of cells, so the \r redraw
    # never wraps; the old len()-based padding overflowed on cjk labels
    assert cells(written) == 23


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="needs a pty")
def test_screen_ok_on_a_real_pty_follows_term():
    cases = [("unknown", "False")]
    if _terminfo_has("xterm"):
        cases.append(("xterm", "True"))
    code = ("import sys\nfrom chartarr import cli\n"
            "sys.stderr.write(str(cli._screen_ok()))")
    for term, expected in cases:
        master, slave = os.openpty()
        try:
            proc = subprocess.run(
                [sys.executable, "-c", code], stdin=slave, stdout=slave,
                stderr=subprocess.PIPE, env={**os.environ, "TERM": term},
                cwd=str(REPO), timeout=30)
        finally:
            os.close(master)
            os.close(slave)
        assert proc.stderr.decode() == expected, term


# accent colour

def test_cherry_brightens_on_a_256_colour_dark_terminal(monkeypatch):
    monkeypatch.setattr(screen.curses, "COLORS", 256, raising=False)
    monkeypatch.delenv("COLORFGBG", raising=False)
    assert screen._cherry() == screen.CHERRY_BRIGHT_256


def test_cherry_settles_on_a_light_background(monkeypatch):
    # the bright shade is thinner on white; 161 reads better there
    monkeypatch.setattr(screen.curses, "COLORS", 256, raising=False)
    monkeypatch.setenv("COLORFGBG", "0;15")
    assert screen._cherry() == screen.CHERRY_256


def test_cherry_falls_back_to_red_without_256_colours(monkeypatch):
    monkeypatch.setattr(screen.curses, "COLORS", 8, raising=False)
    assert screen._cherry() == screen.curses.COLOR_RED


def test_dark_background_reads_colorfgbg(monkeypatch):
    for value, dark in [("15;0", True), ("0;15", False), ("7;0", True),
                        ("", True), ("nonsense", True)]:
        if value:
            monkeypatch.setenv("COLORFGBG", value)
        else:
            monkeypatch.delenv("COLORFGBG", raising=False)
        assert screen._dark_background() is dark, value


def test_accent_pair_is_zero_without_colour(monkeypatch):
    monkeypatch.setattr(screen.curses, "has_colors", lambda: False)
    assert screen.accent_pair() == 0
