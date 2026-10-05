from dataclasses import replace
from pathlib import Path

from specprobe.data_loader import load_spec
from specprobe.domain.schema import EcuSpec
from specprobe.gen.generator import generate_suite
from specprobe.ingest.extractor import extract_spec_fields, reconstruct_spec
from specprobe.ingest.parsers import parse_excel, parse_pdf
from specprobe.ingest.render import render_oem_a_pdf, render_oem_b_xlsx
from specprobe.runner.executor import run_suite
from specprobe.sim.ecu import EcuSimulator

ROOT = Path(__file__).parents[1]


def test_end_to_end_oem_a(tmp_path: Path) -> None:
    truth_path = ROOT / "data" / "synthetic" / "ground_truth" / "oem_a.json"
    pdf_path = tmp_path / "oem_a.pdf"

    render_oem_a_pdf(truth_path, pdf_path)
    blocks, rows = parse_pdf(pdf_path, "OEM-A")
    fields = extract_spec_fields("OEM-A", rows, blocks)

    approved_fields = [
        replace(field, provenance=field.provenance.model_copy(update={"status": "approved"}))
        for field in fields
    ]
    ground_truth = load_spec(truth_path)
    reconstructed = reconstruct_spec(ground_truth, approved_fields)

    diffs: list[str] = []
    for field_name in EcuSpec.model_fields:
        val_rec = getattr(reconstructed, field_name)
        val_truth = getattr(ground_truth, field_name)
        if val_rec != val_truth:
            diffs.append(
                f"Field '{field_name}' differs: "
                f"reconstructed={val_rec!r} != ground_truth={val_truth!r}"
            )
    assert reconstructed == ground_truth, "\n".join(diffs)

    suite = generate_suite(reconstructed)
    assert len(suite) > 0
    results = run_suite(suite, EcuSimulator(reconstructed))
    failing = [r.test_id for r in results if not r.passed]
    assert not failing, f"Test suite had failures on clean simulator: {failing}"


def test_end_to_end_oem_b(tmp_path: Path) -> None:
    truth_path = ROOT / "data" / "synthetic" / "ground_truth" / "oem_b.json"
    xlsx_path = tmp_path / "oem_b.xlsx"

    render_oem_b_xlsx(truth_path, xlsx_path)
    blocks, rows = parse_excel(xlsx_path, "OEM-B")
    fields = extract_spec_fields("OEM-B", rows, blocks)

    approved_fields = [
        replace(field, provenance=field.provenance.model_copy(update={"status": "approved"}))
        for field in fields
    ]
    ground_truth = load_spec(truth_path)
    reconstructed = reconstruct_spec(ground_truth, approved_fields)

    diffs: list[str] = []
    for field_name in EcuSpec.model_fields:
        val_rec = getattr(reconstructed, field_name)
        val_truth = getattr(ground_truth, field_name)
        if val_rec != val_truth:
            diffs.append(
                f"Field '{field_name}' differs: "
                f"reconstructed={val_rec!r} != ground_truth={val_truth!r}"
            )
    assert reconstructed == ground_truth, "\n".join(diffs)

    suite = generate_suite(reconstructed)
    assert len(suite) > 0
    results = run_suite(suite, EcuSimulator(reconstructed))
    failing = [r.test_id for r in results if not r.passed]
    assert not failing, f"Test suite had failures on clean simulator: {failing}"
