# chartarr

Match a CSV of albums against MusicBrainz and add them to Lidarr as
monitored albums.

Lidarr cannot import files, and its import lists operate on artists
rather than albums. chartarr looks up each artist/title pair on
MusicBrainz, lets you resolve uncertain matches, and adds the resulting
albums to Lidarr through its API.

## Installation

    pipx install chartarr

Requires Python 3.9 or later. On Windows, the windows-curses dependency
is installed automatically.

## Usage

    chartarr chart.csv

This runs four stages:

1. **Match.** Each artist/title pair is looked up on MusicBrainz.
   Requests are limited to one per second, per the MusicBrainz rate
   limit. A fullscreen progress view shows the bar, running totals and
   the most recent lookups; press q to stop. Progress is saved to
   `<csv>.chartarr.jsonl`; interrupted runs resume where they left off.
   Rows MusicBrainz could not be reached for are reported as unanswered
   and retried on the next run, rather than recorded as a miss.
2. **Review.** Uncertain matches are shown in an interactive list.
   Arrow keys move, Enter accepts the suggested match, 1-3 select an
   alternative, s skips a row, a accepts all suggestions, q finishes.
   Decisions are saved immediately and can be changed by selecting a
   row again. If every uncertain row is already decided, chartarr offers
   to reopen the list so an earlier choice can be changed.
3. **Push.** Matched albums are added to Lidarr as monitored albums,
   with the same fullscreen progress view. Each artist is added with
   monitoring disabled, so only the listed albums are monitored.
   Albums already in Lidarr are skipped; albums Lidarr knows but does
   not monitor are set to monitored. This stage is safe to re-run.
4. **Download.** Monitoring an album does not fetch it — Lidarr only
   looks for files when something asks it to search. chartarr reports
   what the push landed and asks whether to start downloads for it.
   Answering yes queues a Lidarr album search, which is the same thing
   the Search button in the Lidarr UI does. Answering no leaves the
   albums monitored, for Lidarr's own scheduled task or a later run.

Only albums this run added or newly monitored are offered for download;
albums that were already monitored are left alone, so re-running does
not re-grab anything.

When output is piped or no terminal is available, the progress screens
are replaced by plain line output, and the download step does nothing
unless `--search` was passed — there is nobody to ask.

On first run, chartarr asks for the Lidarr URL and API key (Settings >
General > Security) and stores them in `~/.config/chartarr/config.json`.
The environment variables `LIDARR_URL` and `LIDARR_API_KEY` take
precedence over the file.

To try it without your own data: `chartarr --example` writes a small
sample CSV, and `chartarr --demo` simulates a full run (match, review,
push, download) on sample data without saving or sending anything.

## Options

    --dry-run           show what would be pushed without changing anything
    --yes               skip the review stage
    --search            start downloads without asking
    --no-search         never start downloads, don't ask
    --match-only        run only the match stage
    --review-only       run only the review stage
    --push-only         run only the push stage
    --example           write sample.csv to the current directory
    --demo              simulate a full run with sample data
    --quality-profile   Lidarr quality profile (default: first)
    --metadata-profile  Lidarr metadata profile (default: first)
    --root-folder       Lidarr root folder (default: first)
    --state             state file path (default: <csv>.chartarr.jsonl)

## CSV format

The file must contain an artist column (`artist`, `artists`,
`artist_name`) and a title column (`title`, `album`, `release`). Other
columns are ignored. RateYourMusic exports work without changes.

A `rank` or `id` column, when present, identifies rows in the state file.
Repeated values are fine — later rows get a suffix so nothing is lost.

## Notes

- A Lidarr album corresponds to a MusicBrainz release group; that is
  what chartarr matches.
- MusicBrainz allows one request per second per client. Do not run
  multiple instances at once.
- A search queries every indexer you have configured, once per album, so
  a large chart is a lot of requests. Lidarr queues the work and gets
  through it in the background; chartarr exits once it is handed over.
- Adding an album under an unmonitored artist can make Lidarr unmonitor
  it again moments later ([Lidarr#5012][]). chartarr re-checks the albums
  it pushed and restores monitoring before searching.

[Lidarr#5012]: https://github.com/Lidarr/Lidarr/issues/5012

## Troubleshooting

- **Nothing downloads after a push.** Monitoring an album does not fetch
  it. Answer yes at the download prompt, or pass `--search`. If neither
  happened, the albums are monitored and Lidarr's scheduled task will
  find them eventually.
- **Some rows say "unanswered".** MusicBrainz could not be reached for
  them. Rerun and they are tried again; nothing is lost.
- **An album failed with an HTTP error.** The rest of the push still
  went through. Rerun to retry just the failures — adding and monitoring
  are both safe to repeat.
- **A row was skipped by mistake.** Rerun with `--review-only`; chartarr
  offers to reopen the review list so the decision can be changed.

## License

MIT
