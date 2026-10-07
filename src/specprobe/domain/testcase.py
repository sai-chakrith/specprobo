from pydantic import BaseModel, ConfigDict, Field


class TraceRef(BaseModel):
    field_id: str
    page: int


class TestCase(BaseModel):
    model_config = ConfigDict(ser_json_bytes="hex", val_json_bytes="hex")
    id: str
    trace_to: list[TraceRef]
    preconditions: dict[str, object]
    setup_steps: list[bytes] = Field(default_factory=list)
    steps: list[bytes]
    environment: dict[str, object] = Field(default_factory=dict)
    expected: bytes | None
    tags: list[str]
    setup_expected: list[bytes | None] = Field(default_factory=list)
    step_expected: list[bytes | None] = Field(default_factory=list)
    response_mask: bytes | None = None
    idle_before_ms: float = Field(default=0, ge=0)
