from datetime import UTC, datetime
from typing import Generic, Literal, TypeVar
from uuid import uuid4

from pydantic import BaseModel
from pydantic import Field as PydanticField

ValueT = TypeVar("ValueT")


class SourceReference(BaseModel):
    document_id: str
    page: int | None = None
    sheet: str | None = None
    row: int | None = None
    table: int | None = None
    source_snippet: str


class Provenance(BaseModel):
    field_id: str = PydanticField(default_factory=lambda: str(uuid4()))
    document_id: str
    page: int | None = None
    sheet: str | None = None
    row: int | None = None
    table: int | None = None
    origin: Literal["source", "normalized_json"] = "source"
    defaulted: bool = False
    references: list[SourceReference] = PydanticField(default_factory=list)
    source_snippet: str
    confidence: float = PydanticField(ge=0, le=1)
    status: str = PydanticField(pattern="^(proposed|approved|edited|rejected)$")
    reviewer: str | None = None
    timestamp: datetime = PydanticField(default_factory=lambda: datetime.now(UTC))


class Field(BaseModel, Generic[ValueT]):
    value: ValueT
    provenance: Provenance


APPROVED_STATUSES = frozenset({"approved", "edited"})
