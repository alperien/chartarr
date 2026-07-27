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


# --- hardening: broken input fails cleanly instead of crashing ---

import io
import json
import os
import subprocess
import sys
from pathlib import Path

from chartarr import cli
from chartarr.cli import fail, load_config, setup_wizard

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def config_home(tmp_path, monkeypatch):
    """point the config at tmp and silence the env overrides."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    for var in ("CHARTARR_LIDARR_URL", "LIDARR_URL",
                "CHARTARR_API_KEY", "LIDARR_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    p = tmp_path / "chartarr" / "config.json"
    p.parent.mkdir(parents=True)
    return p


class _Tty:
    """stdin stand-in that claims to be a terminal."""

    def isatty(self):
        return True


def test_fail_prints_prefixed_message_and_exits_1(capsys):
    with pytest.raises(SystemExit) as exc:
        fail("something went sideways")
    assert exc.value.code == 1
    assert capsys.readouterr().err == "chartarr: something went sideways\n"


def test_config_that_is_not_an_object_is_ignored(config_home):
    # a config.json holding [] or "hello" used to crash at startup with
    # AttributeError: 'list' object has no attribute 'get'
    for junk in ("[]", '"hello"', "3"):
        config_home.write_text(junk, encoding="utf-8")
        assert load_config() == {}


def test_env_still_wins_over_a_junk_config(config_home, monkeypatch):
    config_home.write_text("[]", encoding="utf-8")
    monkeypatch.setenv("LIDARR_URL", "http://example:8686")
    assert load_config()["lidarr_url"] == "http://example:8686"


def test_load_csv_latin1_fails_with_utf8_advice(tmp_path, capsys):
    p = tmp_path / "latin.csv"
    p.write_bytes("title,artist\nsmørrebrød,æ\n".encode("latin-1"))
    with pytest.raises(SystemExit) as exc:
        load_csv(p)
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith("chartarr: ")
    assert "utf-8" in err and str(p) in err


def test_load_csv_utf16_mentions_excels_unicode_export(tmp_path, capsys):
    # excel's "unicode text" export is utf-16: ascii bytes with NULs in
    # between. python 3.11 and older rejected that in the csv reader; 3.12
    # parses it into gibberish column names instead, so chartarr looks for
    # the NULs itself rather than letting the error depend on the version
    p = tmp_path / "chart.csv"
    p.write_bytes("title\tartist\nRumours\tFleetwood Mac\n".encode("utf-16-le"))
    with pytest.raises(SystemExit) as exc:
        load_csv(p)
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "excel" in err and "utf-16" in err


def test_load_csv_on_a_directory_fails_cleanly(tmp_path, capsys):
    with pytest.raises(SystemExit):
        load_csv(tmp_path)
    assert "can't read" in capsys.readouterr().err


def test_setup_wizard_refuses_to_prompt_without_a_tty(monkeypatch, capsys):
    # `chartarr x.csv --push-only < /dev/null` used to die with EOFError
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))  # isatty() is False
    with pytest.raises(SystemExit) as exc:
        setup_wizard({})
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "LIDARR_URL" in err and "LIDARR_API_KEY" in err and "--setup" in err


def test_setup_wizard_eof_at_a_prompt_cancels_cleanly(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", _Tty())

    def eof(prompt=""):
        raise EOFError

    # both prompts, or the unpatched one blocks on a real stdin read
    monkeypatch.setattr("builtins.input", eof)
    monkeypatch.setattr(cli.getpass, "getpass", eof)
    with pytest.raises(SystemExit) as exc:
        setup_wizard({})
    assert exc.value.code == 1
    assert "setup cancelled" in capsys.readouterr().err


def test_setup_wizard_ctrl_c_at_a_prompt_cancels_cleanly(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", _Tty())

    def interrupt(prompt=""):
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", interrupt)
    monkeypatch.setattr(cli.getpass, "getpass", interrupt)
    with pytest.raises(SystemExit) as exc:
        setup_wizard({})
    assert exc.value.code == 1
    assert "setup cancelled" in capsys.readouterr().err


def test_setup_wizard_key_goes_through_getpass_and_file_is_0600(
        config_home, monkeypatch):
    monkeypatch.setattr(sys, "stdin", _Tty())
    prompts = {"input": [], "getpass": []}

    def fake_input(prompt=""):
        prompts["input"].append(prompt)
        return "http://lidarr:8686"

    def fake_getpass(prompt=""):
        prompts["getpass"].append(prompt)
        return "s3kret"

    class Api:
        def __init__(self, url, key):
            pass

        def status(self):
            return {"version": "2.0"}

    monkeypatch.setattr("builtins.input", fake_input)
    monkeypatch.setattr(cli.getpass, "getpass", fake_getpass)
    monkeypatch.setattr(cli.lidarr, "Lidarr", Api)
    # the perms must come from creation, not from the chmod afterthought
    monkeypatch.setattr(Path, "chmod", lambda *a, **kw: None)
    old_umask = os.umask(0o022) if os.name == "posix" else None
    try:
        cfg = setup_wizard({})
    finally:
        if old_umask is not None:
            os.umask(old_umask)
    assert cfg == {"lidarr_url": "http://lidarr:8686", "api_key": "s3kret"}
    assert json.loads(config_home.read_text())["api_key"] == "s3kret"
    if os.name == "posix":  # windows doesn't carry unix mode bits
        assert (config_home.stat().st_mode & 0o777) == 0o600
    assert any("api key" in p for p in prompts["getpass"])
    assert not any("api key" in p for p in prompts["input"])


@pytest.mark.skipif(os.name != "posix",
                    reason="closing a pipe read end only signals the writer on posix")
def test_broken_pipe_exits_quietly_not_120(tmp_path):
    # `chartarr ... | head -0` used to end with "Exception ignored ...
    # BrokenPipeError" from the interpreter's exit flush, exit code 120
    chart = tmp_path / "c.csv"
    chart.write_text("title,artist\nRumours,Fleetwood Mac\n", encoding="utf-8")
    env = {**os.environ, "XDG_CONFIG_HOME": str(tmp_path)}
    proc = subprocess.Popen(
        [sys.executable, "-m", "chartarr", str(chart), "--push-only", "--dry-run"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=str(REPO))
    proc.stdout.close()  # the reader goes away before chartarr can flush
    try:
        # read with a deadline: a child that never notices the closed pipe
        # would otherwise hang the suite rather than fail it
        _, err = proc.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise AssertionError(
            "chartarr did not exit after its reader went away") from None
    assert proc.returncode == 1
    assert b"BrokenPipeError" not in err and b"Traceback" not in err


def _unreachable_match(rows, artist_col, title_col):
    for row in rows:
        yield row, None  # musicbrainz never answered


def test_outage_before_any_match_admits_nothing_was_saved(tmp_path, monkeypatch, capsys):
    # the message used to say "the rows matched so far are saved" even when
    # the very first lookup failed and there was nothing to resume
    monkeypatch.setattr(cli.matcher, "iter_match", _unreachable_match)
    rows = [{"artist": "Radiohead", "title": "Kid A", "_key": "k1"}]
    state = State(tmp_path / "s.jsonl")
    with pytest.raises(SystemExit):
        cli.stage_match(rows, "artist", "title", state)
    err = capsys.readouterr().err
    assert "nothing was matched" in err and "nothing was saved" in err
    assert not state.results


def test_outage_midway_reports_what_it_kept(tmp_path, monkeypatch, capsys):
    def half(rows, artist_col, title_col):
        yield rows[0], {"status": "matched", "release_group_mbid": "rg-1"}
        yield rows[1], None

    monkeypatch.setattr(cli.matcher, "iter_match", half)
    rows = [{"artist": "a", "title": "t1", "_key": "k1"},
            {"artist": "b", "title": "t2", "_key": "k2"}]
    state = State(tmp_path / "s.jsonl")
    with pytest.raises(SystemExit):
        cli.stage_match(rows, "artist", "title", state)
    assert "1 row matched so far is saved" in capsys.readouterr().err
    assert list(state.results) == ["k1"]


def test_review_choice_beats_the_auto_match_and_skips_are_dropped(tmp_path):
    # the reviewed pick has to reach lidarr, not the candidate the matcher
    # led with; that's the whole point of the review screen
    p = _csv(tmp_path, "title,artist\nZiggy Stardust,David Bowie\n"
                       "Kid A,Radiohead\nDummy,Portishead\n")
    rows, _, _ = load_csv(p)
    k = [r["_key"] for r in rows]
    state = State(tmp_path / "s.jsonl")
    state.add_result(k[0], {"status": "review", "release_group_mbid": "the-live-one",
                            "artist_mbid": "a-bowie"})
    state.add_result(k[1], {"status": "matched", "release_group_mbid": "rg-kida",
                            "artist_mbid": "a-rh"})
    state.add_result(k[2], {"status": "review", "release_group_mbid": "rg-dummy",
                            "artist_mbid": "a-p"})
    state.add_decision(k[0], {"action": "accept", "mbid": "the-studio-one",
                              "artist_mbid": "a-bowie"})
    state.add_decision(k[2], {"action": "skip"})
    items = cli.import_set(rows, state)
    assert {i["rgid"] for i in items} == {"the-studio-one", "rg-kida"}
    # artist mbid rides along, or same-artist albums unmonitor each other
    assert all(i["artist_mbid"] for i in items)


def test_rematch_clears_only_the_rows_nothing_was_found_for(tmp_path):
    state = State(tmp_path / "s.jsonl")
    state.add_result("miss", {"status": "not_found"})
    state.add_result("hit", {"status": "matched", "release_group_mbid": "rg-1"})
    state.add_result("ask", {"status": "review", "release_group_mbid": "rg-2"})
    state.add_decision("ask", {"action": "accept", "mbid": "rg-2"})
    state.forget([k for k, r in state.results.items() if r["status"] == "not_found"])
    reloaded = State(tmp_path / "s.jsonl")
    assert set(reloaded.results) == {"hit", "ask"}
    assert reloaded.decisions["ask"]["mbid"] == "rg-2"  # the review survives


def test_plain_output_accent_matches_the_curses_cherry(monkeypatch):
    # piped output and the tui should agree on the colour
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.delenv("COLORTERM", raising=False)
    assert cli._accent_code() == f"38;5;{cli.screen.CHERRY_256}"
    monkeypatch.setenv("TERM", "xterm")
    assert cli._accent_code() == "31"


def test_no_color_env_still_wins(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)
    assert cli.accent("39") == "39"
