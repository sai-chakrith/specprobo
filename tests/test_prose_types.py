from specprobe.ingest.extractor import extract_spec_fields
from specprobe.ingest.models import TableRow, TextBlock


def test_boolean_and_numeric_prose_conditions_are_not_deduplicated_as_equivalent():
    fields = extract_spec_fields(
        "doc",
        [
            TableRow(
                "doc",
                {
                    "DID": "0x1000",
                    "Bytes": 2,
                    "Preconditions": [
                        {
                            "kind": "signal",
                            "signal": "mode",
                            "op": "==",
                            "value": False,
                            "source_text": "mode is false",
                        }
                    ],
                },
            )
        ],
        [TextBlock("doc", "DID 0x1000 requires mode equal to 0.")],
    )
    conditions = next(f.value for f in fields if f.path == "dids[0].preconditions")
    assert len(conditions) == 2
