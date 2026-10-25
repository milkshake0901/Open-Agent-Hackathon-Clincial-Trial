"""app/config.py — settings from .env (never committed; see .env.example)."""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings

_REPO = Path(__file__).resolve().parents[2]
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
    trials_snapshot_dir: str = str(_REPO / "data" / "trials_snapshot")   # saved Trials, loaded at start-up (#12)

    # every pipeline step and model call, one JSON object per line (app/logfile.py, #35); gitignored
    log_file: str = str(_REPO / "data" / "logs" / "trialmatch.jsonl")
    log_max_bytes: int = 10_000_000           # rotated at this size, keeping log_backups old files (.1, .2, ...)
    log_backups: int = 5

    # repo root .env, whether run from the root or backend/; keys other tools use (Zetaris admin, scripts) are ignored
    model_config = {"env_file": ("../.env", ".env"), "extra": "ignore"}
