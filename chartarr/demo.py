"""sample data for --demo: a simulated full run, nothing saved."""
from __future__ import annotations

import sys
import time

from . import review


def _item(key, artist, title, date, candidates):
    row = {"artist": artist, "title": title, "release_date": date}
    result = {"key": key, "status": "review" if candidates else "not_found",
              "candidates": candidates}
    return row, result


def _cand(mbid, artist, title, ptype, date, t_sim, a_sim):
    return {"release_group_mbid": mbid, "mb_artist": artist, "mb_title": title,
            "artist_mbid": None, "mb_primary_type": ptype,
            "mb_secondary_types": "", "mb_first_release": date,
            "title_sim": t_sim, "artist_sim": a_sim,
            "confidence": round(0.55 * t_sim + 0.45 * a_sim, 3)}


ITEMS = [
    _item("1", "David Bowie", "★ [Blackstar]", "8 January 2016", [
        _cand("1fd18f5b-9a92-41fd-a590-da6b5cc60d85", "David Bowie", "★",
              "Album", "2016-01-08", 1.0, 1.0),
        _cand("902e4653-a038-4666-b608-b31b2feeb15e", "David Bowie", "★",
              "Single", "2015-11-19", 1.0, 1.0),
    ]),
    _item("2", "Mingus", "The Black Saint and the Sinner Lady", "1963", [
        _cand("demo-mingus-1", "Charles Mingus",
              "The Black Saint and the Sinner Lady", "Album", "1963-07", 1.0, 0.67),
    ]),
    _item("3", "Fiona Apple", "When the Pawn", "9 November 1999", [
        _cand("demo-apple-1", "Fiona Apple", "When the Pawn Hits the Conflicts…",
              "Album", "1999-11-09", 0.55, 1.0),
        _cand("demo-apple-2", "Fiona Apple", "Tidal / When the Pawn…",
              "Album", "2000-01-01", 0.72, 1.0),
    ]),
    _item("4", "Fishmans", "98.12.28 Otokotachi no wakare\n98.12.28 男達の別れ",
          "17 March 1999", [
              _cand("9fcb2418-1d16-4d22-b6bd-3bf1a7928530", "Fishmans",
                    "98.12.28 男達の別れ", "Album", "1999-03-17", 1.0, 1.0),
          ]),
    _item("5", "Godspeed You Black Emperor!", "F♯A♯∞", "14 August 1997", [
        _cand("01d06c6e-a4e6-3d8b-8a45-42a598fe87d7",
              "Godspeed You Black Emperor!", "F♯ A♯ ∞",
              "Album", "1997-08-14", 0.8, 1.0),
    ]),
    _item("6", "The Caretaker", "Everywhere at the End of Time, Stage 7",
          "2019", []),
]

CATALOG = [
    ("Miles Davis", "Kind of Blue", "1959", "Modal Jazz"),
    ("The Beach Boys", "Pet Sounds", "1966", "Baroque Pop"),
    ("The Velvet Underground & Nico", "The Velvet Underground & Nico", "1967", "Art Rock"),
    ("King Crimson", "In the Court of the Crimson King", "1969", "Progressive Rock"),
    ("Nick Drake", "Pink Moon", "1972", "Contemporary Folk"),
    ("Stevie Wonder", "Songs in the Key of Life", "1976", "Soul"),
    ("Fleetwood Mac", "Rumours", "1977", "Soft Rock"),
    ("Joy Division", "Unknown Pleasures", "1979", "Post-Punk"),
    ("Talking Heads", "Remain in Light", "1980", "New Wave"),
    ("Kate Bush", "Hounds of Love", "1985", "Art Pop"),
    ("Slint", "Spiderland", "1991", "Post-Rock"),
    ("My Bloody Valentine", "Loveless", "1991", "Shoegaze"),
    ("Aphex Twin", "Selected Ambient Works 85-92", "1992", "Ambient Techno"),
    ("Wu-Tang Clan", "Enter the Wu-Tang (36 Chambers)", "1993", "Hardcore Hip Hop"),
    ("Portishead", "Dummy", "1994", "Trip Hop"),
    ("Radiohead", "OK Computer", "1997", "Art Rock"),
    ("Neutral Milk Hotel", "In the Aeroplane Over the Sea", "1998", "Indie Folk"),
    ("Sigur Rós", "Ágætis byrjun", "1999", "Post-Rock"),
    ("Modest Mouse", "The Moon & Antarctica", "2000", "Indie Rock"),
    ("Radiohead", "Kid A", "2000", "Electronic"),
    ("The Avalanches", "Since I Left You", "2000", "Plunderphonics"),
    ("Boards of Canada", "Geogaddi", "2002", "IDM"),
    ("Sufjan Stevens", "Illinois", "2005", "Chamber Folk"),
    ("J Dilla", "Donuts", "2006", "Instrumental Hip Hop"),
    ("LCD Soundsystem", "Sound of Silver", "2007", "Dance-Punk"),
    ("Radiohead", "In Rainbows", "2007", "Art Rock"),
    ("Kanye West", "My Beautiful Dark Twisted Fantasy", "2010", "Pop Rap"),
    ("Death Grips", "The Money Store", "2012", "Experimental Hip Hop"),
    ("Freddie Gibbs & Madlib", "Piñata", "2014", "Gangsta Rap"),
    ("Swans", "To Be Kind", "2014", "Experimental Rock"),
    ("Kendrick Lamar", "To Pimp a Butterfly", "2015", "Jazz Rap"),
    ("Sufjan Stevens", "Carrie & Lowell", "2015", "Indie Folk"),
    ("Frank Ocean", "Blonde", "2016", "Alternative R&B"),
    ("Charli XCX", "Pop 2", "2017", "Bubblegum Bass"),
]


def run() -> None:
    from . import cli  # imported late; cli imports this module

    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("the demo needs a terminal")
        return

    print(cli.dim("demo: simulated data, nothing is saved or sent"))
    total = len(CATALOG) + len(ITEMS)
    print(cli.dim(f"chart.csv: {cli._n(total, 'album')}"))

    try:
        # match, sped up
        print(f"matching {cli._n(total, 'album')} against musicbrainz "
              + cli.dim("(simulated; a real run is ~1/sec)"))
        names = [(a, t) for a, t, _, _ in CATALOG]
        for i, (row, _) in enumerate(ITEMS):
            names.insert(6 * (i + 1), (row["artist"], row["title"]))
        matched = 0
        for i, (artist, title) in enumerate(names, 1):
            if (artist, title) not in [(r["artist"], r["title"]) for r, _ in ITEMS]:
                matched += 1
            pct = matched / i
            cli.status(f"  {i}/{total}  ok {pct:.0%}  "
                       f"{artist.splitlines()[0]} — {title.splitlines()[0]}")
            time.sleep(0.05)
        cli.status_end()
        review_n = sum(1 for _, res in ITEMS if res["status"] == "review")
        lost_n = len(ITEMS) - review_n
        print(f"matched {cli.accent(matched)} · review {cli.accent(review_n)} · "
              f"not found {cli.accent(lost_n)}")

        # review, for real
        decisions = {}
        review.run(ITEMS, "artist", "title",
                   lambda key, d: decisions.__setitem__(key, d))
        picked = sum(1 for d in decisions.values() if d.get("action") == "accept")
        skipped = sum(1 for d in decisions.values() if d.get("action") == "skip")
        print(f"review: {cli.accent(picked)} picked · {cli.accent(skipped)} skipped · "
              f"{cli.accent(len(ITEMS) - picked - skipped)} left")

        # push, sped up
        by_key = {res["key"]: row for row, res in ITEMS}
        push_rows = [{"artist": a, "title": t, "release_date": y, "genres": g}
                     for a, t, y, g in CATALOG]
        push_rows += [dict(by_key[k]) for k, d in decisions.items()
                      if d.get("action") == "accept"]
        print(f"pushing {cli._n(len(push_rows), 'album')} to lidarr "
              + cli.dim("(simulated)"))
        counts = {"added": 0, "monitored": 0, "skipped": 0}
        for i, row in enumerate(push_rows, 1):
            outcome = "monitored" if i % 9 == 4 else ("skipped" if i == 17 else "added")
            counts[outcome] += 1
            cli.status(f"  {i}/{len(push_rows)}  {outcome}  "
                       f"{row['artist'].splitlines()[0]} — {row['title'].splitlines()[0]}")
            time.sleep(0.04)
        cli.status_end()
        print(f"added {cli.accent(counts['added'])} · "
              f"monitored {cli.accent(counts['monitored'])} · "
              f"already there {cli.accent(counts['skipped'])}")
        cli.closing_line(push_rows, "artist")
    except KeyboardInterrupt:
        cli.status_end()
        print()

    print(cli.dim("demo over — nothing was saved or sent"))
