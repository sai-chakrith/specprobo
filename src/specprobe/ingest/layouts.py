"""Explicit header aliases; source coordinates are never rewritten."""

import re
from typing import Any

ALIASES = {
    "DID": ["did", "did code", "did identifier", "data identifier", "identifier"],
    "Bytes": ["bytes", "payload octets", "data size bytes", "length bytes", "byte length"],
    "Signal name": ["signal name", "description", "data name", "name"],
    "Read modes": ["read modes", "read sessions", "read session"],
    "Write modes": ["write modes", "write sessions", "write session"],
    "Encoding": ["encoding", "data type", "datatype"],
    "Read security": ["read security", "read security level"],
    "Write security": ["write security", "write security level"],
    "Service code": ["sid", "service id", "service code"],
    "Service label": ["service name", "service label"],
    "Routine identifier": ["rid", "routine id", "routine identifier"],
    "Operation": ["routine name", "operation"],
    "Controls": ["controls", "control types", "routine controls"],
    "Parameter octets": ["parameter octets", "parameter lengths"],
    "Allowed modes": ["allowed modes", "allowed sessions"],
}


def header(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value).lower()).strip()


def normalize(values: dict[str, Any]) -> dict[str, Any]:
    lookup = {header(key): value for key, value in values.items()}
    result = dict(values)
    for canonical, names in ALIASES.items():
        found = [lookup[name] for name in names if name in lookup]
        if found:
            if any(value != found[0] for value in found):
                raise ValueError(f"Conflicting aliases for {canonical}")
            result[canonical] = found[0]
    return result


def section(values: dict[str, Any], fallback: str | None) -> str:
    if "DID" in values:
        return "DIDs"
    if "Routine identifier" in values:
        return "Routines"
    if "Service code" in values:
        return "Services"
    return fallback or ""


def is_header(values: list[Any]) -> bool:
    recognized = {alias for names in ALIASES.values() for alias in names}
    recognized |= {
        "mode code",
        "label",
        "access tier",
        "nrc order",
        "ecu name",
        "oem",
        "version",
        "p2 milliseconds",
        "p2 star milliseconds",
        "s3 seconds",
        "s3 milliseconds",
    }
    tokens = [header(value) for value in values if value is not None]
    return sum(token in recognized for token in tokens) >= 2 or tokens == ["nrc order"]
