"""HTTP: the Trial detail shows who to contact (#27): central contact, overall official, sponsor, responsible party,
each Australian Trial site's facility and contacts, and the ClinicalTrials.gov link. Ingest behaviour is covered in
tests/trials; this checks the wiring."""
from __future__ import annotations

import httpx

from app import trials
from app.main import app
from tests.trials.test_ingest import AU, save_pages, site, study, with_contacts


async def test_the_trial_detail_lists_its_contacts_and_australian_sites(ctx, tmp_path):
    sydney = {**AU, "contacts": [{"name": "Sam Coordinator", "role": "CONTACT", "email": "sam@example.org"}]}
    await trials.ingest(ctx, save_pages(tmp_path, [with_contacts(study("NCT00000007", sites=[
        site("Mayo Clinic", "Rochester", "United States"), sydney]))]))
    app.state.ctx = ctx
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        detail = (await http.get("/api/trials/NCT00000007")).json()
        missing = await http.get("/api/trials/NCT09999999")

    assert detail["nct_id"] == "NCT00000007" and detail["status"] == "RECRUITING"
    assert detail["title"] == "Synthetic trial NCT00000007"
    assert detail["page_url"] == "https://clinicaltrials.gov/study/NCT00000007"
    assert detail["sponsor"] == "Example Oncology Group"
    assert detail["responsible_party"] == {"name": "Jane Citizen", "role": "PRINCIPAL_INVESTIGATOR", "email": "",
                                           "phone": "", "affiliation": "Example University", "title": "Professor"}
    assert [(c["name"], c["email"], c["phone"]) for c in detail["central_contacts"]] == [
        ("Trial Contact Centre", "trials@example.org", "1800 000 000")]
    assert [(c["name"], c["role"]) for c in detail["overall_officials"]] == [
        ("Dr Jane Citizen", "PRINCIPAL_INVESTIGATOR")]
    assert [(s["facility"], s["city"], s["status"], [c["email"] for c in s["contacts"]]) for s in detail["sites"]] == [
        ("Royal Prince Alfred Hospital", "Camperdown", "RECRUITING", ["sam@example.org"])]
    assert missing.status_code == 404


async def test_the_trial_detail_shows_a_closed_trials_outcomes(ctx, tmp_path):
    from tests.trials.test_outcomes import with_outcomes

    await trials.ingest(ctx, save_pages(tmp_path, [with_outcomes(study("NCT00000011", status="COMPLETED",
                                                                       primary_completion="2024-06", sites=[AU]))]))
    app.state.ctx = ctx
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        o = (await http.get("/api/trials/NCT00000011")).json()["outcomes"]

    assert o["primary"] == [{"measure": "Overall survival", "description": "Time from randomisation to death",
                             "time_frame": "Up to 5 years"}]
    assert [m["measure"] for m in o["secondary"]] == ["Progression-free survival", "Quality of life (EORTC QLQ-C30)"]
    assert [m["measure"] for m in o["other"]] == ["Biomarker levels"]
    assert o["has_results"] is True
    [result] = o["results"]
    assert (result["type"], result["title"], result["unit"], result["param_type"]) == (
        "PRIMARY", "Overall survival", "months", "MEDIAN")
    assert result["values"] == [
        {"group": "Drug A", "value": "18.2", "spread": "", "lower": "15.1", "upper": "21.0", "label": ""},
        {"group": "Placebo", "value": "12.4", "spread": "3.1", "lower": "", "upper": "", "label": ""}]
    assert o["publications"] == [
        {"pmid": "31000001", "type": "RESULT", "citation": "Citizen J, et al. Overall survival in NSCLC. 2024.",
         "url": "https://pubmed.ncbi.nlm.nih.gov/31000001/"},
        {"pmid": "", "type": "BACKGROUND", "citation": "Background reading without a PubMed id.", "url": ""}]
