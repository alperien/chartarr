"""matcher tests. every case here happened on a real chart."""
from chartarr.matcher import norm, score_rgs, sim, variants


def rg(title, artist, mbid, ptype="Album", score=100, secondary=None):
    return {
        "id": mbid,
        "title": title,
        "primary-type": ptype,
        "secondary-types": secondary or [],
        "score": score,
        "first-release-date": "2000-01-01",
        "artist-credit": [{"name": artist, "artist": {"id": f"a-{mbid}", "name": artist}}],
    }


def test_norm_strips_diacritics_and_punctuation():
    assert norm("Sigur Rós") == norm("sigur ros")
    assert norm("Piñata") == norm("pinata")
    assert norm("good kid, m.A.A.d city") == norm("Good Kid, M.A.A.D City")


def test_norm_treats_ampersand_as_and():
    assert norm("Freddie Gibbs & Madlib") == norm("Freddie Gibbs and Madlib")


def test_norm_symbol_only_is_empty():
    assert norm("★") == ""


def test_sim_symbol_only_titles_compare_raw():
    assert sim("★", "★") == 1.0
    assert sim("★", "✝") < 1.0


def test_sim_sharp_signs_and_infinity():
    # rym writes F♯A♯∞, musicbrainz writes F♯ A♯ ∞
    assert sim("F♯A♯∞", "F♯ A♯ ∞") > 0.7


def test_sim_punctuation_in_artist_names():
    # rym: "Godspeed You Black Emperor!" / mb: "Godspeed You! Black Emperor"
    assert sim("Godspeed You Black Emperor!", "Godspeed You! Black Emperor") == 1.0


def test_variants_dual_script_title():
    vs = variants("98.12.28 Otokotachi no wakare\n98.12.28 男達の別れ")
    assert "98.12.28 Otokotachi no wakare" in vs
    assert "98.12.28 男達の別れ" in vs


def test_variants_bracketed_alt_title():
    vs = variants("★ [Blackstar]")
    assert "★" in vs
    assert "Blackstar" in vs


def test_blackstar_album_beats_single_at_equal_similarity():
    # bowie has an album and a single both titled ★; the album must win
    cands = score_rgs(
        [rg("★", "David Bowie", "single-id", ptype="Single"),
         rg("★", "David Bowie", "album-id", ptype="Album")],
        variants("★ [Blackstar]"), variants("David Bowie"))
    assert cands[0]["release_group_mbid"] == "album-id"
    assert cands[0]["title_sim"] == 1.0


def test_exact_match_beats_near_match():
    cands = score_rgs(
        [rg("Twin Fantasy Demos", "Car Seat Headrest", "demos-id"),
         rg("Twin Fantasy", "Car Seat Headrest", "real-id")],
        variants("Twin Fantasy"), variants("Car Seat Headrest"))
    assert cands[0]["release_group_mbid"] == "real-id"


def test_dual_script_matches_original_script_release():
    cands = score_rgs(
        [rg("98.12.28 男達の別れ", "Fishmans", "fish-id")],
        variants("98.12.28 Otokotachi no wakare\n98.12.28 男達の別れ"),
        variants("Fishmans"))
    assert cands[0]["title_sim"] == 1.0
