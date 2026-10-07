from pathlib import Path

import pytest
from openpyxl import Workbook

from specprobe.ingest.extractor import extract_spec_fields
from specprobe.ingest.models import TableRow
from specprobe.ingest.parsers import parse_excel


def test_first_row_header_aliases_keep_physical_sheet_and_row(tmp_path: Path):
    book = Workbook()
    sheet = book.active
    sheet.title = "Diagnostic data"
    sheet.append(
        ["DID Code", "Data size (bytes)", "Description", "Read sessions", "Write sessions"]
    )
    sheet.append(["0xF190", 17, "VIN", "1,3", "3"])
    path = tmp_path / "varied.xlsx"
    book.save(path)
    blocks, rows = parse_excel(path, "doc")
    fields = extract_spec_fields("doc", rows, blocks)
    identifier = next(f for f in fields if f.path == "dids[0].did")
    assert identifier.value == 0xF190
    assert identifier.provenance.sheet == "Diagnostic data"
    assert identifier.provenance.row == 2


def test_conflicting_extraction_is_not_last_value_wins():
    rows = [
        TableRow("doc", {"DID": "0xF190", "Bytes": 17}, page=1),
        TableRow("doc", {"DID": "0xF190", "Bytes": 16}, page=2),
    ]
    with pytest.raises(ValueError, match="Conflicting"):
        extract_spec_fields("doc", rows, [])
