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

import requests

BATCH = 100


class LidarrError(Exception):
    """an error worth showing the user."""


def _chunks(seq: list, size: int):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def _reason(e: Exception) -> str:
    """a short, readable cause for a failed call."""
    resp = getattr(e, "response", None)
    if resp is not None:
        body = (resp.text or "")[:200].strip()
        return f"HTTP {resp.status_code}" + (f": {body}" if body else "")
    return str(e)


class Lidarr:
    def __init__(self, url: str, api_key: str):
        self.base = url.rstrip("/")
        self.s = requests.Session()
        self.s.headers["X-Api-Key"] = api_key

    def _call(self, path: str, method: str = "GET", **kw):
        try:
            r = self.s.request(method, f"{self.base}/api/v1/{path}", timeout=60, **kw)
        except requests.ConnectionError as e:
            raise LidarrError(
                f"Can't reach Lidarr at {self.base} — is it running, and is the "
                f"URL right? (the address you use in your browser)") from e
        except requests.Timeout as e:
            raise LidarrError(f"Lidarr at {self.base} timed out.") from e
        if r.status_code == 401:
            raise LidarrError(
                "Lidarr rejected the API key (401). Copy it from "
                "Settings → General → Security → API Key.")
        r.raise_for_status()
        return r.json() if r.text else None

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
        except (LidarrError, requests.HTTPError):
            return None
        for a in albums:
            if a.get("foreignAlbumId") == rgid:
                return a
        return None

    def set_monitored(self, album: dict) -> None:
        try:
            self._call("album/monitor", method="PUT",
                       json={"albumIds": [album["id"]], "monitored": True})
        except requests.HTTPError:
            album["monitored"] = True
            self._call(f"album/{album['id']}", method="PUT", json=album)

    def lookup(self, rgid: str) -> dict | None:
        results = self._call("album/lookup", params={"term": f"lidarr:{rgid}"})
        return results[0] if results else None

    def _row_id(self, created, rgid: str):
        """the new row's id, from the post response or a follow-up lookup."""
        if isinstance(created, dict) and created.get("id"):
            return created["id"]
        found = self.find_album(rgid)
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
        except requests.HTTPError as e:
            body = e.response.text[:300] if e.response is not None else ""
            code = e.response.status_code if e.response is not None else 0
            conflict = (code == 409 or "UNIQUE constraint" in body
                        or (code == 400 and "exist" in body.lower()))
            if not conflict:
                raise LidarrError(f"HTTP {code}: {body or e}") from e
            # the row appeared mid-run (artist side effect); monitor it
            found = self.find_album(rgid)
            if found is None:
                raise LidarrError(f"conflict but album not found afterwards ({body})") from e
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
            except requests.HTTPError:
                for album_id in chunk:
                    self.set_monitored({"id": album_id})

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
            except (LidarrError, requests.HTTPError) as e:
                errors.append(_reason(e))
        return queued, errors
