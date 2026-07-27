# chartarr

Match a CSV of albums against MusicBrainz and add them to Lidarr as
monitored albums.

Lidarr cannot import files, and its import lists operate on artists
rather than albums. chartarr looks up each artist/title pair on
MusicBrainz, lets you resolve uncertain matches, and adds the resulting
albums to Lidarr through its API.

## Installation

    pipx install git+https://github.com/alperien/chartarr

or, with [uv](https://docs.astral.sh/uv/):

    uv tool install git+https://github.com/alperien/chartarr

Requires Python 3.10 or later. On Windows, the windows-curses dependency
is installed automatically. Not on PyPI, install from here.

## Usage

    chartarr chart.csv

This runs three stages:

1. **Match.** Each artist/title pair is looked up on MusicBrainz.
   Requests are limited to one per second, per the MusicBrainz rate
   limit, and a row usually costs two or three of them. A fullscreen
   progress view shows the bar, running totals and the most recent
   lookups; press q to stop. Progress is saved to
   `<csv>.chartarr.jsonl`; interrupted runs resume where they left off.
   If MusicBrainz stops answering, the run stops with what it has rather
   than writing those rows off as unmatched.
2. **Review.** Uncertain matches are shown in an interactive list.
   Arrow keys move, Enter accepts the suggested match, 1-3 select an
   alternative, s skips a row, u undoes a decision, a accepts all
   suggestions, q finishes. Decisions are saved immediately and can be
   changed by selecting a row again.
3. **Push.** Matched albums are added to Lidarr as monitored albums,
   with the same fullscreen progress view. Adding an album means adding
   its artist, and Lidarr fills in their whole discography behind the
   scenes; chartarr names the albums from your chart as it goes, so
   those stay monitored and the rest of the discography does not.
   Albums already in Lidarr are skipped; albums Lidarr knows but does
   not monitor are set to monitored. This stage is safe to re-run.

When output is piped or no terminal is available, the progress screens
are replaced by plain line output.

On first run, chartarr asks for the Lidarr URL and API key (Settings >
General > Security) and stores them in `~/.config/chartarr/config.json`,
readable only by you. The environment variables `LIDARR_URL` and
`LIDARR_API_KEY` take precedence over the file; `CHARTARR_LIDARR_URL` and
`CHARTARR_API_KEY` work too, if the shorter names are already taken.

To try it without your own data: `chartarr --example` writes a small
sample CSV, and `chartarr --demo` simulates a full run (match, review,
push) on sample data without saving or sending anything.

## Options

    --dry-run           show what would be pushed without changing anything
    --yes               skip the review stage
    --search            trigger a Lidarr search for added albums
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

## CSV format

The file must contain an artist column (`artist`, `artists`,
`artist_name`, `albumartist`, `album artist`) and a title column
(`title`, `album`, `album_title`, `release`, `name`). Other columns are
ignored, except `release_date` and `genres`, which are used for the
summary line at the end. RateYourMusic exports work without changes.

Rows are tracked by artist and title rather than by position, so you can
add, remove or reorder lines between runs and each album keeps its own
match.

## Notes

- A Lidarr album corresponds to a MusicBrainz release group; that is
  what chartarr matches.
- Charts write album titles loosely, and MusicBrainz is precise. Live
  albums and compilations often share a title with the studio record , 
  when one of those wins, chartarr sends the row to review rather than
  guessing. A title that asks for the live version ("Live at the
  Apollo") is taken at its word.
- MusicBrainz allows one request per second per client. Do not run
  multiple instances at once.

## License

MIT
