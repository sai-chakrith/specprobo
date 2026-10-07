"""Reviewed specification assembly and portable, hexadecimal test snapshots."""

import hashlib
import json
import re
from collections import Counter
from typing import Any

from .domain.provenance import Provenance
from .domain.schema import EcuSpec
from .domain.testcase import TestCase
from .storage.models import ExtractedField


def spec_fields(spec: EcuSpec) -> list[tuple[str, Any]]:
    result: list[tuple[str, Any]] = []
    for key, value in spec.model_dump(mode="json", exclude={"field_registry"}).items():
        if isinstance(value, list) and key != "nrc_priority" and value:
            for index, item in enumerate(value):
                for name, child in item.items():
                    result.append((f"{key}[{index}].{name}", child))
        elif key == "timing":
            result.extend((f"timing.{name}", child) for name, child in value.items())
        else:
            result.append((key, value))
    return result


def assemble_spec(fields: list[ExtractedField], document_id: str) -> EcuSpec:
    data: dict[str, Any] = {}
    registry: dict[str, Provenance] = {}
    seen: dict[str, Any] = {}
    for field in fields:
        if field.document_id != document_id:
            continue
        path = field.json_path
        value = field.value.get("value", field.value)
        if path in registry:
            if seen[path] != value:
                raise ValueError(f"Conflicting approved values for {path}")
            continue
        match = re.fullmatch(r"(\w+)\[(\d+)\]\.(\w+)", path)
        if match:
            root, number, name = match.groups()
            index = int(number)
            if index > 10000:
                raise ValueError("Specification index exceeds limit")
            items = data.setdefault(root, [])
            while len(items) <= index:
                items.append({})
            items[index][name] = value
        elif path.startswith("timing."):
            data.setdefault("timing", {})[path.split(".", 1)[1]] = value
        elif path in EcuSpec.model_fields and path != "field_registry":
            data[path] = value
        else:
            raise ValueError(f"Unsupported specification path: {path}")
        raw = field.value.get("provenance", {})
        seen[path] = value
        registry[path] = Provenance(
            field_id=field.id,
            document_id=document_id,
            page=raw.get("page"),
            sheet=raw.get("sheet"),
            row=raw.get("row"),
            source_snippet=raw.get("source_snippet", json.dumps(value, sort_keys=True)),
            confidence=raw.get("confidence", 1.0),
            status=field.value.get("review_status", "approved"),
            reviewer=field.value.get("reviewer"),
        )
    data["field_registry"] = registry
    spec = EcuSpec.model_validate(data)
    validate_spec(spec)
    return spec


def validate_spec(spec: EcuSpec) -> None:
    if not spec.sessions or not spec.services or not spec.nrc_priority:
        raise ValueError("Sessions, services and NRC priority must not be empty")
    for values in (
        [x.id for x in spec.sessions],
        [x.sid for x in spec.services],
        [x.did for x in spec.dids],
        [x.rid for x in spec.routines],
        [x.level for x in spec.security_levels],
        spec.nrc_priority,
    ):
        if len(values) != len(set(values)):
            raise ValueError("Duplicate specification identifiers")
    sessions = {x.id for x in spec.sessions}
    levels = {x.level for x in spec.security_levels}
    if any(level > 63 for level in levels):
        raise ValueError("Simulator supports security levels 0 through 63")
    for item in [*spec.services, *spec.dids, *spec.routines]:
        payload = item.model_dump()
        for key in ("allowed_sessions", "read_sessions", "write_sessions", "sessions"):
            if not set(payload.get(key, [])) <= sessions:
                raise ValueError(f"Unknown session reference in {payload['name']}")
        for key in ("required_security_level", "read_security", "write_security", "security"):
            if payload.get(key) is not None and payload[key] not in levels:
                raise ValueError(f"Unknown security reference in {payload['name']}")
    if any(nrc < 0 or nrc > 255 for nrc in spec.nrc_priority):
        raise ValueError("NRC values must fit in one byte")


def case_payload(case: TestCase) -> dict[str, Any]:
    data = case.model_dump(exclude={"setup_steps", "steps", "expected"})
    data.update(
        setup_steps=[x.hex() for x in case.setup_steps],
        steps=[x.hex() for x in case.steps],
        expected=case.expected.hex() if case.expected is not None else None,
    )
    return data


def restore_case(data: dict[str, Any]) -> TestCase:
    return TestCase.model_validate(
        {
            **data,
            "setup_steps": [bytes.fromhex(x) for x in data["setup_steps"]],
            "steps": [bytes.fromhex(x) for x in data["steps"]],
            "expected": bytes.fromhex(data["expected"]) if data["expected"] is not None else None,
        }
    )


def snapshot_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def coverage(cases: list[TestCase]) -> dict[str, Any]:
    outcomes: Counter[str] = Counter()
    services: Counter[str] = Counter()
    nrcs: Counter[str] = Counter()
    tags: Counter[str] = Counter()
    for case in cases:
        response = case.expected
        outcome = (
            "suppressed"
            if response is None
            else ("negative" if response[:1] == b"\x7f" else "positive")
        )
        outcomes[outcome] += 1
        if case.steps and case.steps[-1]:
            services[f"0x{case.steps[-1][0]:02X}"] += 1
        if outcome == "negative" and response is not None:
            nrcs[f"0x{response[2]:02X}"] += 1
        for tag in case.tags:
            tags[tag.split("-", 1)[0]] += 1
    return {
        "total": len(cases),
        "outcomes": dict(outcomes),
        "services": dict(services),
        "nrcs": dict(nrcs),
        "families": dict(tags),
        "limitations": [
            "Timing values are modeled; wall-clock timing is not measured.",
            "Security keys and DID read data use simulator conventions.",
        ],
    }


def export_python(payload: dict[str, Any]) -> str:
    """Export a runnable simulator template, with a transport seam for approved benches."""
    encoded = json.dumps(payload, sort_keys=True)
    return f'''"""Reviewed SpecProbe suite. Default execution uses the simulator.
Replace make_transport only after validating the adapter and ECU-specific data/key behavior.
"""
import json
from specprobe.domain.schema import EcuSpec
from specprobe.runner.executor import run_suite
from specprobe.sim.ecu import EcuSimulator
from specprobe.workflow import restore_case

SNAPSHOT = json.loads({encoded!r})

def make_transport(spec):
    return EcuSimulator(spec)

def main():
    spec = EcuSpec.model_validate(SNAPSHOT["spec"])
    cases = [restore_case(item) for item in SNAPSHOT["cases"]]
    results = run_suite(cases, make_transport(spec))
    failures = [r.test_id for r in results if not r.passed]
    print(json.dumps({{"passed": len(results) - len(failures),
                      "total": len(results), "failures": failures}}, indent=2))
    return 1 if failures else 0

if __name__ == "__main__":
    raise SystemExit(main())
'''
