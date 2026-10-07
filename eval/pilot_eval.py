"""Aggregate signed pilot observations; targets are never substituted for data."""

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    groups = defaultdict(list)
    identifiers = set()
    with args.observations.open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            key = (row["participant_id"], row["task_id"], row["mode"])
            if (
                key in identifiers
                or row["mode"] not in {"manual", "assisted"}
                or not row["reviewer"]
            ):
                raise ValueError("Duplicate observation or missing valid mode/reviewer")
            identifiers.add(key)
            for field in [
                "author_seconds",
                "review_seconds",
                "generated_cases",
                "accepted_cases",
                "requirements_total",
                "requirements_covered",
                "confirmed_defects",
            ]:
                row[field] = float(row[field])
                if not math.isfinite(row[field]) or row[field] < 0:
                    raise ValueError("Negative observation: " + field)
            if (
                row["accepted_cases"] > row["generated_cases"]
                or row["requirements_covered"] > row["requirements_total"]
            ):
                raise ValueError("Invalid accepted-case or requirement counts")
            if row["confirmed_defects"] and not row["defect_confirmation_reference"]:
                raise ValueError("Confirmed defects require an independent confirmation reference")
            groups[row["mode"]].append(row)
    results = {}
    for mode, rows in groups.items():
        generated = sum(r["generated_cases"] for r in rows)
        total = sum(r["requirements_total"] for r in rows)
        results[mode] = {
            "observations": len(rows),
            "median_author_seconds": statistics.median(r["author_seconds"] for r in rows),
            "median_review_seconds": statistics.median(r["review_seconds"] for r in rows),
            "accepted_cases": sum(r["accepted_cases"] for r in rows),
            "case_acceptance": sum(r["accepted_cases"] for r in rows) / generated
            if generated
            else None,
            "requirement_coverage": sum(r["requirements_covered"] for r in rows) / total
            if total
            else None,
            "confirmed_defects": sum(r["confirmed_defects"] for r in rows),
        }
    report = {
        "status": "MEASURED_PILOT" if groups else "NOT_RUN",
        "results": results,
        "proposed_targets": None,
        "limitations": (
            "Observational summary only. Confirm counterbalancing, catalogue scope, "
            "defect identity deduplication and human signatures before interpreting benefits."
        ),
    }
    args.output.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
