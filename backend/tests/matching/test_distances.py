"""Site distances (#16) through the matching facade. The postcode is a search preference: code turns it into a
coarse point, the Matcher sees each site only as "site name · status · km", and distance ranks Verdicts (outcome,
then nearest recruiting site) without ever changing one. Trials beyond the travel limit are flagged, never dropped."""
from __future__ import annotations

from app import matching, trials
from tests.matching.test_rescan import ANSWERS, NCT, _setup, answer_all, script, study, write_snapshot


def unknown_everywhere(user):
    return [{"criterion_id": line.split()[1], "outcome": "unknown", "fact_id": None, "rationale": "x"}
            for line in user.splitlines() if line.startswith("- NCT")]


async def test_the_matcher_sees_sites_as_name_status_and_km_and_never_the_postcode(clean_db):
    ctx, fake, version = await _setup(clean_db)          # postcode 2031 (Randwick, Sydney)
    script(fake, answer_all(await trials.criteria(ctx, NCT)))

    await matching.rescan(ctx, version.id)

    prompt = next(c for c in fake.calls if c.lane == "deep").user
    sites = prompt.split("Sites", 1)[1].splitlines()[1:]
    # Camperdown is ~6 km from Randwick, Westmead ~26 km; both Australian sites are not yet recruiting.
    assert sites[0] == "- Local Institution - 0424, Camperdown, Australia · not yet recruiting · 6 km"
    assert sites[1] == "- Local Institution - 0439, Westmead, Australia · not yet recruiting · 26 km"
    assert "2031" not in "".join(c.system + c.user for c in fake.calls)
    assert all("2031" not in f.value and "2031" not in f.quote for f in version.facts)


CAMPERDOWN, WESTMEAD, MELBOURNE = (-33.89, 151.18), (-33.80, 150.99), (-37.81, 144.96)   # ~6, ~26, ~700 km


def located(nct, sites, **kw):
    """A synthetic study (test_rescan.study) with locations: (facility, city, status, (lat, lon))."""
    s = study(nct, **kw)
    s["protocolSection"]["contactsLocationsModule"] = {"locations": [
        {"facility": f, "city": c, "country": "Australia", "status": st, "geoPoint": {"lat": p[0], "lon": p[1]}}
        for f, c, st, p in sites]}
    return s


ECOG = {"inclusion": ["ECOG Performance Status 0-1"]}
RANKING_SNAPSHOT = [
    located("NCT00000011", [("Near Not Yet", "Camperdown", "NOT_YET_RECRUITING", CAMPERDOWN),
                            ("Westmead Hospital", "Westmead", "RECRUITING", WESTMEAD)], **ECOG),
    located("NCT00000012", [("RPA", "Camperdown", "RECRUITING", CAMPERDOWN)], **ECOG),
    located("NCT00000013", [("Peter Mac", "Melbourne", "RECRUITING", MELBOURNE)], **ECOG),
    located("NCT00000014", [("Next Door", "Camperdown", "RECRUITING", CAMPERDOWN)],
            inclusion=["Female participants"], exclusion=["Fully active patients"]),
]


def ecog_met_matcher(facts):
    def matcher(user):
        out = []
        for line in (l for l in user.splitlines() if l.startswith("- NCT")):
            c = line.split()[1]
            if "ECOG" in line or "Fully active" in line:
                out.append({"criterion_id": c, "outcome": "met", "fact_id": facts["daily activity"].id, "rationale": "x"})
            elif "Female" in line:
                out.append({"criterion_id": c, "outcome": "met", "fact_id": facts["sex assigned at birth"].id,
                            "rationale": "x"})
            else:
                out.append({"criterion_id": c, "outcome": "unknown", "fact_id": None, "rationale": "x"})
        return out
    return matcher


async def test_verdicts_rank_by_outcome_then_nearest_recruiting_site_and_trials_beyond_the_limit_are_flagged(
        clean_db, tmp_path):
    ctx, fake, version = await _setup(clean_db, answers={**ANSWERS, "max_travel_km": "50"},
                                      snapshot=write_snapshot(tmp_path, RANKING_SNAPSHOT))
    script(fake, ecog_met_matcher(version.current()))
    await matching.rescan(ctx, version.id)

    ranked = await matching.verdicts_for_version(ctx, version.id)

    assert [(v.nct_id, v.outcome, v.further_away) for v in ranked] == [
        ("NCT00000012", "eligible", False),       # recruiting site ~6 km
        ("NCT00000011", "eligible", False),       # recruiting site ~26 km (a closer site is not yet recruiting)
        ("NCT00000013", "eligible", True),        # ~700 km: beyond 50 km, still listed
        (NCT, "possible", True),                  # recruiting sites are overseas
        ("NCT00000014", "excluded", False),       # nearest of all, but outcome ranks first
    ]
    by_id = {v.nct_id: v for v in ranked}
    assert by_id["NCT00000011"].nearest_site == matching.TrialSiteDistance(
        "Westmead Hospital, Westmead, Australia", "recruiting", 26)
    assert by_id["NCT00000011"].sites[0] == matching.TrialSiteDistance(
        "Near Not Yet, Camperdown, Australia", "not yet recruiting", 6)


async def _ranked(clean_db, tmp_path, answers):
    ctx, fake, version = await _setup(clean_db, answers=answers, snapshot=write_snapshot(tmp_path, RANKING_SNAPSHOT))
    script(fake, ecog_met_matcher(version.current()))
    await matching.rescan(ctx, version.id)
    return fake, await matching.verdicts_for_version(ctx, version.id)


async def test_the_same_verdict_outcomes_result_with_and_without_a_postcode(clean_db, tmp_path):
    from app import record
    ctx, fake, version = await _setup(clean_db, answers={**ANSWERS, "max_travel_km": "50"},
                                      snapshot=write_snapshot(tmp_path, RANKING_SNAPSHOT))
    script(fake, ecog_met_matcher(version.current()))
    await matching.rescan(ctx, version.id)
    outcomes = {v.nct_id: v.outcome for v in await matching.verdicts_for_version(ctx, version.id)}
    other = await record.create_patient(ctx, "Demo patient without a postcode")
    no_postcode = {k: v for k, v in ANSWERS.items() if k != "postcode"}
    v2 = (await record.submit_questionnaire(ctx, other, {**no_postcode, "max_travel_km": "50"},
                                            respondent="other")).version
    script(fake, ecog_met_matcher((await record.profile_version(ctx, v2.id)).current()))
    fake.calls.clear()

    await matching.rescan(ctx, v2.id)
    without = await matching.verdicts_for_version(ctx, v2.id)

    assert {v.nct_id: v.outcome for v in without} == outcomes
    assert all(sd.km is None for v in without for sd in v.sites)
    assert not any(v.further_away for v in without)       # unknown distance is never "further away"
    assert "· distance unknown" in next(c for c in fake.calls if c.lane == "deep").user


async def test_an_unknown_postcode_means_distance_unknown_and_the_trial_is_still_listed(clean_db, tmp_path):
    fake, ranked = await _ranked(clean_db, tmp_path, {**ANSWERS, "postcode": "0872", "max_travel_km": "10"})

    assert len(ranked) == 5
    assert all(v.nearest_site is None or v.nearest_site.km is None for v in ranked)
    assert not any(v.further_away for v in ranked)
    assert "0872" not in "".join(c.system + c.user for c in fake.calls)


async def test_the_snapshot_trials_nearest_recruiting_site_is_overseas_while_its_sydney_sites_are_not_yet_open(
        clean_db):
    ctx, fake, version = await _setup(clean_db, answers={**ANSWERS, "max_travel_km": "100"})
    script(fake, answer_all(await trials.criteria(ctx, NCT)))
    await matching.rescan(ctx, version.id)

    [v] = await matching.verdicts_for_version(ctx, version.id)

    # Of its recruiting sites, Taichung (Taiwan) is nearest to Randwick: ~7,200 km.
    assert v.nearest_site == matching.TrialSiteDistance("China Medical University Hospital, Taichung, Taiwan",
                                                   "recruiting", 7219)
    assert v.further_away
    assert v.sites[0] == matching.TrialSiteDistance("Local Institution - 0424, Camperdown, Australia",
                                               "not yet recruiting", 6)
    assert not any("withdrawn" in sd.status for sd in v.sites)
    assert v == await matching.verdict(ctx, NCT, version.id)
