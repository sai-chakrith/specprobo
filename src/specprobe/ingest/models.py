from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TextBlock:
    document_id: str
    text: str
    page: int | None = None
    sheet: str | None = None
    row: int | None = None


@dataclass(frozen=True)
class TableRow:
    document_id: str
    values: dict[str, Any]
    page: int | None = None
    sheet: str | None = None
    row: int | None = None

    @property
    def location(self) -> str:
        if self.page is not None:
            return f"page {self.page}"
        return f"sheet {self.sheet!r}, row {self.row}"
