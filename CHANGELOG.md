# Changelog

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

Until 1.0, a minor bump means something changed that you might notice: a
command-line flag, the CSV columns that get recognised, the state file, or
the config file. Patch releases are fixes and additions that leave those
alone.

## [Unreleased]

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
