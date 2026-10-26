"""The recruiting search is condition plus place. A prior drug is not a required term."""
from app.trials.ctgov import location_for_search, studies_url


def test_the_search_is_recruiting_for_the_condition_and_place():
    url = studies_url("metastatic castration-resistant prostate cancer", "UK", 20)
    assert "query.cond=metastatic+castration-resistant+prostate+cancer" in url
    assert "filter.overallStatus=RECRUITING" in url
    assert "query.locn=United+Kingdom" in url
    assert "query.term" not in url
    assert "cabazitaxel" not in url


def test_united_kingdom_is_how_uk_sites_are_indexed():
    assert location_for_search("UK") == "United Kingdom"
    assert location_for_search("Hong Kong") == "Hong Kong"
