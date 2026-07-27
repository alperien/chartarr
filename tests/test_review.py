"""review loop: the keys, and what each one records.

the loop is driven through a fake curses window that replays a scripted
list of keypresses, so every binding is exercised without a terminal.
"""
import pytest

from chartarr import review, screen


class FakeScreen:
    """a curses window that answers from a script instead of a keyboard."""

    def __init__(self, keys, size=(24, 80)):
        self.keys = list(keys)
        self.size = size
        self.nodelay_calls = []
        self.drawn = []

    def getmaxyx(self):
        return self.size

    def erase(self):
        self.drawn.append(None)

    def addstr(self, y, x, s, attr=0):
        self.drawn.append((y, x, s))

    def refresh(self):
        pass

    def nodelay(self, flag):
        self.nodelay_calls.append(flag)

    def getch(self):
        # an exhausted script means the loop ignored q; fail loudly rather
        # than spinning the way the nodelay bug did
        if not self.keys:
            raise AssertionError("loop asked for more input after the script ran out")
        return self.keys.pop(0)

    def text(self):
        return "\n".join(s for d in self.drawn if d for _, _, s in [d])


ENTER = 10
DOWN = 258   # curses.KEY_DOWN
UP = 259     # curses.KEY_UP
Q = ord("q")


def cand(mbid, title="Ziggy Stardust", artist="David Bowie"):
    return {"release_group_mbid": mbid, "mb_artist": artist, "mb_title": title,
            "artist_mbid": f"a-{mbid}", "mb_primary_type": "Album",
            "mb_secondary_types": "", "mb_first_release": "1972-06-16",
            "title_sim": 1.0, "artist_sim": 1.0, "confidence": 1.0}


def item(key, candidates, artist="David Bowie", title="Ziggy Stardust"):
    return ({"artist": artist, "title": title},
            {"key": key, "status": "review" if candidates else "not_found",
             "candidates": candidates})


@pytest.fixture(autouse=True)
def offline_curses(monkeypatch):
    """the loop's terminal calls, neutered — no initscr, no real screen."""
    if review.curses is None:
        pytest.skip("no curses at all")
    monkeypatch.setattr(review.curses, "curs_set", lambda n: None)
    monkeypatch.setattr(review, "accent_pair", lambda: 0)


def drive(items, keys):
    """run the loop over items with keys; returns the decisions it logged."""
    logged = []
    scr = FakeScreen(keys)
    review._loop(scr, items, "artist", "title",
                 lambda k, d: logged.append((k, d)))
    return logged, scr


def test_enter_accepts_the_leading_candidate():
    items = [item("1", [cand("rg-top"), cand("rg-other")])]
    logged, _ = drive(items, [ENTER, Q])
    assert logged == [("1", {"action": "accept", "mbid": "rg-top",
                             "artist_mbid": "a-rg-top"})]


def test_number_keys_pick_the_matching_alternative():
    items = [item("1", [cand("rg-1"), cand("rg-2"), cand("rg-3")])]
    logged, _ = drive(items, [ord("2"), Q])
    assert logged[0][1]["mbid"] == "rg-2"
    logged, _ = drive(items, [ord("3"), Q])
    assert logged[0][1]["mbid"] == "rg-3"


def test_number_key_past_the_candidate_list_does_nothing():
    items = [item("1", [cand("rg-1")])]
    logged, _ = drive(items, [ord("3"), Q])
    assert logged == []


def test_s_skips_the_row():
    items = [item("1", [cand("rg-1")])]
    logged, _ = drive(items, [ord("s"), Q])
    assert logged == [("1", {"action": "skip"})]


def test_enter_on_a_row_with_no_candidates_records_nothing():
    # "nothing found on musicbrainz" rows can only be skipped
    items = [item("1", [])]
    logged, _ = drive(items, [ENTER, Q])
    assert logged == []


def test_a_accepts_every_undecided_row_and_skips_the_hopeless_ones():
    items = [item("1", [cand("rg-1")]), item("2", []), item("3", [cand("rg-3")])]
    logged, _ = drive(items, [ord("a"), Q])
    assert [(k, d["action"]) for k, d in logged] == [
        ("1", "accept"), ("2", "skip"), ("3", "accept")]


def test_a_leaves_an_existing_decision_alone():
    items = [item("1", [cand("rg-1"), cand("rg-2")]), item("2", [cand("rg-9")])]
    # pick candidate 2 on the first row, then accept-all
    logged, _ = drive(items, [ord("2"), ord("a"), Q])
    assert logged[0][1]["mbid"] == "rg-2"
    assert [k for k, _ in logged] == ["1", "2"]  # row 1 not re-decided


def test_choosing_again_replaces_the_earlier_decision():
    items = [item("1", [cand("rg-1"), cand("rg-2")])]
    logged, _ = drive(items, [ord("s"), UP, ord("1"), Q])
    assert [d["action"] for _, d in logged] == ["skip", "accept"]
    assert logged[-1][1]["mbid"] == "rg-1"


def test_u_undoes_a_decision_and_is_a_noop_on_an_undecided_row():
    items = [item("1", [cand("rg-1")])]
    # undo before deciding anything: nothing logged
    logged, _ = drive(items, [ord("u"), Q])
    assert logged == []
    # skip, then undo: the clear reaches the state log
    logged, _ = drive(items, [ord("s"), UP, ord("u"), Q])
    assert [d["action"] for _, d in logged] == ["skip", "clear"]


def test_undone_row_counts_as_undecided_again():
    items = [item("1", [cand("rg-1")])]
    _, scr = drive(items, [ord("s"), UP, ord("u"), Q])
    # the header is redrawn each pass; the last one is after the undo
    assert "review — 1 to decide" in scr.text()


def test_arrows_move_the_cursor_between_rows():
    items = [item("1", [cand("rg-1")]), item("2", [cand("rg-2")])]
    logged, _ = drive(items, [DOWN, ord("s"), Q])
    assert logged == [("2", {"action": "skip"})]
    logged, _ = drive(items, [DOWN, UP, ord("s"), Q])
    assert logged == [("1", {"action": "skip"})]


def test_jk_move_like_the_arrows():
    items = [item("1", [cand("rg-1")]), item("2", [cand("rg-2")])]
    logged, _ = drive(items, [ord("j"), ord("s"), Q])
    assert logged == [("2", {"action": "skip"})]
    logged, _ = drive(items, [ord("j"), ord("k"), ord("s"), Q])
    assert logged == [("1", {"action": "skip"})]


def test_cursor_stops_at_both_ends():
    items = [item("1", [cand("rg-1")]), item("2", [cand("rg-2")])]
    logged, _ = drive(items, [UP, UP, ord("s"), Q])
    assert logged == [("1", {"action": "skip"})]
    logged, _ = drive(items, [DOWN, DOWN, DOWN, ord("s"), Q])
    assert logged == [("2", {"action": "skip"})]


def test_q_returns_immediately():
    items = [item("1", [cand("rg-1")])]
    logged, scr = drive(items, [Q])
    assert logged == []
    assert scr.keys == []


def test_deciding_the_last_row_does_not_walk_off_the_end():
    # every decision advances the cursor; on the final row it must stay put
    items = [item("1", [cand("rg-1")])]
    logged, _ = drive(items, [ENTER, ord("s"), Q])
    assert [d["action"] for _, d in logged] == ["accept", "skip"]


def test_the_footer_advertises_the_keys_it_actually_binds():
    items = [item("1", [cand("rg-1")])]
    _, scr = drive(items, [Q])
    footer = scr.text()
    for hint in ("enter accept", "1-3 pick", "s skip", "u undo",
                 "a accept all", "q done"):
        assert hint in footer


def test_a_narrow_terminal_still_draws_without_raising():
    items = [item("1", [cand("rg-1")], artist="Fishmans",
                  title="98.12.28 男達の別れ")]
    scr = FakeScreen([Q], size=(6, 20))
    review._loop(scr, items, "artist", "title", lambda k, d: None)


# --- the nodelay regression ---

def test_progress_screen_does_not_leave_the_next_session_non_blocking():
    """_run must hand every screen a blocking window.

    _progress needs nodelay(True) to poll for q while it draws. cpython
    keeps that flag on the window and curses.wrapper does not reset it
    between sessions, so it used to carry into the review loop that runs
    next: getch() returned -1 forever and the loop redrew ~17k times a
    second on a pinned core, with no key ever pressed.
    """
    seen = []

    def fake_wrapper(func, *args):
        scr = FakeScreen([Q])
        seen.append(scr)
        return func(scr, *args)

    import unittest.mock as mock
    with mock.patch.object(screen.curses, "wrapper", fake_wrapper):
        screen._run(lambda scr: None)

    assert seen[0].nodelay_calls[0] is False, (
        "_run must reset nodelay before the screen's own code runs")


def test_an_empty_read_costs_a_full_redraw():
    """why the flag matters: -1 does nothing but go round again.

    the loop has no idle branch — a non-blocking getch returns -1, falls
    through every key test, and redraws. that is the spin: on a real
    terminal it ran ~17k times a second until a key arrived.
    """
    items = [item("1", [cand("rg-1")])]
    quiet = FakeScreen([Q])
    review._loop(quiet, items, "artist", "title", lambda k, d: None)
    baseline = len(quiet.drawn)

    spun = FakeScreen([-1, -1, -1, Q])
    logged = []
    review._loop(spun, items, "artist", "title", lambda k, d: logged.append(k))
    assert logged == []                       # three reads, nothing decided
    assert spun.keys == []                    # all four consumed
    assert len(spun.drawn) == baseline * 4    # and a full redraw for each
