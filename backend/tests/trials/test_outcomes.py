"""The trials facade's Outcomes read (#25): a Trial's planned outcome measures, whether it posted results and the
results themselves, and its linked publications, as the ingest stored them from saved ClinicalTrials.gov v2 pages."""
from __future__ import annotations

from app import trials, worldmodel
from tests.trials.test_ingest import AU, save_pages, study


def with_outcomes(raw):
    """The study with the outcome fields ClinicalTrials.gov lists: planned outcome measures, posted results for one
    primary measure across two groups, and two references."""
    p = raw["protocolSection"]
    p["outcomesModule"] = {
        "primaryOutcomes": [{"measure": "Overall survival", "description": "Time from randomisation to death",
                             "timeFrame": "Up to 5 years"}],
        "secondaryOutcomes": [{"measure": "Progression-free survival", "timeFrame": "Up to 3 years"},
                              {"measure": "Quality of life (EORTC QLQ-C30)"}],
        "otherOutcomes": [{"measure": "Biomarker levels"}]}
    p["referencesModule"] = {"references": [
        {"pmid": "31000001", "type": "RESULT", "citation": "Citizen J, et al. Overall survival in NSCLC. 2024."},
        {"type": "BACKGROUND", "citation": "Background reading without a PubMed id."}]}
    raw["hasResults"] = True
    raw["resultsSection"] = {"outcomeMeasuresModule": {"outcomeMeasures": [{
        "type": "PRIMARY", "title": "Overall survival", "description": "Median time to death",
        "timeFrame": "Up to 5 years", "unitOfMeasure": "months", "paramType": "MEDIAN",
        "groups": [{"id": "OG000", "title": "Drug A"}, {"id": "OG001", "title": "Placebo"}],
        "classes": [{"categories": [{"measurements": [
            {"groupId": "OG000", "value": "18.2", "lowerLimit": "15.1", "upperLimit": "21.0"},
            {"groupId": "OG001", "value": "12.4", "spread": "3.1"}]}]}]}]}}
    return raw


async def test_a_closed_trials_planned_outcome_measures_are_stored(ctx, tmp_path):
    await trials.ingest(ctx, save_pages(tmp_path, [with_outcomes(study("NCT00000011", status="COMPLETED",
                                                                       primary_completion="2024-06", sites=[AU]))]))

    o = await trials.outcomes(ctx, trials.NctId("NCT00000011"))

    assert o.primary == (trials.OutcomeMeasure(measure="Overall survival", description="Time from randomisation to death",
                                               time_frame="Up to 5 years"),)
    assert o.secondary == (trials.OutcomeMeasure(measure="Progression-free survival", time_frame="Up to 3 years"),
                           trials.OutcomeMeasure(measure="Quality of life (EORTC QLQ-C30)"))
    assert o.other == (trials.OutcomeMeasure(measure="Biomarker levels"),)


async def test_posted_results_are_stored_with_each_groups_values(ctx, tmp_path):
    await trials.ingest(ctx, save_pages(tmp_path, [with_outcomes(study("NCT00000011", status="COMPLETED",
                                                                       primary_completion="2024-06", sites=[AU]))]))

    o = await trials.outcomes(ctx, trials.NctId("NCT00000011"))

    assert o.has_results is True
    assert o.results == (trials.PostedResult(
        type="PRIMARY", title="Overall survival", description="Median time to death", time_frame="Up to 5 years",
        unit="months", param_type="MEDIAN", values=(
            trials.ResultValue(group="Drug A", value="18.2", lower="15.1", upper="21.0"),
            trials.ResultValue(group="Placebo", value="12.4", spread="3.1"))),)


async def test_a_trial_without_posted_results_says_so_and_has_no_outcomes_beyond_its_measures(ctx, tmp_path):
    await trials.ingest(ctx, save_pages(tmp_path, [study("NCT00000012", status="COMPLETED", sites=[AU])]))

    o = await trials.outcomes(ctx, trials.NctId("NCT00000012"))

    assert o == trials.Outcomes(primary=(), secondary=(), other=(), has_results=False, results=(), publications=())
    assert await trials.outcomes(ctx, trials.NctId("NCT09999999")) is None


async def test_linked_publications_are_stored_with_their_pubmed_links(ctx, tmp_path):
    await trials.ingest(ctx, save_pages(tmp_path, [with_outcomes(study("NCT00000011", status="COMPLETED",
                                                                       primary_completion="2024-06", sites=[AU]))]))

    o = await trials.outcomes(ctx, trials.NctId("NCT00000011"))

    assert o.publications == (
        trials.Publication(pmid="31000001", type="RESULT",
                           citation="Citizen J, et al. Overall survival in NSCLC. 2024."),
        trials.Publication(pmid="", type="BACKGROUND", citation="Background reading without a PubMed id."))
    assert [p.url for p in o.publications] == ["https://pubmed.ncbi.nlm.nih.gov/31000001/", ""]


async def test_changed_outcomes_replace_the_stored_ones(ctx, tmp_path):
    await trials.ingest(ctx, save_pages(tmp_path / "before", [with_outcomes(study("NCT00000011", status="COMPLETED",
                                                                                  sites=[AU]))]))
    later = study("NCT00000011", status="COMPLETED", sites=[AU])
    later["protocolSection"]["outcomesModule"] = {"primaryOutcomes": [{"measure": "Response rate"}]}

    report = await trials.ingest(ctx, save_pages(tmp_path / "after", [later]))

    assert report.changed == ("NCT00000011",)
    assert await trials.outcomes(ctx, trials.NctId("NCT00000011"), for_agent=True) == trials.Outcomes(
        primary=(trials.OutcomeMeasure(measure="Response rate"),), secondary=(), other=())


async def test_lost_outcomes_are_rebuilt_from_the_world_model_event_log(ctx, clean_db, tmp_path):
    await trials.ingest(ctx, save_pages(tmp_path / "before", [study("NCT00000011", status="COMPLETED", sites=[AU])]))
    await trials.ingest(ctx, save_pages(tmp_path / "after", [with_outcomes(study("NCT00000011", status="COMPLETED",
                                                                                 sites=[AU]))]))
    stored = await trials.outcomes(ctx, trials.NctId("NCT00000011"))
    await clean_db.execute("TRUNCATE trial_outcome_value, trial_outcome, trial_publication")  # the projection is lost
    await clean_db.execute("UPDATE trial SET has_results = false")

    await worldmodel.rebuild_projections(ctx.writer, ctx.wm.namespace)

    assert await trials.outcomes(ctx, trials.NctId("NCT00000011")) == stored
    assert stored.has_results and stored.results and stored.publications
