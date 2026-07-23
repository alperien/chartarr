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

This runs three stages:

1. **Match.** Each artist/title pair is looked up on MusicBrainz.
   Requests are limited to one per second, per the MusicBrainz rate
   limit. Progress is saved to `<csv>.chartarr.jsonl`; interrupted runs
   resume where they left off.
2. **Review.** Uncertain matches are shown in an interactive list.
   Arrow keys move, Enter accepts the suggested match, 1-3 select an
   alternative, s skips a row, a accepts all suggestions, q finishes.
   Decisions are saved immediately and can be changed by selecting a
   row again.
3. **Push.** Matched albums are added to Lidarr as monitored albums.
   Each artist is added with monitoring disabled, so only the listed
   albums are monitored. Albums already in Lidarr are skipped; albums
   Lidarr knows but does not monitor are set to monitored. This stage
   is safe to re-run.

On first run, chartarr asks for the Lidarr URL and API key (Settings >
General > Security) and stores them in `~/.config/chartarr/config.json`.
The environment variables `LIDARR_URL` and `LIDARR_API_KEY` take
precedence over the file.

To try it without your own data: `chartarr --example` writes a small
sample CSV, and `chartarr --demo` opens the review screen with sample
data without saving anything.

## Options

    --dry-run           show what would be pushed without changing anything
    --yes               skip the review stage
    --search            trigger a Lidarr search for added albums
    --match-only        run only the match stage
    --review-only       run only the review stage
    --push-only         run only the push stage
    --example           write sample.csv to the current directory
    --demo              open the review screen with sample data
    --quality-profile   Lidarr quality profile (default: first)
    --metadata-profile  Lidarr metadata profile (default: first)
    --root-folder       Lidarr root folder (default: first)
    --state             state file path (default: <csv>.chartarr.jsonl)

## CSV format

The file must contain an artist column (`artist`, `artists`,
`artist_name`) and a title column (`title`, `album`, `release`). Other
columns are ignored. RateYourMusic exports work without changes.

## Notes

- A Lidarr album corresponds to a MusicBrainz release group; that is
  what chartarr matches.
- MusicBrainz allows one request per second per client. Do not run
  multiple instances at once.

## License

MIT
