from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class TextBlock:
    text: str
    page: int


class Parser(Protocol):
    def parse(self, path: str) -> list[TextBlock]: ...
