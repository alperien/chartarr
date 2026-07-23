# chartarr

match a csv of albums against musicbrainz and add them to lidarr as
monitored albums.

lidarr can't import files, and its import lists only work on whole
artists. this fills the gap: you bring a csv (a rateyourmusic chart
export, a best-of list, a spreadsheet), chartarr finds the release-group
ids and adds exactly those albums — not entire discographies.

    pipx install chartarr

## use

    chartarr chart.csv

    chart.csv: 1395 albums
    matching 1395 albums against musicbrainz (about 26 min, ctrl-c resumes)
      212/1395  ok 91%  miles davis — kind of blue
    matched 1236 · review 154 · not found 5
    ...

three stages, all resumable — progress lives in a small file next to
your csv, so ctrl-c and rerun whenever:

- **match** — each artist + title is looked up on musicbrainz, paced to
  their rate limit (about one per second).
- **review** — uncertain matches open in a small fullscreen screen.
  up/down moves between albums, 1-3 picks a candidate, s skips,
  u undoes, o opens musicbrainz in the browser, q saves and quits.
  decisions are written the moment you press the key.
- **push** — matched albums go to lidarr, monitored, with each artist
  set to monitor nothing else. albums lidarr already has are skipped;
  ones it knows but doesn't monitor get monitored. rerun freely.

first run asks for your lidarr url and api key (settings > general >
security) and keeps them in ~/.config/chartarr/config.json.

no csv handy? `chartarr --example` writes a small one to play with.

## flags

    --dry-run        show what would be pushed, change nothing
    --yes            skip review, push confident matches only
    --search         have lidarr search for the added albums
    --match-only     stop after matching
    --review-only    just the review screen
    --push-only      just the push
    --example        write sample.csv to the current directory

quality profile, metadata profile and root folder default to the first
of each; override with --quality-profile, --metadata-profile,
--root-folder.

## csv

any csv with an artist column and a title (or album) column works.
rateyourmusic exports work as they are. extra columns are ignored,
though release_date and genres make the closing line nicer.

## notes

- a lidarr "album" is a musicbrainz release group; that's what gets
  matched.
- musicbrainz allows one request per second. chartarr obeys. don't run
  two copies at once.
- the review screen uses curses; on windows it comes via the
  windows-curses package, installed automatically.

## license

mit
