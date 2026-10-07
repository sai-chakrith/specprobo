from tests.test_api import HEADERS, client_for, uploaded


def test_normalized_json_evidence_does_not_invent_source_line_numbers():
    client = client_for()
    uploaded(client)
    fields = client.get("/workspaces/one/fields", headers=HEADERS).json()
    assert all(f["provenance"].get("row") is None for f in fields)
    version = next(f for f in fields if f["json_path"] == "standard_version")
    assert version["provenance"]["origin"] == "normalized_json"
    assert version["provenance"]["defaulted"] is True
