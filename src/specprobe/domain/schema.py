from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .provenance import Field as ProvenanceField


class Precondition(BaseModel):
    kind: Literal["signal", "session", "security", "timing"]
    signal: str | None = None
    op: Literal["==", "!=", "<", "<=", ">", ">="] | None = None
    value: str | int | float | bool | None = None
    source_text: str


class Session(BaseModel):
    id: int = Field(ge=0, le=255)
    name: str


class SecurityLevel(BaseModel):
    level: int = Field(ge=0, le=255)
    name: str


class Subfunction(BaseModel):
    value: int = Field(ge=0, le=0xFF)
    name: str
    allowed_sessions: list[int] = []
    required_security_level: int | None = None


class Service(BaseModel):
    sid: int = Field(ge=0, le=0xFF)
    name: str
    allowed_sessions: list[int] = []
    required_security_level: int | None = None
    subfunctions: list[Subfunction] = []
    suppress_positive_response_supported: bool = False


class DataIdentifier(BaseModel):
    did: int = Field(ge=0, le=0xFFFF)
    name: str
    length_bytes: int = Field(gt=0)
    encoding: str
    read_sessions: list[int] = []
    write_sessions: list[int] = []
    read_security: int | None = None
    write_security: int | None = None
    preconditions: list[Precondition] = []


class Routine(BaseModel):
    rid: int = Field(ge=0, le=0xFFFF)
    name: str
    control_types: list[int] = []
    sessions: list[int] = []
    security: int | None = None
    parameter_lengths: dict[int, int] = {}
    preconditions: list[Precondition] = []


class Timing(BaseModel):
    p2_ms: int = Field(gt=0)
    p2_star_ms: int = Field(gt=0)
    s3_ms: int = Field(gt=0)


class EcuSpec(BaseModel):
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

    def service(self, sid: int) -> Service | None:
        return next((item for item in self.services if item.sid == sid), None)

    def did(self, value: int) -> DataIdentifier | None:
        return next((item for item in self.dids if item.did == value), None)


def export_json_schema() -> dict[str, object]:
    return EcuSpec.model_json_schema()
