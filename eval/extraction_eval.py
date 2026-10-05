import json
from collections.abc import Callable
from pathlib import Path

from specprobe.ingest.extractor import extract_spec_fields
from specprobe.ingest.models import TableRow, TextBlock
from specprobe.ingest.parsers import parse_excel, parse_pdf


def _expected(path: Path) -> dict[str, set[tuple[object, ...]]]:
    spec = json.loads(path.read_text(encoding="utf-8"))
    expected: dict[str, set[tuple[object, ...]]] = {
        "did": {("did", item["did"]) for item in spec["dids"]},
        "length_bytes": {("length_bytes", item["length_bytes"]) for item in spec["dids"]},
        "precondition": {
            (
                f"0x{item['did']:04x}",
                condition["signal"],
                condition["op"],
                condition["value"],
            )
            for item in spec["dids"]
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
    expected["timing"] = {
        (f"timing.{key}", value) for key, value in spec["timing"].items()
    }
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
        actual: dict[str, set[tuple[object, ...]]] = {
            "did": {("did", field.value) for field in extracted if field.path.endswith(".did")},
            "length_bytes": {
                ("length_bytes", field.value)
                for field in extracted
                if field.path.endswith("length_bytes")
            },
            "precondition": {
                (
                    str(field.value.get("target")),
                    field.value.get("signal"),
                    field.value.get("op"),
                    field.value.get("value"),
                )
                for field in extracted
                if field.path.endswith(".preconditions") and isinstance(field.value, dict)
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
                actual.setdefault("nrc_priority", set()).add(
                    (field.path, json.dumps(field.value))
                )
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
