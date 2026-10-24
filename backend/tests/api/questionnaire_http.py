"""Submit the Intake questionnaire over HTTP and follow its run, as the web form does: the response carries the
Document and its run; the ingest (then Re-scan) runs in the background, so the outcome is the run's state."""
from __future__ import annotations

from app import record


async def submit(http, patient: str, answers: dict, respondent: str = "patient") -> tuple[dict, dict]:
    """(the 202 body, the run's state once the background ingest has ended)."""
    r = await http.post(f"/api/patients/{patient}/questionnaire", json={
        "definition_version": record.questionnaire_definition().version, "respondent": respondent, "answers": answers})
    assert r.status_code == 202, r.text
    accepted = r.json()
    return accepted, (await http.get(f"/api/runs/{accepted['run_id']}")).json()["state"]
