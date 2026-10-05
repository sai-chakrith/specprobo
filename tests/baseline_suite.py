import json
from pathlib import Path
from typing import cast

from specprobe.domain.testcase import TestCase, TraceRef


def _bytes(value: str) -> bytes:
    return bytes.fromhex(value.replace(" ", ""))


def build_baseline_suite(path: str | Path | None = None) -> list[TestCase]:
    cases_path = Path(path) if path else Path(__file__).with_name("baseline_cases.json")
    raw = cast(list[dict[str, object]], json.loads(cases_path.read_text(encoding="utf-8")))
    cases: list[TestCase] = []
    for item in raw:
        case_id = str(item["id"])
        cases.append(
            TestCase(
                id=case_id,
                trace_to=[TraceRef(field_id=f"baseline.{case_id}", page=1)],
                preconditions={},
                setup_steps=[_bytes(value) for value in cast(list[str], item.get("setup", []))],
                steps=[_bytes(str(item["request"]))],
                environment=cast(dict[str, object], item.get("environment", {})),
                expected=_bytes(str(item["expected"])),
                tags=["baseline", str(item.get("reason", ""))],
            )
        )
    return cases
