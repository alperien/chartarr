# Changelog

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

Until 1.0, a minor bump means something changed that you might notice: a
command-line flag, the CSV columns that get recognised, the state file, or
the config file. Patch releases are fixes and additions that leave those
alone.

## [Unreleased]

## [0.1.1] - 2026-07-28

A fix release. The first one is the reason to upgrade.

### Fixed

- **The review screen pinned a CPU core while it waited for you.** The
  progress screens poll for a keypress so they can notice `q` mid-run,
  and that non-blocking mode stayed on the window afterwards —
  `curses.wrapper` does not reset it between screens. The review list,
  which expects to wait for input, read "no key pressed" instead and
  redrew immediately: about 17,000 times a second, for as long as the
  screen was open. It flickered, and on a laptop you could hear it. Every
  screen now starts in blocking mode. Waiting on the review list costs
  one redraw and no measurable CPU.
- **A skip or a re-pick was ignored on a row that also matched.** The
  push took the automatic match whenever there was one and consulted your
  decision only otherwise, so a row you skipped that later matched on a
  `--rematch` went to Lidarr anyway, and a re-pick lost to the candidate
  the matcher had led with. A decision now outranks the match result. A
  matched row carrying no release group id — possible in a state file
  from an older version — is left out instead of failing at Lidarr's
  lookup.
- **One failed search request stranded the albums behind it.** Searches
  go out in batches of a hundred and a failing batch stopped the rest, so
  on a 250-album chart a single timed-out request left the last fifty
  unsearched, reported as one line that did not say how many albums it
  had cost. Every batch is attempted now, and the summary says how many
  albums missed out and why.
- **A Lidarr URL with credentials in it appeared in error messages.**
  `http://user:pw@host` is how you get through a reverse proxy that asks
  for basic auth, and the whole URL was quoted back in connection errors,
  timeouts, non-JSON replies and proxy error pages — the kind of text
  that ends up pasted into a bug report. The password is stripped from
  what's printed; the request still sends it.

### Added

- **`u` undoes a decision in the review screen.** A mistyped `s` used to
  be permanent for that run: the state file has always understood a
  cleared decision, but nothing could write one.
- **A push without `--search` now says how many albums are monitored but
  idle.** Monitoring is not downloading — Lidarr picks monitored albums
  up on its own schedule — and a run ending "added 40" while nothing
  downloads reads like a finished job.

### Changed

- chartarr no longer sends `addOptions.searchForNewAlbum` when it adds an
  album. Lidarr stores the flag and drops it unread for an artist created
  by the same request ([Lidarr#5012](https://github.com/Lidarr/Lidarr/issues/5012)),
  so it never did anything; the explicit `AlbumSearch` command was always
  the thing starting downloads. No change in behaviour, one less
  misleading field on the wire.

### Internal

- The review screen's keys had no tests, which is how the redraw bug
  shipped. They have 19 now, driven through a fake curses window, plus a
  pty test that the non-blocking flag cannot survive a screen. 97 tests
  at 0.1.0, 142 here.

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

[Unreleased]: https://github.com/alperien/chartarr/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/alperien/chartarr/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/alperien/chartarr/releases/tag/v0.1.0
