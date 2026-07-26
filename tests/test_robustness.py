"""the audit fixes: no raw exceptions, no poisoned state, no silent drops."""
import argparse
import json

import pytest
import requests

from chartarr import cli, lidarr, matcher


def _args(**over):
    base = {"dry_run": False, "search": True, "no_search": False,
            "quality_profile": None, "metadata_profile": None,
            "root_folder": None}
    base.update(over)
    return argparse.Namespace(**base)


class Response:
    """the bits of requests.Response that _call touches."""

    def __init__(self, status_code=200, text="", payload=None):
        self.status_code = status_code
        self.text = text
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class Session:
    def __init__(self, responder):
        self.headers = {}
        self.responder = responder

    def request(self, method, url, **kw):
        return self.responder(method, url, kw)


def _api(responder):
    api = lidarr.Lidarr("http://lidarr.test", "key")
    api.s = Session(responder)
    return api


# 1. nothing raw escapes the client


@pytest.mark.parametrize("code", [400, 403, 404, 409, 500, 502, 503])
def test_every_http_error_becomes_a_lidarr_error(code):
    api = _api(lambda *a: Response(code, f"boom {code}"))
    with pytest.raises(lidarr.LidarrError) as got:
        api.status()
    assert got.value.status_code == code
    assert str(code) in str(got.value)


@pytest.mark.parametrize("exc", [
    requests.ConnectionError("refused"),
    requests.Timeout("slow"),
    requests.TooManyRedirects("loop"),
    requests.RequestException("odd"),
])
def test_every_requests_failure_becomes_a_lidarr_error(exc):
    def responder(*a):
        raise exc

    with pytest.raises(lidarr.LidarrError):
        _api(responder).status()


def test_html_instead_of_json_is_a_readable_error():
    """a reverse proxy login page should not look like a parse crash."""
    api = _api(lambda *a: Response(200, "<html>sign in</html>"))
    with pytest.raises(lidarr.LidarrError) as got:
        api.status()
    assert "isn't JSON" in str(got.value)


def test_a_lookup_failure_does_not_escape_add_album():
    """the bug: a 500 on album/lookup used to kill the whole push."""
    def responder(method, url, kw):
        if "album/lookup" in url:
            return Response(500, "server error")
        return Response(200, "[]", payload=[])

    with pytest.raises(lidarr.LidarrError):
        _api(responder).add_album("rg-1", 1, 2, "/music")


def test_one_bad_album_does_not_abort_the_push(monkeypatch, capsys):
    """the push must report the failure and carry on to the rest."""
    class Api:
        def status(self):
            return {"version": "2.14"}

        def quality_profiles(self):
            return [{"id": 1, "name": "flac"}]

        def metadata_profiles(self):
            return [{"id": 2, "name": "std"}]

        def root_folders(self):
            return [{"id": 3, "path": "/music"}]

        def add_album(self, rgid, q, m, r):
            n = int(rgid.split("-")[1])
            if n == 2:
                raise lidarr.LidarrError("Lidarr returned HTTP 500",
                                         status_code=500)
            return ("added", 100 + n)

        def unmonitored_among(self, ids):
            return []

        def monitor_albums(self, ids):
            pass

        def search_albums(self, ids):
            self.searched = list(ids)
            return len(ids), []

    api = Api()
    monkeypatch.setattr(cli.lidarr, "Lidarr", lambda u, k: api)
    monkeypatch.setattr(cli, "_screen_ok", lambda: False)
    items = [{"key": str(i), "rgid": f"rg-{i}",
              "row": {"artist": f"a{i}", "title": f"t{i}"}} for i in range(1, 6)]
    cli.stage_push(items, "artist", "title", _args(),
                   {"lidarr_url": "http://x", "api_key": "k"})
    out = capsys.readouterr().out
    assert "failed 1" in out
    assert api.searched == [101, 103, 104, 105]  # the other four still went


# 2. a musicbrainz outage is not a "not found"


def test_unreachable_musicbrainz_raises_rather_than_returning_none(monkeypatch):
    monkeypatch.setattr(matcher.time, "sleep", lambda *_: None)

    def boom(*a, **k):
        raise OSError("dns is down")

    monkeypatch.setattr(matcher.urllib.request, "urlopen", boom)
    with pytest.raises(matcher.Unreachable):
        matcher.mb_search("anything")


def test_match_row_reports_unreachable_not_not_found(monkeypatch):
    def boom(*a, **k):
        raise matcher.Unreachable("dns is down")

    monkeypatch.setattr(matcher, "mb_search", boom)
    result = matcher.match_row("OK Computer", "Radiohead")
    assert result["status"] == "unreachable"


def test_a_bad_query_is_still_a_real_answer(monkeypatch):
    """a 400 means musicbrainz understood and rejected it; don't retry forever."""
    monkeypatch.setattr(matcher.time, "sleep", lambda *_: None)
    calls = {"n": 0}

    def urlopen(*a, **k):
        calls["n"] += 1
        raise matcher.urllib.error.HTTPError("u", 400, "bad", {}, None)

    monkeypatch.setattr(matcher.urllib.request, "urlopen", urlopen)
    assert matcher.mb_search("bad:query") is None
    assert calls["n"] == 1


def test_unreachable_rows_are_retried_on_the_next_run(monkeypatch, tmp_path,
                                                      capsys):
    """the bug: a network blip used to be recorded as a permanent miss."""
    sp = tmp_path / "s.jsonl"
    state = cli.State(sp)
    state.add_result("1", {"status": "unreachable", "candidates": []})
    state.add_result("2", {"status": "matched", "release_group_mbid": "rg-2"})
    rows = [{"_key": "1", "artist": "A", "title": "T"},
            {"_key": "2", "artist": "B", "title": "U"}]

    seen = []

    def fake_iter(pending, a, t):
        for row in pending:
            seen.append(row["_key"])
            yield row, {"status": "matched", "release_group_mbid": "rg-1"}

    monkeypatch.setattr(cli.matcher, "iter_match", fake_iter)
    monkeypatch.setattr(cli, "_screen_ok", lambda: False)
    cli.stage_match(rows, "artist", "title", cli.State(sp))
    assert seen == ["1"]          # the unreachable row, not the matched one
    assert "retrying 1 row" in capsys.readouterr().out


def test_matched_rows_are_still_not_rematched(monkeypatch, tmp_path):
    sp = tmp_path / "s.jsonl"
    state = cli.State(sp)
    for key, st in (("1", "matched"), ("2", "review"), ("3", "not_found")):
        state.add_result(key, {"status": st, "release_group_mbid": "rg"})
    rows = [{"_key": k, "artist": "A", "title": "T"} for k in ("1", "2", "3")]
    monkeypatch.setattr(cli, "_screen_ok", lambda: False)
    seen = []
    monkeypatch.setattr(cli.matcher, "iter_match",
                        lambda p, a, t: [(r, {}) for r in p if seen.append(r)])
    cli.stage_match(rows, "artist", "title", cli.State(sp))
    assert seen == []


# 3. duplicate csv keys


def test_tied_rank_values_do_not_drop_rows(tmp_path):
    """the bug: both rows keyed '1', so one silently vanished."""
    p = tmp_path / "c.csv"
    p.write_text("rank,artist,title\n1,Radiohead,OK Computer\n"
                 "1,Slint,Spiderland\n1,Swans,Soundtracks\n", encoding="utf-8")
    rows, artist, title = cli.load_csv(p)
    keys = [r["_key"] for r in rows]
    assert len(set(keys)) == 3, keys
    assert keys[0] == "1"  # first keeps the bare rank, for old state files


def test_unique_ranks_are_left_alone(tmp_path):
    p = tmp_path / "c.csv"
    p.write_text("rank,artist,title\n1,A,T\n2,B,U\n", encoding="utf-8")
    rows, _, _ = cli.load_csv(p)
    assert [r["_key"] for r in rows] == ["1", "2"]


def test_blank_rank_falls_back_to_the_row_number(tmp_path):
    p = tmp_path / "c.csv"
    p.write_text("rank,artist,title\n,A,T\n2,B,U\n", encoding="utf-8")
    rows, _, _ = cli.load_csv(p)
    assert [r["_key"] for r in rows] == ["row1", "2"]


def test_every_tied_row_survives_the_whole_pipeline(tmp_path):
    p = tmp_path / "c.csv"
    p.write_text("rank,artist,title\n1,A,T\n1,B,U\n", encoding="utf-8")
    rows, _, _ = cli.load_csv(p)
    state = cli.State(tmp_path / "s.jsonl")
    for r in rows:
        state.add_result(r["_key"], {"status": "matched",
                                     "release_group_mbid": "rg-" + r["artist"]})
    items = cli.import_set(rows, state)
    assert sorted(i["rgid"] for i in items) == ["rg-A", "rg-B"]


# 4 and 6. import_set honours decisions and tolerates missing ids


def test_a_skip_is_respected_even_on_a_matched_row(tmp_path):
    """the bug: matched rows ignored decisions and got pushed anyway."""
    state = cli.State(tmp_path / "s.jsonl")
    state.add_result("1", {"status": "matched", "release_group_mbid": "rg-1"})
    state.add_decision("1", {"action": "skip"})
    rows = [{"_key": "1", "artist": "A", "title": "T"}]
    assert cli.import_set(rows, state) == []


def test_a_re_pick_overrides_the_automatic_match(tmp_path):
    state = cli.State(tmp_path / "s.jsonl")
    state.add_result("1", {"status": "matched", "release_group_mbid": "rg-old"})
    state.add_decision("1", {"action": "accept", "mbid": "rg-new"})
    rows = [{"_key": "1", "artist": "A", "title": "T"}]
    assert [i["rgid"] for i in cli.import_set(rows, state)] == ["rg-new"]


def test_a_matched_row_without_an_mbid_is_skipped_not_a_crash(tmp_path):
    """the bug: KeyError on an old or hand-edited state file."""
    state = cli.State(tmp_path / "s.jsonl")
    state.add_result("1", {"status": "matched"})  # no release_group_mbid
    rows = [{"_key": "1", "artist": "A", "title": "T"}]
    assert cli.import_set(rows, state) == []


def test_normal_matched_rows_still_get_pushed(tmp_path):
    state = cli.State(tmp_path / "s.jsonl")
    state.add_result("1", {"status": "matched", "release_group_mbid": "rg-1"})
    state.add_result("2", {"status": "review", "candidates": []})
    state.add_decision("2", {"action": "accept", "mbid": "rg-2"})
    rows = [{"_key": "1", "artist": "A", "title": "T"},
            {"_key": "2", "artist": "B", "title": "U"}]
    assert sorted(i["rgid"] for i in cli.import_set(rows, state)) == ["rg-1", "rg-2"]


# 7. credentials stay out of messages


def test_url_credentials_are_scrubbed_from_errors():
    api = lidarr.Lidarr("http://bob:hunter2@lidarr.test:8686", "SECRET_KEY")

    def responder(*a):
        raise requests.ConnectionError("refused")

    api.s = Session(responder)
    with pytest.raises(lidarr.LidarrError) as got:
        api.status()
    msg = str(got.value)
    assert "hunter2" not in msg
    assert "bob" not in msg
    assert "SECRET_KEY" not in msg
    assert "lidarr.test:8686" in msg  # still says where it tried


def test_safe_url_keeps_ordinary_urls_intact():
    assert lidarr._safe_url("http://localhost:8686") == "http://localhost:8686"
    assert lidarr._safe_url("https://lidarr.example.com/lidarr") == \
        "https://lidarr.example.com/lidarr"


# 8. match_row hardening


@pytest.mark.parametrize("title,artist", [
    ("", "Radiohead"), ("Kid A", ""), ("", ""), ("   ", "A"), ("\t\n", "\xa0"),
])
def test_match_row_survives_empty_variants(title, artist, monkeypatch):
    """not reachable from load_csv, but callers shouldn't get an IndexError."""
    monkeypatch.setattr(matcher, "mb_search",
                        lambda *a, **k: pytest.fail("should not query"))
    assert matcher.match_row(title, artist)["status"] == "not_found"


# state file integrity


def test_a_torn_final_line_is_skipped(tmp_path):
    sp = tmp_path / "s.jsonl"
    state = cli.State(sp)
    state.add_result("1", {"status": "matched", "release_group_mbid": "rg-1"})
    with sp.open("a", encoding="utf-8") as f:
        f.write('{"key":"2","status":"mat')
    assert list(cli.State(sp).results) == ["1"]


def test_old_state_files_still_load(tmp_path):
    """written before this change: no unreachable status, bare rank keys."""
    sp = tmp_path / "s.jsonl"
    sp.write_text(
        json.dumps({"key": "1", "status": "matched",
                    "release_group_mbid": "rg-1"}) + "\n"
        + json.dumps({"key": "2", "status": "review", "candidates": []}) + "\n"
        + json.dumps({"type": "decision", "key": "2",
                      "decision": {"action": "accept", "mbid": "rg-2"}}) + "\n",
        encoding="utf-8")
    state = cli.State(sp)
    assert state.results["1"]["release_group_mbid"] == "rg-1"
    assert state.decisions["2"]["mbid"] == "rg-2"
    rows = [{"_key": "1", "artist": "A", "title": "T"},
            {"_key": "2", "artist": "B", "title": "U"}]
    assert len(cli.import_set(rows, state)) == 2
