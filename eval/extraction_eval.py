import json
from collections.abc import Callable
from pathlib import Path

from specprobe.domain.schema import EcuSpec
from specprobe.ingest.extractor import extract_spec_fields
from specprobe.ingest.models import TableRow, TextBlock
from specprobe.ingest.parsers import parse_excel, parse_pdf


def _normalize_precondition(
    target: str | None,
    signal: str | None,
    op: str | None,
    value: object,
    unit: str | None = None,
) -> tuple[str, str, str, object, str | None]:
    norm_target = str(target or "").lower()
    norm_signal = str(signal or "")
    norm_op = str(op or "==")
    norm_val = value
    norm_unit = unit.strip() if isinstance(unit, str) and unit.strip() else None

    # Boolean normalization: != False is == True; != True is == False
    if isinstance(norm_val, bool) or str(norm_val).lower() in ("true", "false"):
        bool_val = norm_val if isinstance(norm_val, bool) else (str(norm_val).lower() == "true")
        if norm_op == "!=":
            norm_op = "=="
            norm_val = not bool_val
        elif norm_op == "==":
            norm_val = bool_val
        norm_unit = None

    # Numeric unit normalization to canonical units (km/h, V, ms, °C)
    elif norm_unit is not None:
        u = norm_unit.lower()
        num_val: float | int | None = None
        if isinstance(norm_val, (int, float)):
            num_val = norm_val
        elif isinstance(norm_val, str):
            try:
                num_val = float(norm_val)
            except ValueError:
                num_val = None

        if num_val is not None:
            if u in ("v", "volt", "volts"):
                norm_unit = "V"
                norm_val = num_val
            elif u in ("mv", "millivolt", "millivolts"):
                norm_unit = "V"
                norm_val = num_val / 1000.0
            elif u in ("kv", "kilovolt", "kilovolts"):
                norm_unit = "V"
                norm_val = num_val * 1000.0
            elif u in ("ms", "millisecond", "milliseconds"):
                norm_unit = "ms"
                norm_val = num_val
            elif u in ("s", "sec", "second", "seconds"):
                norm_unit = "ms"
                norm_val = num_val * 1000.0
            elif u in ("km/h", "kph", "kmh"):
                norm_unit = "km/h"
                norm_val = num_val
            elif u in ("m/s", "mps"):
                norm_unit = "km/h"
                norm_val = num_val * 3.6
            elif u in ("°c", "c", "degc", "deg_c", "celsius"):
                norm_unit = "°C"
                norm_val = num_val

            if isinstance(norm_val, float) and norm_val.is_integer():
                norm_val = int(norm_val)

    return (norm_target, norm_signal, norm_op, norm_val, norm_unit)


def _expected(path: Path) -> dict[str, set[tuple[object, ...]]]:
    spec = EcuSpec.model_validate_json(path.read_text(encoding="utf-8")).model_dump(mode="json")
    expected: dict[str, set[tuple[object, ...]]] = {
        "did": {("did", item["did"]) for item in spec["dids"]},
        "length_bytes": {("length_bytes", item["length_bytes"]) for item in spec["dids"]},
        "precondition": {
            _normalize_precondition(
                f"0x{item['did']:04x}",
                condition.get("signal"),
                condition.get("op", "=="),
                condition.get("value"),
                condition.get("unit"),
            )
            for item in spec["dids"]
            for condition in item.get("preconditions", [])
        }
        | {
            _normalize_precondition(
                f"0x{item['rid']:04x}",
                condition.get("signal"),
                condition.get("op", "=="),
                condition.get("value"),
                condition.get("unit"),
            )
            for item in spec.get("routines", [])
            for condition in item.get("preconditions", [])
        },
    }
    expected["session"] = {
        (f"sessions[{index}].{key}", value)
        for index, item in enumerate(spec["sessions"])
        for key, value in item.items()
    }
    expected["security"] = {
        (f"security_levels[{index}].{key}", value)
        for index, item in enumerate(spec["security_levels"])
        for key, value in item.items()
    }
    expected["service"] = {
        (f"services[{index}].{key}", json.dumps(value, sort_keys=True))
        for index, item in enumerate(spec["services"])
        for key, value in {
            **item,
            "allowed_sessions": item.get("allowed_sessions", []),
            "required_security_level": item.get("required_security_level"),
            "subfunctions": item.get("subfunctions", []),
            "suppress_positive_response_supported": item.get(
                "suppress_positive_response_supported", False
            ),
        }.items()
    }
    expected["routine"] = {
        (f"routines[{index}].{key}", json.dumps(value, sort_keys=True))
        for index, item in enumerate(spec["routines"])
        for key, value in {
            **item,
            "sessions": item.get("sessions", []),
            "security": item.get("security"),
            "preconditions": item.get("preconditions", []),
        }.items()
    }
    expected["timing"] = {(f"timing.{key}", value) for key, value in spec["timing"].items()}
    expected["nrc_priority"] = {("nrc_priority", json.dumps(spec["nrc_priority"]))}
    return expected


def main() -> None:
    root = Path(__file__).parents[1]
    cases: dict[
        str, tuple[Path, Path, Callable[[str | Path, str], tuple[list[TextBlock], list[TableRow]]]]
    ] = {
        "OEM-A": (
            root / "data/synthetic/ground_truth/oem_a.json",
            root / "data/synthetic/rendered/oem_a.pdf",
            parse_pdf,
        ),
        "OEM-B": (
            root / "data/synthetic/ground_truth/oem_b.json",
            root / "data/synthetic/rendered/oem_b.xlsx",
            parse_excel,
        ),
    }
    print("oem | field type | precision | recall")
    for name, (truth_path, document_path, parser) in cases.items():
        blocks, rows = parser(document_path, name)
        extracted = extract_spec_fields(name, rows, blocks)
        identifiers = {
            field.path.rsplit(".", 1)[0]: int(field.value)
            for field in extracted
            if field.path.endswith((".did", ".rid"))
        }
        actual: dict[str, set[tuple[object, ...]]] = {
            "did": {("did", field.value) for field in extracted if field.path.endswith(".did")},
            "length_bytes": {
                ("length_bytes", field.value)
                for field in extracted
                if field.path.endswith("length_bytes")
            },
            "precondition": {
                _normalize_precondition(
                    f"0x{identifiers[field.path.rsplit('.', 1)[0]]:04x}",
                    condition.get("signal"),
                    condition.get("op"),
                    condition.get("value"),
                    condition.get("unit"),
                )
                for field in extracted
                if field.path.endswith(".preconditions") and isinstance(field.value, list)
                for condition in field.value
            },
            "session": set(),
            "security": set(),
            "service": set(),
            "routine": set(),
            "timing": set(),
            "nrc_priority": set(),
        }
        for field in extracted:
            if field.path.startswith("sessions["):
                actual.setdefault("session", set()).add((field.path, field.value))
            elif field.path.startswith("security_levels["):
                actual.setdefault("security", set()).add((field.path, field.value))
            elif field.path.startswith("services["):
                actual.setdefault("service", set()).add(
                    (field.path, json.dumps(field.value, sort_keys=True))
                )
            elif field.path.startswith("routines["):
                actual.setdefault("routine", set()).add(
                    (field.path, json.dumps(field.value, sort_keys=True))
                )
            elif field.path.startswith("timing."):
                actual.setdefault("timing", set()).add((field.path, field.value))
            elif field.path == "nrc_priority":
                actual.setdefault("nrc_priority", set()).add((field.path, json.dumps(field.value)))
        for field_type, expected in _expected(truth_path).items():
            correct = expected & actual[field_type]
            precision = len(correct) / len(actual[field_type]) if actual[field_type] else 1.0
            recall = len(correct) / len(expected) if expected else 1.0
            print(f"{name} | {field_type} | {precision:.1%} | {recall:.1%}")
            for value in sorted(actual[field_type] - expected):
                print(f"wrong {name} {field_type}: {value}")
            for value in sorted(expected - actual[field_type]):
                print(f"missed {name} {field_type}: {value}")
    print("Ollama run: not executed; offline evaluation uses FakeLLM.")


if __name__ == "__main__":
    main()
