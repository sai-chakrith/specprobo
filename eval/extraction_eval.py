import json
from collections.abc import Callable
from pathlib import Path

from specprobe.ingest.extractor import extract_fields
from specprobe.ingest.models import TableRow, TextBlock
from specprobe.ingest.parsers import parse_excel, parse_pdf


def _expected(path: Path) -> dict[str, set[str]]:
    spec = json.loads(path.read_text(encoding="utf-8"))
    return {
        "did": {str(item["did"]) for item in spec["dids"]},
        "length_bytes": {str(item["length_bytes"]) for item in spec["dids"]},
        "precondition": {
            str(condition["signal"])
            for item in spec["dids"]
            for condition in item.get("preconditions", [])
        },
    }


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
        extracted = extract_fields(name, rows, blocks)
        actual: dict[str, set[str]] = {
            "did": {str(field.value) for field in extracted if field.path.endswith(".did")},
            "length_bytes": {
                str(field.value) for field in extracted if field.path.endswith("length_bytes")
            },
            "precondition": {
                str(field.value["signal"]) for field in extracted if field.path == "preconditions"
            },
        }
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
