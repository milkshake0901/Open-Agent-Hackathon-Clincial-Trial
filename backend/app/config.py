"""app/config.py — settings from .env (never committed; see .env.example)."""
from __future__ import annotations

from pydantic_settings import BaseSettings

NEMOTRON_LIGHTNING = "nvidia/nemotron-3.5-lightning-30b-a3b"   # listed by this box's GET /v1/models


class Settings(BaseSettings):
    pg_dsn: str = "postgresql://trialmatch:trialmatch@localhost:5433/trialmatch"

    zetaris_rest_url: str = "http://localhost:8888/api/v1.0"
    zetaris_org_id: str = "1"
    zetaris_api_key: str = ""
    zetaris_datasource: str = "trialmatch"   # name our Postgres is registered under in Zetaris

    meterless_base_url: str = "http://127.0.0.1:8088/v1"
    meterless_runtime_token: str = ""
    meterless_app_id: str = "trialmatch"
    meterless_model: str = NEMOTRON_LIGHTNING  # plain text calls outside a lane
    # lane → Nightshift model id. Pinned to a Nemotron lane (meterless/auto may route elsewhere);
    # override with LANE_MODELS='{"deep": "..."}'. Per-lane choice is still open.
    lane_models: dict[str, str] = {"fast": NEMOTRON_LIGHTNING, "deep": NEMOTRON_LIGHTNING, "judge": NEMOTRON_LIGHTNING}

    media_dir: str = "data/media"             # generated images and audio; gitignored
    media_privacy: str = "local-only"         # floor for media source jobs: local-only | edge-only | cloud-ok

    intake_attempts: int = 3
    match_attempts: int = 3
    match_concurrency: int = 2
    zetaris_visibility_wait_s: float = 5.0

    raw_documents_dir: str = "data/raw"       # gitignored

    model_config = {"env_file": ("../.env", ".env")}   # repo root .env, whether run from the root or backend/
