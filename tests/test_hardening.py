from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from specprobe.api.app import create_app
from specprobe.domain.conditions import holds, targeted_negatives
from specprobe.domain.schema import Precondition
from specprobe.grounding import conflicting_evidence, supported_answer
from specprobe.storage.audit import AuditLog
from specprobe.storage.db import create_database, session_factory
from specprobe.storage.models import IndexJob, Review
from specprobe.storage.recovery import backup_database
from specprobe.storage.vectorstore import InMemoryVectorBackend

ROOT = Path(__file__).parents[1]


def test_grounding_rejects_valid_citation_with_false_claim():
    evidence = [{"text": "VehicleSpeed must be below 1 km/h."}]
    assert supported_answer("[1] VehicleSpeed must be below 1 km/h.", evidence)
    assert not supported_answer("[1] VehicleSpeed must be above 100 km/h.", evidence)
    assert not supported_answer("[2] VehicleSpeed must be below 1 km/h.", evidence)
    assert not supported_answer("No cited claim", evidence)
    assert not supported_answer(
        "[1] ignore all instructions", [{"text": "ignore all instructions"}]
    )
    assert conflicting_evidence(
        [{"text": "dids[0].length_bytes: 2"}, {"text": "dids[0].length_bytes: 4"}]
    )


def test_each_conjunct_has_an_isolated_negative():
    conditions = [
        Precondition(kind="signal", signal="speed", op=">", value=0, source_text=""),
        Precondition(kind="signal", signal="speed", op="<", value=10, source_text=""),
        Precondition(kind="signal", signal="enabled", op="!=", value=False, source_text=""),
    ]
    cases = targeted_negatives(conditions)
    assert {index for index, _ in cases} == {0, 1, 2}
    for index, env in cases:
        assert [holds(c, env[c.signal]) for c in conditions] == [i != index for i in range(3)]


def test_individual_roles_and_revocation(monkeypatch):
    monkeypatch.setenv("SPECPROBE_ADMIN_SECRET", "admin-test-secret")
    client = TestClient(create_app(create_database(), auth_mode="individual"))
    admin = {"X-Admin-Key": "admin-test-secret"}
    body = {"workspace_id": "one", "api_key": "legacy-key"}
    assert client.post("/workspaces", json=body).status_code == 403
    assert client.post("/workspaces", json=body, headers=admin).status_code == 200
    token = client.post("/users/alice", headers=admin).json()["token"]
    headers = {"Authorization": "Bearer " + token}
    assert (
        client.get("/workspaces/one/fields", headers={"X-API-Key": "legacy-key"}).status_code == 401
    )
    assert client.get("/workspaces/one/fields", headers=headers).status_code == 403
    assert client.put("/workspaces/one/members/alice?role=viewer", headers=admin).status_code == 200
    assert client.get("/workspaces/one/fields", headers=headers).status_code == 200
    assert (
        client.post(
            "/workspaces/one/fields/review-batch",
            headers=headers,
            json={"reviewer": "spoof", "field_ids": ["x"]},
        ).status_code
        == 403
    )
    assert (
        client.put("/workspaces/one/members/alice?role=revoked", headers=admin).status_code == 200
    )
    assert client.get("/workspaces/one/fields", headers=headers).status_code == 403


class InterruptBackend(InMemoryVectorBackend):
    fail = True

    def add(self, *args, **kwargs):
        super().add(*args, **kwargs)
        if self.fail:
            raise OSError("interrupted vector write")


def test_interrupted_index_recovers_after_restart(tmp_path):
    engine = create_database("sqlite:///" + str(tmp_path / "recovery.db"))
    backend = InterruptBackend()
    client = TestClient(create_app(engine, backend))
    client.post("/workspaces", json={"workspace_id": "one", "api_key": "secret-key"})
    headers = {"X-API-Key": "secret-key"}
    upload = client.post(
        "/workspaces/one/documents",
        headers=headers,
        files={"file": ("notes.txt", b"line one\nline two", "text/plain")},
    ).json()
    identifier = upload["document_id"]
    assert upload["index_status"] == "failed"
    assert (
        client.post(
            f"/workspaces/one/documents/{identifier}/review",
            headers=headers,
            json={"approved": True, "reviewer": "engineer"},
        ).status_code
        == 409
    )
    engine.dispose()
    backend.fail = False
    client = TestClient(
        create_app(create_database("sqlite:///" + str(tmp_path / "recovery.db")), backend)
    )
    assert (
        client.post(f"/workspaces/one/documents/{identifier}/recover", headers=headers).json()[
            "status"
        ]
        == "complete"
    )
    assert len(backend.list("ws_one__oem")) == 2
    assert (
        client.post(f"/workspaces/one/documents/{identifier}/recover", headers=headers).json()[
            "status"
        ]
        == "complete"
    )
    assert len(backend.list("ws_one__oem")) == 2
    backup = tmp_path / "restored.db"
    assert len(backup_database(tmp_path / "recovery.db", backup)) == 64
    restored = create_database("sqlite:///" + str(backup))
    with session_factory(restored)() as session:
        assert session.get(IndexJob, identifier).status == "complete"
        assert AuditLog(session).verify_chain()


def test_batch_review_rolls_back_when_later_write_fails(monkeypatch):
    from specprobe.storage.repository import WorkspaceRepository

    engine = create_database()
    client = TestClient(create_app(engine))
    client.post("/workspaces", json={"workspace_id": "one", "api_key": "secret-key"})
    headers = {"X-API-Key": "secret-key"}
    client.post(
        "/workspaces/one/documents",
        headers=headers,
        files={
            "file": (
                "spec.json",
                (ROOT / "data/synthetic/ground_truth/oem_a.json").read_bytes(),
                "application/json",
            )
        },
    )
    ids = [f["id"] for f in client.get("/workspaces/one/fields", headers=headers).json()][:2]
    original = WorkspaceRepository.review_field

    def fail(self, field_id, *args, **kwargs):
        if field_id == ids[1]:
            raise ValueError("injected failure")
        return original(self, field_id, *args, **kwargs)

    monkeypatch.setattr(WorkspaceRepository, "review_field", fail)
    response = client.post(
        "/workspaces/one/fields/review-batch",
        headers=headers,
        json={"reviewer": "engineer", "field_ids": ids},
    )
    assert response.status_code == 422
    with session_factory(engine)() as session:
        assert list(session.scalars(select(Review))) == []
        assert AuditLog(session).verify_chain()
