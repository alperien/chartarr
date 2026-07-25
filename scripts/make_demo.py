"""Render docs/demo.svg from real chartarr UI components (no network)."""
from collections import Counter

from rich.console import Console

import chartarr.ui as ui
from chartarr.review import _card

console = Console(record=True, width=78, force_terminal=True)
ui.console = console  # render everything into the recording console

ui.banner()
console.print("[dim]rym_chart.csv: 1395 albums (artist: 'artist', title: 'title')[/]")
ui.rule("matching 1395 albums against MusicBrainz")
console.print("[dim]~1/sec — MusicBrainz rate limit. Ctrl+C anytime; it resumes.[/]")
console.print("  [bold]89%[/] auto-matched · ♪ Fishmans — 98.12.28 男達の別れ "
              "[magenta]━━━━━━━━━╸━━[/] [green]1102/1395[/] 0:05:22")
ui.match_summary(Counter({"matched": 1236, "review": 154, "not_found": 5}))

ui.rule("review — 154 uncertain matches")
row = {"artist": "Car Seat Headrest", "title": "Twin Fantasy",
       "release_date": "2 November 2011"}
result = {"key": "120", "candidates": [
    {"release_group_mbid": "x", "mb_artist": "Car Seat Headrest",
     "mb_title": "Twin Fantasy (Face to Face)", "mb_primary_type": "Album",
     "mb_secondary_types": "", "mb_first_release": "2018-02-16",
     "title_sim": 0.79, "artist_sim": 1.0},
    {"release_group_mbid": "y", "mb_artist": "Car Seat Headrest",
     "mb_title": "Twin Fantasy", "mb_primary_type": "Album",
     "mb_secondary_types": "", "mb_first_release": "2011-11-02",
     "title_sim": 1.0, "artist_sim": 1.0},
    {"release_group_mbid": "z", "mb_artist": "Car Seat Headrest",
     "mb_title": "Twin Fantasy Demos", "mb_primary_type": "Album",
     "mb_secondary_types": "Demo", "mb_first_release": "2011-01-01",
     "title_sim": 0.86, "artist_sim": 1.0},
]}
console.print(_card(row, result, "artist", "title", 12, 154))
console.print("  [green]✓ Car Seat Headrest — Twin Fantasy[/]")

ui.rule("pushing 1389 albums to Lidarr")
ui.push_summary(Counter({"added": 1102, "monitored": 287, "skipped": 0}))

rows = [
    {"artist": "Miles Davis", "title": "Kind of Blue",
     "release_date": "17 August 1959", "genres": "Modal Jazz"},
    {"artist": "Radiohead", "title": "OK Computer",
     "release_date": "16 June 1997", "genres": "Art Rock, Alternative Rock"},
    {"artist": "Kendrick Lamar", "title": "To Pimp a Butterfly",
     "release_date": "15 March 2015", "genres": "Jazz Rap"},
]
ui.stats_panel(rows, "artist", "title")

console.save_svg("docs/demo.svg", title="chartarr")
print("wrote docs/demo.svg")
