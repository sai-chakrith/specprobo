import socket
from pathlib import Path

import pytest
from sqlalchemy import delete, update
from sqlalchemy.exc import IntegrityError

from specprobe.storage.audit import AuditLog
from specprobe.storage.db import create_database, session_factory
from specprobe.storage.models import AuditLogRow, Workspace
from specprobe.storage.repository import WorkspaceRepository, create_workspace
from specprobe.storage.vectorstore import (
    ChromaVectorBackend,
    HashEmbedding,
    InMemoryVectorBackend,
    collection_name,
    scoped_store,
)


def _repositories() -> tuple[WorkspaceRepository, WorkspaceRepository, object]:
    engine = create_database()
    factory = session_factory(engine)
    session = factory()
    create_workspace(session, "a", "key-a")
    create_workspace(session, "b", "key-b")
    backend = InMemoryVectorBackend()
    return (
        WorkspaceRepository(session, scoped_store(backend, "a"), "a", "key-a"),
        WorkspaceRepository(session, scoped_store(backend, "b"), "b", "key-b"),
        session,
    )


def test_workspace_repository_and_vectors_are_isolated() -> None:
    repository_a, repository_b, _ = _repositories()
    repository_a.add_document("a.txt", "A")
    assert [item.content for item in repository_a.list_documents()] == ["A"]
    assert repository_b.list_documents() == []
    with pytest.raises(PermissionError):
        WorkspaceRepository(
            repository_a.session, repository_a.vectors, "b", "key-a"
        ).list_documents()
    repository_a.vectors.add("oem", "a-vector", "A", {})
    assert repository_a.vectors.list("oem")
    assert repository_b.vectors.list("oem") == []
    assert collection_name("a", "oem") != collection_name("b", "oem")


def test_workspace_api_keys_are_salted_and_hashed() -> None:
    _, _, session = _repositories()
    workspace = session.get(Workspace, "a")
    assert workspace is not None
    assert workspace.api_key_hash != "key-a"
    assert workspace.api_key_salt
    assert len(workspace.api_key_hash) == 64


def test_persistent_vectors_never_open_a_socket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("chromadb")

    def reject_connect(*args: object, **kwargs: object) -> None:
        raise AssertionError("vector persistence attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", reject_connect)
    backend = ChromaVectorBackend(tmp_path / "chroma-offline", HashEmbedding())
    scoped_store(backend, "offline").add("oem", "doc", "offline", {})
    assert scoped_store(backend, "offline").list("oem")


def test_audit_database_triggers_reject_update_and_delete() -> None:
    repository_a, _, session = _repositories()
    AuditLog(session).append("a", "test", "engineer", {"value": 1})
    session.commit()
    with pytest.raises(IntegrityError):
        session.execute(update(AuditLogRow).values(action="tampered"))
        session.commit()
    session.rollback()
    with pytest.raises(IntegrityError):
        session.execute(delete(AuditLogRow))
        session.commit()
    session.rollback()
    assert repository_a.audit_entries()


def test_audit_hash_chain_detects_in_memory_tampering() -> None:
    _, _, session = _repositories()
    audit = AuditLog(session)
    audit.append("a", "one", "engineer", {"value": 1})
    audit.append("a", "two", "engineer", {"value": 2})
    session.commit()
    assert audit.verify_chain()
    row = session.query(AuditLogRow).first()
    assert row is not None
    row.payload["value"] = 99
    assert not audit.verify_chain()


def test_review_generation_and_run_are_audited() -> None:
    repository_a, _, _ = _repositories()
    repository_a.review_field("field-1", "approved", "engineer")
    repository_a.generate_suite("suite-1", {"count": 1}, "engineer")
    repository_a.record_run("run-1", "suite-1", {"passed": 1}, "engineer")
    actions = [entry.action for entry in repository_a.audit_entries()]
    assert actions == ["review_decision", "suite_generation", "suite_run"]


def test_persistent_chroma_backend_uses_workspace_collections(tmp_path: Path) -> None:
    pytest.importorskip("chromadb")
    backend = ChromaVectorBackend(tmp_path / "chroma", HashEmbedding())
    scoped_store(backend, "a").add("oem", "a-doc", "A", {})
    assert scoped_store(backend, "a").list("oem")
    assert scoped_store(backend, "b").list("oem") == []
