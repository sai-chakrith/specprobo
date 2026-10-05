from pydantic import BaseModel

from .provenance import Provenance


class TestCase(BaseModel):
    id: str
    trace_to: list[Provenance]
    preconditions: dict[str, object]
    steps: list[bytes]
    expected: bytes | None
    tags: list[str]
