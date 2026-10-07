import hashlib
import hmac
import json
import os
import re
import secrets
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal, cast
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from ..domain.schema import EcuSpec
from ..gen.generator import generate_suite
from ..grounding import conflicting_evidence, supported_answer
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
from ..storage.models import (
    Document,
    DocumentBlob,
    IndexJob,
    Membership,
    Review,
    TestCaseRow,
    TestRun,
    User,
)
from ..storage.recovery import recover_index
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


def create_app(
    engine: Engine | None = None, backend: VectorBackend | None = None, auth_mode: str | None = None
) -> FastAPI:
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
    app.state.auth_mode = auth_mode or os.environ.get(
        "SPECPROBE_AUTH_MODE", "workspace_key" if engine is not None else "individual"
    )
    if app.state.auth_mode not in {"individual", "workspace_key"}:
        raise ValueError("Unknown authentication mode")

    def administrator(request: Request) -> None:
        secret_file = os.environ.get("SPECPROBE_ADMIN_SECRET_FILE")
        configured = (
            Path(secret_file).read_text().strip()
            if secret_file
            else os.environ.get("SPECPROBE_ADMIN_SECRET", "")
        )
        supplied = request.headers.get("X-Admin-Key", "")
        if not configured or not hmac.compare_digest(configured, supplied):
            raise HTTPException(403, "Administrator credential required")

    @app.post("/users/{user_id}")
    def provision_user(user_id: str, request: Request) -> dict[str, str]:
        administrator(request)
        token = secrets.token_urlsafe(32)
        with app.state.sessions() as session:
            if session.get(User, user_id):
                raise HTTPException(409, "User already exists")
            session.add(
                User(id=user_id, token_hash=hashlib.sha256(token.encode()).hexdigest(), active=1)
            )
            session.commit()
        return {"user_id": user_id, "token": token}

    @app.put("/workspaces/{workspace_id}/members/{user_id}")
    def membership(
        workspace_id: str,
        user_id: str,
        role: Literal["viewer", "editor", "reviewer", "revoked"],
        request: Request,
    ) -> dict[str, str]:
        administrator(request)
        with app.state.sessions() as session:
            from ..storage.models import Workspace

            if not session.get(User, user_id) or not session.get(Workspace, workspace_id):
                raise HTTPException(404, "User or workspace not found")
            session.merge(Membership(user_id=user_id, workspace_id=workspace_id, role=role))
            AuditLog(session).append(
                workspace_id,
                "membership_change",
                "administrator",
                {"user_id": user_id, "role": role},
            )
            session.commit()
        return {"role": role}

    @app.post("/users/{user_id}/credential")
    def user_credential(user_id: str, request: Request, revoke: bool = False) -> dict[str, str]:
        administrator(request)
        with app.state.sessions() as session:
            user = session.get(User, user_id)
            if user is None:
                raise HTTPException(404, "User not found")
            token = secrets.token_urlsafe(32)
            user.active = 0 if revoke else 1
            user.token_hash = hashlib.sha256(token.encode()).hexdigest()
            session.commit()
        return {"user_id": user_id, "token": "" if revoke else token}

    def actor(session: Session, supplied: str) -> str:
        return str(session.info.get("actor", supplied))

    def session_dependency(request: Request) -> Any:
        session = app.state.sessions()
        try:
            workspace_id = request.path_params.get("workspace_id")
            if app.state.auth_mode == "individual" and workspace_id:
                credential = request.headers.get("Authorization", "")
                if not credential.startswith("Bearer "):
                    raise HTTPException(401, "Individual bearer token required")
                user = session.scalar(
                    select(User).where(
                        User.token_hash == hashlib.sha256(credential[7:].encode()).hexdigest(),
                        User.active == 1,
                    )
                )
                member = session.get(Membership, (user.id, workspace_id)) if user else None
                levels = {"viewer": 1, "editor": 2, "reviewer": 3}
                required = (
                    1 if request.method == "GET" or request.url.path.endswith("/query") else 2
                )
                if "/review" in request.url.path:
                    required = 3
                if member is None or levels.get(member.role, 0) < required:
                    raise HTTPException(403, "Workspace role does not permit this action")
                session.info.update(authorized_workspace=workspace_id, actor=user.id)
            yield session
        except IntegrityError as error:
            session.rollback()
            raise HTTPException(409, "Identifier already exists") from error
        except OperationalError as error:
            session.rollback()
            raise HTTPException(503, "Database unavailable; retry the transaction") from error
        finally:
            session.close()

    SessionDep = Annotated[Session, Depends(session_dependency)]

    def repository(workspace_id: str, session: Session, api_key: str | None) -> WorkspaceRepository:
        if not api_key and session.info.get("authorized_workspace") != workspace_id:
            raise HTTPException(401, "missing X-API-Key")
        repo = WorkspaceRepository(
            session, ScopedVectorStore(app.state.backend, workspace_id), workspace_id, api_key or ""
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

    def source_usable(row: Document) -> bool:
        return (
            not row.name.lower().endswith(".json")
            or json.loads(row.content).get("source_revision") == 2
        )

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

    @app.post("/workspaces/{workspace_id}/documents/{document_id}/recover")
    def recover_document(
        workspace_id: str,
        document_id: str,
        session: SessionDep,
        x_api_key: str | None = Header(default=None),
    ) -> dict[str, Any]:
        repo = repository(workspace_id, session, x_api_key)
        job = recover_index(session, document(repo, document_id), repo.vectors)
        return {"status": job.status, "attempts": job.attempts, "error_type": job.error}

    @app.get("/ready")
    def ready() -> dict[str, Any]:
        with app.state.sessions() as session:
            incomplete = list(
                session.scalars(select(IndexJob).where(IndexJob.status != "complete"))
            )
            chain = AuditLog(session).verify_chain()
        if not chain:
            raise HTTPException(503, "Audit integrity check failed")
        return {
            "database": "ok",
            "audit_chain": "valid",
            "incomplete_indexes": len(incomplete),
            "auth_mode": app.state.auth_mode,
            "execution": "simulator",
            "model_revision": 2,
        }

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "execution": "simulator"}

    @app.post("/workspaces")
    def create_workspace_route(
        request: WorkspaceRequest, http_request: Request, session: SessionDep
    ) -> dict[str, str]:
        if app.state.auth_mode == "individual":
            administrator(http_request)
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
                "requires_reingest": not source_usable(row),
                "approved": is_approved(repo, "document_review", row.id),
                "index_status": job.status if (job := session.get(IndexJob, row.id)) else "legacy",
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
                source_data = json.loads(raw)

                def source_contains(path: str) -> bool:
                    match = re.fullmatch(r"(\w+)\[(\d+)\]\.(\w+)", path)
                    if match:
                        root, index, key = match.groups()
                        return key in source_data[root][int(index)]
                    if path.startswith("timing."):
                        return path.split(".", 1)[1] in source_data.get("timing", {})
                    return path in source_data

                blocks = [
                    TextBlock(document_id, f"{path}: {json.dumps(value)}")
                    for path, value in spec_fields(spec)
                    if source_contains(path)
                ]
                proposals = [
                    {
                        "document_id": document_id,
                        "json_path": path,
                        "value": {
                            "value": value,
                            "provenance": {
                                "row": None,
                                "origin": "normalized_json",
                                "defaulted": not source_contains(path),
                                "source_snippet": f"{path}: {json.dumps(value)}",
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
            "source_revision": 2,
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
        session.add(IndexJob(document_id=document_id, status="pending", attempts=0, error=""))
        session.add(DocumentBlob(document_id=document_id, content=raw))
        stored = repo.propose_fields(proposals, actor(session, "upload"))
        job = recover_index(session, document(repo, document_id), repo.vectors)
        return {
            "document_id": document_id,
            "index_status": job.status,
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
        job = session.get(IndexJob, document_id)
        if request.approved and job is not None and job.status != "complete":
            raise HTTPException(409, "Document indexing is incomplete; recover before approval")
        AuditLog(session).append(
            workspace_id,
            "document_review",
            actor(session, request.reviewer),
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
            review = repo.review_field(
                field_id, request.decision, actor(session, request.reviewer), request.value
            )
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
        selected_source = document(repo, document_id)
        if not source_usable(selected_source):
            raise HTTPException(
                409, "Reingest the original legacy JSON and review its explicit defaults"
            )
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
            "model_revision": 2,
            "document_id": document_id,
            "approved_field_ids": [f.id for f in approved],
            "spec": spec.model_dump(mode="json"),
            "cases": [case_payload(c) for c in cases],
            "case_count": len(cases),
            "coverage": coverage(cases),
        }
        repo.generate_suite(suite_id, payload, actor(session, "engineer"))
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
            actor(session, request.reviewer),
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
        if payload.get("model_revision") != 2:
            raise HTTPException(409, "Legacy protocol snapshot; regenerate and review the suite")
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
        if payload.get("model_revision") != 2:
            raise HTTPException(409, "Legacy protocol snapshot; regenerate and review the suite")
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
                    "failure_kind": r.failure_kind,
                    "detail": r.detail,
                    "checks": [c.model_dump(mode="json") for c in r.checks],
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
            d.id
            for d in repo.list_documents()
            if source_usable(d) and is_approved(repo, "document_review", d.id)
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
        conflict = conflicting_evidence(evidence)
        if conflict:
            answer = "Contradictory approved sources; engineer resolution required."
        if request.use_llm and evidence and not conflict:
            try:
                answer = OllamaClient(
                    model=os.environ.get("SPECPROBE_OLLAMA_MODEL", "llama3.2")
                ).answer(request.question, evidence)
                if not supported_answer(answer, evidence):
                    answer = (
                        "Insufficient supported evidence for the model answer; "
                        "inspect the cited source excerpts."
                    )
            except (OSError, RuntimeError, ValueError) as error:
                raise HTTPException(503, f"Local inference unavailable: {error}") from error
        return {
            "answer": answer,
            "citations": evidence,
            "mode": "evidence_conflict"
            if conflict
            else "local_llm"
            if request.use_llm and evidence
            else "evidence_only",
            "review_required": True,
            "conflict": conflict,
            "grounding_policy": "contiguous extractive support; semantic entailment not validated",
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
        try:
            for field_id in dict.fromkeys(request.field_ids):
                repo.review_field(
                    field_id, "approved", actor(session, request.reviewer), commit=False
                )
            session.commit()
        except (ValueError, PermissionError) as error:
            session.rollback()
            raise HTTPException(422, "Batch approval failed; no decisions committed") from error
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
