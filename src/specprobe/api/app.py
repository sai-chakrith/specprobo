import tempfile
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from ..demo import build_spec
from ..gen.generator import generate_suite
from ..ingest.extractor import extract_fields
from ..ingest.parsers import parse_excel, parse_pdf
from ..runner.executor import run_suite
from ..sim.auto_mutants import classify_survivors, run_auto_mutants
from ..sim.ecu import EcuSimulator
from ..storage.db import create_database, session_factory
from ..storage.models import Review, TestRun, Workspace
from ..storage.repository import WorkspaceRepository, create_workspace
from ..storage.vectorstore import InMemoryVectorBackend, ScopedVectorStore


class WorkspaceRequest(BaseModel):
    workspace_id: str = Field(min_length=1)
    api_key: str = Field(min_length=1)


class ReviewRequest(BaseModel):
    decision: str
    value: dict[str, Any] | None = None


def create_app(engine: Engine | None = None) -> FastAPI:
    app = FastAPI(title="SpecProbe review API")
    app.state.engine = engine or create_database()
    app.state.sessions = session_factory(app.state.engine)

    def repository(workspace_id: str, api_key: str | None) -> tuple[Session, WorkspaceRepository]:
        if not api_key:
            raise HTTPException(status_code=401, detail="missing X-API-Key")
        session = app.state.sessions()
        repo = WorkspaceRepository(
            session, ScopedVectorStore(InMemoryVectorBackend(), workspace_id), workspace_id, api_key
        )
        try:
            repo._authorize()
        except PermissionError as error:
            session.close()
            raise HTTPException(status_code=403, detail="workspace access denied") from error
        return session, repo

    @app.post("/workspaces")
    def create_workspace_route(request: WorkspaceRequest) -> dict[str, str]:
        session = app.state.sessions()
        if session.get(Workspace, request.workspace_id) is not None:
            raise HTTPException(status_code=409, detail="workspace exists")
        create_workspace(session, request.workspace_id, request.api_key)
        return {"workspace_id": request.workspace_id, "api_key": request.api_key}

    @app.post("/workspaces/{workspace_id}/documents")
    async def upload_document(
        workspace_id: str,
        file: Annotated[UploadFile, File()],
        x_api_key: str | None = Header(default=None),
    ) -> dict[str, Any]:
        session, repo = repository(workspace_id, x_api_key)
        content = await file.read()
        document = repo.add_document(
            file.filename or "document", content.decode("utf-8", errors="ignore")
        )
        suffix = Path(file.filename or "").suffix.lower()
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temporary:
            temporary.write(content)
            temporary_path = Path(temporary.name)
        try:
            parser = parse_pdf if suffix == ".pdf" else parse_excel
            blocks, rows = parser(temporary_path, document.id)
            proposed = extract_fields(document.id, rows, blocks)
            fields = [
                {
                    "document_id": document.id,
                    "json_path": field.path,
                    "value": (
                        field.value if isinstance(field.value, dict) else {"value": field.value}
                    ),
                }
                for field in proposed
            ]
            stored = repo.propose_fields(fields, "upload")
        finally:
            temporary_path.unlink(missing_ok=True)
            session.close()
        return {"document_id": document.id, "field_ids": [field.id for field in stored]}

    @app.get("/workspaces/{workspace_id}/fields")
    def list_fields(
        workspace_id: str, x_api_key: str | None = Header(default=None)
    ) -> list[dict[str, Any]]:
        session, repo = repository(workspace_id, x_api_key)
        fields = repo.list_fields()
        reviews = session.scalars(select(Review).where(Review.workspace_id == workspace_id))
        decisions = {review.field_id: review.decision for review in reviews}
        result = [
            {
                "id": field.id,
                "json_path": field.json_path,
                "value": field.value,
                "status": decisions.get(field.id, "proposed"),
            }
            for field in fields
        ]
        session.close()
        return result

    @app.post("/workspaces/{workspace_id}/fields/{field_id}/review")
    def review_field(
        workspace_id: str,
        field_id: str,
        request: ReviewRequest,
        x_api_key: str | None = Header(default=None),
    ) -> dict[str, str]:
        session, repo = repository(workspace_id, x_api_key)
        try:
            review = repo.review_field(field_id, request.decision, "api", request.value)
        except (PermissionError, ValueError) as error:
            session.close()
            raise HTTPException(status_code=403, detail=str(error)) from error
        session.close()
        return {"review_id": review.id, "decision": review.decision}

    @app.post("/workspaces/{workspace_id}/suites/{suite_id}")
    def generate_suite_route(
        workspace_id: str, suite_id: str, x_api_key: str | None = Header(default=None)
    ) -> dict[str, Any]:
        session, repo = repository(workspace_id, x_api_key)
        approved = repo.list_approved_fields()
        payload = {
            "approved_field_ids": [field.id for field in approved],
            "case_count": len(generate_suite(build_spec())),
        }
        repo.generate_suite(suite_id, payload, "api")
        session.close()
        return payload

    @app.post("/workspaces/{workspace_id}/runs/{run_id}")
    def run_route(
        workspace_id: str,
        run_id: str,
        suite_id: str,
        mutants: bool = False,
        x_api_key: str | None = Header(default=None),
    ) -> dict[str, Any]:
        session, repo = repository(workspace_id, x_api_key)
        spec = build_spec()
        suite = generate_suite(spec)
        clean = run_suite(suite, EcuSimulator(spec))
        report: dict[str, Any] = {
            "passed": sum(result.passed for result in clean),
            "total": len(clean),
        }
        if mutants:
            results = run_auto_mutants(spec, suite)
            survivors = [
                item
                for item in results
                if item.compilable and not item.killed_by and not item.crashed_by
            ]
            report["mutants"] = [item.__dict__ for item in results]
            report["classifications"] = classify_survivors(spec, survivors)
        repo.record_run(run_id, suite_id, report, "api")
        session.close()
        return report

    @app.get("/workspaces/{workspace_id}/runs/{run_id}")
    def get_run(
        workspace_id: str, run_id: str, x_api_key: str | None = Header(default=None)
    ) -> dict[str, Any]:
        session, repo = repository(workspace_id, x_api_key)
        row = session.scalar(
            select(TestRun).where(TestRun.id == run_id, TestRun.workspace_id == workspace_id)
        )
        session.close()
        if row is None:
            raise HTTPException(status_code=404, detail="run not found")
        return row.report

    return app


app = create_app()
