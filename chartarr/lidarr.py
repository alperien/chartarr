"""small lidarr api client.

adding an album means adding its artist too, and lidarr then fills in the
artist's whole discography in the background. the trick is to tell lidarr
which albums to keep monitored while that happens: addOptions.albumsToMonitor
names them, and everything else in the discography is left unmonitored.

do not be tempted by addOptions.monitor = "none". lidarr force-unmonitors the
artist when it sees that, and the post-add scan then unmonitors every album
including the one just added.
"""
from __future__ import annotations

import json
import time
import urllib.parse

import requests


class LidarrError(Exception):
    """an error worth showing the user."""

    def __init__(self, message: str, status: int = 0, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body


def _safe_url(url: str) -> str:
    """the url with any user:password@ removed, for showing in messages.

    a lidarr url can carry basic-auth credentials: behind a reverse proxy
    that asks for them, http://user:pw@host is how you get through. those
    end up in every connection error otherwise, and errors get pasted into
    bug reports.
    """
    try:
        parts = urllib.parse.urlsplit(url)
        host = parts.hostname
    except ValueError:
        return url
    if not host:
        return url  # nothing parsed as a host; nothing to hide
    if parts.port:
        host = f"{host}:{parts.port}"
    return urllib.parse.urlunsplit(
        (parts.scheme, host, parts.path, parts.query, parts.fragment))


def _is_duplicate(status: int, body: str) -> bool:
    """true if lidarr is saying "this album is already here".

    newer lidarr rejects duplicates with a 400 from AlbumExistsValidator;
    older versions let the insert hit the unique index and return 409.
    the 400 body has to be read properly: several unrelated validation
    failures ("Quality Profile does not exist") also say "exist".
    """
    if status == 409 or "UNIQUE constraint" in body:
        return True
    if status != 400:
        return False
    try:
        failures = json.loads(body)
    except ValueError:
        return False
    if not isinstance(failures, list):
        return False
    for f in failures:
        if not isinstance(f, dict):
            continue
        if (f.get("propertyName") or "").lower() == "foreignalbumid":
            return True
        if f.get("errorCode") == "AlbumExistsValidator":
            return True
        if "already been added" in (f.get("errorMessage") or "").lower():
            return True
    return False


class Lidarr:
    def __init__(self, url: str, api_key: str):
        self.base = url.rstrip("/")
        # what the user sees in errors: the same address minus any
        # credentials, so a pasted traceback doesn't carry a password
        self.shown = _safe_url(self.base)
        self.s = requests.Session()
        self.s.headers["X-Api-Key"] = api_key

    def _scrub(self, text) -> str:
        """text with this instance's url swapped for the credential-free one."""
        out = str(text)
        return out.replace(self.base, self.shown) if self.base != self.shown else out

    def _call(self, path: str, method: str = "GET", **kw):
        url = f"{self.base}/api/v1/{path}"
        try:
            r = self.s.request(method, url, timeout=60, **kw)
        except requests.ConnectionError as e:
            raise LidarrError(
                f"Can't reach Lidarr at {self.shown}; is it running, and is the "
                f"URL right? (the address you use in your browser)") from e
        except requests.Timeout as e:
            raise LidarrError(f"Lidarr at {self.shown} timed out.") from e
        except (requests.exceptions.InvalidSchema,
                requests.exceptions.MissingSchema,
                requests.exceptions.InvalidURL) as e:
            raise LidarrError(
                f"{self.shown} is not a URL Lidarr can be reached at; it needs "
                f"to start with http:// or https://") from e
        except requests.RequestException as e:
            # requests quotes the url it was given, credentials and all
            raise LidarrError(
                f"Lidarr request to {self.shown} failed: {self._scrub(e)}") from e

        if r.status_code == 401:
            raise LidarrError(
                "Lidarr rejected the API key (401). Copy it from "
                "Settings → General → Security → API Key.", status=401)
        if r.status_code >= 400:
            # a proxy's error page can quote the request url back at us
            raise LidarrError(
                f"HTTP {r.status_code}: {self._scrub(r.text)[:300] or 'no details'}",
                status=r.status_code, body=r.text)
        if not r.text:
            return None
        try:
            return r.json()
        except ValueError as e:
            raise LidarrError(
                f"Lidarr returned something that isn't JSON; is {self.shown} "
                f"really Lidarr, and not a login page or another service?") from e

    def status(self) -> dict:
        return self._call("system/status")

    def quality_profiles(self) -> list[dict]:
        return self._call("qualityprofile")

    def metadata_profiles(self) -> list[dict]:
        return self._call("metadataprofile")

    def root_folders(self) -> list[dict]:
        return self._call("rootfolder")

    def find_album(self, rgid: str) -> dict | None:
        # filtered server-side; re-checked here because old versions ignore it
        try:
            albums = self._call("album", params={"foreignAlbumId": rgid}) or []
        except LidarrError as e:
            if e.status and e.status < 500:
                return None
            raise
        for a in albums:
            if a.get("foreignAlbumId") == rgid:
                return a
        return None

    def set_monitored(self, album: dict) -> None:
        try:
            self._call("album/monitor", method="PUT",
                       json={"albumIds": [album["id"]], "monitored": True})
        except LidarrError:
            album["monitored"] = True
            self._call(f"album/{album['id']}", method="PUT", json=album)

    def lookup(self, rgid: str) -> dict | None:
        results = self._call("album/lookup", params={"term": f"lidarr:{rgid}"})
        return results[0] if results else None

    def add_album(self, rgid: str, quality_profile_id: int,
                  metadata_profile_id: int, root_folder: str,
                  also_monitor: list[str] | None = None) -> tuple[str, int | None]:
        """add one release group.

        returns (outcome, album_id) where outcome is added, monitored or
        skipped. also_monitor lists other release groups by the same artist
        that this run will push, so they survive lidarr's post-add scan.

        adding does not search. lidarr's addOptions.searchForNewAlbum is
        read by SearchForRecentlyAdded, which ArtistScannedHandler only
        reaches for an artist with no AddOptions (never the artist this
        add just created), and the handler clears AddOptions on its way
        out, so the flag is stored and then dropped (Lidarr#5012). the
        caller searches explicitly with search_albums instead.
        """
        existing = self.find_album(rgid)
        if existing is not None:
            if existing.get("monitored"):
                return "skipped", existing.get("id")
            self.set_monitored(existing)
            return "monitored", existing.get("id")

        album = self.lookup(rgid)
        if album is None:
            raise LidarrError(
                "Lidarr's lookup didn't find this MusicBrainz ID; it needs a "
                "release group ID, not a release ID")
        wanted = [rgid] + [r for r in (also_monitor or []) if r != rgid]
        artist = album["artist"]
        artist.update({
            "qualityProfileId": quality_profile_id,
            "metadataProfileId": metadata_profile_id,
            "rootFolderPath": root_folder,
            "monitored": True,
            # leave future releases alone; the default is "all"
            "monitorNewItems": "none",
            "addOptions": {
                # anything but "none": that flag force-unmonitors the artist
                "monitor": "existing",
                "albumsToMonitor": wanted,
                "searchForMissingAlbums": False,
            },
        })
        album["artist"] = artist
        album["monitored"] = True
        # not searchForNewAlbum: see the docstring. leaving it false also
        # keeps AddAlbumService from tangling it with searchForMissingAlbums
        album["addOptions"] = {"searchForNewAlbum": False}
        try:
            created = self._call("album", method="POST", json=album)
        except LidarrError as e:
            if not _is_duplicate(e.status, e.body):
                raise
            # the row appeared mid-run (artist side effect); monitor it
            found = self.find_album(rgid)
            if found is None:
                raise LidarrError(
                    f"Lidarr says this album already exists but won't return "
                    f"it ({e.body[:200]})") from e
            if found.get("monitored"):
                return "skipped", found.get("id")
            self.set_monitored(found)
            return "monitored", found.get("id")
        time.sleep(0.2)  # be gentle
        return "added", (created or {}).get("id")

    def search_albums(self, album_ids: list[int]) -> None:
        for i in range(0, len(album_ids), 100):
            self._call("command", method="POST",
                       json={"name": "AlbumSearch", "albumIds": album_ids[i:i + 100]})
