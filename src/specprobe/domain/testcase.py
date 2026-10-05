from pydantic import BaseModel, Field


class TraceRef(BaseModel):
    field_id: str
    page: int


class TestCase(BaseModel):
    id: str
    trace_to: list[TraceRef]
    preconditions: dict[str, object]
    setup_steps: list[bytes] = Field(default_factory=list)
    steps: list[bytes]
    environment: dict[str, object] = Field(default_factory=dict)
    expected: bytes | None
    tags: list[str]
