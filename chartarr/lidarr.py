"""small lidarr api client.

adding an artist makes lidarr quietly create rows for their whole
discography, unmonitored. re-adding one of those albums 409s, so
add_album finds the existing row and flips it to monitored instead.

monitoring an album is not enough to get the files: lidarr only fetches
when something asks it to search. that is the AlbumSearch command, which
search_albums sends once the push is done. add-time searching is not
used, because lidarr drops it when the artist is added unmonitored
(lidarr#5012) -- the same race unmonitored_among/monitor_albums exist to
clean up after.
"""
from __future__ import annotations

import time
import urllib.parse

import requests

BATCH = 100


class LidarrError(Exception):
    """an error worth showing the user.

    carries the http status and body when there was one, so callers can
    tell a conflict from a real failure without catching raw requests
    exceptions.
    """

    def __init__(self, message: str, status_code: int = 0, body: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


def _safe_url(url: str) -> str:
    """the url without any user:password@ part, for error messages."""
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return url
    if not parts.hostname:
        return url
    host = parts.hostname
    if parts.port:
        host = f"{host}:{parts.port}"
    return urllib.parse.urlunsplit(
        (parts.scheme, host, parts.path, parts.query, parts.fragment))


def _chunks(seq: list, size: int):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


class Lidarr:
    def __init__(self, url: str, api_key: str):
        self.base = url.rstrip("/")
        self.s = requests.Session()
        self.s.headers["X-Api-Key"] = api_key

    def _call(self, path: str, method: str = "GET", **kw):
        """one api call. every failure leaves here as a LidarrError.

        callers that want to react to a specific status catch
        LidarrError and read .status_code; nothing raw escapes, so a
        single flaky album cannot take down a whole run.
        """
        where = _safe_url(self.base)
        try:
            r = self.s.request(method, f"{self.base}/api/v1/{path}", timeout=60, **kw)
        except requests.ConnectionError as e:
            raise LidarrError(
                f"Can't reach Lidarr at {where} — is it running, and is the "
                f"URL right? (the address you use in your browser)") from e
        except requests.Timeout as e:
            raise LidarrError(f"Lidarr at {where} timed out.") from e
        except requests.RequestException as e:
            raise LidarrError(f"Lidarr request to {where} failed: {e}") from e
        if r.status_code == 401:
            raise LidarrError(
                "Lidarr rejected the API key (401). Copy it from "
                "Settings → General → Security → API Key.", status_code=401)
        if r.status_code >= 400:
            body = (r.text or "")[:200].strip()
            raise LidarrError(
                f"Lidarr returned HTTP {r.status_code}" + (f": {body}" if body else ""),
                status_code=r.status_code, body=r.text or "")
        try:
            return r.json() if r.text else None
        except ValueError as e:
            raise LidarrError(
                f"Lidarr sent something that isn't JSON (HTTP {r.status_code}). "
                f"Is {where} really Lidarr, and not a proxy or login page?") from e

    def status(self) -> dict:
        return self._call("system/status")

    def quality_profiles(self) -> list[dict]:
        return self._call("qualityprofile")

    def metadata_profiles(self) -> list[dict]:
        return self._call("metadataprofile")

    def root_folders(self) -> list[dict]:
        return self._call("rootfolder")

    def all_albums(self) -> list[dict]:
        return self._call("album") or []

    def find_album(self, rgid: str) -> dict | None:
        # filtered client-side; the query param varies across lidarr versions
        try:
            albums = self._call("album", params={"foreignAlbumId": rgid}) or []
        except LidarrError:
            return None
        for a in albums:
            if a.get("foreignAlbumId") == rgid:
                return a
        return None

    def set_monitored(self, album: dict) -> None:
        try:
            self._call("album/monitor", method="PUT",
                       json={"albumIds": [album["id"]], "monitored": True})
        except LidarrError:
            # older lidarr versions want the whole album resource instead
            album = dict(album, monitored=True)
            self._call(f"album/{album['id']}", method="PUT", json=album)

    def lookup(self, rgid: str) -> dict | None:
        results = self._call("album/lookup", params={"term": f"lidarr:{rgid}"})
        return results[0] if results else None

    def _row_id(self, created, rgid: str):
        """the new row's id, from the post response or a follow-up lookup.

        the id is only needed in order to search later, so not finding it
        is not worth losing a successful add over.
        """
        if isinstance(created, dict) and created.get("id"):
            return created["id"]
        found = self.find_album(rgid)  # returns None on error
        return found.get("id") if found else None

    def add_album(self, rgid: str, quality_profile_id: int,
                  metadata_profile_id: int, root_folder: str) -> tuple:
        """add one release group.

        returns (outcome, album_id). outcome is added, monitored or
        skipped; album_id is lidarr's row id, or None when lidarr did not
        report one and a follow-up lookup could not find it.
        """
        existing = self.find_album(rgid)
        if existing is not None:
            if existing.get("monitored"):
                return "skipped", existing.get("id")
            self.set_monitored(existing)
            return "monitored", existing.get("id")

        album = self.lookup(rgid)
        if album is None:
            raise LidarrError("MusicBrainz ID not found by Lidarr's lookup")
        artist = album["artist"]
        artist.update({
            "qualityProfileId": quality_profile_id,
            "metadataProfileId": metadata_profile_id,
            "rootFolderPath": root_folder,
            "monitored": True,
            "addOptions": {"monitor": "none", "searchForMissingAlbums": False},
        })
        album["artist"] = artist
        album["monitored"] = True
        # searching happens later, via the AlbumSearch command
        album["addOptions"] = {"searchForNewAlbum": False}
        try:
            created = self._call("album", method="POST", json=album)
        except LidarrError as e:
            body = (e.body or "")[:300]
            conflict = (e.status_code == 409 or "UNIQUE constraint" in body
                        or (e.status_code == 400 and "exist" in body.lower()))
            if not conflict:
                raise
            # the row appeared mid-run (artist side effect); monitor it
            found = self.find_album(rgid)
            if found is None:
                raise LidarrError(
                    f"Lidarr says this album already exists but won't return it "
                    f"({body})", status_code=e.status_code, body=e.body) from e
            if found.get("monitored"):
                return "skipped", found.get("id")
            self.set_monitored(found)
            return "monitored", found.get("id")
        time.sleep(0.2)  # be gentle
        return "added", self._row_id(created, rgid)

    def unmonitored_among(self, album_ids: list) -> list:
        """which of these rows lidarr currently has unmonitored.

        lidarr's post-add handler can unmonitor an album moments after it
        was added with the artist left unmonitored (lidarr#5012), which
        would leave it out of any search. one library read is cheaper than
        a status call per album.
        """
        wanted = {i for i in album_ids if i is not None}
        if not wanted:
            return []
        return [a["id"] for a in self.all_albums()
                if a.get("id") in wanted and not a.get("monitored")]

    def monitor_albums(self, album_ids: list) -> None:
        """flip these rows to monitored, in batches."""
        ids = [i for i in album_ids if i is not None]
        for chunk in _chunks(ids, BATCH):
            try:
                self._call("album/monitor", method="PUT",
                           json={"albumIds": chunk, "monitored": True})
            except LidarrError:
                for album_id in chunk:
                    try:
                        self.set_monitored({"id": album_id})
                    except LidarrError:
                        pass  # best effort; the search still gets queued

    def search_albums(self, album_ids: list) -> tuple:
        """queue an AlbumSearch for these rows.

        this is what actually starts downloads: lidarr searches its
        indexers and grabs what it finds. returns (queued, errors) so a
        batch that fails partway is visible rather than silent.
        """
        ids = [i for i in album_ids if i is not None]
        if not ids:
            return 0, []
        queued, errors = 0, []
        for chunk in _chunks(ids, BATCH):
            try:
                self._call("command", method="POST",
                           json={"name": "AlbumSearch", "albumIds": chunk})
                queued += len(chunk)
            except LidarrError as e:
                errors.append(str(e))
        return queued, errors
