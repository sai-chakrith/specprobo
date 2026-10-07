"""Field-level extraction evaluator for frozen documents and reviewed annotations."""

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from specprobe.ingest.extractor import extract_spec_fields
from specprobe.ingest.parsers import parse_excel, parse_pdf


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=Path("data/evaluation/manifest.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    metrics = defaultdict(lambda: dict(tp=0, fp=0, fn=0, missed=[], incorrect=[]))
    cases = []
    for case in manifest["cases"]:
        path = args.manifest.parent / case["file"]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != case["sha256"]:
            raise ValueError("Frozen input hash mismatch: " + case["file"])
        try:
            blocks, rows = (parse_pdf if path.suffix == ".pdf" else parse_excel)(path, case["id"])
            fields = extract_spec_fields(case["id"], rows, blocks)
            extraction_error = None
        except ValueError as error:
            fields = []
            extraction_error = str(error)
        actual = json.loads(json.dumps({f.path: f.value for f in fields}))
        cases.append(
            {
                "id": case["id"],
                "extraction_error": extraction_error,
                "locations": [f.provenance.model_dump(mode="json") for f in fields],
            }
        )
        for field_type, expected in case["expected"].items():
            observed = {key: value for key, value in actual.items() if key in expected}
            for key, value in expected.items():
                if observed.get(key) == value:
                    metrics[field_type]["tp"] += 1
                else:
                    metrics[field_type]["fn"] += 1
                    metrics[field_type]["missed"].append(
                        {"case": case["id"], "path": key, "expected": value}
                    )
                    if key in observed:
                        metrics[field_type]["fp"] += 1
                        metrics[field_type]["incorrect"].append(
                            {"case": case["id"], "path": key, "actual": observed[key]}
                        )
        # Extra unannotated fields count as FP unless explicitly excluded from the annotation scope.
        annotated = {key for values in case["expected"].values() for key in values}
        for key, value in actual.items():
            if key not in annotated and key not in case.get("excluded_paths", []):
                category = key.rsplit(".", 1)[-1]
                metrics[category]["fp"] += 1
                metrics[category]["incorrect"].append(
                    {"case": case["id"], "path": key, "actual": value}
                )
    for field_type, values in metrics.items():
        tp, fp, fn = (values[k] for k in ("tp", "fp", "fn"))
        missed_paths = {(item["case"], item["path"]) for item in values["missed"]}
        replacements = sum(
            (item["case"], item["path"]) in missed_paths for item in values["incorrect"]
        )
        values.update(
            precision=tp / (tp + fp) if tp + fp else None,
            recall=tp / (tp + fn) if tp + fn else None,
            correction_actions=fp + fn - replacements,
            measured_correction_seconds=manifest.get("correction_seconds_by_field_type", {}).get(
                field_type
            ),
        )
    report = {
        "status": "ENGINEER_REVIEWED_HELD_OUT"
        if manifest["review_status"] == "approved" and manifest.get("reviewer")
        else "PROVISIONAL_SYNTHETIC_CANDIDATE",
        "manifest_sha256": hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
        "review_status": manifest["review_status"],
        "field_metrics": dict(metrics),
        "measured_correction_seconds": manifest.get("measured_correction_seconds"),
        "cases": cases,
        "limitation": (
            "Field edit counts are not measured engineering effort; "
            "synthetic results do not estimate OEM reliability."
        ),
    }
    args.output.write_text(json.dumps(report, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k != "cases"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
