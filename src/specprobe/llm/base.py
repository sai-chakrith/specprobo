from typing import Any, Protocol


class LLMClient(Protocol):
    def generate_structured(self, prompt: str, json_schema: dict[str, Any]) -> dict[str, Any]: ...
