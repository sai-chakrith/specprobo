import json
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal, cast
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..domain.schema import EcuSpec
from ..gen.generator import generate_suite
from ..ingest.extractor import extract_spec_fields
from ..ingest.llm import OllamaClient
from ..ingest.models import TextBlock
from ..ingest.parsers import parse_excel, parse_pdf
from ..rules.oracle import State, step
from ..runner.executor import run_suite
from ..sim.auto_mutants import classify_survivors, run_auto_mutants
from ..sim.ecu import EcuSimulator
from ..storage.audit import AuditLog
from ..storage.db import create_database, session_factory
from ..storage.models import Document, Review, TestCaseRow, TestRun
from ..storage.repository import WorkspaceRepository, create_workspace
from ..storage.vectorstore import (
    ChromaVectorBackend,
    HashEmbedding,
    InMemoryVectorBackend,
    LocalEmbedding,
    ScopedVectorStore,
    VectorBackend,
)
from ..workflow import (
    assemble_spec,
    case_payload,
    coverage,
    export_python,
    restore_case,
    snapshot_hash,
    spec_fields,
    validate_spec,
)


class WorkspaceRequest(BaseModel):
    workspace_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    api_key: str = Field(min_length=8)


class ReviewRequest(BaseModel):
    decision: Literal["approved", "edited", "rejected"]
    value: dict[str, Any] | None = None
    reviewer: str = Field(min_length=1, default="engineer")


class ApprovalRequest(BaseModel):
    reviewer: str = Field(min_length=1)
    approved: bool


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    kind: Literal["standard", "oem", "ecu", "project"] = "oem"
    use_llm: bool = False


class MessageRequest(BaseModel):
    request_hex: str
    setup_hex: list[str] = Field(default_factory=list)
    environment: dict[str, Any] = Field(default_factory=dict)
    actual_hex: str | None = None


class BatchReviewRequest(BaseModel):
    reviewer: str = Field(min_length=1)
    field_ids: list[str] = Field(min_length=1, max_length=1000)


def create_app(engine: Engine | None = None, backend: VectorBackend | None = None) -> FastAPI:
    app = FastAPI(title="SpecProbe diagnostics assistant")
    app.state.engine = (
        engine
        if engine is not None
        else create_database(os.environ.get("SPECPROBE_DATABASE_URL", "sqlite:///specprobe.db"))
    )
    app.state.sessions = session_factory(app.state.engine)
    if backend is None:
        if engine is not None:
            backend = InMemoryVectorBackend()
        else:
            embedding = (
                LocalEmbedding()
                if os.environ.get("SPECPROBE_EMBED_MODEL_PATH")
                else (HashEmbedding(dimension=256))
            )
            backend = ChromaVectorBackend(
                os.environ.get("SPECPROBE_VECTOR_PATH", ".specprobe/chroma"), embedding
            )
    app.state.backend = backend

    def session_dependency() -> Any:
        session = app.state.sessions()
        try:
            yield session
        except IntegrityError as error:
            session.rollback()
            raise HTTPException(409, "Identifier already exists") from error
        finally:
            session.close()

    SessionDep = Annotated[Session, Depends(session_dependency)]

    def repository(workspace_id: str, session: Session, api_key: str | None) -> WorkspaceRepository:
        if not api_key:
            raise HTTPException(401, "missing X-API-Key")
        repo = WorkspaceRepository(
            session, ScopedVectorStore(app.state.backend, workspace_id), workspace_id, api_key
        )
        try:
            repo._authorize()
        except PermissionError as error:
            raise HTTPException(403, "workspace access denied") from error
        return repo

    def document(repo: WorkspaceRepository, document_id: str) -> Document:
        row = repo.session.scalar(
            select(Document).where(
                Document.id == document_id, Document.workspace_id == repo.workspace_id
            )
        )
        if row is None:
            raise HTTPException(404, "Document not found")
        return row

    def suite(repo: WorkspaceRepository, suite_id: str) -> TestCaseRow:
        row = repo.session.scalar(
            select(TestCaseRow).where(
                TestCaseRow.id == suite_id, TestCaseRow.workspace_id == repo.workspace_id
            )
        )
        if row is None:
            raise HTTPException(404, "Suite not found")
        return row

    def is_approved(
        repo: WorkspaceRepository, action: str, identifier: str, digest: str | None = None
    ) -> bool:
        entries = [
            row
            for row in repo.audit_entries()
            if row.action == action and row.payload.get("id") == identifier
        ]
        return bool(
            entries
            and entries[-1].payload.get("approved")
            and (digest is None or entries[-1].payload.get("hash") == digest)
        )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "execution": "simulator"}

    @app.post("/workspaces")
    def create_workspace_route(request: WorkspaceRequest, session: SessionDep) -> dict[str, str]:
        create_workspace(session, request.workspace_id, request.api_key)
        return {"workspace_id": request.workspace_id}

    @app.get("/workspaces/{workspace_id}/documents")
    def list_documents(
        workspace_id: str, session: SessionDep, x_api_key: str | None = Header(default=None)
    ) -> list[dict[str, Any]]:
        repo = repository(workspace_id, session, x_api_key)
        return [
            {
                "id": row.id,
                "name": row.name,
                "kind": json.loads(row.content)["kind"],
                "approved": is_approved(repo, "document_review", row.id),
            }
            for row in repo.list_documents()
        ]

    @app.post("/workspaces/{workspace_id}/documents")
    async def upload_document(
        workspace_id: str,
        session: SessionDep,
        file: Annotated[UploadFile, File()],
        kind: Literal["standard", "oem", "ecu", "project"] = "oem",
        x_api_key: str | None = Header(default=None),
    ) -> dict[str, Any]:
        repo = repository(workspace_id, session, x_api_key)
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in {".pdf", ".xlsx", ".json", ".txt", ".md"}:
            raise HTTPException(415, "Use PDF, XLSX, EcuSpec JSON, TXT or Markdown")
        raw = await file.read(10 * 1024 * 1024 + 1)
        if len(raw) > 10 * 1024 * 1024:
            raise HTTPException(413, "Maximum document size is 10 MB")
        document_id = str(uuid4())
        proposals: list[dict[str, Any]] = []
        try:
            if suffix == ".json":
                spec = EcuSpec.model_validate_json(raw)
                validate_spec(spec)
                blocks = [
                    TextBlock(document_id, f"{path}: {json.dumps(value)}", row=i + 1)
                    for i, (path, value) in enumerate(spec_fields(spec))
                ]
                proposals = [
                    {
                        "document_id": document_id,
                        "json_path": path,
                        "value": {
                            "value": value,
                            "provenance": {
                                "row": i + 1,
                                "source_snippet": blocks[i].text,
                                "confidence": 1.0,
                            },
                        },
                    }
                    for i, (path, value) in enumerate(spec_fields(spec))
                ]
            elif suffix in {".txt", ".md"}:
                blocks = [
                    TextBlock(document_id, text, row=i + 1)
                    for i, text in enumerate(raw.decode("utf-8").splitlines())
                    if text.strip()
                ]
            else:
                with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temporary:
                    temporary.write(raw)
                    temporary_path = Path(temporary.name)
                try:
                    blocks, rows = (parse_pdf if suffix == ".pdf" else parse_excel)(
                        temporary_path, document_id
                    )
                    llm = (
                        OllamaClient(model=os.environ.get("SPECPROBE_OLLAMA_MODEL", "llama3.2"))
                        if os.environ.get("SPECPROBE_EXTRACTION_MODE") == "ollama"
                        else None
                    )
                    proposed = extract_spec_fields(document_id, rows, blocks, llm)
                    canonical = {
                        field.path: field for field in proposed if not field.path.startswith("0x")
                    }
                    proposals = [
                        {
                            "document_id": document_id,
                            "json_path": field.path,
                            "value": {
                                "value": field.value,
                                "provenance": field.provenance.model_dump(mode="json"),
                            },
                        }
                        for field in canonical.values()
                    ]
                finally:
                    temporary_path.unlink(missing_ok=True)
        except (ValueError, OSError, KeyError) as error:
            raise HTTPException(422, f"Cannot parse document: {error}") from error
        if not blocks:
            raise HTTPException(422, "No text extracted; scanned PDFs require OCR before upload")
        envelope = {
            "kind": kind,
            "blocks": [
                {"text": b.text, "page": b.page, "sheet": b.sheet, "row": b.row} for b in blocks
            ],
        }
        session.add(
            Document(
                id=document_id,
                workspace_id=workspace_id,
                name=file.filename or "document",
                content=json.dumps(envelope),
                created_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )
        session.flush()
        stored = repo.propose_fields(proposals, "upload")
        for index, block in enumerate(blocks):
            repo.vectors.add(
                kind,
                f"{document_id}:{index}",
                block.text,
                {
                    "document_id": document_id,
                    "name": file.filename or "document",
                    "page": str(block.page or ""),
                    "sheet": block.sheet or "",
                    "row": str(block.row or ""),
                },
            )
        return {
            "document_id": document_id,
            "field_ids": [field.id for field in stored],
            "review_required": True,
        }

    @app.post("/workspaces/{workspace_id}/documents/{document_id}/review")
    def review_document(
        workspace_id: str,
        document_id: str,
        request: ApprovalRequest,
        session: SessionDep,
        x_api_key: str | None = Header(default=None),
    ) -> dict[str, bool]:
        repo = repository(workspace_id, session, x_api_key)
        document(repo, document_id)
        AuditLog(session).append(
            workspace_id,
            "document_review",
            request.reviewer,
            {"id": document_id, "approved": request.approved},
        )
        session.commit()
        return {"approved": request.approved}

    @app.get("/workspaces/{workspace_id}/fields")
    def list_fields(
        workspace_id: str, session: SessionDep, x_api_key: str | None = Header(default=None)
    ) -> list[dict[str, Any]]:
        repo = repository(workspace_id, session, x_api_key)
        reviews = session.scalars(
            select(Review)
            .where(Review.workspace_id == workspace_id)
            .order_by(Review.created_at, Review.id)
        )
        decisions = {review.field_id: review.decision for review in reviews}
        return [
            {
                "id": field.id,
                "document_id": field.document_id,
                "json_path": field.json_path,
                "value": field.value.get("value", field.value),
                "provenance": field.value.get("provenance", {}),
                "status": decisions.get(field.id, "proposed"),
            }
            for field in repo.list_fields()
        ]

    @app.post("/workspaces/{workspace_id}/fields/{field_id}/review")
    def review_field(
        workspace_id: str,
        field_id: str,
        request: ReviewRequest,
        session: SessionDep,
        x_api_key: str | None = Header(default=None),
    ) -> dict[str, str]:
        repo = repository(workspace_id, session, x_api_key)
        try:
            review = repo.review_field(field_id, request.decision, request.reviewer, request.value)
        except (PermissionError, ValueError) as error:
            raise HTTPException(422, str(error)) from error
        return {"review_id": review.id, "decision": review.decision}

    @app.post("/workspaces/{workspace_id}/suites/{suite_id}")
    def generate_suite_route(
        workspace_id: str,
        suite_id: str,
        document_id: str,
        session: SessionDep,
        x_api_key: str | None = Header(default=None),
    ) -> dict[str, Any]:
        repo = repository(workspace_id, session, x_api_key)
        document(repo, document_id)
        if not is_approved(repo, "document_review", document_id):
            raise HTTPException(409, "Approve the source document before generation")
        approved = [f for f in repo.list_approved_fields() if f.document_id == document_id]
        all_fields = [f for f in repo.list_fields() if f.document_id == document_id]
        if not approved or len(approved) != len(all_fields):
            raise HTTPException(
                409, "Review all specification fields; correct rejected fields first"
            )
        try:
            spec = assemble_spec(approved, document_id)
            cases = generate_suite(spec)
        except (ValueError, IndexError, KeyError) as error:
            raise HTTPException(422, f"Incomplete or unsupported specification: {error}") from error
        payload = {
            "document_id": document_id,
            "approved_field_ids": [f.id for f in approved],
            "spec": spec.model_dump(mode="json"),
            "cases": [case_payload(c) for c in cases],
            "case_count": len(cases),
            "coverage": coverage(cases),
        }
        repo.generate_suite(suite_id, payload, "engineer")
        return {
            "suite_id": suite_id,
            "case_count": len(cases),
            "coverage": payload["coverage"],
            "approved_field_ids": payload["approved_field_ids"],
            "approved": False,
        }

    @app.get("/workspaces/{workspace_id}/suites/{suite_id}")
    def get_suite(
        workspace_id: str,
        suite_id: str,
        session: SessionDep,
        x_api_key: str | None = Header(default=None),
    ) -> dict[str, Any]:
        repo = repository(workspace_id, session, x_api_key)
        payload = suite(repo, suite_id).payload
        return {
            **payload,
            "approved": is_approved(repo, "suite_review", suite_id, snapshot_hash(payload)),
        }

    @app.post("/workspaces/{workspace_id}/suites/{suite_id}/review")
    def review_suite(
        workspace_id: str,
        suite_id: str,
        request: ApprovalRequest,
        session: SessionDep,
        x_api_key: str | None = Header(default=None),
    ) -> dict[str, bool]:
        repo = repository(workspace_id, session, x_api_key)
        payload = suite(repo, suite_id).payload
        AuditLog(session).append(
            workspace_id,
            "suite_review",
            request.reviewer,
            {"id": suite_id, "approved": request.approved, "hash": snapshot_hash(payload)},
        )
        session.commit()
        return {"approved": request.approved}

    @app.get("/workspaces/{workspace_id}/suites/{suite_id}/export")
    def export_suite(
        workspace_id: str,
        suite_id: str,
        session: SessionDep,
        format: Literal["python", "json"] = "python",
        x_api_key: str | None = Header(default=None),
    ) -> Response:
        repo = repository(workspace_id, session, x_api_key)
        payload = suite(repo, suite_id).payload
        if not is_approved(repo, "suite_review", suite_id, snapshot_hash(payload)):
            raise HTTPException(409, "Approve this suite snapshot before export")
        if not is_approved(repo, "document_review", str(payload["document_id"])):
            raise HTTPException(409, "Source document approval has been revoked")
        body = export_python(payload) if format == "python" else json.dumps(payload, indent=2)
        return Response(body, media_type="text/plain" if format == "python" else "application/json")

    @app.post("/workspaces/{workspace_id}/runs/{run_id}")
    def run_route(
        workspace_id: str,
        run_id: str,
        suite_id: str,
        session: SessionDep,
        mutants: bool = False,
        x_api_key: str | None = Header(default=None),
    ) -> dict[str, Any]:
        repo = repository(workspace_id, session, x_api_key)
        payload = suite(repo, suite_id).payload
        if not is_approved(repo, "suite_review", suite_id, snapshot_hash(payload)):
            raise HTTPException(409, "Approve this suite snapshot before execution")
        if not is_approved(repo, "document_review", str(payload["document_id"])):
            raise HTTPException(409, "Source document approval has been revoked")
        spec = EcuSpec.model_validate(payload["spec"])
        cases = [restore_case(c) for c in payload["cases"]]
        results = run_suite(cases, EcuSimulator(spec))
        report: dict[str, Any] = {
            "passed": sum(r.passed for r in results),
            "total": len(results),
            "suite_hash": snapshot_hash(payload),
            "execution": "simulator",
            "coverage": payload["coverage"],
            "results": [
                {
                    "test_id": r.test_id,
                    "passed": r.passed,
                    "expected": r.expected.hex() if r.expected is not None else None,
                    "actual": r.actual.hex() if r.actual is not None else None,
                }
                for r in results
            ],
        }
        if mutants:
            mutations = run_auto_mutants(spec, cases)
            survivors = [
                m for m in mutations if m.compilable and not m.killed_by and not m.crashed_by
            ]
            report["mutants"] = [m.__dict__ for m in mutations]
            report["classifications"] = classify_survivors(spec, survivors)
        repo.record_run(run_id, suite_id, report, "engineer")
        return report

    @app.get("/workspaces/{workspace_id}/runs/{run_id}")
    def get_run(
        workspace_id: str,
        run_id: str,
        session: SessionDep,
        x_api_key: str | None = Header(default=None),
    ) -> dict[str, Any]:
        repository(workspace_id, session, x_api_key)
        row = session.scalar(
            select(TestRun).where(TestRun.id == run_id, TestRun.workspace_id == workspace_id)
        )
        if row is None:
            raise HTTPException(404, "Run not found")
        return row.report

    @app.post("/workspaces/{workspace_id}/query")
    def query(
        workspace_id: str,
        request: QueryRequest,
        session: SessionDep,
        x_api_key: str | None = Header(default=None),
    ) -> dict[str, Any]:
        repo = repository(workspace_id, session, x_api_key)
        approved_ids = {
            d.id for d in repo.list_documents() if is_approved(repo, "document_review", d.id)
        }
        hits = [
            hit
            for hit in repo.vectors.search(
                request.kind, request.question, limit=5, allowed_document_ids=approved_ids
            )
            if cast(dict[str, str], hit["metadata"]).get("document_id") in approved_ids
        ][:5]
        evidence = [
            {
                "citation": i + 1,
                "text": hit["text"],
                "score": hit["score"],
                **cast(dict[str, str], hit["metadata"]),
            }
            for i, hit in enumerate(hits)
        ]
        answer = "No relevant approved evidence found."
        if evidence:
            answer = "\n\n".join(f"[{e['citation']}] {e['text']}" for e in evidence)
        if request.use_llm and evidence:
            try:
                answer = OllamaClient(
                    model=os.environ.get("SPECPROBE_OLLAMA_MODEL", "llama3.2")
                ).answer(request.question, evidence)
                citations = {int(value) for value in re.findall(r"\[(\d+)\]", answer)}
                if not citations or not citations <= set(range(1, len(evidence) + 1)):
                    raise RuntimeError("Local answer lacks valid evidence citations")
            except (OSError, RuntimeError, ValueError) as error:
                raise HTTPException(503, f"Local inference unavailable: {error}") from error
        return {
            "answer": answer,
            "citations": evidence,
            "mode": "local_llm" if request.use_llm and evidence else "evidence_only",
            "review_required": True,
            "limitation": "Retrieval scores are similarity scores, not calibrated confidence.",
        }

    @app.post("/workspaces/{workspace_id}/fields/review-batch")
    def batch_review(
        workspace_id: str,
        request: BatchReviewRequest,
        session: SessionDep,
        x_api_key: str | None = Header(default=None),
    ) -> dict[str, int]:
        repo = repository(workspace_id, session, x_api_key)
        allowed = {f.id for f in repo.list_fields()}
        if not set(request.field_ids) <= allowed:
            raise HTTPException(404, "Field not found in this workspace")
        for field_id in dict.fromkeys(request.field_ids):
            repo.review_field(field_id, "approved", request.reviewer)
        return {"reviewed": len(set(request.field_ids))}

    @app.post("/workspaces/{workspace_id}/suites/{suite_id}/validate-message")
    def validate_message(
        workspace_id: str,
        suite_id: str,
        request: MessageRequest,
        session: SessionDep,
        x_api_key: str | None = Header(default=None),
    ) -> dict[str, Any]:
        repo = repository(workspace_id, session, x_api_key)
        spec = EcuSpec.model_validate(suite(repo, suite_id).payload["spec"])
        state = State(session=spec.sessions[0].id)
        try:
            for setup in request.setup_hex:
                _, state = step(spec, state, request.environment, bytes.fromhex(setup))
            response, _ = step(spec, state, request.environment, bytes.fromhex(request.request_hex))
            actual = bytes.fromhex(request.actual_hex) if request.actual_hex is not None else None
        except ValueError as error:
            raise HTTPException(422, "Messages must be hexadecimal byte strings") from error
        expected = response.bytes
        return {
            "expected_hex": expected.hex() if expected is not None else None,
            "nrc": response.nrc,
            "matches": actual == expected,
            "comparison_supplied": request.actual_hex is not None,
        }

    @app.get("/workspaces/{workspace_id}/audit")
    def audit(
        workspace_id: str, session: SessionDep, x_api_key: str | None = Header(default=None)
    ) -> dict[str, Any]:
        repo = repository(workspace_id, session, x_api_key)
        return {
            "chain_valid": AuditLog(session).verify_chain(),
            "entries": [
                {
                    "action": r.action,
                    "actor": r.actor,
                    "payload": r.payload,
                    "timestamp": r.timestamp.isoformat(),
                    "hash": r.row_hash,
                }
                for r in repo.audit_entries()
            ],
        }

    return app


app = create_app()
