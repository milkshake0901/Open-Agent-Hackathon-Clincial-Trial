"""The request's Ctx (built once by the lifespan in app/main.py; tests set app.state.ctx directly)."""
from fastapi import Request

from app.ctx import Ctx


def get_ctx(request: Request) -> Ctx:
    return request.app.state.ctx
