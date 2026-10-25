"""app/api — thin HTTP shell over the facades. Parses requests, calls record / trials / matching /
trace, maps domain types to wire schemas. No business logic here. Endpoints: docs/api.md."""
from fastapi import APIRouter

from app.api import documents, enquiries, health, patients, questionnaire, returns, runs, trials, verdicts
from app.api.deps import EXCEPTION_HANDLERS

__all__ = ["router", "EXCEPTION_HANDLERS"]

router = APIRouter(prefix="/api")
for module in (questionnaire, returns, patients, documents, runs, trials, verdicts, enquiries, health):
    router.include_router(module.router)
