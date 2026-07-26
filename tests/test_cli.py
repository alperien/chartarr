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


def test_load_csv_accepts_album_header_and_makes_keys(tmp_path):
    p = _csv(tmp_path, "album,artist\nRumours,Fleetwood Mac\nAja,Steely Dan\n")
    rows, artist_col, title_col = load_csv(p)
    assert title_col == "album"
    assert len({r["_key"] for r in rows}) == 2


def test_keys_follow_the_row_when_the_csv_is_edited(tmp_path):
    # inserting a row used to shift every key by one, which handed each
    # album the previous album's match on the next run
    first = _csv(tmp_path, "title,artist\nRumours,Fleetwood Mac\nAja,Steely Dan\n")
    before = {r["title"]: r["_key"] for r in load_csv(first)[0]}
    (tmp_path / "chart.csv").write_text(
        "title,artist\nKind of Blue,Miles Davis\nRumours,Fleetwood Mac\n"
        "Aja,Steely Dan\n", encoding="utf-8")
    after = {r["title"]: r["_key"] for r in load_csv(first)[0]}
    assert before["Rumours"] == after["Rumours"]
    assert before["Aja"] == after["Aja"]


def test_same_album_twice_gets_two_keys(tmp_path):
    p = _csv(tmp_path, "title,artist\nRumours,Fleetwood Mac\nRumours,Fleetwood Mac\n")
    rows, _, _ = load_csv(p)
    assert len({r["_key"] for r in rows}) == 2


def test_keys_ignore_case_accents_and_punctuation(tmp_path):
    # the same row retyped shouldn't look like a different album
    a = _csv(tmp_path, "title,artist\nÁgætis byrjun,Sigur Rós\n")
    b = tmp_path / "other.csv"
    b.write_text('title,artist\n"  ágætis, byrjun!",SIGUR ROS\n', encoding="utf-8")
    assert load_csv(a)[0][0]["_key"] == load_csv(b)[0][0]["_key"]


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


def test_truncated_write_does_not_eat_the_next_record(tmp_path):
    # a run killed mid-append leaves a line with no newline; the record
    # written after it used to fuse onto the stub and vanish on replay
    path = tmp_path / "s.jsonl"
    s = State(path)
    s.add_result("a", {"status": "matched"})
    with path.open("a", encoding="utf-8") as f:
        f.write('{"key": "b", "status": "mat')  # killed here
    again = State(path)
    again.add_decision("a", {"action": "accept", "mbid": "m-1"})
    third = State(path)
    assert third.decisions["a"]["mbid"] == "m-1"
    assert "b" not in third.results


def test_forget_lets_a_row_be_looked_up_again(tmp_path):
    path = tmp_path / "s.jsonl"
    s = State(path)
    s.add_result("a", {"status": "not_found"})
    s.forget(["a"])
    assert "a" not in s.results
    assert "a" not in State(path).results


def test_state_ignores_junk_records(tmp_path):
    path = tmp_path / "s.jsonl"
    path.write_text('[]\n"nope"\n{"no_key": 1}\n{"key": "a", "status": "matched"}\n',
                    encoding="utf-8")
    assert list(State(path).results) == ["a"]
