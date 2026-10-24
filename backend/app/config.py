"""app/config.py — settings from .env (never committed; see .env.example)."""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings

_REPO = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    pg_dsn: str = "postgresql://trialmatch:trialmatch@localhost:5433/trialmatch"

    zetaris_rest_url: str = "http://localhost:8888/api/v1.0"
    zetaris_org_id: str = "1"
    zetaris_api_key: str = ""
    zetaris_datasource: str = "trialmatch"   # name our Postgres is registered under in Zetaris

    meterless_base_url: str = "http://127.0.0.1:8088/v1"
    meterless_runtime_token: str = ""
    meterless_app_id: str = "trialmatch"
    lane_models: dict[str, str] = {}          # lane → Nightshift model id; decided later

    intake_attempts: int = 3
    match_attempts: int = 3
    match_concurrency: int = 2
    zetaris_visibility_wait_s: float = 5.0

    raw_documents_dir: str = "data/raw"       # gitignored
    trials_snapshot_dir: str = str(_REPO / "data" / "trials_snapshot")   # saved Trials, loaded at start-up (#12)

    model_config = {"env_file": ".env"}
