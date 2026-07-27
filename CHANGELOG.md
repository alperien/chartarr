# Changelog

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

Until 1.0, a minor bump means something changed that you might notice: a
command-line flag, the CSV columns that get recognised, the state file, or
the config file. Patch releases are fixes and additions that leave those
alone.

## [Unreleased]

### Fixed

- **One failed search request no longer strands the albums behind it.**
  Searches go out in batches of a hundred, and a batch that failed raised
  immediately, so on a 250-album chart a single timed-out request left the
  last fifty albums unsearched with nothing said about it. Every batch is
  now attempted, and the summary reports how many albums missed out and
  why.
- **`--search` did not start downloads for the first album of each new
  artist.** Adding an album was assumed to search it, via Lidarr's
  `addOptions.searchForNewAlbum`. That flag is read by
  `SearchForRecentlyAdded`, which Lidarr's `ArtistScannedHandler` only
  reaches for an artist that has no pending add options — never the
  artist the add just created — and the handler clears those options on
  its way out, so the flag is stored and dropped
  ([Lidarr#5012](https://github.com/Lidarr/Lidarr/issues/5012)). The
  second and later albums by an artist were unaffected: Lidarr
  pre-creates the discography, so those come back "already added" and
  take the flip-to-monitored path, which chartarr searched explicitly.
  Every album this run adds or turns on is now named in one `AlbumSearch`
  command, which searches unconditionally. Without `--search`, the
  summary says how many albums are monitored but idle, instead of looking
  like a finished job that downloaded nothing.

- **A skip in the review screen is now honoured on a row that also
  matched.** The push took the automatic match whenever there was one and
  only consulted your decision otherwise, so a row that was skipped and
  then matched on a later `--rematch` went to Lidarr anyway, and a re-pick
  lost to the candidate the matcher had led with. A decision now outranks
  the match result. A matched row carrying no release group id — possible
  in a state file written by an older version — is left out instead of
  failing at Lidarr's lookup.
- **A Lidarr URL with credentials in it no longer appears in error
  messages.** `http://user:pw@host` is how you get through a reverse proxy
  that asks for basic auth, and the whole URL was quoted back in every
  connection error, timeout and proxy error page. The password is stripped
  from what's printed; the request still sends it.

- **The review screen pinned a CPU core while it waited for you.** The
  progress screens poll for a keypress so they can notice `q` mid-run, and
  that non-blocking mode stayed on the window afterwards — `curses.wrapper`
  does not reset it between screens. The review list, which expects to wait
  for input, instead read "no key pressed" and redrew immediately, about
  17,000 times a second for as long as the screen was open. It also
  flickered. Every screen now starts in blocking mode.
- **`--search` asked Lidarr to search newly added albums twice.** An added
  album already carries `searchForNewAlbum`, and it was then named in the
  follow-up `AlbumSearch` command as well. Only albums that were flipped
  from unmonitored to monitored need that second request, since the flag
  never fires for them.

### Added

- **u undoes a decision in the review screen.** A mistyped `s` used to be
  permanent for that run — the state file has always understood a cleared
  decision, but nothing could write one.
- Tests for the review screen's keys, which had none.

## [0.1.0] - 2026-07-27

First release.

Match a CSV of albums against MusicBrainz, resolve the uncertain ones in a
review screen, and add the results to Lidarr as monitored albums. Runs in
three resumable stages and can be stopped and restarted at any point.

Notes for anyone who ran this from git before the release — three fixes
changed behaviour you may have been affected by:

- **Albums pushed to Lidarr stayed unmonitored.** The artist was added with
  `addOptions.monitor = "none"`, which makes Lidarr unmonitor the artist and
  then, once its background scan finishes, every album of theirs including
  the one just pushed. Verified against Lidarr 3.1.0.4875: a fresh push
  reported "added" and fifteen seconds later nothing was monitored. If you
  pushed a chart with an earlier build, check Lidarr — those albums are
  probably sitting there unmonitored, and re-running chartarr will fix them.
- **Editing the CSV between runs mixed up the matches.** Rows were keyed by
  position, so inserting a line at the top shifted every key and each album
  inherited the one above it's match. Keys are now derived from the artist
  and title, so a row keeps its own match wherever it moves. Existing state
  files use the old keys and will be re-matched from scratch; delete them or
  let them be.
- **A dropped connection permanently marked rows as "not found".** An
  unreachable MusicBrainz and a genuine miss were recorded the same way, and
  nothing ever looked at those rows again. The run now stops instead, and
  `--rematch` re-queries rows nothing was found for.

[Unreleased]: https://github.com/alperien/chartarr/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/alperien/chartarr/releases/tag/v0.1.0
