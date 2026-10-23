"""app/api — thin HTTP shell over the facades. Parses requests, calls record / trials / matching /
trace, maps domain types to wire schemas. No business logic here. Endpoints: docs/api.md."""
from fastapi import APIRouter

from app.api import documents, health, patients, runs, trials, verdicts

router = APIRouter(prefix="/api")
for module in (patients, documents, runs, trials, verdicts, health):
    router.include_router(module.router)
