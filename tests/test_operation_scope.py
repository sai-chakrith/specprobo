from specprobe.demo import build_spec
from specprobe.gen.generator import generate_suite
from specprobe.ingest.extractor import extract_spec_fields
from specprobe.ingest.models import TableRow, TextBlock


def test_isolated_write_condition_negatives_target_write_operation():
    suite = generate_suite(build_spec())
    cases = [c for c in suite if c.tags[0].startswith("dids-conjunct-0-")]
    assert cases and all(c.steps[-1][0] == 0x2E and c.expected == b"\x7f\x2e\x22" for c in cases)


def test_read_prose_conditions_keep_operation_scope():
    fields = extract_spec_fields(
        "doc",
        [TableRow("doc", {"DID": "0x1000", "Bytes": 2})],
        [TextBlock("doc", "DID 0x1000 may be read only when ignition is true.", page=4)],
    )
    assert any(f.path == "dids[0].read_preconditions" for f in fields)
    assert not any(f.path == "dids[0].preconditions" for f in fields)
