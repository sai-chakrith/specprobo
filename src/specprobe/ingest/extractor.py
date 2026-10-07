import ast
import json
import re
from dataclasses import dataclass
from typing import Any

from jsonschema import validate  # type: ignore[import-untyped]

from ..domain.provenance import Provenance
from ..domain.schema import EcuSpec, Precondition
from .llm import FakeLLM, LLMClient
from .models import TableRow, TextBlock


@dataclass(frozen=True)
class ProposedField:
    path: str
    value: Any
    provenance: Provenance


def _provenance(row: TableRow, snippet: str) -> Provenance:
    return Provenance(
        document_id=row.document_id,
        page=row.page,
        sheet=row.sheet,
        row=row.row,
        source_snippet=snippet,
        confidence=1.0,
        status="proposed",
    )


def extract_fields(
    document_id: str,
    rows: list[TableRow],
    blocks: list[TextBlock],
    llm: LLMClient | None = None,
) -> list[ProposedField]:
    client = llm or FakeLLM()
    fields: list[ProposedField] = []
    did_index = 0
    for row in rows:
        identifier = row.values.get("DID") or row.values.get("Identifier")
        if identifier is not None:
            fields.append(
                ProposedField(
                    f"dids[{did_index}].did",
                    int(str(identifier), 0),
                    _provenance(row, str(row.values)),
                )
            )
            length = row.values.get("Bytes") or row.values.get("Payload octets")
            if length is not None:
                fields.append(
                    ProposedField(
                        f"dids[{did_index}].length_bytes",
                        int(length),
                        _provenance(row, str(row.values)),
                    )
                )
            did_index += 1
    for block in blocks:
        for sentence in (part.strip() for part in block.text.split(".") if part.strip()):
            if not re.search(r"\b(?:when|while|requires)\b", sentence, re.IGNORECASE):
                continue
            result = client.parse_condition(sentence)
            if result is None:
                continue
            condition = result.condition.model_copy(update={"target": result.target})
            validate(condition.model_dump(), Precondition.model_json_schema())
            provenance = Provenance(
                document_id=document_id,
                page=block.page,
                sheet=block.sheet,
                row=block.row,
                source_snippet=sentence,
                confidence=1.0,
                status="proposed",
            )
            fields.append(
                ProposedField(
                    f"{result.target}.preconditions",
                    condition.model_dump(),
                    provenance,
                )
            )
    return fields


def reconstruct_spec(template: EcuSpec, fields: list[ProposedField]) -> EcuSpec:
    data = template.model_dump(mode="python")
    for field in fields:
        if field.path.endswith(".preconditions"):
            continue
        _assign_path(data, field.path, field.value)
    return EcuSpec.model_validate(data)


def extract_spec_fields(
    document_id: str,
    rows: list[TableRow],
    blocks: list[TextBlock],
    llm: LLMClient | None = None,
) -> list[ProposedField]:
    fields = extract_fields(document_id, rows, blocks, llm)
    counters: dict[str, int] = {}
    for row in rows:
        sheet = row.sheet or ""
        if sheet in {"Sessions", "Security", "DIDs", "Routines", "Services"}:
            index = counters.get(sheet, 0)
            counters[sheet] = index + 1
        else:
            index = 0
        mappings: dict[str, list[tuple[str, Any]]] = {
            "Metadata": [(key, row.values.get(key)) for key in ("ecu_name", "oem", "version")],
            "DIDs": [
                (f"dids[{index}].name", row.values.get("Signal name")),
                (f"dids[{index}].encoding", row.values.get("Encoding")),
                (f"dids[{index}].read_sessions", _csv_ints(row.values.get("Read modes"))),
                (f"dids[{index}].write_sessions", _csv_ints(row.values.get("Write modes"))),
                (f"dids[{index}].read_security", _literal(row.values.get("Read security"))),
                (f"dids[{index}].write_security", _literal(row.values.get("Write security"))),
                (f"dids[{index}].preconditions", _literal(row.values.get("Preconditions"))),
            ],
            "Sessions": [
                (f"sessions[{index}].id", row.values.get("Mode code")),
                (f"sessions[{index}].name", row.values.get("Label")),
            ],
            "Security": [
                (f"security_levels[{index}].level", row.values.get("Access tier")),
                (f"security_levels[{index}].name", row.values.get("Label")),
            ],
            "Routines": [
                (f"routines[{index}].rid", _number(row.values.get("Routine identifier"))),
                (f"routines[{index}].name", row.values.get("Operation")),
                (f"routines[{index}].control_types", _csv_ints(row.values.get("Controls"))),
                (
                    f"routines[{index}].parameter_lengths",
                    _literal(row.values.get("Parameter octets")),
                ),
                (f"routines[{index}].sessions", _csv_ints(row.values.get("Allowed modes"))),
                (f"routines[{index}].security", _literal(row.values.get("Access tier"))),
                (f"routines[{index}].preconditions", _literal(row.values.get("Preconditions"))),
            ],
            "Services": [
                (f"services[{index}].sid", _number(row.values.get("Service code"))),
                (f"services[{index}].name", row.values.get("Service label")),
                (f"services[{index}].allowed_sessions", _csv_ints(row.values.get("Session gate"))),
                (
                    f"services[{index}].required_security_level",
                    _literal(row.values.get("Security gate")),
                ),
                (f"services[{index}].subfunctions", _literal(row.values.get("Subfunctions"))),
                (
                    f"services[{index}].suppress_positive_response_supported",
                    row.values.get("SPR"),
                ),
            ],
            "Timing": [
                ("timing.p2_ms", row.values.get("P2 milliseconds")),
                ("timing.p2_star_ms", row.values.get("P2-star milliseconds")),
                ("timing.s3_ms", row.values.get("S3 seconds")),
            ],
            "Priority": [("nrc_priority", _csv_ints(row.values.get("NRC order")))],
        }
        for path, value in mappings.get(sheet, []):
            keep_explicit_null = (
                sheet == "Services"
                and path.endswith("required_security_level")
                and "Security gate" in row.values
            )
            keep_explicit_null = keep_explicit_null or (
                sheet == "DIDs"
                and path.endswith(("read_security", "write_security"))
                and ("Read security" if path.endswith("read_security") else "Write security")
                in row.values
            )
            if (value is not None and value != "") or keep_explicit_null:
                fields.append(ProposedField(path, value, _provenance(row, str(row.values))))
    for block in blocks:
        for section, value in _section_values(block.text):
            parsed = _literal(value)
            if parsed is None:
                continue
            if section == "timing" and isinstance(parsed, dict):
                for key, item_value in parsed.items():
                    fields.append(
                        ProposedField(f"timing.{key}", item_value, _block_provenance(block, value))
                    )
            elif section == "nrc_priority":
                fields.append(ProposedField(section, parsed, _block_provenance(block, value)))
            elif isinstance(parsed, list):
                for index, item in enumerate(parsed):
                    if isinstance(item, dict):
                        for key, item_value in item.items():
                            path = f"{section}[{index}].{key}"
                            fields.append(
                                ProposedField(path, item_value, _block_provenance(block, value))
                            )
        for path, value in _path_values(block.text):
            parsed = value if path in {"ecu_name", "oem", "version"} else _literal(value)
            fields.append(ProposedField(path, parsed, _block_provenance(block, value)))
    return fields


def _block_provenance(block: TextBlock, snippet: str) -> Provenance:
    return Provenance(
        document_id=block.document_id,
        page=block.page,
        sheet=block.sheet,
        row=block.row,
        source_snippet=snippet,
        confidence=1.0,
        status="proposed",
    )


def _literal(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            pass
        return ast.literal_eval(value)
    except (SyntaxError, ValueError):
        return value


def _number(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return int(value, 0)
        except ValueError:
            return value
    return value


def _csv_ints(value: Any) -> list[int]:
    if value is None or value == "":
        return []
    return [int(item.strip(), 0) for item in str(value).split(",") if item.strip()]


def _section_values(text: str) -> list[tuple[str, str]]:
    pattern = re.compile(
        r"(?m)^(sessions|security_levels|services|routines|timing|nrc_priority):\s*(.+?)(?=\n\w+:|\Z)",
        re.DOTALL,
    )
    return [(match.group(1), match.group(2).strip()) for match in pattern.finditer(text)]


def _path_values(text: str) -> list[tuple[str, str]]:
    pattern = re.compile(
        r"(?m)^(sessions|security_levels|services|routines|dids)\[(\d+)\]\.([\w]+):[ \t]*"
    )
    values: list[tuple[str, str]] = []
    for match in pattern.finditer(text):
        remaining = text[match.end() :].strip()
        # Decode a complete JSON value, including wrapped PDF lines, without consuming headings.
        try:
            parsed, _ = json.JSONDecoder().raw_decode(remaining.replace("\n", " "))
            value = json.dumps(parsed)
        except json.JSONDecodeError:
            value = remaining.split("\n", 1)[0]
        values.append((f"{match.group(1)}[{match.group(2)}].{match.group(3)}", value))
    scalar = re.compile(r"(?m)^(ecu_name|oem|version):\s*(.+)$")
    values.extend((m.group(1), _literal(m.group(2))) for m in scalar.finditer(text))
    return values


def _assign_path(data: dict[str, Any], path: str, value: Any) -> None:
    match = re.fullmatch(r"([A-Za-z_]+)(?:\[(\d+)\])?\.?(.*)", path)
    if match is None:
        return
    root, index, tail = match.groups()
    target: Any = data[root]
    if index is not None:
        target = target[int(index)]
    if tail:
        target[tail] = value
    else:
        data[root] = value
