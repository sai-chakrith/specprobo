from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class AuditEntry:
    workspace_id: str
    action: str
    actor: str
    payload: dict[str, Any]
    timestamp: datetime


class AuditLog:
    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []

    def append(self, workspace_id: str, action: str, actor: str, payload: dict[str, Any]) -> AuditEntry:
        entry = AuditEntry(workspace_id, action, actor, dict(payload), datetime.now(timezone.utc))
        self._entries.append(entry)
        return entry

    def entries(self, workspace_id: str) -> tuple[AuditEntry, ...]:
        return tuple(item for item in self._entries if item.workspace_id == workspace_id)


class WorkspaceRepository:
    def __init__(self) -> None:
        self._rows: dict[str, dict[str, dict[str, Any]]] = {}

    def put(self, workspace_id: str, row_id: str, row: dict[str, Any]) -> None:
        self._rows.setdefault(workspace_id, {})[row_id] = dict(row)

    def get(self, workspace_id: str, row_id: str) -> dict[str, Any] | None:
        row = self._rows.get(workspace_id, {}).get(row_id)
        return None if row is None else dict(row)

    def list(self, workspace_id: str) -> list[dict[str, Any]]:
        return [dict(row) for row in self._rows.get(workspace_id, {}).values()]


def collection_name(workspace_id: str, kind: str) -> str:
    if kind not in {"standard", "oem", "ecu", "project"}:
        raise ValueError("unsupported collection kind")
    return f"ws_{workspace_id}__{kind}"
