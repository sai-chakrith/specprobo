"""Reviewed specification assembly and portable, hexadecimal test snapshots."""

import hashlib
import json
import re
from collections import Counter
from typing import Any

from .domain.conditions import environment, holds
from .domain.provenance import Provenance
from .domain.schema import EcuSpec
from .domain.testcase import TestCase
from .storage.models import ExtractedField


def spec_fields(spec: EcuSpec) -> list[tuple[str, Any]]:
    result: list[tuple[str, Any]] = []
    for key, value in spec.model_dump(mode="json", exclude={"field_registry"}).items():
        if (
            isinstance(value, list)
            and key not in {"nrc_priority", "unresolved_requirements"}
            and value
        ):
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
            table=raw.get("table"),
            origin=raw.get("origin", "source"),
            defaulted=raw.get("defaulted", False),
            references=raw.get("references", []),
            status=field.value.get("review_status", "approved"),
            reviewer=field.value.get("reviewer"),
        )
    data["field_registry"] = registry
    spec = EcuSpec.model_validate(data)
    validate_spec(spec)
    return spec


def validate_spec(spec: EcuSpec) -> None:
    if spec.unresolved_requirements:
        raise ValueError("Unresolved requirements: " + "; ".join(spec.unresolved_requirements))
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
    services = {x.sid for x in spec.services}
    supported = {0x10, 0x11, 0x22, 0x27, 0x2E, 0x31, 0x3E}
    if not services <= supported:
        raise ValueError(
            "Services without an implemented response model: " + str(services - supported)
        )
    if 0x10 not in services or spec.sessions[0].id != 1:
        raise ValueError("Explicit default session 0x01 and SessionControl support are required")
    if not {0x11, 0x12, 0x13, 0x22, 0x24, 0x31, 0x33, 0x35, 0x7E, 0x7F} <= set(spec.nrc_priority):
        raise ValueError("NRC ordering is incomplete for implemented diagnostic rules")
    for service in spec.services:
        if service.suppress_positive_response_supported and service.sid in {0x22, 0x2E}:
            raise ValueError("Suppression requires a modeled subfunction service")
        if len({s.value for s in service.subfunctions}) != len(service.subfunctions):
            raise ValueError("Duplicate subfunctions")
        for sub in service.subfunctions:
            if not set(sub.allowed_sessions) <= sessions:
                raise ValueError("Unknown nested subfunction session")
            if (
                sub.required_security_level is not None
                and sub.required_security_level not in levels
            ):
                raise ValueError("Unknown nested subfunction security")
    for did in spec.dids:
        if not did.read_sessions and not did.write_sessions:
            raise ValueError("DID read/write permission requirements are unresolved")
        if (
            did.read_sessions
            and 0x22 not in services
            or did.write_sessions
            and 0x2E not in services
        ):
            raise ValueError("DID references an unsupported read/write service")
        if did.length_bytes > 4095:
            raise ValueError("DID payload exceeds supported transport limit")
    for routine in spec.routines:
        if not routine.sessions:
            raise ValueError("Routine session requirements are unresolved")
        if 0x31 not in services or not routine.control_types:
            raise ValueError("Routine service or controls missing")
        if not set(routine.control_types) <= {1, 2, 3}:
            raise ValueError("Unsupported routine control")
        if set(routine.parameter_lengths) != set(routine.control_types):
            raise ValueError("Routine parameter lengths must explicitly cover every control")
        if any(n < 0 or n > 4091 for n in routine.parameter_lengths.values()):
            raise ValueError("Invalid routine parameter length")
    if spec.timing.p2_star_ms < spec.timing.p2_ms:
        raise ValueError("P2-star must not be shorter than P2")
    if spec.standard_version >= 2013 and (
        spec.timing.p2_ms > 65535 or spec.timing.p2_star_ms > 655350 or spec.timing.p2_star_ms % 10
    ):
        raise ValueError(
            "Session timing cannot be represented in the declared standard wire format"
        )
    for identifier, value in spec.response_profile.did_data.items():
        configured_did = spec.did(identifier)
        if configured_did is None or len(bytes.fromhex(value)) != configured_did.length_bytes:
            raise ValueError("Configured DID data length or identifier is invalid")
    if spec.response_profile.basis == "engineer_configured":
        if not {d.did for d in spec.dids if d.read_sessions} <= set(spec.response_profile.did_data):
            raise ValueError(
                "Engineer-configured profiles require explicit data for every readable DID"
            )
        if not (levels - {0}) <= set(spec.response_profile.seeds):
            raise ValueError(
                "Engineer-configured profiles require explicit seeds for every unlocked level"
            )
    for level, seed in spec.response_profile.seeds.items():
        if level not in levels or len(bytes.fromhex(seed)) != 2:
            raise ValueError("Configured seed must use a known level and two bytes for this model")
    for sid, mask in spec.response_profile.response_masks.items():
        raw = bytes.fromhex(mask)
        identity_length = {0x10: 2, 0x11: 2, 0x22: 3, 0x27: 2, 0x2E: 3, 0x31: 4, 0x3E: 2}.get(
            sid, 1
        )
        if (
            sid not in services
            or len(raw) < identity_length
            or raw[:identity_length] != b"\xff" * identity_length
        ):
            raise ValueError("Masks cannot hide response service or echoed request identity")
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
        for conditions in [
            getattr(item, "preconditions", []),
            getattr(item, "read_preconditions", []),
        ]:
            state_conditions = [c for c in conditions if c.kind in {"session", "security"}]
            if state_conditions and not any(
                all(holds(c, session if c.kind == "session" else level) for c in state_conditions)
                for session in sessions
                for level in {0, *levels}
            ):
                raise ValueError("Contradictory session/security conditions")
            for condition in conditions:
                if condition.op is None or condition.value is None:
                    raise ValueError("Missing condition operator or value")
                if condition.kind in {"signal", "timing"} and not condition.signal:
                    raise ValueError("Missing condition signal")
                if condition.unit not in {None, "km/h", "V", "ms", "°C"}:
                    raise ValueError(
                        "Unsupported or noncanonical unit; engineer conversion required"
                    )
                if condition.kind == "session" and condition.value not in sessions:
                    raise ValueError("Unknown condition session")
                if condition.kind == "security" and condition.value not in levels:
                    raise ValueError("Unknown condition security")
                if condition.op in {"<", "<=", ">", ">="} and (
                    isinstance(condition.value, bool)
                    or not isinstance(condition.value, (int, float))
                ):
                    raise ValueError("Numeric comparisons need a numeric value")
            environment(conditions, True)
            for signal in {c.signal for c in conditions}:
                if len({c.unit for c in conditions if c.signal == signal}) > 1:
                    raise ValueError("Mixed units for the same signal")
    if any(nrc < 0 or nrc > 255 for nrc in spec.nrc_priority):
        raise ValueError("NRC values must fit in one byte")


def case_payload(case: TestCase) -> dict[str, Any]:
    data = case.model_dump(mode="json", exclude={"setup_steps", "steps", "expected"})
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
