"""Config's REPO_ROOT is the folder scripts anchor .env, data/raw and data/media to (#40)."""
from __future__ import annotations

from app.config import REPO_ROOT


def test_repo_root_holds_backend_frontend_and_env_template():
    assert (REPO_ROOT / "backend").is_dir()
    assert (REPO_ROOT / "frontend").is_dir()
    assert (REPO_ROOT / ".env.example").is_file()
