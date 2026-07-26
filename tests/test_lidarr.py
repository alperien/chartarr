"""the lidarr client: album ids out of add_album, monitoring, searching."""
import pytest
import requests

from chartarr import lidarr


class FakeResponse:
    def __init__(self, status_code=200, text="", payload=None):
        self.status_code = status_code
        self.text = text
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}", response=self)


class FakeLidarr(lidarr.Lidarr):
    """a Lidarr whose _call is a scripted lookup instead of a socket."""

    def __init__(self, handler):
        self.base = "http://lidarr.test"
        self.handler = handler
        self.calls = []

    def _call(self, path, method="GET", **kw):
        self.calls.append((method, path, kw))
        return self.handler(method, path, kw)


def _album(album_id, rgid="rg-1", monitored=False):
    return {"id": album_id, "foreignAlbumId": rgid, "monitored": monitored}


def _lookup_payload(rgid="rg-1"):
    return {"foreignAlbumId": rgid, "artist": {"id": 9}, "monitored": False}


# add_album returns an id on every path


def test_add_album_returns_id_for_a_new_album(monkeypatch):
    monkeypatch.setattr(lidarr.time, "sleep", lambda *_: None)

    def handler(method, path, kw):
        if path == "album" and method == "GET":
            return []
        if path == "album/lookup":
            return [_lookup_payload()]
        if path == "album" and method == "POST":
            return {"id": 41, "foreignAlbumId": "rg-1", "monitored": True}
        raise AssertionError(path)

    api = FakeLidarr(handler)
    assert api.add_album("rg-1", 1, 1, "/music") == ("added", 41)


def test_add_album_falls_back_to_lookup_when_post_returns_no_id(monkeypatch):
    """some lidarr versions answer the post with a thinner body."""
    monkeypatch.setattr(lidarr.time, "sleep", lambda *_: None)
    state = {"created": False}

    def handler(method, path, kw):
        if path == "album" and method == "GET":
            return [_album(77, monitored=True)] if state["created"] else []
        if path == "album/lookup":
            return [_lookup_payload()]
        if path == "album" and method == "POST":
            state["created"] = True
            return None
        raise AssertionError(path)

    api = FakeLidarr(handler)
    assert api.add_album("rg-1", 1, 1, "/music") == ("added", 77)


def test_add_album_returns_id_when_flipping_an_existing_row():
    def handler(method, path, kw):
        if path == "album" and method == "GET":
            return [_album(12, monitored=False)]
        if path == "album/monitor":
            return None
        raise AssertionError(path)

    api = FakeLidarr(handler)
    assert api.add_album("rg-1", 1, 1, "/music") == ("monitored", 12)


def test_add_album_returns_id_when_already_monitored():
    def handler(method, path, kw):
        if path == "album" and method == "GET":
            return [_album(5, monitored=True)]
        raise AssertionError(path)

    api = FakeLidarr(handler)
    assert api.add_album("rg-1", 1, 1, "/music") == ("skipped", 5)


def test_add_album_recovers_the_id_after_a_conflict(monkeypatch):
    monkeypatch.setattr(lidarr.time, "sleep", lambda *_: None)
    seen = {"get": 0}

    def handler(method, path, kw):
        if path == "album" and method == "GET":
            seen["get"] += 1
            return [] if seen["get"] == 1 else [_album(88, monitored=False)]
        if path == "album/lookup":
            return [_lookup_payload()]
        if path == "album" and method == "POST":
            raise requests.HTTPError(
                "409", response=FakeResponse(409, "already exists"))
        if path == "album/monitor":
            return None
        raise AssertionError(path)

    api = FakeLidarr(handler)
    assert api.add_album("rg-1", 1, 1, "/music") == ("monitored", 88)


def test_add_album_no_longer_asks_lidarr_to_search_at_add_time(monkeypatch):
    """search happens later, via the command endpoint (lidarr#5012)."""
    monkeypatch.setattr(lidarr.time, "sleep", lambda *_: None)
    posted = {}

    def handler(method, path, kw):
        if path == "album" and method == "GET":
            return []
        if path == "album/lookup":
            return [_lookup_payload()]
        if path == "album" and method == "POST":
            posted.update(kw["json"])
            return {"id": 1}
        raise AssertionError(path)

    FakeLidarr(handler).add_album("rg-1", 1, 1, "/music")
    assert posted["addOptions"] == {"searchForNewAlbum": False}


# the lidarr#5012 monitoring race


def test_unmonitored_among_finds_rows_lidarr_dropped():
    def handler(method, path, kw):
        if path == "album" and method == "GET":
            return [_album(1, monitored=True), _album(2, monitored=False),
                    _album(3, monitored=False)]
        raise AssertionError(path)

    api = FakeLidarr(handler)
    assert api.unmonitored_among([1, 2, 3]) == [2, 3]


def test_unmonitored_among_ignores_rows_we_did_not_touch():
    def handler(method, path, kw):
        return [_album(1, monitored=False), _album(99, monitored=False)]

    assert FakeLidarr(handler).unmonitored_among([1]) == [1]


def test_unmonitored_among_skips_the_call_for_an_empty_list():
    api = FakeLidarr(lambda *a: pytest.fail("should not call the api"))
    assert api.unmonitored_among([]) == []
    assert api.unmonitored_among([None]) == []


def test_monitor_albums_batches_and_drops_blanks():
    api = FakeLidarr(lambda method, path, kw: None)
    api.monitor_albums(list(range(1, 251)) + [None])
    monitor = [c for c in api.calls if c[1] == "album/monitor"]
    assert [len(c[2]["json"]["albumIds"]) for c in monitor] == [100, 100, 50]
    assert all(c[2]["json"]["monitored"] is True for c in monitor)


# searching


def test_search_albums_sends_the_album_search_command():
    api = FakeLidarr(lambda method, path, kw: None)
    queued, errors = api.search_albums([7, 8])
    assert (queued, errors) == (2, [])
    method, path, kw = api.calls[0]
    assert (method, path) == ("POST", "command")
    assert kw["json"] == {"name": "AlbumSearch", "albumIds": [7, 8]}


def test_search_albums_batches_at_a_hundred():
    api = FakeLidarr(lambda method, path, kw: None)
    queued, errors = api.search_albums(list(range(250)))
    assert (queued, errors) == (250, [])
    assert [len(c[2]["json"]["albumIds"]) for c in api.calls] == [100, 100, 50]


def test_search_albums_does_nothing_for_an_empty_list():
    api = FakeLidarr(lambda *a: pytest.fail("should not call the api"))
    assert api.search_albums([]) == (0, [])
    assert api.search_albums([None]) == (0, [])


def test_search_albums_reports_a_partial_failure():
    """one bad batch must not look like a clean run."""
    seen = {"n": 0}

    def handler(method, path, kw):
        seen["n"] += 1
        if seen["n"] == 2:
            raise requests.HTTPError(
                "500", response=FakeResponse(500, "indexer exploded"))
        return None

    queued, errors = FakeLidarr(handler).search_albums(list(range(250)))
    assert queued == 150
    assert len(errors) == 1
    assert "500" in errors[0]


def test_search_albums_surfaces_a_lidarr_error_message():
    def handler(method, path, kw):
        raise lidarr.LidarrError("Lidarr timed out.")

    queued, errors = FakeLidarr(handler).search_albums([1])
    assert queued == 0
    assert errors == ["Lidarr timed out."]
