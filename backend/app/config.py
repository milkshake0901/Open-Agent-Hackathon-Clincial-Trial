"""app/config.py — settings from .env (never committed; see .env.example)."""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings

_REPO = Path(__file__).resolve().parents[2]
NEMOTRON_LIGHTNING = "nvidia/nemotron-3.5-lightning-30b-a3b"   # listed by this box's GET /v1/models
NEMOTRON_ULTRA = "nvidia/nemotron-3-ultra-550b-a55b"


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
    # Nemotron Parse only. A separate Doppler secret from the Nightshift NVIDIA key. Never commit it.
    nvidia_parse_api_key: str = ""
    nvidia_parse_model: str = "nvidia/nemotron-parse"
    # lane → Nightshift model id, pinned rather than meterless/* so the model behind each agent is fixed (DEVELOPER.md).
    # All on Ultra: Lightning stops at ~60 s on the Intake prompt and is switched off in this box's Compute sources.
    # Once it is on, move judge to Lightning so a second model checks the Matcher. Override with LANE_MODELS='{...}'.
    lane_models: dict[str, str] = {"fast": NEMOTRON_ULTRA, "deep": NEMOTRON_ULTRA, "judge": NEMOTRON_ULTRA}

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
