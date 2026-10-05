import re
from dataclasses import dataclass
from typing import Any

from jsonschema import validate  # type: ignore[import-untyped]

from ..domain.provenance import Provenance
from ..domain.schema import Precondition
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
    for index, row in enumerate(rows):
        identifier = row.values.get("DID") or row.values.get("Identifier")
        if identifier is not None:
            fields.append(
                ProposedField(
                    f"dids[{index}].did", int(str(identifier), 0), _provenance(row, str(row.values))
                )
            )
        length = row.values.get("Bytes") or row.values.get("Payload octets")
        if length is not None:
            fields.append(
                ProposedField(
                    f"dids[{index}].length_bytes", int(length), _provenance(row, str(row.values))
                )
            )
    for block in blocks:
        for sentence in block.text.split("."):
            signals = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", sentence)
            signals = [
                signal
                for signal in signals
                if signal.startswith("signal_")
                or signal
                in {
                    "ignition_on",
                    "speed_zero",
                    "doors_closed",
                    "battery_ok",
                    "vehicle_stopped",
                    "service_brake",
                }
            ]
            for signal in signals:
                condition = client.parse_condition(signal)
                validate(condition.model_dump(), Precondition.model_json_schema())
                provenance = Provenance(
                    document_id=document_id,
                    page=block.page,
                    sheet=block.sheet,
                    row=block.row,
                    source_snippet=sentence.strip(),
                    confidence=1.0,
                    status="proposed",
                )
                fields.append(ProposedField("preconditions", condition.model_dump(), provenance))
    return fields
