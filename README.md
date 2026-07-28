# chartarr

[![test](https://github.com/alperien/chartarr/actions/workflows/test.yml/badge.svg)](https://github.com/alperien/chartarr/actions/workflows/test.yml)

Feed a CSV of albums to Lidarr.

chartarr looks up every artist/title pair on MusicBrainz, lets you settle
the doubtful ones in a small terminal UI, and adds the results to Lidarr
as monitored albums. The albums from your list, not the discographies
they came from.

<img src="docs/review.svg" alt="the review screen: a list of uncertain matches, candidates for the selected row underneath">

Lidarr can't do this by itself. It has no album import, and its import
lists work on artists, where one artist brings a whole discography
along. chartarr adds each album's artist with only your albums marked
for monitoring, so the rest of the catalogue stays quiet.

## Install

    pipx install git+https://github.com/alperien/chartarr

or, with [uv](https://docs.astral.sh/uv/):

    uv tool install git+https://github.com/alperien/chartarr

Python 3.10 or later. Windows pulls in windows-curses automatically.
Not on PyPI yet, so install from here.

## Use

    chartarr chart.csv

Matching runs first. MusicBrainz allows one request per second and a row
usually needs two or three, so a 200-row chart takes around ten minutes.
Everything is written to `<csv>.chartarr.jsonl` as it happens; press q,
or lose your connection, and the next run picks up where this one
stopped.

<img src="docs/match.svg" alt="the match screen: a progress bar, running totals, and the most recent lookups">

Rows the matcher wasn't sure about go to review. Enter accepts the
suggestion, 1-3 pick an alternative, s skips the row, u undoes a
decision, a accepts everything left, q finishes. Decisions are saved the
moment you make them.

Then the push. Albums Lidarr already has are skipped or flipped to
monitored rather than added twice, so re-running a chart is always safe.
Note that monitoring an album doesn't download it, Lidarr gets to those
on its own schedule. Pass `--search` to have it start looking
immediately; without it, chartarr tells you how many albums are waiting.

<img src="docs/push.svg" alt="the push screen: adding albums to lidarr with per-album outcomes">

At the end you get a one-line portrait of the chart:

    39 albums, 36 artists · 1959-2017 ▂▄▄▂█▆▇ · mostly art rock

When output is piped, the screens are replaced by plain lines, and rows
that need review wait for a terminal (`--yes` pushes without them).

To try it without your own data: `chartarr --example` writes a small
sample CSV, and `chartarr --demo` plays a whole run on made-up data
without saving or sending anything.

## Options

    --dry-run           show what would be pushed without changing anything
    --yes               skip the review stage
    --search            have Lidarr look for the albums and download them
    --match-only        run only the match stage
    --review-only       run only the review stage
    --push-only         run only the push stage
    --example           write sample.csv to the current directory
    --demo              simulate a full run with sample data
    --quality-profile   Lidarr quality profile (default: first)
    --metadata-profile  Lidarr metadata profile (default: first)
    --root-folder       Lidarr root folder (default: first)
    --state             state file path (default: <csv>.chartarr.jsonl)
    --rematch           look up rows nothing was found for again
    --setup             set the Lidarr URL and API key

## The CSV

chartarr needs an artist column (`artist`, `artists`, `artist_name`,
`albumartist`, `album artist`) and a title column (`title`, `album`,
`album_title`, `release`, `name`). Everything else is ignored, except
`release_date` and `genres`, which feed the closing line. A
RateYourMusic export works as-is.

Rows are tracked by artist and title, not by position. Add, remove and
reorder lines between runs; every album keeps its own match.

## Configuration

The first run asks for your Lidarr URL and API key (Settings > General >
Security) and stores them in `~/.config/chartarr/config.json`, readable
only by you. `LIDARR_URL` and `LIDARR_API_KEY` override the file, and the
`CHARTARR_`-prefixed versions work if the short names are already taken.
`chartarr --setup` reconfigures.

## Notes

- A Lidarr album corresponds to a MusicBrainz release group; that's what
  chartarr matches.
- Charts write titles loosely and MusicBrainz is precise. When a live
  album or a compilation shares its title with the studio record, the row
  goes to review instead of being guessed at. A title that asks for the
  live version ("Live at the Apollo") is taken at its word.
- One request per second is the MusicBrainz limit for everybody, so
  don't run two copies at once.

## License

MIT
