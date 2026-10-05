from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from .audit import AuditLog
from .models import AuditLogRow, Document, Review, TestCaseRow, TestRun, Workspace
from .vectorstore import ScopedVectorStore


class WorkspaceRepository:
    def __init__(
        self, session: Session, vectors: ScopedVectorStore, workspace_id: str, api_key: str
    ) -> None:
        self.session = session
        self.vectors = vectors
        self.workspace_id = workspace_id
        self.api_key = api_key

    def _authorize(self) -> None:
        workspace = self.session.get(Workspace, self.workspace_id)
        if workspace is None or workspace.api_key != self.api_key:
            raise PermissionError("workspace access denied")

    def add_document(self, name: str, content: str) -> Document:
        self._authorize()
        document = Document(
            id=str(uuid4()),
            workspace_id=self.workspace_id,
            name=name,
            content=content,
            created_at=datetime.now(UTC).replace(tzinfo=None),
        )
        self.session.add(document)
        self.session.commit()
        return document

    def list_documents(self) -> list[Document]:
        self._authorize()
        return list(
            self.session.scalars(select(Document).where(Document.workspace_id == self.workspace_id))
        )

    def review_field(self, field_id: str, decision: str, reviewer: str) -> Review:
        self._authorize()
        review = Review(
            id=str(uuid4()),
            workspace_id=self.workspace_id,
            field_id=field_id,
            decision=decision,
            reviewer=reviewer,
            created_at=datetime.now(UTC).replace(tzinfo=None),
        )
        self.session.add(review)
        AuditLog(self.session).append(
            self.workspace_id,
            "review_decision",
            reviewer,
            {"field_id": field_id, "decision": decision},
        )
        self.session.commit()
        return review

    def generate_suite(self, suite_id: str, payload: dict[str, Any], actor: str) -> TestCaseRow:
        self._authorize()
        row = TestCaseRow(
            id=suite_id,
            workspace_id=self.workspace_id,
            payload=dict(payload),
            created_at=datetime.now(UTC).replace(tzinfo=None),
        )
        self.session.add(row)
        AuditLog(self.session).append(
            self.workspace_id, "suite_generation", actor, {"suite_id": suite_id}
        )
        self.session.commit()
        return row

    def record_run(self, run_id: str, suite_id: str, report: dict[str, Any], actor: str) -> TestRun:
        self._authorize()
        row = TestRun(
            id=run_id,
            workspace_id=self.workspace_id,
            suite_id=suite_id,
            report=dict(report),
            created_at=datetime.now(UTC).replace(tzinfo=None),
        )
        self.session.add(row)
        AuditLog(self.session).append(
            self.workspace_id, "suite_run", actor, {"run_id": run_id, "suite_id": suite_id}
        )
        self.session.commit()
        return row

    def audit_entries(self) -> list[AuditLogRow]:
        self._authorize()
        return list(
            self.session.scalars(
                select(AuditLogRow).where(AuditLogRow.workspace_id == self.workspace_id)
            )
        )


def create_workspace(session: Session, workspace_id: str, api_key: str) -> Workspace:
    workspace = Workspace(
        id=workspace_id, api_key=api_key, created_at=datetime.now(UTC).replace(tzinfo=None)
    )
    session.add(workspace)
    session.commit()
    return workspace
