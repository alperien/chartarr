"""csv loading and state replay."""
import pytest

from chartarr.cli import State, load_csv


def _csv(tmp_path, text):
    p = tmp_path / "chart.csv"
    p.write_text(text, encoding="utf-8")
    return p


def test_load_csv_detects_rym_columns(tmp_path):
    p = _csv(tmp_path, "rank,title,artist\n1,OK Computer,Radiohead\n")
    rows, artist_col, title_col = load_csv(p)
    assert (artist_col, title_col) == ("artist", "title")
    assert rows[0]["_key"] == "1"


def test_load_csv_accepts_album_header_and_makes_keys(tmp_path):
    p = _csv(tmp_path, "album,artist\nRumours,Fleetwood Mac\nAja,Steely Dan\n")
    rows, artist_col, title_col = load_csv(p)
    assert title_col == "album"
    assert [r["_key"] for r in rows] == ["row1", "row2"]


def test_load_csv_skips_blank_rows(tmp_path):
    p = _csv(tmp_path, "title,artist\nRumours,Fleetwood Mac\n,\n")
    rows, _, _ = load_csv(p)
    assert len(rows) == 1


def test_load_csv_without_artist_column_fails(tmp_path):
    p = _csv(tmp_path, "title,year\nRumours,1977\n")
    with pytest.raises(SystemExit):
        load_csv(p)


def test_state_replays_results_and_decisions(tmp_path):
    path = tmp_path / "s.jsonl"
    s = State(path)
    s.add_result("1", {"status": "review"})
    s.add_decision("1", {"action": "accept", "mbid": "m-1"})
    again = State(path)
    assert again.results["1"]["status"] == "review"
    assert again.decisions["1"]["mbid"] == "m-1"


def test_state_clear_removes_a_decision(tmp_path):
    path = tmp_path / "s.jsonl"
    s = State(path)
    s.add_decision("1", {"action": "skip"})
    s.add_decision("1", {"action": "clear"})
    assert "1" not in State(path).decisions
