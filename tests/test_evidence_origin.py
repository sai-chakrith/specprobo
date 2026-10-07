from specprobe.ingest.extractor import extract_spec_fields
from specprobe.ingest.models import TableRow, TextBlock
from tests.test_api import HEADERS, approve_source, client_for, uploaded


def test_schema_defaults_are_not_cited_as_uploaded_source_evidence():
    client = client_for()
    document = uploaded(client)
    approve_source(client, document)
    result = client.post(
        "/workspaces/one/query", headers=HEADERS, json={"question": "standard_version"}
    ).json()
    assert result["citations"] == []


def test_case_insensitive_name_collision_requires_engineer_resolution():
    sentence = "The VIN data identifier requires ignition is true."
    rows = [
        TableRow("doc", {"DID": "0x1000", "Bytes": 2, "Signal name": "vin"}),
        TableRow("doc", {"DID": "0x1001", "Bytes": 2, "Signal name": "VIN"}),
    ]
    fields = extract_spec_fields("doc", rows, [TextBlock("doc", sentence, page=2)])
    assert any(f.path == "unresolved_requirements" for f in fields)
    assert not any(f.path.endswith(".preconditions") for f in fields)
