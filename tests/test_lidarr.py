"""lidarr client tests. responses fakes the http transport, so url building,
headers, query params, bodies and status handling are all real; nothing
touches the network."""
import json

import pytest
import requests
import responses

from chartarr import lidarr
from chartarr.lidarr import Lidarr, LidarrError

BASE = "http://lidarr.test:8686"
API = BASE + "/api/v1"
RGID = "b1392450-e666-3926-a536-22c65f834433"  # OK Computer


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    # add_album sleeps 0.2s per add to be gentle on the server; not on us
    monkeypatch.setattr(lidarr.time, "sleep", lambda _: None)


def api():
    return Lidarr(BASE, "sekrit")


def add(**kw):
    return api().add_album(RGID, 1, 2, "/music", **kw)


def lookup_result():
    # real album/lookup shape (trimmed) from lidarr 3.1.0.4875
    return {"title": "OK Computer", "foreignAlbumId": RGID, "monitored": False,
            "artist": {"artistName": "Radiohead", "id": 0,
                       "foreignArtistId": "a74b1b7f-71a5-4011-9441-d0b5e4122711"}}


def library_row(rgid=RGID, album_id=7, monitored=False):
    return {"id": album_id, "foreignAlbumId": rgid, "title": "OK Computer",
            "monitored": monitored, "artistId": 3}


def stage_lookup():
    """the album isn't in the library yet and lookup can see it."""
    responses.add(responses.GET, API + "/album", json=[])
    responses.add(responses.GET, API + "/album/lookup", json=[lookup_result()])


def posted_album():
    body = next(c.request.body for c in responses.calls
                if c.request.method == "POST")
    return json.loads(body)


DUP_400 = [{"propertyName": "ForeignAlbumId",
            "errorMessage": "This album has already been added.",
            "errorCode": "AlbumExistsValidator"}]


@responses.activate
def test_add_album_posts_profiles_and_returns_added():
    stage_lookup()
    responses.add(responses.POST, API + "/album", json={"id": 42}, status=201)
    assert add() == ("added", 42)
    body = posted_album()
    assert body["monitored"] is True
    assert body["addOptions"] == {"searchForNewAlbum": False}
    artist = body["artist"]
    assert artist["qualityProfileId"] == 1
    assert artist["metadataProfileId"] == 2
    assert artist["rootFolderPath"] == "/music"
    assert artist["monitored"] is True


@responses.activate
def test_add_album_never_sends_monitor_none():
    # the bug this tool shipped with: addOptions.monitor = "none" does not
    # mean "add the artist quietly". lidarr force-unmonitors the artist on
    # that flag, and the post-add scan then unmonitors every album INCLUDING
    # the one just pushed. proven on lidarr 3.1.0.4875: with "none" a fresh
    # add reported "added" and 15s later the artist had 0 of 9 monitored;
    # with monitor="existing" + albumsToMonitor it stays monitored
    # indefinitely. do not "simplify" this payload.
    stage_lookup()
    responses.add(responses.POST, API + "/album", json={"id": 42}, status=201)
    add()
    artist = posted_album()["artist"]
    assert artist["addOptions"]["monitor"] != "none"
    assert artist["addOptions"]["albumsToMonitor"]  # always named, never empty
    assert RGID in artist["addOptions"]["albumsToMonitor"]
    assert artist["monitorNewItems"] == "none"  # future releases stay quiet


@responses.activate
def test_also_monitor_names_every_sibling_once():
    # albums by the same artist must all be named on the first add: the
    # post-add scan unmonitors any sibling that isn't in albumsToMonitor,
    # and the primary rgid must survive even when the caller's list repeats it
    stage_lookup()
    responses.add(responses.POST, API + "/album", json={"id": 42}, status=201)
    add(also_monitor=["rg-kid-a", RGID, "rg-kid-b"])
    monitor = posted_album()["artist"]["addOptions"]["albumsToMonitor"]
    assert monitor == [RGID, "rg-kid-a", "rg-kid-b"]


@responses.activate
def test_search_flag_stays_on_the_album_not_the_artist():
    # --search must ask for this album only, never the whole discography
    stage_lookup()
    responses.add(responses.POST, API + "/album", json={"id": 42}, status=201)
    add(search=True)
    body = posted_album()
    assert body["addOptions"] == {"searchForNewAlbum": True}
    assert body["artist"]["addOptions"]["searchForMissingAlbums"] is False


@responses.activate
def test_monitored_row_is_skipped_without_further_traffic():
    responses.add(responses.GET, API + "/album",
                  json=[library_row(monitored=True)])
    assert add() == ("skipped", 7)
    assert len(responses.calls) == 1  # no lookup, no post


@responses.activate
def test_unmonitored_row_is_flipped_via_album_monitor():
    responses.add(responses.GET, API + "/album", json=[library_row()])
    responses.add(responses.PUT, API + "/album/monitor", json={})
    assert add() == ("monitored", 7)
    flip = json.loads(responses.calls[1].request.body)
    assert flip == {"albumIds": [7], "monitored": True}


@responses.activate
def test_monitor_endpoint_failure_falls_back_to_full_row_put():
    # if album/monitor is refused, the full-row PUT still gets it done
    responses.add(responses.GET, API + "/album", json=[library_row()])
    responses.add(responses.PUT, API + "/album/monitor", body="boom", status=500)
    responses.add(responses.PUT, API + "/album/7", json={})
    assert add() == ("monitored", 7)
    row = json.loads(responses.calls[2].request.body)
    assert row == library_row(monitored=True)


@responses.activate
def test_validator_400_duplicate_flips_the_existing_row():
    # modern lidarr rejects a re-add with a 400 from AlbumExistsValidator
    stage_lookup()
    responses.add(responses.POST, API + "/album", json=DUP_400, status=400)
    responses.add(responses.GET, API + "/album", json=[library_row()])
    responses.add(responses.PUT, API + "/album/monitor", json={})
    assert add() == ("monitored", 7)


@responses.activate
def test_legacy_409_duplicate_flips_the_existing_row():
    # older lidarr lets the insert hit the unique index instead
    stage_lookup()
    responses.add(responses.POST, API + "/album", status=409,
                  body="UNIQUE constraint failed: Albums.ForeignAlbumId")
    responses.add(responses.GET, API + "/album", json=[library_row()])
    responses.add(responses.PUT, API + "/album/monitor", json={})
    assert add() == ("monitored", 7)


@responses.activate
def test_duplicate_row_already_monitored_is_skipped():
    # adding a sibling earlier in the run can create and monitor the row
    stage_lookup()
    responses.add(responses.POST, API + "/album", json=DUP_400, status=400)
    responses.add(responses.GET, API + "/album",
                  json=[library_row(monitored=True)])
    assert add() == ("skipped", 7)


@responses.activate
def test_config_400_is_an_error_not_a_duplicate():
    # the original client sniffed the body for "exist", so "Quality Profile
    # does not exist" — a config mistake — took the duplicate path and died
    # with a baffling "conflict but album not found afterwards". it must
    # surface as the validation error it is.
    stage_lookup()
    responses.add(responses.POST, API + "/album", status=400,
                  json=[{"propertyName": "QualityProfileId",
                         "errorMessage": "Quality Profile does not exist"}])
    with pytest.raises(LidarrError, match="Quality Profile"):
        add()
    assert len(responses.calls) == 3  # find, lookup, post — no duplicate dance


@responses.activate
def test_duplicate_that_wont_come_back_is_reported():
    stage_lookup()
    responses.add(responses.POST, API + "/album", json=DUP_400, status=400)
    responses.add(responses.GET, API + "/album", json=[])
    with pytest.raises(LidarrError, match="already exists"):
        add()


@responses.activate
def test_lookup_miss_blames_the_id_kind():
    # pasting a release id where a release GROUP id belongs is the usual way
    # to get an empty lookup; the error has to say which kind lidarr wants
    responses.add(responses.GET, API + "/album", json=[])
    responses.add(responses.GET, API + "/album/lookup", json=[])
    with pytest.raises(LidarrError, match="release group"):
        add()
    assert RGID in responses.calls[1].request.url  # term=lidarr:<rgid>


@responses.activate
def test_find_album_refilters_what_old_servers_return():
    # old lidarr ignores the foreignAlbumId query param and returns the
    # whole library; only the exact match may come back
    responses.add(responses.GET, API + "/album", json=[
        library_row("someone-else", album_id=1),
        library_row(album_id=7),
        library_row("third-album", album_id=9)])
    assert api().find_album(RGID)["id"] == 7
    assert "foreignAlbumId=" + RGID in responses.calls[0].request.url


@responses.activate
def test_find_album_treats_4xx_as_absent():
    responses.add(responses.GET, API + "/album", body="bad request", status=400)
    assert api().find_album(RGID) is None


@responses.activate
def test_find_album_raises_on_5xx():
    responses.add(responses.GET, API + "/album", body="oops", status=500)
    with pytest.raises(LidarrError):
        api().find_album(RGID)


@responses.activate
def test_search_albums_chunks_by_100_and_loses_nothing():
    responses.add(responses.POST, API + "/command", json={"id": 1}, status=201)
    ids = list(range(250))
    api().search_albums(ids)
    bodies = [json.loads(c.request.body) for c in responses.calls]
    assert [b["name"] for b in bodies] == ["AlbumSearch"] * 3
    assert [len(b["albumIds"]) for b in bodies] == [100, 100, 50]
    assert [i for b in bodies for i in b["albumIds"]] == ids


@responses.activate
def test_wrong_api_key_says_where_to_find_the_right_one():
    responses.add(responses.GET, API + "/system/status",
                  json={"error": "Unauthorized"}, status=401)
    with pytest.raises(LidarrError) as e:
        api().status()
    assert "API key" in str(e.value)
    assert "Settings" in str(e.value)


@responses.activate
def test_connection_refused_becomes_a_lidarr_error():
    responses.add(responses.GET, API + "/system/status",
                  body=requests.ConnectionError("refused"))
    with pytest.raises(LidarrError, match="reach Lidarr"):
        api().status()


@responses.activate
def test_timeout_becomes_a_lidarr_error():
    responses.add(responses.GET, API + "/system/status",
                  body=requests.Timeout("60s"))
    with pytest.raises(LidarrError, match="timed out"):
        api().status()


@responses.activate
def test_url_without_scheme_is_explained():
    # "127.0.0.1:8686" pasted straight from the lidarr ui
    with pytest.raises(LidarrError, match="http://"):
        Lidarr("127.0.0.1:8686", "sekrit").status()


@responses.activate
def test_html_login_page_is_not_mistaken_for_lidarr():
    # a reverse proxy answering 200 with its login page instead of json
    responses.add(responses.GET, API + "/system/status", status=200,
                  body="<html><body>Sign in to continue</body></html>")
    with pytest.raises(LidarrError, match="really Lidarr"):
        api().status()
