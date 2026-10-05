from typing import Any


class OllamaClient:
    """Offline-safe adapter seam; network invocation is deliberately deferred."""

    def __init__(self, model: str = "qwen2.5") -> None:
        self.model = model

    def generate_structured(self, prompt: str, json_schema: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("OllamaClient requires an explicitly configured local server")
