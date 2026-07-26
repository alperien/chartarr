"""demo data sanity."""
from chartarr.demo import ITEMS


def test_demo_items_are_well_formed():
    keys = [res["key"] for _, res in ITEMS]
    assert len(keys) == len(set(keys))
    for row, res in ITEMS:
        assert row["artist"] and row["title"]
        assert res["status"] in ("review", "not_found")
        for c in res["candidates"]:
            assert c["release_group_mbid"]
            assert 0 <= c["title_sim"] <= 1


def test_demo_covers_the_interesting_states():
    statuses = {res["status"] for _, res in ITEMS}
    assert "review" in statuses
    assert "not_found" in statuses
    assert max(len(res["candidates"]) for _, res in ITEMS) >= 2


def test_demo_catalog_is_well_formed():
    from chartarr.demo import CATALOG
    assert len(CATALOG) >= 30
    for artist, title, year, genre in CATALOG:
        assert artist and title and year and genre
