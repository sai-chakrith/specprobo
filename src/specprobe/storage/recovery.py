"""Durable, idempotent indexing and SQLite online backups."""

import hashlib
import json
import sqlite3
from pathlib import Path

from sqlalchemy.orm import Session

from .models import Document, IndexJob
from .vectorstore import ScopedVectorStore


def recover_index(session: Session, document: Document, vectors: ScopedVectorStore) -> IndexJob:
    job = session.get(IndexJob, document.id)
    if job is None:
        job = IndexJob(document_id=document.id, status="pending", attempts=0, error="")
        session.add(job)
    job.status = "indexing"
    job.attempts += 1
    session.commit()
    try:
        envelope = json.loads(document.content)
        for index, block in enumerate(envelope["blocks"]):
            vectors.add(
                envelope["kind"],
                f"{document.id}:{index}",
                block["text"],
                {
                    "document_id": document.id,
                    "name": document.name,
                    "page": str(block.get("page") or ""),
                    "sheet": block.get("sheet") or "",
                    "row": str(block.get("row") or ""),
                },
            )
        job.status, job.error = "complete", ""
    except Exception as error:
        # Failed jobs remain durable; callers can retry after restart with original IDs.
        job.status, job.error = "failed", type(error).__name__
    session.commit()
    return job


def backup_database(source: Path, destination: Path) -> str:
    if source.resolve() == destination.resolve() or destination.exists():
        raise ValueError("Backup must use a new destination")
    with sqlite3.connect(f"file:{source.resolve().as_posix()}?mode=ro", uri=True) as origin:
        with sqlite3.connect(destination) as target:
            origin.backup(target)
            if target.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise ValueError("Backup integrity check failed")
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_suffix(destination.suffix + ".sha256").write_text(digest, encoding="utf-8")
    return digest
