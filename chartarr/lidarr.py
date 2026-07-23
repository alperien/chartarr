"""small lidarr api client.

adding an artist makes lidarr quietly create rows for their whole
discography, unmonitored. re-adding one of those albums 409s, so
add_album finds the existing row and flips it to monitored instead.
"""
from __future__ import annotations

import time

import requests


class LidarrError(Exception):
    """an error worth showing the user."""


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

    def add_album(self, rgid: str, quality_profile_id: int,
                  metadata_profile_id: int, root_folder: str,
                  search: bool = False) -> str:
        """add one release group; returns added, monitored or skipped."""
        existing = self.find_album(rgid)
        if existing is not None:
            if existing.get("monitored"):
                return "skipped"
            self.set_monitored(existing)
            return "monitored"

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
        album["addOptions"] = {"searchForNewAlbum": bool(search)}
        try:
            self._call("album", method="POST", json=album)
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
                return "skipped"
            self.set_monitored(found)
            return "monitored"
        time.sleep(0.2)  # be gentle
        return "added"

    def search_albums(self, album_ids: list[int]) -> None:
        for i in range(0, len(album_ids), 100):
            self._call("command", method="POST",
                       json={"name": "AlbumSearch", "albumIds": album_ids[i:i + 100]})
