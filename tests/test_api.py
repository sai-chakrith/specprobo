from fastapi.testclient import TestClient

from specprobe.api import create_app
from specprobe.storage.db import create_database, session_factory
from specprobe.storage.repository import WorkspaceRepository
from specprobe.storage.vectorstore import InMemoryVectorBackend, ScopedVectorStore


def _client() -> tuple[TestClient, object]:
    engine = create_database()
    return TestClient(create_app(engine)), engine


def test_review_and_generation_use_only_approved_fields() -> None:
    client, engine = _client()
    assert (
        client.post("/workspaces", json={"workspace_id": "one", "api_key": "key-one"}).status_code
        == 200
    )
    session = session_factory(engine)()
    repo = WorkspaceRepository(
        session,
        ScopedVectorStore(InMemoryVectorBackend(), "one"),
        "one",
        "key-one",
    )
    fields = repo.propose_fields(
        [
            {"document_id": "doc", "json_path": "dids[0].did", "value": {"value": 4096}},
            {"document_id": "doc", "json_path": "dids[0].length_bytes", "value": {"value": 4}},
        ],
        "test",
    )
    session.close()
    assert (
        client.post(
            f"/workspaces/one/fields/{fields[0].id}/review",
            headers={"X-API-Key": "key-one"},
            json={"decision": "approved"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/workspaces/one/fields/{fields[1].id}/review",
            headers={"X-API-Key": "key-one"},
            json={"decision": "rejected"},
        ).status_code
        == 200
    )
    response = client.post("/workspaces/one/suites/suite-one", headers={"X-API-Key": "key-one"})
    assert response.status_code == 200
    assert response.json()["approved_field_ids"] == [fields[0].id]


def test_cross_workspace_access_is_denied() -> None:
    client, _ = _client()
    assert (
        client.post("/workspaces", json={"workspace_id": "one", "api_key": "key-one"}).status_code
        == 200
    )
    assert (
        client.post("/workspaces", json={"workspace_id": "two", "api_key": "key-two"}).status_code
        == 200
    )
    response = client.get("/workspaces/one/fields", headers={"X-API-Key": "key-two"})
    assert response.status_code == 403
