import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AuditLogRow


def _content(row: AuditLogRow) -> str:
    return json.dumps(
        {
            "id": row.id,
            "workspace_id": row.workspace_id,
            "action": row.action,
            "actor": row.actor,
            "payload": row.payload,
            "timestamp": row.timestamp.isoformat(),
            "previous_hash": row.previous_hash,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _digest(row: AuditLogRow) -> str:
    return hashlib.sha256(_content(row).encode("utf-8")).hexdigest()


class AuditLog:
    def __init__(self, session: Session) -> None:
        self.session = session

    def append(
        self, workspace_id: str, action: str, actor: str, payload: dict[str, Any]
    ) -> AuditLogRow:
        # A database write lock serializes the read/hash/append transaction across processes.
        self.session.connection().exec_driver_sql("UPDATE audit_mutex SET value=value+1 WHERE id=1")
        previous = self.session.scalar(select(AuditLogRow).order_by(AuditLogRow.id.desc()).limit(1))
        row = AuditLogRow(
            id=(previous.id + 1) if previous else 1,
            workspace_id=workspace_id,
            action=action,
            actor=actor,
            payload=dict(payload),
            timestamp=datetime.now(UTC).replace(tzinfo=None),
            previous_hash=previous.row_hash if previous else "",
            row_hash="pending",
        )
        row.row_hash = _digest(row)
        self.session.add(row)
        self.session.flush()
        return row

    def verify_chain(self) -> bool:
        rows = list(self.session.scalars(select(AuditLogRow).order_by(AuditLogRow.id)))
        previous = ""
        for row in rows:
            if row.previous_hash != previous or row.row_hash != _digest(row):
                return False
            previous = row.row_hash
        return True
