"""app/record/storage.py — a clinical Document's identity and its raw bytes on disk. Private to record.

The raw bytes are kept only on disk (settings.raw_documents_dir), never in Postgres and never shown: Citations display
the de-identified page text.
"""
from __future__ import annotations

import hashlib
from pathlib import Path, PurePath

from app.record.types import DocumentHash, PatientId


def document_hash(patient_id: PatientId, content: bytes) -> DocumentHash:
    """Document hashes are global keys, so the patient is part of an added Document's identity: the same bytes from two
    patients are two Documents, and one patient's Document can never resolve to another patient's pages."""
    return DocumentHash(hashlib.sha256(f"document\n{patient_id}\n".encode() + content).hexdigest())


def filename(raw: str) -> str:
    """The file's own name, without any client-side path."""
    return PurePath(raw.replace("\\", "/")).name or "document.pdf"


def keep_raw(directory: str, h: DocumentHash, content: bytes) -> None:
    raw = Path(directory)
    raw.mkdir(parents=True, exist_ok=True)
    (raw / f"{h}.pdf").write_bytes(content)
