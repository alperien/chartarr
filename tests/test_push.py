"""the push stage: which album ids get collected, and whether we search."""
import argparse

import pytest

from chartarr import cli, lidarr


def _args(**over):
    base = {"dry_run": False, "search": False, "no_search": False,
            "quality_profile": None, "metadata_profile": None,
            "root_folder": None}
    base.update(over)
    return argparse.Namespace(**base)


class FakeApi:
    """stands in for chartarr.lidarr.Lidarr inside stage_push."""

    def __init__(self, outcomes, unmonitored=None):
        self.outcomes = list(outcomes)
        self._unmonitored = unmonitored or []
        self.searched = []
        self.monitored = []
        self.checked = []

    def status(self):
        return {"version": "2.0"}

    def quality_profiles(self):
        return [{"id": 1, "name": "flac"}]

    def metadata_profiles(self):
        return [{"id": 2, "name": "standard"}]

    def root_folders(self):
        return [{"id": 3, "path": "/music"}]

    def add_album(self, rgid, qp, mp, rf):
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def unmonitored_among(self, ids):
        self.checked.append(list(ids))
        return list(self._unmonitored)

    def monitor_albums(self, ids):
        self.monitored.extend(ids)

    def search_albums(self, ids):
        self.searched.extend(ids)
        return len(ids), []


@pytest.fixture
def items():
    def make(n):
        return [{"key": str(i), "rgid": f"rg-{i}",
                 "row": {"artist": f"artist {i}", "title": f"album {i}"}}
                for i in range(1, n + 1)]
    return make


@pytest.fixture
def push(monkeypatch, items):
    """run stage_push against a FakeApi with no terminal available."""
    def run(outcomes, args=None, unmonitored=None, screen_ok=False):
        api = FakeApi(outcomes, unmonitored)
        monkeypatch.setattr(cli.lidarr, "Lidarr", lambda url, key: api)
        monkeypatch.setattr(cli, "_screen_ok", lambda: screen_ok)
        cli.stage_push(items(len(outcomes)), "artist", "title",
                       args or _args(search=True),
                       {"lidarr_url": "http://x", "api_key": "k"})
        return api
    return run


# which ids reach the search


def test_added_and_monitored_albums_are_searched(push):
    api = push([("added", 1), ("monitored", 2)])
    assert api.searched == [1, 2]


def test_already_monitored_albums_are_not_searched(push):
    """re-running a push must not re-grab what was already handled."""
    api = push([("added", 1), ("skipped", 2), ("added", 3)])
    assert api.searched == [1, 3]


def test_failed_albums_are_not_searched(push):
    api = push([("added", 1), lidarr.LidarrError("nope"), ("added", 3)])
    assert api.searched == [1, 3]


def test_albums_without_an_id_are_not_searched(push):
    """no id means nothing to point the command at."""
    api = push([("added", None), ("added", 4)])
    assert api.searched == [4]


def test_nothing_to_search_means_no_command(push):
    api = push([("skipped", 1), ("skipped", 2)])
    assert api.searched == []


# the lidarr#5012 recheck


def test_albums_lidarr_unmonitored_are_restored_before_searching(push):
    api = push([("added", 1), ("added", 2)], unmonitored=[2])
    assert api.monitored == [2]
    assert api.searched == [1, 2]


def test_the_recheck_only_covers_albums_this_run_touched(push):
    api = push([("added", 1), ("skipped", 9)])
    assert api.checked == [[1]]


def test_a_failed_recheck_does_not_stop_the_search(push, monkeypatch, capsys):
    api = FakeApi([("added", 1)])

    def boom(ids):
        raise lidarr.LidarrError("lidarr went away")

    api.unmonitored_among = boom
    monkeypatch.setattr(cli.lidarr, "Lidarr", lambda url, key: api)
    monkeypatch.setattr(cli, "_screen_ok", lambda: False)
    cli.stage_push([{"key": "1", "rgid": "rg-1",
                     "row": {"artist": "a", "title": "t"}}],
                   "artist", "title", _args(search=True),
                   {"lidarr_url": "http://x", "api_key": "k"})
    assert api.searched == [1]
    assert "could not verify monitoring" in capsys.readouterr().out


# the search decision


def test_search_flag_searches_without_asking(monkeypatch):
    monkeypatch.setattr(cli, "_screen_ok", lambda: True)
    monkeypatch.setattr(cli.screen, "confirm_screen",
                        lambda *a, **k: pytest.fail("should not ask"))
    assert cli.want_search(3, _args(search=True)) is True


def test_no_search_flag_never_searches(monkeypatch):
    monkeypatch.setattr(cli, "_screen_ok", lambda: True)
    monkeypatch.setattr(cli.screen, "confirm_screen",
                        lambda *a, **k: pytest.fail("should not ask"))
    assert cli.want_search(3, _args(no_search=True)) is False


def test_a_terminal_gets_asked(monkeypatch):
    asked = {}

    def confirm(title, lines, question, hint=""):
        asked["question"] = question
        return True

    monkeypatch.setattr(cli, "_screen_ok", lambda: True)
    monkeypatch.setattr(cli.screen, "confirm_screen", confirm)
    assert cli.want_search(42, _args()) is True
    assert "42 albums" in asked["question"]


def test_declining_the_prompt_skips_the_search(monkeypatch):
    monkeypatch.setattr(cli, "_screen_ok", lambda: True)
    monkeypatch.setattr(cli.screen, "confirm_screen", lambda *a, **k: False)
    api = FakeApi([])
    cli.stage_search(api, [1, 2], _args())
    assert api.searched == []


def test_a_piped_run_does_not_search_on_its_own(monkeypatch, capsys):
    """nobody to ask, so don't fire indexer queries unasked."""
    monkeypatch.setattr(cli, "_screen_ok", lambda: False)
    assert cli.want_search(5, _args()) is False
    assert "--search" in capsys.readouterr().out


# dry run


def test_dry_run_touches_nothing(monkeypatch, items, capsys):
    def no_client(*a, **k):
        pytest.fail("dry run must not build a client")

    monkeypatch.setattr(cli.lidarr, "Lidarr", no_client)
    monkeypatch.setattr(cli, "_screen_ok", lambda: False)
    cli.stage_push(items(3), "artist", "title", _args(dry_run=True), {})
    out = capsys.readouterr().out
    assert "would push 3 albums" in out
    assert "would then offer to search for up to 3 albums" in out


def test_dry_run_with_no_search_is_quiet_about_it(monkeypatch, items, capsys):
    monkeypatch.setattr(cli, "_screen_ok", lambda: False)
    cli.stage_push(items(2), "artist", "title",
                   _args(dry_run=True, no_search=True), {})
    assert "search" not in capsys.readouterr().out


# flags


def test_search_and_no_search_are_mutually_exclusive():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["c.csv", "--search", "--no-search"])


def test_search_flags_parse():
    p = cli.build_parser()
    assert p.parse_args(["c.csv", "--search"]).search is True
    assert p.parse_args(["c.csv", "--no-search"]).no_search is True
    plain = p.parse_args(["c.csv"])
    assert (plain.search, plain.no_search) == (False, False)
