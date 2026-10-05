import re
from typing import Any, Protocol

from ..domain.schema import Precondition


class LLMClient(Protocol):
    def parse_condition(self, text: str) -> Precondition: ...

    def normalize(self, name: str, value: Any) -> Any: ...


class FakeLLM:
    def parse_condition(self, text: str) -> Precondition:
        match = re.match(r"([A-Za-z_][A-Za-z0-9_]*)", text)
        signal = match.group(1) if match else text
        return Precondition(kind="signal", signal=signal, op="==", value=True, source_text=text)

    def normalize(self, name: str, value: Any) -> Any:
        return value


class Ollama:
    def __init__(self, model: str = "llama3.2") -> None:
        self.model = model

    def parse_condition(self, text: str) -> Precondition:
        raise RuntimeError("Ollama is opt-in and unavailable in offline mode")

    def normalize(self, name: str, value: Any) -> Any:
        raise RuntimeError("Ollama is opt-in and unavailable in offline mode")
