from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .provenance import Provenance


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Precondition(StrictModel):
    kind: Literal["signal", "session", "security", "timing"]
    signal: str | None = None
    op: Literal["==", "!=", "<", "<=", ">", ">="] | None = None
    value: str | int | float | bool | None = None
    unit: str | None = None
    target: str | None = None
    source_text: str


class Session(StrictModel):
    id: int = Field(ge=0, le=255)
    name: str


class SecurityLevel(StrictModel):
    level: int = Field(ge=0, le=255)
    name: str


class Subfunction(StrictModel):
    value: int = Field(ge=0, le=0xFF)
    name: str
    allowed_sessions: list[int] = Field(default_factory=list)
    required_security_level: int | None = None


class Service(StrictModel):
    sid: int = Field(ge=0, le=0xFF)
    name: str
    allowed_sessions: list[int] = Field(default_factory=list)
    required_security_level: int | None = None
    subfunctions: list[Subfunction] = Field(default_factory=list)
    suppress_positive_response_supported: bool = False


class DataIdentifier(StrictModel):
    did: int = Field(ge=0, le=0xFFFF)
    name: str
    length_bytes: int = Field(gt=0)
    encoding: str
    read_sessions: list[int] = Field(default_factory=list)
    write_sessions: list[int] = Field(default_factory=list)
    read_security: int | None = None
    write_security: int | None = None
    preconditions: list[Precondition] = Field(default_factory=list)
    read_preconditions: list[Precondition] = Field(default_factory=list)


class Routine(StrictModel):
    rid: int = Field(ge=0, le=0xFFFF)
    name: str
    control_types: list[int] = Field(default_factory=list)
    sessions: list[int] = Field(default_factory=list)
    security: int | None = None
    parameter_lengths: dict[int, int] = Field(default_factory=dict)
    preconditions: list[Precondition] = Field(default_factory=list)


class Timing(StrictModel):
    p2_ms: int = Field(gt=0)
    p2_star_ms: int = Field(gt=0)
    s3_ms: int = Field(gt=0)


class ResponseProfile(StrictModel):
    model_config = ConfigDict(extra="forbid")
    basis: Literal["simulator_convention", "engineer_configured"] = "simulator_convention"
    did_data: dict[int, str] = Field(default_factory=dict)
    seeds: dict[int, str] = Field(default_factory=dict)
    key_algorithm: Literal["xor", "identity"] = "xor"
    xor_byte: int = Field(default=0x5A, ge=0, le=255)
    response_masks: dict[int, str] = Field(default_factory=dict)


class EcuSpec(StrictModel):
    model_config = ConfigDict(extra="forbid")
    ecu_name: str
    oem: str
    version: str
    sessions: list[Session]
    security_levels: list[SecurityLevel]
    services: list[Service]
    dids: list[DataIdentifier]
    routines: list[Routine]
    timing: Timing
    nrc_priority: list[int]
    field_registry: dict[str, Provenance] = Field(default_factory=dict)
    unresolved_requirements: list[str] = Field(default_factory=list)
    response_profile: ResponseProfile = Field(default_factory=ResponseProfile)
    standard_version: Literal[2006, 2013, 2020] = 2020

    def service(self, sid: int) -> Service | None:
        return next((item for item in self.services if item.sid == sid), None)

    def did(self, value: int) -> DataIdentifier | None:
        return next((item for item in self.dids if item.did == value), None)

    def routine(self, value: int) -> Routine | None:
        return next((item for item in self.routines if item.rid == value), None)

    def field_is_approved(self, path: str) -> bool:
        provenance = self.field_registry.get(path)
        return provenance is None or provenance.status in {"approved", "edited"}


def export_json_schema() -> dict[str, object]:
    return EcuSpec.model_json_schema()
