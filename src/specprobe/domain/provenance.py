from datetime import datetime, timezone
from typing import Generic, TypeVar
from uuid import uuid4

from pydantic import BaseModel, Field as PydanticField

ValueT = TypeVar("ValueT")


class Provenance(BaseModel):
    field_id: str = PydanticField(default_factory=lambda: str(uuid4()))
    document_id: str
    page: int
    source_snippet: str
    confidence: float = PydanticField(ge=0, le=1)
    status: str = "proposed"
    reviewer: str | None = None
    timestamp: datetime = PydanticField(default_factory=lambda: datetime.now(timezone.utc))


class Field(BaseModel, Generic[ValueT]):
    value: ValueT
    provenance: Provenance
