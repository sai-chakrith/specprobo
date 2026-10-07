import sqlite3
from pathlib import Path

import pytest
from openpyxl import Workbook
from reportlab.pdfgen import canvas

from specprobe.demo import build_spec
from specprobe.gen.generator import generate_suite
from specprobe.ingest.extractor import extract_spec_fields
from specprobe.ingest.models import TableRow
from specprobe.ingest.parsers import parse_excel, parse_pdf
from specprobe.runner.executor import run_suite
from specprobe.sim.ecu import EcuSimulator
from specprobe.storage.db import create_database


def test_seconds_convert_to_milliseconds_with_source_location():
    fields = extract_spec_fields(
        "doc",
        [
            TableRow(
                "doc",
                {"P2 milliseconds": 50, "P2-star milliseconds": 5000, "S3 seconds": 7},
                sheet="Timing",
                row=4,
            )
        ],
        [],
    )
    value = next(f for f in fields if f.path == "timing.s3_ms")
    assert value.value == 7000
    assert value.provenance.sheet == "Timing" and value.provenance.row == 4


def test_scanned_and_unsupported_documents_are_explicit(tmp_path: Path):
    pdf = tmp_path / "scan.pdf"
    page = canvas.Canvas(str(pdf))
    page.rect(20, 20, 50, 50)
    page.save()
    with pytest.raises(ValueError, match="OCR"):
        parse_pdf(pdf, "scan")
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["DID records in an unknown layout"])
    sheet.append(["0xF190 length seventeen"])
    path = tmp_path / "unknown.xlsx"
    workbook.save(path)
    with pytest.raises(ValueError, match="Unsupported"):
        parse_excel(path, "unknown")


def test_database_migration_and_newer_version_rejection(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA user_version=1")
    engine = create_database("sqlite:///" + str(path))
    engine.dispose()
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone() == (3,)
        db.execute("PRAGMA user_version=99")
    with pytest.raises(ValueError, match="newer"):
        create_database("sqlite:///" + str(path))


def test_s3_cases_detect_simulator_that_does_not_expire_session():
    spec = build_spec()
    cases = [c for c in generate_suite(spec) if c.tags[0].startswith("timing-s3")]
    assert len(cases) == 3
    assert all(r.passed for r in run_suite(cases, EcuSimulator(spec)))

    class NoExpiry(EcuSimulator):
        def advance_time(self, elapsed_ms):
            pass

    results = run_suite(cases, NoExpiry(spec))
    assert sum(r.passed for r in results) == 1
    assert all(r.failure_kind == "response_mismatch" for r in results if not r.passed)
