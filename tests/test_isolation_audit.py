from specprobe.storage.audit import AuditLog, WorkspaceRepository, collection_name
from specprobe.storage.vectorstore import VectorStore


def test_workspace_data_and_vectors_are_isolated() -> None:
    repository = WorkspaceRepository()
    vectors = VectorStore()
    repository.put("a", "doc", {"value": 1})
    vectors.add("a", "oem", {"value": 1})
    assert repository.get("b", "doc") is None
    assert repository.list("b") == []
    assert vectors.list("b", "oem") == []
    assert collection_name("a", "oem") != collection_name("b", "oem")


def test_audit_is_append_only() -> None:
    audit = AuditLog()
    audit.append("a", "review", "engineer", {"status": "approved"})
    entries = audit.entries("a")
    assert len(entries) == 1
    assert not hasattr(audit, "update")
    assert not hasattr(audit, "delete")
