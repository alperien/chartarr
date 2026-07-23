"""sample data for --demo: a look at the review screen, nothing saved."""
from __future__ import annotations

import sys

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


def run() -> None:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("the demo needs a terminal")
        return
    review.run(ITEMS, "artist", "title", lambda key, decision: None)
    print("review demo finished; nothing was saved")
