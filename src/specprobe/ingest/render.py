import json
from pathlib import Path
from typing import Any, cast

from openpyxl import Workbook
from openpyxl.styles import Font
from reportlab.lib import colors  # type: ignore[import-untyped]
from reportlab.lib.pagesizes import letter  # type: ignore[import-untyped]
from reportlab.lib.styles import getSampleStyleSheet  # type: ignore[import-untyped]
from reportlab.lib.units import inch  # type: ignore[import-untyped]
from reportlab.platypus import (  # type: ignore[import-untyped]
    LongTable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    TableStyle,
)


def _load(path: str | Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(Path(path).read_text(encoding="utf-8")))


def render_oem_a_pdf(ground_truth: str | Path, output: str | Path) -> None:
    spec = _load(ground_truth)
    styles = getSampleStyleSheet()
    story: list[Any] = [Paragraph(f"{spec['ecu_name']} diagnostic specification", styles["Title"])]
    story.append(Paragraph(f"OEM {spec['oem']} | version {spec['version']}", styles["Normal"]))
    story.append(Spacer(1, 0.2 * inch))
    header = [
        ["Data identifiers", "", "", "", ""],
        ["DID", "Name", "Bytes", "Read sessions", "Write sessions"],
    ]
    data = header + [
        [
            f"0x{item['did']:04X}",
            item["name"],
            item["length_bytes"],
            ", ".join(map(str, item["read_sessions"])),
            ", ".join(map(str, item["write_sessions"])),
        ]
        for item in spec["dids"]
    ]

    def make_table(table_data: list[list[Any]]) -> LongTable:
        table = LongTable(
            table_data,
            colWidths=[0.8 * inch, 1.7 * inch, 0.7 * inch, 1.2 * inch, 1.2 * inch],
            repeatRows=2,
        )
        table.setStyle(
            TableStyle(
                [
                    ("SPAN", (0, 0), (-1, 0)),
                    ("BACKGROUND", (0, 0), (-1, 1), colors.HexColor("#1d4e89")),
                    ("TEXTCOLOR", (0, 0), (-1, 1), colors.white),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                    (
                        "ROWBACKGROUNDS",
                        (0, 2),
                        (-1, -1),
                        [colors.whitesmoke, colors.HexColor("#eaf2f8")],
                    ),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]
            )
        )
        return table

    tables = [make_table(data[:7]), PageBreak(), make_table([header[0], header[1], *data[7:]])]
    story.extend(
        [
            *tables,
            Spacer(1, 0.2 * inch),
            Paragraph("Prose appendix: operating conditions", styles["Heading2"]),
        ]
    )
    for item in spec["dids"]:
        for condition in item.get("preconditions", []):
            signal = condition["signal"]
            did = f"0x{item['did']:04X}"
            statements = (
                f"DID {did} may be written only when {signal} is true.",
                f"Writing DID {did} requires {signal} to be true.",
                f"DID {did} must not be written while {signal} is false.",
            )
            story.extend(Paragraph(statement, styles["BodyText"]) for statement in statements)
    story.append(
        Paragraph(
            "The six documented operating conditions are signal_0 through signal_5; "
            "each must be true before its corresponding write is accepted.",
            styles["BodyText"],
        )
    )
    for section in (
        "sessions",
        "security_levels",
        "services",
        "routines",
        "timing",
        "nrc_priority",
    ):
        section_value = spec[section]
        if section == "services":
            section_value = [
                {
                    **item,
                    "allowed_sessions": item.get("allowed_sessions", []),
                    "required_security_level": item.get("required_security_level"),
                    "subfunctions": item.get("subfunctions", []),
                    "suppress_positive_response_supported": item.get(
                        "suppress_positive_response_supported", False
                    ),
                }
                for item in section_value
            ]
        if section == "routines":
            section_value = [
                {
                    **item,
                    "sessions": item.get("sessions", []),
                    "security": item.get("security"),
                    "preconditions": item.get("preconditions", []),
                }
                for item in section_value
            ]
        story.append(Paragraph(f"{section}: {section_value}", styles["BodyText"]))
        if section in {"sessions", "security_levels", "services", "routines"}:
            for index, item in enumerate(section_value):
                for key, value in item.items():
                    story.append(
                        Paragraph(
                            f"{section}[{index}].{key}: {json.dumps(value, sort_keys=True)}",
                            styles["BodyText"],
                        )
                    )
    SimpleDocTemplate(str(output), pagesize=letter, rightMargin=36, leftMargin=36).build(story)


def render_oem_b_xlsx(ground_truth: str | Path, output: str | Path) -> None:
    spec = _load(ground_truth)
    workbook = Workbook()
    active = workbook.active
    assert active is not None
    workbook.remove(active)
    sections = {
        "Sessions": (
            ["Mode code", "Label"],
            [[item["id"], item["name"]] for item in spec["sessions"]],
        ),
        "Security": (
            ["Access tier", "Label"],
            [[item["level"], item["name"]] for item in spec["security_levels"]],
        ),
        "DIDs": (
            ["Identifier", "Signal name", "Payload octets", "Read modes", "Write modes"],
            [
                [
                    f"0x{item['did']:04X}",
                    item["name"],
                    item["length_bytes"],
                    ",".join(map(str, item["read_sessions"])),
                    ",".join(map(str, item["write_sessions"])),
                ]
                for item in spec["dids"]
            ],
        ),
        "Routines": (
            [
                "Routine identifier",
                "Operation",
                "Controls",
                "Parameter octets",
                "Allowed modes",
                "Access tier",
                "Preconditions",
            ],
            [
                [
                    f"0x{item['rid']:04X}",
                    item["name"],
                    ",".join(map(str, item["control_types"])),
                    str(item["parameter_lengths"]),
                    ",".join(map(str, item.get("sessions", []))),
                    json.dumps(item.get("security")),
                    str(item.get("preconditions", [])),
                ]
                for item in spec["routines"]
            ],
        ),
        "Services": (
            [
                "Service code",
                "Service label",
                "Session gate",
                "Security gate",
                "Subfunctions",
                "SPR",
            ],
            [
                [
                    f"0x{item['sid']:02X}",
                    item["name"],
                    ",".join(map(str, item.get("allowed_sessions", []))),
                    json.dumps(item.get("required_security_level")),
                    str(item.get("subfunctions", [])),
                    item.get("suppress_positive_response_supported", False),
                ]
                for item in spec["services"]
            ],
        ),
        "Timing": (
            ["P2 milliseconds", "P2-star milliseconds", "S3 seconds"],
            [[spec["timing"]["p2_ms"], spec["timing"]["p2_star_ms"], spec["timing"]["s3_ms"]]],
        ),
        "Priority": (["NRC order"], [[",".join(map(str, spec["nrc_priority"]))]]),
    }
    for title, (headers, values) in sections.items():
        sheet = workbook.create_sheet(title)
        sheet.append([f"{spec['ecu_name']} {title} reference"])
        sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(headers))
        sheet["A1"].font = Font(bold=True)
        sheet.append(headers)
        for row in values:
            sheet.append(row)
    appendix = workbook.create_sheet("Appendix")
    appendix.append(["Prose conditions"])
    for item in spec["dids"]:
        for condition in item.get("preconditions", []):
            appendix.append(
                [
                    f"DID 0x{item['did']:04X} may be written only when "
                    f"{condition['signal']} is true."
                ]
            )
            appendix.append(
                [f"Writing DID 0x{item['did']:04X} requires {condition['signal']} to be true."]
            )
            appendix.append(
                [
                    f"DID 0x{item['did']:04X} must not be written while "
                    f"{condition['signal']} is false."
                ]
            )
    workbook.save(output)
