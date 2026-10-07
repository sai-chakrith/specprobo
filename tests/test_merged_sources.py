from specprobe.ingest.extractor import extract_spec_fields
from specprobe.ingest.models import TableRow, TextBlock


def test_merged_conditions_preserve_all_source_locations():
    clauses = [
        TextBlock("doc", "DID 0x1000 requires ignition is true.", page=2),
        TextBlock("doc", "DID 0x1000 requires speed below 5 km/h.", page=8),
    ]
    fields = extract_spec_fields("doc", [TableRow("doc", {"DID": "0x1000", "Bytes": 2})], clauses)
    field = next(f for f in fields if f.path == "dids[0].preconditions")
    assert {reference.page for reference in field.provenance.references} == {2, 8}
    assert all(
        reference.source_snippet and reference.document_id == "doc"
        for reference in field.provenance.references
    )
