# chartarr

[![test](https://github.com/alperien/chartarr/actions/workflows/test.yml/badge.svg)](https://github.com/alperien/chartarr/actions/workflows/test.yml)

Feed a CSV of albums to Lidarr.

chartarr matches each artist/title pair against MusicBrainz and adds the
results to Lidarr as monitored albums. Anything it isn't sure about gets
a review screen.

<img src="docs/review.svg" alt="the review screen">

Lidarr has no album import of its own. The import lists it does have
take artists, and adding an artist pulls in everything they ever
released. chartarr monitors just the albums in your CSV and leaves the
rest unmonitored.

## Install

    pipx install git+https://github.com/alperien/chartarr

or with [uv](https://docs.astral.sh/uv/):

    uv tool install git+https://github.com/alperien/chartarr

Python 3.10 or later. Not on PyPI yet.

## Use

    chartarr chart.csv

MusicBrainz allows one request per second, so a long chart takes a few
minutes. Progress is saved to `<csv>.chartarr.jsonl` after every row;
stop any time and the next run continues where this one left off.

<img src="docs/match.svg" alt="the match screen">

Uncertain rows go to review. Enter accepts the suggestion, 1-3 pick
another candidate, s skips, u undoes, a accepts everything left, q
finishes.

The push skips albums Lidarr already has, so rerunning a chart is safe.
Monitoring doesn't download anything by itself; add `--search` to start
the downloads. `--dry-run` shows the push without doing it.

<img src="docs/push.svg" alt="the push screen">

`chartarr --demo` plays through a whole run on fake data, `--example`
writes a CSV to try it on, and `--help` has the rest of the flags.

## The CSV

An artist column (`artist`, `artists`, `artist_name`, `albumartist`,
`album artist`) and a title column (`title`, `album`, `album_title`,
`release`, `name`). Other columns are ignored. A RateYourMusic export
works unchanged; that's the file this was written for in the first
place.

Rows are keyed by artist and title, not position, so the CSV can be
edited and reordered between runs without losing any matches.

## Configuration

The first run asks for the Lidarr URL and API key and saves them to
`~/.config/chartarr/config.json`, readable only by you. `LIDARR_URL`
and `LIDARR_API_KEY` override the file; `chartarr --setup` changes it.

## Notes

- When a live album or compilation has the same title as the studio
  record, the row goes to review instead of being guessed. A title that
  names the live version ("Live at the Apollo") matches it directly.
- One request per second is the MusicBrainz limit, so don't run two
  copies at once.
