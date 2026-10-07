import ast
import json
import re
from dataclasses import dataclass, replace
from typing import Any

from jsonschema import validate  # type: ignore[import-untyped]

from ..domain.provenance import Provenance, SourceReference
from ..domain.schema import EcuSpec, Precondition
from .layouts import normalize
from .layouts import section as layout_section
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
        table=row.table,
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
    did_ids: dict[int, tuple[int, Any]] = {}
    for row in rows:
        identifier = row.values.get("DID") or row.values.get("Identifier")
        if identifier is not None:
            did_number = int(str(identifier), 0)
            length = row.values.get("Bytes") or row.values.get("Payload octets")
            if did_number in did_ids:
                if did_ids[did_number][1] != length:
                    raise ValueError(f"Conflicting lengths for DID {identifier}")
                continue
            did_ids[did_number] = (did_index, length)
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
    names: dict[str, tuple[str, int] | None] = {}
    for row in rows:
        for kind, id_key, name_key in (
            ("DID", "DID", "Signal name"),
            ("routine", "Routine identifier", "Operation"),
        ):
            if row.values.get(id_key) is not None and row.values.get(name_key):
                name = str(row.values[name_key]).casefold()
                target = (kind, int(str(row.values[id_key]), 0))
                names[name] = target if name not in names or names[name] == target else None
    for block in blocks:
        for sentence in (
            part.strip() for part in re.split(r"(?<!\d)\.(?!\d)|\n", block.text) if part.strip()
        ):
            if not re.search(r"\b(?:when|while|requires)\b", sentence, re.IGNORECASE):
                continue
            parse_text = sentence
            for name, named_target in names.items():
                if named_target is not None:
                    kind, identifier = named_target
                    noun = "data identifier" if kind == "DID" else "routine"
                    parse_text = re.sub(
                        r"\b" + re.escape(name) + r"\s+" + noun + r"\b",
                        f"{kind} 0x{identifier:04x}",
                        parse_text,
                        flags=re.I,
                    )
            results = (
                client.parse_conditions(parse_text)
                if isinstance(client, FakeLLM)
                else [result]
                if (result := client.parse_condition(parse_text)) is not None
                else []
            )
            if not results:
                fields.append(
                    ProposedField(
                        "unresolved_requirements", [sentence], _block_provenance(block, sentence)
                    )
                )
                continue
            for result in results:
                result.condition.source_text = sentence
                fields.append(_prose_field(result, document_id, sentence, block))
    unresolved = [field for field in fields if field.path == "unresolved_requirements"]
    if unresolved:
        fields = [field for field in fields if field.path != "unresolved_requirements"]
        fields.append(
            ProposedField(
                "unresolved_requirements",
                [s for f in unresolved for s in f.value],
                unresolved[0].provenance,
            )
        )
    return fields


def _prose_field(result: Any, document_id: str, sentence: str, block: TextBlock) -> ProposedField:
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
    return ProposedField(
        f"{result.target_kind}:{result.target}."
        + (
            "read_preconditions"
            if result.target_kind == "did" and re.search(r"\bread\b", sentence, re.I)
            else "preconditions"
        ),
        condition.model_dump(),
        provenance,
    )


def reconstruct_spec(template: EcuSpec, fields: list[ProposedField]) -> EcuSpec:
    data = template.model_dump(mode="python")
    for field in fields:
        if field.path.endswith(".preconditions") and ":" in field.path:
            continue
        _assign_path(data, field.path, field.value)
    return EcuSpec.model_validate(data)


def extract_spec_fields(
    document_id: str,
    rows: list[TableRow],
    blocks: list[TextBlock],
    llm: LLMClient | None = None,
) -> list[ProposedField]:
    rows = [replace(row, values=normalize(row.values)) for row in rows]
    fields = extract_fields(document_id, rows, blocks, llm)
    counters: dict[str, int] = {}
    row_ids: dict[tuple[str, str], int] = {}
    for row in rows:
        sheet = layout_section(row.values, row.sheet)
        if sheet in {"Sessions", "Security", "DIDs", "Routines", "Services"}:
            id_key = {
                "DIDs": "DID",
                "Routines": "Routine identifier",
                "Sessions": "Mode code",
                "Security": "Access tier",
                "Services": "Service code",
            }[sheet]
            key = (sheet, str(row.values.get(id_key)))
            if key not in row_ids:
                row_ids[key] = counters.get(sheet, 0)
                counters[sheet] = row_ids[key] + 1
            index = row_ids[key]
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
                (
                    f"dids[{index}].read_preconditions",
                    _literal(row.values.get("Read preconditions")),
                ),
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
                (
                    "timing.s3_ms",
                    row.values.get("S3 milliseconds")
                    if "S3 milliseconds" in row.values
                    else float(row.values["S3 seconds"]) * 1000
                    if row.values.get("S3 seconds") is not None
                    else None,
                ),
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
    return resolve_fields(bind_prose_conditions(fields))


def resolve_fields(fields: list[ProposedField]) -> list[ProposedField]:
    result: dict[str, ProposedField] = {}
    for field in fields:
        if field.path in result and result[field.path].value != field.value:
            raise ValueError(
                f"Conflicting extraction for {field.path}; engineer correction required"
            )
        result[field.path] = field
    return list(result.values())


def bind_prose_conditions(fields: list[ProposedField]) -> list[ProposedField]:
    identifiers = {
        (
            ("did" if field.path.startswith("dids[") else "routine"),
            int(field.value),
        ): field.path.rsplit(".", 1)[0]
        for field in fields
        if re.fullmatch(r"(dids\[\d+\]\.did|routines\[\d+\]\.rid)", field.path)
    }
    result = [field for field in fields if ":" not in field.path]
    grouped: dict[str, list[ProposedField]] = {}
    for field in fields:
        if ":" not in field.path:
            continue
        kind, suffix = field.path.split(":", 1)
        key = (kind, int(suffix.split(".")[0], 0))
        root = identifiers.get(key)
        if root is None:
            raise ValueError(f"Unresolved prose target {field.path}")
        grouped.setdefault(root + "." + suffix.split(".", 1)[1], []).append(field)
    for path, prose in grouped.items():
        structured = [f for f in result if f.path == path and isinstance(f.value, list)]
        values = [c for f in structured for c in f.value]

        def signature(c: dict[str, Any]) -> tuple[Any, ...]:
            op, value = c.get("op"), c.get("value")
            if op == "!=" and isinstance(value, bool):
                op, value = "==", not value
            value_type = (
                "bool"
                if isinstance(value, bool)
                else "number"
                if isinstance(value, (int, float))
                else "other"
            )
            return (c.get("kind"), c.get("signal"), op, value_type, value, c.get("unit"))

        signatures = {signature(c) for c in values}
        for field in prose:
            condition = {**field.value, "target": None}
            if signature(condition) not in signatures:
                values.append(condition)
                signatures.add(signature(condition))
        result = [f for f in result if f.path != path]
        references: list[SourceReference] = []
        for field in structured + prose:
            source = SourceReference.model_validate(field.provenance.model_dump())
            for reference in [source, *field.provenance.references]:
                if reference not in references:
                    references.append(reference)
        provenance = (structured[0] if structured else prose[0]).provenance.model_copy(
            update={"references": references}
        )
        result.append(ProposedField(path, values, provenance))
    return result


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
