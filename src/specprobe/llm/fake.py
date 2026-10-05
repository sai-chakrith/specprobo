from typing import Any


class FakeLLMClient:
    def __init__(self, canned: dict[str, Any]) -> None:
        self.canned = canned

    def generate_structured(self, prompt: str, json_schema: dict[str, Any]) -> dict[str, Any]:
        return dict(self.canned)
