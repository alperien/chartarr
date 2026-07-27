# Changelog

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

Until 1.0, a minor bump means something changed that you might notice: a
command-line flag, the CSV columns that get recognised, the state file, or
the config file. Patch releases are fixes and additions that leave those
alone.

## [Unreleased]

### Fixed

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
