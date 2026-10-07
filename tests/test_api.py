from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from specprobe.api import create_app
from specprobe.domain.schema import EcuSpec
from specprobe.ingest.render import render_oem_a_pdf, render_oem_b_xlsx
from specprobe.storage.db import create_database

ROOT = Path(__file__).parents[1]
HEADERS = {"X-API-Key": "key-one1"}


def client_for(engine: Engine | None = None) -> TestClient:
    client = TestClient(create_app(engine if engine is not None else create_database()))
    assert (
        client.post("/workspaces", json={"workspace_id": "one", "api_key": "key-one1"}).status_code
        == 200
    )
    return client


def uploaded(client: TestClient, filename: str = "oem_b.json") -> str:
    raw = (ROOT / "data/synthetic/ground_truth" / filename).read_bytes()
    response = client.post(
        "/workspaces/one/documents",
        headers=HEADERS,
        files={"file": (filename, raw, "application/json")},
    )
    assert response.status_code == 200, response.text
    return response.json()["document_id"]


def approve_source(client: TestClient, doc: str) -> None:
    response = client.post(
        f"/workspaces/one/documents/{doc}/review",
        headers=HEADERS,
        json={"approved": True, "reviewer": "engineer"},
    )
    assert response.status_code == 200


def approve_fields(client: TestClient, doc: str) -> None:
    fields = client.get("/workspaces/one/fields", headers=HEADERS).json()
    for field in fields:
        if field["document_id"] == doc:
            response = client.post(
                f"/workspaces/one/fields/{field['id']}/review",
                headers=HEADERS,
                json={"decision": "approved", "reviewer": "engineer"},
            )
            assert response.status_code == 200, response.text


def generated(client: TestClient, doc: str, suite: str = "suite-one") -> dict:
    approve_source(client, doc)
    approve_fields(client, doc)
    response = client.post(
        f"/workspaces/one/suites/{suite}", headers=HEADERS, params={"document_id": doc}
    )
    assert response.status_code == 200, response.text
    return client.get(f"/workspaces/one/suites/{suite}", headers=HEADERS).json()


def approve_suite(client: TestClient, suite: str = "suite-one", approved: bool = True) -> None:
    response = client.post(
        f"/workspaces/one/suites/{suite}/review",
        headers=HEADERS,
        json={"approved": approved, "reviewer": "engineer"},
    )
    assert response.status_code == 200


def test_uploaded_oem_drives_saved_tests_and_executable_export() -> None:
    client = client_for()
    doc = uploaded(client)
    payload = generated(client, doc)
    assert payload["spec"]["ecu_name"] == "SYNTH-OEM-B"
    assert payload["spec"]["dids"][0]["did"] == 0x2000
    assert any(c["steps"][-1].startswith("222000") for c in payload["cases"])
    assert not any(c["steps"][-1].startswith("221000") for c in payload["cases"])
    response = client.post(
        "/workspaces/one/runs/run-one", headers=HEADERS, params={"suite_id": "suite-one"}
    )
    assert response.status_code == 409
    assert client.get("/workspaces/one/suites/suite-one/export", headers=HEADERS).status_code == 409
    approve_suite(client)
    response = client.post(
        "/workspaces/one/runs/run-one", headers=HEADERS, params={"suite_id": "suite-one"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["total"] == payload["case_count"]
    assert response.json()["passed"] == response.json()["total"]
    exported = client.get("/workspaces/one/suites/suite-one/export", headers=HEADERS)
    assert exported.status_code == 200
    namespace = {"__name__": "exported_suite"}
    exec(compile(exported.text, "exported_suite.py", "exec"), namespace)
    assert namespace["main"]() == 0
    assert client.get("/workspaces/one/audit", headers=HEADERS).json()["chain_valid"]
    approve_suite(client, approved=False)
    assert (
        client.post(
            "/workspaces/one/runs/run-two", headers=HEADERS, params={"suite_id": "suite-one"}
        ).status_code
        == 409
    )


def test_generation_blocks_unreviewed_and_rejected_fields() -> None:
    client = client_for()
    doc = uploaded(client)
    path = "/workspaces/one/suites/suite-one"
    assert client.post(path, headers=HEADERS, params={"document_id": doc}).status_code == 409
    approve_source(client, doc)
    assert client.post(path, headers=HEADERS, params={"document_id": doc}).status_code == 409
    approve_fields(client, doc)
    fields = client.get("/workspaces/one/fields", headers=HEADERS).json()
    field = next(f for f in fields if f["json_path"] == "dids[0].length_bytes")
    client.post(
        f"/workspaces/one/fields/{field['id']}/review",
        headers=HEADERS,
        json={"decision": "rejected"},
    )
    assert client.post(path, headers=HEADERS, params={"document_id": doc}).status_code == 409
    assert (
        client.post(
            f"/workspaces/one/fields/{field['id']}/review",
            headers=HEADERS,
            json={"decision": "edited"},
        ).status_code
        == 422
    )
    client.post(
        f"/workspaces/one/fields/{field['id']}/review",
        headers=HEADERS,
        json={"decision": "edited", "value": {"value": 5}, "reviewer": "engineer"},
    )
    assert client.post(path, headers=HEADERS, params={"document_id": doc}).status_code == 200
    payload = client.get(path, headers=HEADERS).json()
    assert payload["spec"]["dids"][0]["length_bytes"] == 5
    # Edits after generation cannot silently alter saved requests or expected responses.
    client.post(
        f"/workspaces/one/fields/{field['id']}/review",
        headers=HEADERS,
        json={"decision": "edited", "value": {"value": 7}},
    )
    assert client.get(path, headers=HEADERS).json()["spec"]["dids"][0]["length_bytes"] == 5


def test_query_is_cited_approved_only_and_workspace_scoped() -> None:
    client = client_for()
    response = client.post(
        "/workspaces/one/documents",
        headers=HEADERS,
        files={"file": ("reference.md", b"VIN is read using DID 0xF190.", "text/plain")},
    )
    doc = response.json()["document_id"]
    query = {"question": "VIN DID", "kind": "oem"}
    assert (
        client.post("/workspaces/one/query", headers=HEADERS, json=query).json()["citations"] == []
    )
    approve_source(client, doc)
    result = client.post("/workspaces/one/query", headers=HEADERS, json=query).json()
    assert result["citations"][0]["document_id"] == doc
    assert result["citations"][0]["row"] == "1"
    assert "[1]" in result["answer"]
    client.post("/workspaces", json={"workspace_id": "two", "api_key": "key-two2"})
    assert (
        client.get("/workspaces/one/fields", headers={"X-API-Key": "key-two2"}).status_code == 403
    )
    assert (
        client.post("/workspaces/two/query", headers={"X-API-Key": "key-two2"}, json=query).json()[
            "citations"
        ]
        == []
    )
    assert (
        client.post(
            f"/workspaces/two/documents/{doc}/review",
            headers={"X-API-Key": "key-two2"},
            json={"reviewer": "other", "approved": True},
        ).status_code
        == 404
    )


def test_message_validation_and_conflicting_ids() -> None:
    client = client_for()
    doc = uploaded(client)
    generated(client, doc)
    response = client.post(
        "/workspaces/one/suites/suite-one/validate-message",
        headers=HEADERS,
        json={"request_hex": "1001", "actual_hex": "5001004b001c"},
    )
    assert response.status_code == 200
    assert response.json()["expected_hex"].startswith("5001")
    assert (
        client.post(
            "/workspaces/one/suites/suite-one/validate-message",
            headers=HEADERS,
            json={"request_hex": "broken"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/workspaces/one/suites/suite-one", headers=HEADERS, params={"document_id": doc}
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/workspaces/one/fields/missing/review", headers=HEADERS, json={"decision": "approved"}
        ).status_code
        == 422
    )


def test_invalid_uploads_do_not_create_documents() -> None:
    client = client_for()
    for name, content, status in [
        ("bad.exe", b"x", 415),
        ("bad.json", b"{}", 422),
        ("empty.md", b"", 422),
    ]:
        assert (
            client.post(
                "/workspaces/one/documents", headers=HEADERS, files={"file": (name, content)}
            ).status_code
            == status
        )
    assert client.get("/workspaces/one/documents", headers=HEADERS).json() == []


def test_persistent_workflow_survives_app_restart(tmp_path: Path) -> None:
    from specprobe.storage.vectorstore import ChromaVectorBackend, HashEmbedding

    engine = create_database("sqlite:///" + str(tmp_path / "workflow.db"))
    backend = ChromaVectorBackend(tmp_path / "chroma", HashEmbedding(dimension=256))
    client = TestClient(create_app(engine, backend))
    client.post("/workspaces", json={"workspace_id": "one", "api_key": "key-one1"})
    doc = uploaded(client)
    payload = generated(client, doc)
    approve_suite(client)
    restarted = TestClient(
        create_app(engine, ChromaVectorBackend(tmp_path / "chroma", HashEmbedding(dimension=256)))
    )
    assert restarted.get("/workspaces/one/suites/suite-one", headers=HEADERS).json()["approved"]
    result = restarted.post(
        "/workspaces/one/query",
        headers=HEADERS,
        json={"question": "ecu_name SYNTH OEM B", "kind": "oem"},
    )
    assert result.json()["citations"]
    result = restarted.post(
        "/workspaces/one/runs/restarted", headers=HEADERS, params={"suite_id": "suite-one"}
    )
    assert result.json()["passed"] == payload["case_count"]


@pytest.mark.parametrize(
    "oem,extension,renderer",
    [("oem_a", "pdf", render_oem_a_pdf), ("oem_b", "xlsx", render_oem_b_xlsx)],
)
def test_pdf_and_excel_uploads_generate_without_demo_template(tmp_path, oem, extension, renderer):
    client = client_for()
    source = ROOT / "data/synthetic/ground_truth" / (oem + ".json")
    path = tmp_path / ("spec." + extension)
    renderer(source, path)
    response = client.post(
        "/workspaces/one/documents", headers=HEADERS, files={"file": (path.name, path.read_bytes())}
    )
    assert response.status_code == 200, response.text
    doc = response.json()["document_id"]
    payload = generated(client, doc)
    expected = EcuSpec.model_validate_json(source.read_text(encoding="utf-8")).model_dump(
        mode="json"
    )
    assert payload["spec"]["ecu_name"] == expected["ecu_name"]
    assert payload["spec"]["dids"][0]["preconditions"] == expected["dids"][0]["preconditions"]
    assert {k: v for k, v in payload["spec"].items() if k != "field_registry"} == {
        k: v for k, v in expected.items() if k != "field_registry"
    }
    approve_suite(client)
    response = client.post(
        "/workspaces/one/runs/format-run", headers=HEADERS, params={"suite_id": "suite-one"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["passed"] == response.json()["total"]


def test_local_answers_require_valid_citations_and_source_revocation_blocks_runs(monkeypatch):
    from specprobe.ingest.llm import OllamaClient

    client = client_for()
    doc = uploaded(client)
    generated(client, doc)
    approve_suite(client)
    monkeypatch.setattr(
        OllamaClient, "answer", lambda self, question, evidence: "DID information [1]"
    )
    result = client.post(
        "/workspaces/one/query",
        headers=HEADERS,
        json={"question": "DID read security", "use_llm": True},
    )
    assert result.status_code == 200
    assert result.json()["mode"] == "local_llm"
    monkeypatch.setattr(
        OllamaClient, "answer", lambda self, question, evidence: "Unsupported claim [99]"
    )
    assert (
        client.post(
            "/workspaces/one/query",
            headers=HEADERS,
            json={"question": "DID read security", "use_llm": True},
        ).status_code
        == 503
    )
    client.post(
        f"/workspaces/one/documents/{doc}/review",
        headers=HEADERS,
        json={"approved": False, "reviewer": "engineer"},
    )
    assert (
        client.post(
            "/workspaces/one/runs/revoked", headers=HEADERS, params={"suite_id": "suite-one"}
        ).status_code
        == 409
    )
    assert client.get("/workspaces/one/suites/suite-one/export", headers=HEADERS).status_code == 409


def test_batch_approval_checks_all_field_permissions_before_writing():
    client = client_for()
    doc = uploaded(client)
    fields = client.get("/workspaces/one/fields", headers=HEADERS).json()
    assert (
        client.post(
            "/workspaces/one/fields/review-batch",
            headers=HEADERS,
            json={"reviewer": "engineer", "field_ids": [fields[0]["id"], "missing"]},
        ).status_code
        == 404
    )
    assert client.get("/workspaces/one/fields", headers=HEADERS).json()[0]["status"] == "proposed"
    result = client.post(
        "/workspaces/one/fields/review-batch",
        headers=HEADERS,
        json={"reviewer": "engineer", "field_ids": [f["id"] for f in fields]},
    )
    assert result.status_code == 200
    assert result.json()["reviewed"] == len(fields)
    assert all(
        f["status"] == "approved"
        for f in client.get("/workspaces/one/fields", headers=HEADERS).json()
    )
    assert doc
