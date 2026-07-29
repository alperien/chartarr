"""matcher tests. every case here happened on a real chart."""
import chartarr.matcher as matcher
from chartarr.matcher import norm, score_rgs, sim, variants


def rg(title, artist, mbid, ptype="Album", score=100, secondary=None, aliases=None):
    d = {
        "id": mbid,
        "title": title,
        "primary-type": ptype,
        "secondary-types": secondary or [],
        "score": score,
        "first-release-date": "2000-01-01",
        "artist-credit": [{"name": artist, "artist": {"id": f"a-{mbid}", "name": artist}}],
    }
    if aliases:  # real search docs omit the key entirely when there are none
        d["aliases"] = [{"name": a, "type": "Release group name"} for a in aliases]
    return d


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


def test_ziggy_studio_album_beats_same_titled_live_and_comp():
    # "David Bowie — Ziggy Stardust": a 1993 rg titled exactly "Ziggy
    # Stardust" [Compilation, Live] hit confidence 1.0 and auto-matched;
    # a 1994 live single shares the title too. an rg whose (alias) title is
    # the same must win only if its secondary types are clean.
    cands = score_rgs(
        [rg("Ziggy Stardust", "David Bowie", "comp-id", secondary=["Compilation", "Live"]),
         rg("Ziggy Stardust", "David Bowie", "single-id", ptype="Single", secondary=["Live"]),
         rg("The Rise and Fall of Ziggy Stardust and the Spiders From Mars",
            "David Bowie", "studio-id", aliases=["Ziggy Stardust"])],
        variants("Ziggy Stardust"), variants("David Bowie"))
    assert [c["release_group_mbid"] for c in cands] == ["studio-id", "single-id", "comp-id"]
    assert cands[0]["title_sim"] == 1.0  # via the alias


def test_fleetwood_mac_studio_beats_same_titled_comp_and_ep():
    # four real rgs titled exactly "Fleetwood Mac" used to tie at 1.0 and be
    # decided by response order; the 1975 studio album must win, and ties
    # must otherwise prefer the fewest secondary types
    cands = score_rgs(
        [rg("Fleetwood Mac", "Fleetwood Mac", "comp-79", secondary=["Compilation"]),
         rg("Fleetwood Mac", "Fleetwood Mac", "comp-live-06", secondary=["Compilation", "Live"]),
         rg("Fleetwood Mac", "Fleetwood Mac", "ep-85", ptype="EP"),
         rg("Fleetwood Mac", "Fleetwood Mac", "studio-75")],
        variants("Fleetwood Mac"), variants("Fleetwood Mac"))
    assert [c["release_group_mbid"] for c in cands] == [
        "studio-75", "ep-85", "comp-79", "comp-live-06"]


def test_legit_live_chart_entry_still_matches_its_live_rg():
    # "The Band — The Last Waltz" is live+soundtrack and belongs on charts;
    # the penalty is sort-key-only, so it still outranks the studio
    # catalogue and keeps the confidence that clears the auto-match gate
    cands = score_rgs(
        [rg("The Last Waltz", "The Band", "waltz-id", secondary=["Live", "Soundtrack"]),
         rg("Islands", "The Band", "islands-id")],
        variants("The Last Waltz"), variants("The Band"))
    assert cands[0]["release_group_mbid"] == "waltz-id"
    assert cands[0]["title_sim"] == 1.0
    assert cands[0]["confidence"] == 1.0  # penalty must not leak into confidence


def test_live_worded_title_waives_the_live_penalty():
    # "James Brown — Live at the Apollo": the row itself asks for a live
    # album, so [Live] keeps essentially full sort strength; a clean rg may
    # still win the exact tie, but only by the tie-break residual
    tv, av = variants("Live at the Apollo"), variants("James Brown")
    live = score_rgs([rg("Live at the Apollo", "James Brown", "live-id",
                         secondary=["Live"])], tv, av)[0]
    clean = score_rgs([rg("Live at the Apollo", "James Brown", "clean-id")], tv, av)[0]
    assert 0 < clean["_sort"] - live["_sort"] < 0.01


def test_hint_waives_only_the_named_type():
    # a "Live at the Apollo" row hints live, not compilation: an apollo
    # recordings comp still sinks below the 1963 live album
    cands = score_rgs(
        [rg("Live at the Apollo", "James Brown", "comp-id", secondary=["Live", "Compilation"]),
         rg("Live at the Apollo", "James Brown", "live-id", secondary=["Live"])],
        variants("Live at the Apollo"), variants("James Brown"))
    assert cands[0]["release_group_mbid"] == "live-id"


def test_alias_counts_as_title():
    # mb titles bowie's Blackstar "★"; the name every chart uses is only an
    # alias, and releasegroup:"Blackstar" returns just "Blackstar Radio
    # Edits"; the aliased album must outscore it
    cands = score_rgs(
        [rg("Blackstar Radio Edits", "David Bowie", "radio-id", ptype="Single"),
         rg("★", "David Bowie", "star-id", aliases=["Blackstar", "★ (Blackstar)"])],
        variants("Blackstar"), variants("David Bowie"))
    assert cands[0]["release_group_mbid"] == "star-id"
    assert cands[0]["title_sim"] == 1.0


def test_match_row_resolves_alias_only_title(monkeypatch):
    # end-to-end blackstar, offline: the fielded rungs cannot see ★ by
    # title; the alias: rung finds it and one alias lookup confirms it, so
    # the row auto-matches instead of stalling on the radio-edits single
    radio = rg("Blackstar Radio Edits", "David Bowie", "radio-id", ptype="Single")
    star = rg("★", "David Bowie", "star-id")
    calls = []

    def fake_search(query, limit=25, dismax=False):
        calls.append((query, dismax))
        return {"release-groups": [star] if query.startswith("alias:") else [radio]}

    monkeypatch.setattr(matcher, "mb_search", fake_search)
    monkeypatch.setattr(matcher, "_rg_aliases",
                        lambda mbid: [{"name": "Blackstar"}] if mbid == "star-id" else [])
    res = matcher.match_row("Blackstar", "David Bowie")
    assert res["status"] == "matched"
    assert res["release_group_mbid"] == "star-id"
    assert res["title_sim"] == 1.0
    assert any(q.startswith("alias:") and not d for q, d in calls)
    assert any(d for _, d in calls)          # unquoted fallback went via dismax
    assert "status:official" in calls[0][0]  # fielded rungs shed bootlegs


def test_unasked_live_release_goes_to_review_not_matched(monkeypatch):
    # "David Bowie — Ziggy Stardust" matches a live single titled exactly
    # that; the studio album is filed under another title. ask, don't push.
    import chartarr.matcher as m

    def fake_search(query, limit=25, dismax=False):
        return {"release-groups": [
            rg("Ziggy Stardust", "David Bowie", "live-single-id",
               ptype="Single", secondary=["Live"]),
        ]}

    monkeypatch.setattr(m, "mb_search", fake_search)
    monkeypatch.setattr(m, "_rg_aliases", lambda mbid: [])
    res = m.match_row("Ziggy Stardust", "David Bowie")
    assert res["status"] == "review"
    assert res["candidates"]


def test_asked_for_live_release_still_matches(monkeypatch):
    # "Live at the Apollo" wants the live record; don't second-guess it.
    import chartarr.matcher as m

    def fake_search(query, limit=25, dismax=False):
        return {"release-groups": [
            rg("Live at the Apollo", "James Brown", "apollo-id",
               ptype="Album", secondary=["Live"]),
        ]}

    monkeypatch.setattr(m, "mb_search", fake_search)
    monkeypatch.setattr(m, "_rg_aliases", lambda mbid: [])
    res = m.match_row("Live at the Apollo", "James Brown")
    assert res["status"] == "matched"
