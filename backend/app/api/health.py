"""Startup and demo check: is each sponsor layer actually reachable?"""
from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    """{postgres, zetaris, nightshift: {status: online|unauthorized|offline, models}, world_model: {events, head}}"""
    raise NotImplementedError
